# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in acceptance against the real Codex CLI using an isolated CODEX_HOME."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from keydous_bridge.codex_rpc import CodexRPC
from keydous_bridge.hook_core import HookStore
from keydous_bridge.integration import Integration, PLUGIN_ID


@unittest.skipUnless(os.environ.get("KEYDOUS_RUN_CODEX_ACCEPTANCE") == "1",
                     "set KEYDOUS_RUN_CODEX_ACCEPTANCE=1 for isolated real-Codex acceptance")
class RealCodexLifecycleAcceptance(unittest.TestCase):
    def test_install_invoke_disable_remove(self):
        parent = Path(os.environ["KEYDOUS_CODEX_ACCEPTANCE_ROOT"]).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="hook-acceptance-", dir=parent) as temporary:
            root = Path(temporary)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            rpc = CodexRPC(environment=environment)
            integration = Integration(root / "bridge", rpc=rpc)
            installed = False
            try:
                review = integration.review()
                try:
                    status = integration.install(review["digest"])
                except Exception as error:
                    expected = review["definitions"][0]["command"]
                    diagnostics = [{
                        "eventName": hook.get("eventName"),
                        "handlerType": hook.get("handlerType"),
                        "executionMode": hook.get("executionMode"),
                        "matcher": hook.get("matcher"),
                        "commandMatches": hook.get("command") == expected,
                        "timeoutSec": hook.get("timeoutSec"),
                        "isManaged": hook.get("isManaged"),
                        "sourceSuffix": str(hook.get("sourcePath", "")).replace("\\", "/").lower().endswith("/hooks/hooks.json"),
                        "hasKey": bool(hook.get("key")),
                        "hasHash": bool(hook.get("currentHash")),
                        "keys": sorted(hook),
                    } for hook in integration._owned(integration._list_hooks())]
                    self.fail(f"{error}; metadata={json.dumps(diagnostics, ensure_ascii=True)}")
                installed = True
                self.assertTrue(status["installed"])
                self.assertTrue(status["trusted"])
                refreshed = integration.status(refresh=True)
                self.assertEqual(refreshed["hook_count"], 8)
                self.assertTrue(refreshed["trusted"])

                payload = {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "isolated-acceptance-session",
                    "turn_id": "isolated-acceptance-turn",
                    "prompt": "must not be persisted",
                }
                command = review["definitions"][0]["command"]
                started = time.monotonic()
                result = subprocess.run(command, input=json.dumps(payload).encode("utf-8"),
                                        capture_output=True, timeout=3, shell=True,
                                        env=environment)
                elapsed = time.monotonic() - started
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"")
                self.assertLess(elapsed, 2.0)
                snapshot = HookStore(integration.data_dir / "hook-state.json").snapshot()
                self.assertEqual(snapshot["state"], "working")
                persisted = (integration.data_dir / "hook-state.json").read_text(encoding="utf-8")
                self.assertNotIn("must not be persisted", persisted)

                disabled = integration.disable()
                self.assertFalse(disabled["trusted"])
                removed = integration.remove()
                installed = False
                self.assertFalse(removed["installed"])
                plugin_ids = Integration._plugins(rpc.cli(["plugin", "list", "--json"]))
                self.assertNotIn(PLUGIN_ID, plugin_ids)
            finally:
                if installed:
                    try:
                        integration.remove()
                    except Exception:
                        pass


if __name__ == "__main__":
    unittest.main()
