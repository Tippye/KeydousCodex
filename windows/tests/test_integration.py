# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keydous_bridge.hook_core import EVENTS
from keydous_bridge.integration import (
    CODEX_EVENT_NAMES, Integration, IntegrationError, MARKETPLACE_NAME, PLUGIN_ID,
)


class FakeRPC:
    def __init__(self):
        self.marketplaces = {"foreign-market"}
        self.plugins = {"foreign@foreign-market"}
        self.hooks = [{
            "key": "foreign:key", "eventName": "Stop", "handlerType": "command",
            "executionMode": "sync", "matcher": None, "command": "foreign.exe",
            "timeoutSec": 5, "sourcePath": "C:/foreign/hooks/hooks.json",
            "pluginId": "foreign@foreign-market", "enabled": True,
            "isManaged": False, "currentHash": "sha256:foreign", "trustStatus": "trusted",
        }]
        self.cli_calls = []
        self.requests = []
        self.fail_config = False

    def _materialize_hooks(self, root: Path):
        payload = json.loads((root / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        for index, event in enumerate(EVENTS):
            command = payload["hooks"][event][0]["hooks"][0]["command"]
            self.hooks.append({
                "key": f"{PLUGIN_ID}:hooks/hooks.json:{event}:0:0",
                "eventName": CODEX_EVENT_NAMES[event], "handlerType": "command", "executionMode": "sync",
                "matcher": None, "command": command, "timeoutSec": 2,
                "sourcePath": str(root / "plugin" / "hooks" / "hooks.json"),
                "pluginId": PLUGIN_ID, "enabled": True, "isManaged": False,
                "currentHash": f"sha256:{index:064x}", "trustStatus": "untrusted",
            })

    def cli(self, args):
        self.cli_calls.append(list(args))
        if args[:3] == ["plugin", "marketplace", "list"]:
            return {"marketplaces": [{"name": name} for name in sorted(self.marketplaces)]}
        if args[:3] == ["plugin", "marketplace", "add"]:
            root = Path(args[3])
            value = json.loads((root / ".agents" / "plugins" / "marketplace.json").read_text())
            self.marketplaces.add(value["name"])
            return {}
        if args[:2] == ["plugin", "list"]:
            return {"installed": [{"pluginId": item, "enabled": True}
                                  for item in sorted(self.plugins)]}
        if args[:2] == ["plugin", "add"]:
            self.plugins.add(args[2])
            roots = [Path(call[3]) for call in self.cli_calls
                     if call[:3] == ["plugin", "marketplace", "add"]]
            if not roots:
                raise AssertionError("marketplace root was not registered")
            self.hooks = [hook for hook in self.hooks if hook.get("pluginId") != PLUGIN_ID]
            self._materialize_hooks(roots[-1])
            return {}
        if args[:2] == ["plugin", "remove"]:
            self.plugins.discard(args[2])
            self.hooks = [hook for hook in self.hooks if hook.get("pluginId") != args[2]]
            return {}
        raise AssertionError(args)

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "hooks/list":
            return {"data": [{"hooks": [dict(item) for item in self.hooks], "errors": []}]}
        if method == "config/batchWrite":
            if self.fail_config:
                raise OSError("injected configuration failure")
            for edit in params["edits"]:
                matches = [hook for hook in self.hooks
                           if edit["keyPath"] == Integration._key_path(hook["key"])]
                if len(matches) != 1:
                    raise AssertionError("write escaped owned hook scope")
                hook = matches[0]
                hook["enabled"] = edit["value"]["enabled"]
                if "trusted_hash" in edit["value"]:
                    self.assert_hash(edit["value"]["trusted_hash"], hook["currentHash"])
                    hook["trustStatus"] = "trusted"
            return {}
        raise AssertionError(method)

    @staticmethod
    def assert_hash(actual, expected):
        if actual != expected:
            raise AssertionError("wrong trusted hash")


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rpc = FakeRPC()
        self.integration = Integration(Path(self.temp.name), rpc=self.rpc)

    def test_review_materializes_exact_eight_privacy_allowlisted_hooks(self):
        review = self.integration.review()
        self.assertEqual([item["event"] for item in review["definitions"]], list(EVENTS))
        self.assertEqual(review["privacy_fields"],
                         ["hook_event_name", "session_id", "agent_id", "turn_id"])
        self.assertIn("Always empty", review["stdout"])
        self.assertTrue(review["digest"].startswith("sha256:"))
        hooks = json.loads((self.integration.plugin_root / "hooks" / "hooks.json").read_text())
        self.assertEqual(set(hooks["hooks"]), set(EVENTS))
        if review["platform"] == "win32":
            self.assertIn("-EncodedCommand", review["definitions"][0]["command"])
            self.assertNotIn('"', review["definitions"][0]["command"])
        for groups in hooks["hooks"].values():
            definition = groups[0]["hooks"][0]
            if review["platform"] == "win32":
                self.assertEqual(definition["commandWindows"], definition["command"])
            else:
                self.assertNotIn("commandWindows", definition)
        self.assertIn("--hook", review["definitions"][0]["command_plaintext"])

    def test_review_and_cached_status_do_not_require_codex(self):
        integration = Integration(Path(self.temp.name) / "no-codex")
        review = integration.review()
        self.assertTrue(review["digest"].startswith("sha256:"))
        self.assertFalse(integration.status()["installed"])
        self.assertIsNone(integration._rpc)

    def test_install_rejects_wrong_digest_and_post_review_tampering_without_rpc(self):
        review = self.integration.review()
        with self.assertRaisesRegex(IntegrationError, "摘要"):
            self.integration.install("sha256:" + "0" * 64)
        self.assertEqual(self.rpc.cli_calls, [])
        hooks_path = self.integration.plugin_root / "hooks" / "hooks.json"
        hooks_path.write_bytes(hooks_path.read_bytes() + b" ")
        with self.assertRaisesRegex(IntegrationError, "发生变化"):
            self.integration.install(review["digest"])
        self.assertEqual(self.rpc.cli_calls, [])

    def test_install_trusts_only_owned_hooks_and_preserves_foreign_state(self):
        foreign_before = dict(self.rpc.hooks[0])
        review = self.integration.review()
        status = self.integration.install(review["digest"])
        self.assertTrue(status["installed"])
        self.assertTrue(status["trusted"])
        self.assertEqual(self.rpc.hooks[0], foreign_before)
        writes = [params for method, params in self.rpc.requests if method == "config/batchWrite"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(len(writes[0]["edits"]), len(EVENTS))
        self.assertTrue(all(edit["keyPath"].startswith("hooks.state.\"")
                            and edit["keyPath"] != "hooks.state" for edit in writes[0]["edits"]))
        self.assertNotIn("foreign:key", json.dumps(writes[0]))

    def test_foreign_hook_cannot_substitute_for_a_missing_owned_event(self):
        review = self.integration.review()
        original_add = self.rpc.cli

        def omit_one(args):
            result = original_add(args)
            if args[:2] == ["plugin", "add"]:
                victim = next(h for h in self.rpc.hooks
                              if h.get("pluginId") == PLUGIN_ID and h["eventName"] == "stop")
                self.rpc.hooks.remove(victim)
            return result

        self.rpc.cli = omit_one
        with self.assertRaisesRegex(IntegrationError, "数量"):
            self.integration.install(review["digest"])
        self.assertEqual(self.rpc.hooks[0]["pluginId"], "foreign@foreign-market")

    def test_partial_trust_failure_is_reported_without_claiming_trust(self):
        review = self.integration.review()
        self.rpc.fail_config = True
        with self.assertRaises(IntegrationError):
            self.integration.install(review["digest"])
        status = self.integration.status()
        self.assertTrue(status["installed"])
        self.assertFalse(status["trusted"])
        self.assertIn("injected configuration failure", status["last_error"])
        self.assertIn(PLUGIN_ID, self.rpc.plugins)
        self.assertIn("foreign@foreign-market", self.rpc.plugins)

    def test_changes_during_plugin_install_are_rechecked_before_trust(self):
        review = self.integration.review()
        original = self.rpc.cli
        def mutate(args):
            result = original(args)
            if args[:2] == ["plugin", "add"]:
                path = self.integration.plugin_root / "hooks" / "hooks.json"
                path.write_bytes(path.read_bytes() + b" ")
            return result
        self.rpc.cli = mutate
        with self.assertRaisesRegex(IntegrationError, "发生变化"):
            self.integration.install(review["digest"])
        self.assertFalse(any(method == "config/batchWrite" for method, _ in self.rpc.requests))

    def test_new_review_cannot_renew_prior_runtime_consent(self):
        review = self.integration.review()
        self.integration.install(review["digest"])
        with patch("keydous_bridge.integration._sha256_file", return_value="sha256:changed"):
            renewed = self.integration.review()
            self.assertNotEqual(renewed["digest"], review["digest"])
            status = self.integration.status(refresh=True)
            self.assertFalse(status["trusted"])
            self.assertTrue(status["last_error"])
        self.assertEqual(self.integration._read_state()["consented_digest"], review["digest"])

    def test_failed_reinstall_does_not_report_removed_plugin_installed(self):
        review = self.integration.review()
        self.integration.install(review["digest"])
        original = self.rpc.cli
        def fail_add(args):
            if args[:2] == ["plugin", "add"]:
                raise OSError("installation unavailable")
            return original(args)
        self.rpc.cli = fail_add
        with self.assertRaises(IntegrationError):
            self.integration.install(review["digest"])
        self.assertNotIn(PLUGIN_ID, self.rpc.plugins)
        self.assertFalse(self.integration.status()["installed"])
        self.assertFalse(self.integration.status()["trusted"])

    def test_disable_and_remove_are_scoped_and_marketplace_is_retained(self):
        review = self.integration.review()
        self.integration.install(review["digest"])
        foreign_before = dict(self.rpc.hooks[0])
        self.integration.disable()
        self.assertEqual(self.rpc.hooks[0], foreign_before)
        self.assertTrue(all(not hook["enabled"] for hook in self.rpc.hooks
                            if hook.get("pluginId") == PLUGIN_ID))
        result = self.integration.remove()
        self.assertFalse(result["installed"])
        self.assertIn("foreign@foreign-market", self.rpc.plugins)
        self.assertIn(MARKETPLACE_NAME, self.rpc.marketplaces)
        self.assertTrue(result["marketplace_retained"])
        self.assertEqual(self.rpc.hooks, [foreign_before])


if __name__ == "__main__":
    unittest.main()
