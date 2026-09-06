# SPDX-License-Identifier: GPL-3.0-only
# Uses BarryBarrywu/Keyphore's tests/fixtures/swift-parity.json unchanged.
# Upstream: https://github.com/BarryBarrywu/Keyphore (9ca11f275809).
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from keydous_bridge.hook_core import HookStore, HookStoreError, normalize_hook


def event(name, session="s", turn="t1", agent=None, **extra):
    result = {"hook_event_name": name, "session_id": session, "turn_id": turn, **extra}
    if agent is not None:
        result["agent_id"] = agent
    return result


def write_session(path, number):
    store = HookStore(Path(path), lock_timeout=3)
    store.handle(event("UserPromptSubmit", session=f"session-{number}"), now=100)
    store.handle(event("PermissionRequest", session=f"session-{number}"), now=101)


class HookCoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "status.json"
        self.store = HookStore(self.path)

    def test_upstream_swift_parity_fixture_all_scenarios(self):
        fixture = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/swift-parity.json").read_text())
        states = {"off": "idle", "execution": "working", "attention": "waiting", "completion": "success"}
        for scenario in fixture["scenarios"]:
            store = HookStore(self.path.with_name(scenario["id"] + ".json"))
            for step in scenario["steps"]:
                now = step["at"] / 1000
                if "event" in step:
                    store.handle(step["event"], now=now)
                if step.get("restart"):
                    store = HookStore(store.path)
                with self.subTest(scenario=scenario["id"], at=step["at"]):
                    self.assertEqual(store.snapshot(now=now)["state"], states[step["aggregate"]])
                    raw = store.path.read_text()
                    for marker in fixture["private_markers"]:
                        self.assertNotIn(marker, raw)

    def test_summary_groups_agents_into_one_session_and_keeps_owners_independent(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        self.store.handle(event("SubagentStart", agent="child", turn="child-turn"), now=1)
        self.store.handle(event("PermissionRequest", agent="child", turn="child-turn"), now=2)
        self.store.handle(event("PermissionRequest", session="other"), now=3)
        self.assertEqual(self.store.snapshot(now=3)["summary"], {"attention": 2, "execution": 0, "completion": 0})
        self.store.handle(event("Stop", session="other"), now=4)
        self.assertEqual(self.store.snapshot(now=4)["state"], "waiting")
        self.store.handle(event("SubagentStop", agent="child", turn="child-turn"), now=5)
        self.assertEqual(self.store.snapshot(now=5)["summary"], {"attention": 0, "execution": 1, "completion": 1})

    def test_completion_and_expiry_do_not_allow_late_same_turn_revival(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        self.store.handle(event("Stop"), now=1)
        generation = self.store.snapshot(now=1)["generation"]
        for name in ("PostToolUse", "PermissionRequest", "UserPromptSubmit", "Stop"):
            self.store.handle(event(name), now=2)
        self.assertEqual(self.store.snapshot(now=5.999)["state"], "success")
        self.assertEqual(self.store.snapshot(now=6)["state"], "idle")
        self.assertEqual(self.store.snapshot(now=6)["generation"], generation)
        self.store.handle(event("PermissionRequest"), now=4000)
        self.assertEqual(self.store.snapshot(now=4000)["state"], "idle")

    def test_old_turn_cannot_overwrite_new_main_or_child_turn(self):
        for name, agent in (("UserPromptSubmit", None), ("SubagentStart", "child")):
            for turn, now in (("old", 0), ("new", 1)):
                self.store.handle(event(name, agent=agent, turn=turn), now=now)
            baseline = self.path.read_bytes()
            for delayed in (name, "PermissionRequest", "PostToolUse", "SubagentStop" if agent else "Stop"):
                self.store.handle(event(delayed, agent=agent, turn="old"), now=2)
            self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.store.snapshot(now=3600)["state"], "working")
        self.assertEqual(self.store.snapshot(now=3601)["state"], "idle")

    def test_main_turn_advance_marks_existing_child_generation_terminal(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        self.store.handle(event("SubagentStart", agent="child", turn="child-1"), now=1)
        self.store.handle(event("UserPromptSubmit", turn="t2"), now=2)
        self.store.handle(event("PermissionRequest", agent="child", turn="child-1"), now=3)
        self.assertEqual(self.store.snapshot(now=3)["state"], "working")
        self.store.handle(event("SubagentStart", agent="child", turn="child-2"), now=4)
        self.store.handle(event("PermissionRequest", agent="child", turn="child-2"), now=5)
        self.assertEqual(self.store.snapshot(now=5)["state"], "waiting")

    def test_session_lifecycle_clears_owners_but_retains_terminal_evidence(self):
        for lifecycle in ("SessionEnd", "SessionStart"):
            with self.subTest(lifecycle=lifecycle):
                store = HookStore(self.path.with_name(lifecycle + ".json"))
                store.handle(event("UserPromptSubmit"), now=0)
                store.handle(event("SubagentStart", agent="child"), now=1)
                store.handle({"hook_event_name": lifecycle, "session_id": "s"}, now=2)
                store.handle(event("PostToolUse", agent="child"), now=3)
                store.handle(event("PermissionRequest"), now=3)
                self.assertEqual(store.snapshot(now=3)["state"], "idle")
                store.handle(event("UserPromptSubmit", turn="next"), now=4)
                self.assertEqual(store.snapshot(now=4)["state"], "working")

    def test_attention_and_execution_expire_at_exact_hour(self):
        self.store.handle(event("PermissionRequest", session="attention"), now=0)
        self.store.handle(event("UserPromptSubmit", session="execution"), now=1)
        self.assertEqual(self.store.snapshot(now=3599.999)["state"], "waiting")
        self.assertEqual(self.store.snapshot(now=3600)["state"], "working")
        self.assertEqual(self.store.snapshot(now=3601)["state"], "idle")

    def test_missing_corrupt_and_oversized_state_are_unavailable_and_not_overwritten(self):
        self.assertEqual(self.store.snapshot(now=0)["validity"], "unknown")
        for raw in (b"{", b"{}", b'{"schema_version":1,"schema_version":1}', b"[1]"):
            self.path.write_bytes(raw)
            self.assertEqual(self.store.snapshot(now=0)["state"], "unknown")
            with self.assertRaises(HookStoreError):
                self.store.handle(event("UserPromptSubmit"), now=1)
            self.assertEqual(self.path.read_bytes(), raw)
        with patch("keydous_bridge.hook_core.MAX_STATE_BYTES", 8):
            self.path.write_bytes(b" " * 9)
            self.assertEqual(self.store.snapshot(now=0)["validity"], "unknown")

    def test_invalid_nested_state_and_private_extra_fields_rejected(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        original = json.loads(self.path.read_text())
        for field, value in (("generation", True), ("expires_at", float("nan")), ("terminal", "false"), ("signal", "failure"), ("prompt", "SECRET")):
            raw = json.loads(json.dumps(original))
            raw["owners"][0][field] = value
            self.path.write_text(json.dumps(raw))
            self.assertEqual(self.store.snapshot(now=0)["state"], "unknown")

    def test_allowlist_validation_rejects_ambiguous_ids_without_echoing_input(self):
        normalized = normalize_hook(event("PermissionRequest", prompt="SECRET", tool_input={"password": "SECRET"}))
        self.assertEqual(set(normalized), {"hook_event_name", "session_id", "agent_id", "turn_id"})
        for invalid in (event("Failure"), event("UserPromptSubmit", turn=""), event("SubagentStart"), event("SubagentStart", agent="main"), event("UserPromptSubmit", session="SECRET" * 256)):
            with self.assertRaises(HookStoreError) as caught:
                self.store.handle(invalid, now=0)
            self.assertNotIn("SECRET", str(caught.exception))
        self.assertFalse(self.path.exists())

    def test_capacities_fail_without_evicting_or_partially_persisting(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        original = self.path.read_bytes()
        with patch("keydous_bridge.hook_core.MAX_OWNERS", 1):
            with self.assertRaisesRegex(HookStoreError, "capacity"):
                self.store.handle(event("UserPromptSubmit", session="other"), now=1)
        with patch("keydous_bridge.hook_core.MAX_PREVIOUS_TURNS", 0):
            with self.assertRaisesRegex(HookStoreError, "capacity"):
                self.store.handle(event("UserPromptSubmit", turn="t2"), now=1)
        self.assertEqual(self.path.read_bytes(), original)

    def test_atomic_replace_failure_preserves_previous_state_and_cleans_temp(self):
        self.store.handle(event("UserPromptSubmit"), now=0)
        original = self.path.read_bytes()
        with patch("keydous_bridge.hook_core.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(HookStoreError):
                self.store.handle(event("PermissionRequest"), now=1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_lock_contention_is_bounded(self):
        store = HookStore(self.path, lock_timeout=0.03)
        with self.store._lock():
            started = time.monotonic()
            with self.assertRaisesRegex(HookStoreError, "Timed out"):
                store.handle(event("UserPromptSubmit"), now=0)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(store.snapshot(now=0)["state"], "unknown")

    def test_session_lifecycle_ignores_unrelated_turn_and_retains_observation_time(self):
        self.store.handle(event("UserPromptSubmit"), now=10)
        self.assertEqual(self.store.snapshot(now=20)["observed_at"], 10)
        self.store.handle(event("SessionEnd", turn={"unrelated": True}), now=21)
        self.assertEqual(self.store.snapshot(now=30)["state"], "idle")
        self.assertEqual(self.store.snapshot(now=30)["observed_at"], 21)

    def test_separate_process_updates_do_not_lose_owners(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(write_session, str(self.path), number) for number in range(24)]
            for future in futures:
                future.result(timeout=20)
        state = self.store.snapshot(now=102)
        self.assertEqual(state["summary"], {"attention": 24, "execution": 0, "completion": 0})
        self.assertEqual(state["generation"], 48)
        self.assertEqual(len(json.loads(self.path.read_text())["owners"]), 24)


if __name__ == "__main__":
    unittest.main()
