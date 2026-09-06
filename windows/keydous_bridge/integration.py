# SPDX-License-Identifier: GPL-3.0-only
# Windows lifecycle port derived from BarryBarrywu/Keyphore (GPL-3.0-only).
"""Review-gated Codex Plugin lifecycle for the Windows Keydous bridge.

The generated Hooks only forward bounded lifecycle JSON to the bridge's ``--hook``
entry point.  This module never reads task prose and never emits Hook decisions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import threading
import shlex
from typing import Any

from .codex_rpc import CodexRPC
from .hook_core import EVENTS
from . import __version__


MARKETPLACE_NAME = "keyphore-keydous-local"
PLUGIN_NAME = "keyphore-keydous"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
PRIVACY_FIELDS = ("hook_event_name", "session_id", "agent_id", "turn_id")
HOOK_TIMEOUT_SECONDS = 2
SCHEMA_VERSION = 1
CODEX_EVENT_NAMES = {event: event[:1].lower() + event[1:] for event in EVENTS}


class IntegrationError(RuntimeError):
    """A content-free lifecycle error suitable for the local control panel."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp",
                                              dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as error:
        raise IntegrationError("无法读取 Hook 运行文件，请重新安装程序") from error
    return "sha256:" + digest.hexdigest()


def _source_command(data_dir: Path) -> tuple[str, list[str], str, str, dict[str, str]]:
    """Return runtime details, integrity hashes, and encoded Windows command."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve().with_name("KeydousCodexHook.exe" if sys.platform == "win32" else "KeydousCodexHook")
        if not executable.is_file():
            raise IntegrationError("安装包缺少 KeydousCodexHook，不能启用 Codex Hook")
        arguments = ["--hook", "--data-dir", str(data_dir.resolve())]
        runtime_files = [executable]
    else:
        executable = Path(sys.executable).resolve()
        if executable.name.lower() == "pythonw.exe":
            console_python = executable.with_name("python.exe")
            if console_python.is_file():
                executable = console_python
        runner = Path(__file__).resolve().parents[1] / "run_bridge.py"
        if not runner.is_file():
            raise IntegrationError("缺少 run_bridge.py，不能启用 Codex Hook")
        arguments = [str(runner), "--hook", "--data-dir", str(data_dir.resolve())]
        # The source launcher imports this exact adjacent package.  Bind every
        # Python module so reviewed consent cannot survive a handler code edit.
        runtime_files = [executable, runner, *sorted((runner.parent / "keydous_bridge").glob("*.py"))]
    integrity = {str(path): _sha256_file(path) for path in runtime_files}
    if sys.platform != "win32":
        command = shlex.join([str(executable), *arguments])
        return str(executable), arguments, command, command, integrity
    readable = "& " + _powershell_literal(str(executable))
    for argument in arguments:
        readable += " " + _powershell_literal(argument)
    readable += "; exit $LASTEXITCODE"
    encoded = base64.b64encode(readable.encode("utf-16-le")).decode("ascii")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if os.name == "nt" and not powershell.is_file():
        raise IntegrationError("找不到 Windows PowerShell，不能启用 Codex Hook")
    # Codex invokes Windows hooks through cmd.exe /C and currently wraps the
    # complete command line in quotes. Keep this outer command quote-free;
    # embedded quotes can otherwise make a successful-looking hook a no-op.
    powershell_text = str(powershell)
    if any(character.isspace() or character == '"' for character in powershell_text):
        raise IntegrationError("Windows PowerShell 路径包含空格，当前 Codex 无法安全执行此 Hook")
    command = powershell_text + " -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    return str(executable), arguments, readable, command, integrity


class Integration:
    """Own the local marketplace, Plugin, and only its eight Hook state entries."""

    def __init__(self, data_dir: Path, rpc: CodexRPC | None = None):
        self.data_dir = Path(data_dir).resolve()
        self._rpc = rpc
        self.cancelled = threading.Event()
        self.marketplace_root = self.data_dir / "codex-marketplace"
        self.plugin_root = self.marketplace_root / "plugin"
        self.state_path = self.data_dir / "integration.json"

    @property
    def rpc(self) -> CodexRPC:
        if self._rpc is None:
            self._rpc = CodexRPC()
        return self._rpc

    def _objects(self) -> tuple[dict, dict, dict, dict]:
        executable, arguments, readable, command, runtime_integrity = _source_command(self.data_dir)
        marketplace = {
            "name": MARKETPLACE_NAME,
            "interface": {"displayName": "Keyphore Keydous Local"},
            "plugins": [{
                "name": PLUGIN_NAME,
                "source": {"source": "local", "path": "./plugin"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }],
        }
        manifest = {
            "name": PLUGIN_NAME,
            "version": __version__,
            "description": "Privacy-allowlisted Codex lifecycle status for Keydous keyboards",
            "author": {"name": "Barry Barry Wu / Keydous Windows port"},
            "homepage": "https://github.com/BarryBarrywu/Keyphore",
            "repository": "https://github.com/BarryBarrywu/Keyphore",
            "license": "GPL-3.0-only",
            "interface": {
                "displayName": "Keyphore Keydous",
                "shortDescription": "Show Codex status on a Keydous keyboard",
                "developerName": "Keyphore contributors",
                "category": "Productivity",
                "capabilities": ["Interactive", "Write"],
            },
        }
        hooks = {
            "description": "Record privacy-allowlisted Codex lifecycle events for local keyboard status.",
            "hooks": {
                event: [{"hooks": [{"type": "command", "command": command,
                                      **({"commandWindows": command} if sys.platform == "win32" else {}),
                                      "timeout": HOOK_TIMEOUT_SECONDS}]}]
                for event in EVENTS
            },
        }
        review = {
            "schema_version": SCHEMA_VERSION,
            "platform": sys.platform,
            "marketplace_name": MARKETPLACE_NAME,
            "plugin_id": PLUGIN_ID,
            "definitions": [{
                "event": event,
                "handler_type": "command",
                "execution_mode": "sync",
                "timeout_seconds": HOOK_TIMEOUT_SECONDS,
                "command": command,
                **({"command_windows": command} if sys.platform == "win32" else {}),
                "command_plaintext": readable,
            } for event in EVENTS],
            "runtime": {"executable": executable, "arguments": arguments,
                        "integrity": runtime_integrity},
            "privacy_fields": list(PRIVACY_FIELDS),
            "stdin": "One bounded JSON object supplied by Codex",
            "stdout": "Always empty; never returns allow, deny, or modified permissions",
        }
        digest_payload = {"marketplace": marketplace, "manifest": manifest,
                          "hooks": hooks, "review": review}
        review["digest"] = "sha256:" + hashlib.sha256(_json_bytes(digest_payload)).hexdigest()
        return marketplace, manifest, hooks, review

    @property
    def _files(self) -> tuple[Path, Path, Path]:
        return (
            self.marketplace_root / ".agents" / "plugins" / "marketplace.json",
            self.plugin_root / ".codex-plugin" / "plugin.json",
            self.plugin_root / "hooks" / "hooks.json",
        )

    def review(self) -> dict:
        """Materialize deterministic files and return the exact consent surface."""
        marketplace, manifest, hooks, review = self._objects()
        for path, value in zip(self._files, (marketplace, manifest, hooks), strict=True):
            _atomic_write(path, _json_bytes(value))
        self._merge_state(prepared_digest=review["digest"], last_error=None)
        return review

    def _require_reviewed_files(self, digest: str) -> tuple[dict, str]:
        if self.cancelled.is_set():
            raise IntegrationError("程序正在退出，Hook 启用已取消")
        marketplace, manifest, hooks, review = self._objects()
        if not isinstance(digest, str) or not hmac.compare_digest(digest, review["digest"]):
            raise IntegrationError("Hook 审阅摘要已变化，请重新审阅后再启用")
        for path, value in zip(self._files, (marketplace, manifest, hooks), strict=True):
            try:
                actual = path.read_bytes()
            except OSError as error:
                raise IntegrationError("Hook 文件不存在，请重新审阅后再启用") from error
            if not hmac.compare_digest(actual, _json_bytes(value)):
                raise IntegrationError("Hook 文件在审阅后发生变化，请重新审阅后再启用")
        return review, review["digest"]

    @staticmethod
    def _marketplaces(payload: dict) -> set[str]:
        values = payload.get("marketplaces", []) if isinstance(payload, dict) else []
        return {item.get("name") for item in values if isinstance(item, dict)
                and isinstance(item.get("name"), str)}

    @staticmethod
    def _plugins(payload: dict) -> set[str]:
        values = payload.get("installed", []) if isinstance(payload, dict) else []
        return {item.get("pluginId") for item in values if isinstance(item, dict)
                and isinstance(item.get("pluginId"), str)}

    def _list_hooks(self) -> list[dict]:
        result = self.rpc.request("hooks/list", {"cwds": [str(self.plugin_root)]})
        try:
            entry = result["data"][0]
            if entry.get("errors"):
                raise IntegrationError("Codex 报告 Hook 配置错误")
            hooks = entry["hooks"]
        except (KeyError, IndexError, TypeError) as error:
            raise IntegrationError("Codex 返回了无法识别的 Hook 列表") from error
        if not isinstance(hooks, list) or any(not isinstance(item, dict) for item in hooks):
            raise IntegrationError("Codex 返回了无法识别的 Hook 元数据")
        return hooks

    @staticmethod
    def _owned(hooks: list[dict]) -> list[dict]:
        return [hook for hook in hooks if hook.get("pluginId") == PLUGIN_ID]

    def _validate_owned(self, hooks: list[dict], expected_command: str) -> list[dict]:
        owned = self._owned(hooks)
        if len(owned) != len(EVENTS):
            raise IntegrationError("Codex 中的 Keyphore Keydous Hook 数量与审阅内容不一致")
        by_event: dict[str, dict] = {}
        metadata_to_hook_event = {value: key for key, value in CODEX_EVENT_NAMES.items()}
        for hook in owned:
            metadata_event = hook.get("eventName")
            event = metadata_to_hook_event.get(metadata_event)
            source_path = str(hook.get("sourcePath", "")).replace("\\", "/").lower()
            if (event is None or event in by_event
                    or hook.get("handlerType") != "command"
                    or hook.get("executionMode") not in (None, "sync")
                    or hook.get("matcher") is not None
                    or hook.get("command") != expected_command
                    or hook.get("timeoutSec") != HOOK_TIMEOUT_SECONDS
                    or hook.get("isManaged") is not False
                    or not source_path.endswith("/hooks/hooks.json")
                    or not isinstance(hook.get("key"), str) or not hook["key"]
                    or not isinstance(hook.get("currentHash"), str) or not hook["currentHash"]):
                raise IntegrationError("Codex 中的 Hook 定义与已审阅内容不一致")
            by_event[event] = hook
        if set(by_event) != set(EVENTS):
            raise IntegrationError("Codex 中的 Hook 事件与已审阅内容不一致")
        return [by_event[event] for event in EVENTS]

    @staticmethod
    def _key_path(key: str) -> str:
        # A quoted TOML key segment keeps colons, slashes and dots inside the Hook key.
        return "hooks.state." + json.dumps(key, ensure_ascii=True)

    def _configure(self, hooks: list[dict], *, enabled: bool, trust: bool) -> None:
        edits = []
        seen = set()
        for hook in hooks:
            key = hook.get("key")
            if not isinstance(key, str) or not key or key in seen:
                raise IntegrationError("Codex 返回了无效或重复的 Hook 键")
            seen.add(key)
            value: dict[str, Any] = {"enabled": enabled}
            if trust:
                current_hash = hook.get("currentHash")
                if not isinstance(current_hash, str) or not current_hash:
                    raise IntegrationError("Codex Hook 缺少可审阅的哈希")
                value["trusted_hash"] = current_hash
            edits.append({"keyPath": self._key_path(key), "value": value,
                          "mergeStrategy": "upsert"})
        if edits:
            self.rpc.request("config/batchWrite", {"edits": edits, "reloadUserConfig": True})

    def install(self, digest: str) -> dict:
        """Install and trust only after the caller echoes the exact review digest."""
        trust_attempted = []
        try:
            review, reviewed_digest = self._require_reviewed_files(digest)
            marketplaces = self._marketplaces(
                self.rpc.cli(["plugin", "marketplace", "list", "--json"]))
            if MARKETPLACE_NAME not in marketplaces:
                self.rpc.cli(["plugin", "marketplace", "add", str(self.marketplace_root), "--json"])
            plugins = self._plugins(self.rpc.cli(["plugin", "list", "--json"]))
            if PLUGIN_ID in plugins:
                self.rpc.cli(["plugin", "remove", PLUGIN_ID, "--json"])
                self._merge_state(installed=False, trusted=False, hook_keys=[], hook_hashes={})
            self.rpc.cli(["plugin", "add", PLUGIN_ID, "--json"])
            installed = self._plugins(self.rpc.cli(["plugin", "list", "--json"]))
            if PLUGIN_ID not in installed:
                raise IntegrationError("Codex 未确认 Keyphore Keydous 插件已安装")
            # Persist the partial state before the separate trust transaction.  If
            # Codex rejects that transaction the control panel must not claim the
            # Plugin disappeared merely because trust is still pending.
            self._merge_state(installed=True, trusted=False, last_error=None,
                              marketplace_retained=True)
            owned = self._validate_owned(self._list_hooks(), review["definitions"][0]["command"])
            reviewed_hashes = {hook["eventName"]: hook["currentHash"] for hook in owned}
            self._require_reviewed_files(digest)
            trust_attempted = owned
            self._configure(owned, enabled=True, trust=True)
            verified = self._validate_owned(self._list_hooks(), review["definitions"][0]["command"])
            if ({hook["eventName"]: hook["currentHash"] for hook in verified} != reviewed_hashes
                    or any(hook.get("enabled") is not True
                           or str(hook.get("trustStatus", "")).lower() != "trusted"
                           for hook in verified)):
                raise IntegrationError("Codex 未确认八条 Hook 已启用并受信任")
            self._require_reviewed_files(digest)
            self._merge_state(installed=True, trusted=True, prepared_digest=reviewed_digest, consented_digest=reviewed_digest,
                              hook_hashes=reviewed_hashes, hook_keys=[hook["key"] for hook in verified],
                              last_error=None, verified_at=time.time(), marketplace_retained=True)
            return self.status(refresh=False)
        except Exception as error:
            failure = error if isinstance(error, IntegrationError) else IntegrationError(str(error))
            if trust_attempted:
                try:
                    self._configure(trust_attempted, enabled=False, trust=False)
                except Exception:
                    failure = IntegrationError(str(failure) + "；自动禁用未获确认，请在 Codex 中禁用本插件")
            self._merge_state(last_error=str(failure), trusted=False)
            raise failure

    def disable(self) -> dict:
        """Disable every currently discoverable Hook owned by this Plugin only."""
        try:
            hooks = self._owned(self._list_hooks())
            self._configure(hooks, enabled=False, trust=False)
            remaining = self._owned(self._list_hooks())
            if any(hook.get("enabled") is not False for hook in remaining):
                raise IntegrationError("Codex 未确认 Keyphore Keydous Hook 已禁用")
            self._merge_state(trusted=False, last_error=None, verified_at=time.time())
            return self.status(refresh=False)
        except Exception as error:
            failure = error if isinstance(error, IntegrationError) else IntegrationError(str(error))
            self._merge_state(last_error=str(failure))
            raise failure

    def remove(self) -> dict:
        """Disable and remove only this Plugin; retain the local marketplace safely."""
        try:
            self.disable()
            plugins = self._plugins(self.rpc.cli(["plugin", "list", "--json"]))
            if PLUGIN_ID in plugins:
                self.rpc.cli(["plugin", "remove", PLUGIN_ID, "--json"])
            if PLUGIN_ID in self._plugins(self.rpc.cli(["plugin", "list", "--json"])):
                raise IntegrationError("Codex 未确认 Keyphore Keydous 插件已移除")
            self._merge_state(installed=False, trusted=False, hook_keys=[], hook_hashes={},
                              last_error=None, verified_at=time.time(), marketplace_retained=True)
            return self.status(refresh=False)
        except Exception as error:
            failure = error if isinstance(error, IntegrationError) else IntegrationError(str(error))
            self._merge_state(last_error=str(failure))
            raise failure

    def _read_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION else {}
        except (OSError, ValueError, UnicodeError):
            return {}

    def _merge_state(self, **changes: Any) -> None:
        state = self._read_state()
        state.update(schema_version=SCHEMA_VERSION, plugin_id=PLUGIN_ID)
        state.update(changes)
        _atomic_write(self.state_path, _json_bytes(state))

    def status(self, *, refresh: bool = False) -> dict:
        """Return cached lifecycle state; optionally perform explicit Codex inspection."""
        state = self._read_state()
        result = {
            "plugin_id": PLUGIN_ID,
            "marketplace_name": MARKETPLACE_NAME,
            "prepared": all(path.is_file() for path in self._files),
            "prepared_digest": state.get("prepared_digest"),
            "installed": bool(state.get("installed", False)),
            "trusted": bool(state.get("trusted", False)),
            "last_error": state.get("last_error"),
            "verified_at": state.get("verified_at"),
            "marketplace_retained": bool(state.get("marketplace_retained", True)),
        }
        if not refresh:
            return result
        try:
            result["installed"] = PLUGIN_ID in self._plugins(
                self.rpc.cli(["plugin", "list", "--json"]))
            hooks = self._owned(self._list_hooks()) if result["installed"] else []
            result["hook_count"] = len(hooks)
            if result["installed"]:
                review, _ = self._require_reviewed_files(state.get("consented_digest"))
                command = review["definitions"][0]["command"]
                hooks = self._validate_owned(hooks, command)
            result["trusted"] = (bool(result["installed"])
                                 and all(hook.get("enabled") is True
                                         and str(hook.get("trustStatus", "")).lower() == "trusted"
                                         for hook in hooks))
            result["last_error"] = None
            result["verified_at"] = time.time()
            self._merge_state(installed=result["installed"], trusted=result["trusted"],
                              last_error=None, verified_at=result["verified_at"])
        except Exception as error:
            result["last_error"] = str(error)
            result["trusted"] = False
            self._merge_state(last_error=result["last_error"], trusted=False)
        return result
