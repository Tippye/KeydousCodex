# SPDX-License-Identifier: GPL-3.0-only
# Windows port of Keyphore's status core, derived from BarryBarrywu/Keyphore
# app/Sources/KeyphoreCore/SignalRuntime.swift and src/hook.rs (9ca11f275809).
# Upstream: https://github.com/BarryBarrywu/Keyphore
"""Privacy-allowlisted Codex Hooks -> atomic durable status; never opens HID.

Turn tombstones are retained, including after TTL expiry, so delayed events cannot
resurrect a completed turn. Capacity exhaustion fails explicitly rather than
silently evicting session history. Timestamps are Unix seconds, unlike Swift's
milliseconds. Snapshot reduction reads current expiries; there are no stale timer
callbacks capable of deleting a newer owner generation.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import math
import os
from pathlib import Path
import tempfile
import time

EVENTS = (
    "SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
    "SubagentStart", "SubagentStop", "Stop", "SessionEnd",
)
MAX_INPUT_BYTES = 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_FIELD_CHARS = 256
MAX_OWNERS = 2048
MAX_PREVIOUS_TURNS = 256
LIFETIMES = {"attention": 3600, "execution": 3600, "completion": 5}
STATES = {"attention": "waiting", "execution": "working", "completion": "success"}


class HookStoreError(ValueError):
    """Safe, content-free error suitable for reporting to the local UI."""


def _identifier(value, name):
    if (not isinstance(value, str) or not value.strip()
            or len(value) > MAX_FIELD_CHARS
            or any(ord(char) < 32 for char in value)):
        raise HookStoreError(f"Hook {name} must be a nonempty identifier of at most {MAX_FIELD_CHARS} characters")
    return value


def normalize_hook(event: dict) -> dict:
    """Copy only the four allowed fields; never retain caller content."""
    if not isinstance(event, dict):
        raise HookStoreError("Hook input must be a JSON object")
    name = event.get("hook_event_name")
    if name not in EVENTS:
        raise HookStoreError("Unsupported Hook event")
    result = {"hook_event_name": name,
              "session_id": _identifier(event.get("session_id"), "session_id")}
    if name in ("SubagentStart", "SubagentStop"):
        agent = _identifier(event.get("agent_id"), "agent_id")
        if agent == "main":
            raise HookStoreError("Subagent Hook requires a distinct agent_id")
    elif name in ("PermissionRequest", "PostToolUse"):
        agent = event.get("agent_id")
        if agent is None or agent == "":
            agent = "main"
        agent = _identifier(agent, "agent_id")
    else:
        agent = "main"
    result["agent_id"] = agent
    if name not in ("SessionStart", "SessionEnd"):
        result["turn_id"] = _identifier(event.get("turn_id"), "turn_id")
    return result


def _timestamp(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or value > 1e15 or not math.isfinite(value)):
        raise HookStoreError("Status timestamp must be finite Unix seconds")
    return float(value)


def _integer(value):
    return type(value) is int and 0 <= value < 2 ** 63


def _decode(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HookStoreError("Durable Hook state contains duplicate fields")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise HookStoreError("Durable Hook state is invalid JSON") from error


def _validate(status):
    """Validate all persisted fields, including privacy and cross-field invariants."""
    if not isinstance(status, dict) or set(status) != {"schema_version", "generation", "observed_at", "owners"}:
        raise HookStoreError("Durable Hook state has an invalid schema")
    if type(status["schema_version"]) is not int or status["schema_version"] != 1 or not _integer(status["generation"]):
        raise HookStoreError("Durable Hook state has an unsupported version or generation")
    _timestamp(status["observed_at"])
    owners = status["owners"]
    if not isinstance(owners, list) or len(owners) > MAX_OWNERS:
        raise HookStoreError("Durable Hook owner capacity exceeded")
    identities = set()
    required = {"session_id", "agent_id", "turn_id", "previous_turn_ids", "terminal",
                "signal", "expires_at", "generation", "hook_event_name", "received_at"}
    for owner in owners:
        if not isinstance(owner, dict) or set(owner) != required:
            raise HookStoreError("Durable Hook owner has an invalid schema")
        for field in ("session_id", "agent_id", "turn_id"):
            _identifier(owner[field], field)
        identity = (owner["session_id"], owner["agent_id"])
        if identity in identities:
            raise HookStoreError("Durable Hook state contains duplicate owners")
        identities.add(identity)
        previous = owner["previous_turn_ids"]
        if not isinstance(previous, list) or len(previous) > MAX_PREVIOUS_TURNS:
            raise HookStoreError("Durable Hook turn history capacity exceeded")
        for turn in previous:
            _identifier(turn, "previous turn_id")
        if len(set(previous)) != len(previous) or owner["turn_id"] in previous:
            raise HookStoreError("Durable Hook turn history is inconsistent")
        if type(owner["terminal"]) is not bool or owner["signal"] not in (None, *LIFETIMES):
            raise HookStoreError("Durable Hook owner has an invalid signal")
        if owner["hook_event_name"] not in EVENTS or not _integer(owner["generation"]) or owner["generation"] > status["generation"]:
            raise HookStoreError("Durable Hook owner has an invalid event or generation")
        received = _timestamp(owner["received_at"])
        expires = _timestamp(owner["expires_at"])
        if received > status["observed_at"] or expires < received:
            raise HookStoreError("Durable Hook owner has inconsistent timestamps")
        if owner["signal"] is not None and expires != received + LIFETIMES[owner["signal"]]:
            raise HookStoreError("Durable Hook owner has an invalid signal lifetime")
        if owner["signal"] == "completion" and not owner["terminal"]:
            raise HookStoreError("Durable Hook completion must be terminal")
        if owner["terminal"] and owner["signal"] not in (None, "completion"):
            raise HookStoreError("Durable Hook terminal owner has an active signal")


class HookStore:
    def __init__(self, path: Path, *, lock_timeout: float = 0.25):
        self.path = Path(path)
        self.lock_timeout = _timestamp(lock_timeout)
        if self.lock_timeout > 10:
            raise HookStoreError("Hook lock timeout must not exceed 10 seconds")

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Stable sibling lock: replacing status.json never changes the lock inode.
        with open(self.path.with_name(self.path.name + ".lock"), "a+b") as lock:
            # Windows permits byte-range locking past EOF; no racing initialization.
            if os.name == "nt":
                import msvcrt
                def acquire():
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                def release():
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                def acquire():
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release():
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    acquire()
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise HookStoreError("Cannot acquire durable Hook state lock") from error
                    if time.monotonic() >= deadline:
                        raise HookStoreError("Timed out waiting for durable Hook state lock") from error
                    time.sleep(0.005)
            try:
                yield
            finally:
                release()

    def _load(self):
        with self.path.open("rb") as file:
            data = file.read(MAX_STATE_BYTES + 1)
        if len(data) > MAX_STATE_BYTES:
            raise HookStoreError("Durable Hook state exceeds file size limit")
        status = _decode(data)
        _validate(status)
        return status

    def _save(self, status):
        _validate(status)
        data = (json.dumps(status, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(data) > MAX_STATE_BYTES:
            raise HookStoreError("Durable Hook state exceeds file size limit")
        descriptor, temporary = tempfile.mkstemp(prefix="." + self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def handle(self, event: dict, now: float | None = None) -> None:
        event = normalize_hook(event)
        now = _timestamp(time.time() if now is None else now)
        try:
            with self._lock():
                try:
                    status = self._load()
                except FileNotFoundError:
                    status = {"schema_version": 1, "generation": 0, "observed_at": now, "owners": []}
                self._apply(status, event, now)
                self._save(status)
        except OSError as error:
            raise HookStoreError("Cannot update durable Hook state") from error

    @staticmethod
    def _apply(status, event, now):
        name, session = event["hook_event_name"], event["session_id"]
        owners = status["owners"]
        # Keep timestamps valid through local wall-clock rollback.
        now = max(now, status["observed_at"])
        if name in ("SessionStart", "SessionEnd"):
            for owner in owners:
                if owner["session_id"] == session:
                    owner["terminal"], owner["signal"] = True, None
            status["generation"] += 1
            status["observed_at"] = now
            return
        agent, turn = event["agent_id"], event["turn_id"]
        owner = next((item for item in owners if (item["session_id"], item["agent_id"]) == (session, agent)), None)
        if owner is not None:
            if owner["turn_id"] == turn:
                if owner["terminal"]:
                    return
            else:
                if name not in ("UserPromptSubmit", "SubagentStart") or turn in owner["previous_turn_ids"]:
                    return
                if len(owner["previous_turn_ids"]) >= MAX_PREVIOUS_TURNS:
                    raise HookStoreError("Durable Hook turn history capacity exceeded; explicit state reset required")
                owner["previous_turn_ids"].append(owner["turn_id"])
                owner["turn_id"], owner["terminal"] = turn, False
        else:
            if len(owners) >= MAX_OWNERS:
                raise HookStoreError("Durable Hook owner capacity exceeded; explicit state reset required")
            owner = {"session_id": session, "agent_id": agent, "turn_id": turn,
                     "previous_turn_ids": [], "terminal": False}
            owners.append(owner)
        if name == "UserPromptSubmit":
            for other in owners:
                if other is not owner and other["session_id"] == session:
                    other["terminal"], other["signal"] = True, None
        signal = (None if name == "SubagentStop" else "completion" if name == "Stop"
                  else "attention" if name == "PermissionRequest" else "execution")
        status["generation"] += 1
        status["observed_at"] = now
        owner.update(signal=signal, terminal=name in ("Stop", "SubagentStop"),
                     generation=status["generation"], hook_event_name=name,
                     received_at=now, expires_at=now + LIFETIMES.get(signal, 0))

    def snapshot(self, now: float | None = None) -> dict:
        now = _timestamp(time.time() if now is None else now)
        result = {"state": "unknown", "source": "hooks", "source_detail": "Hook state unavailable",
                  "validity": "unknown", "observed_at": now,
                  "summary": {"attention": 0, "execution": 0, "completion": 0}, "generation": 0}
        try:
            with self._lock():
                status = self._load()
        except FileNotFoundError:
            result["source_detail"] = "No durable Hook state has been received"
            return result
        except (HookStoreError, OSError) as error:
            result["source_detail"] = str(error) if isinstance(error, HookStoreError) else "Cannot read durable Hook state"
            return result
        sessions = {}
        priorities = {"attention": 3, "execution": 2, "completion": 1}
        for owner in status["owners"]:
            signal = owner["signal"]
            if signal is not None and owner["expires_at"] > now:
                session = owner["session_id"]
                if priorities[signal] > priorities.get(sessions.get(session), 0):
                    sessions[session] = signal
        for signal in sessions.values():
            result["summary"][signal] += 1
        active = next((signal for signal in priorities if result["summary"][signal]), None)
        result.update(state=STATES.get(active, "idle"), validity="observed",
                      observed_at=status["observed_at"], generation=status["generation"], source_detail="Keyphore durable Hook state")
        return result
