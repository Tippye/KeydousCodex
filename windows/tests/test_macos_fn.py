import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from keydous_bridge.macos_fn import MacFnController


class MacFnControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controller = MacFnController(Path(self.tmp.name))
        self.controller.supported = True
        self.controller.wrapper = Path(self.tmp.name)/"wrapper"
        self.controller.wrapper.write_text("fixture")

    def result(self, state="active", code=0):
        return subprocess.CompletedProcess([],code,json.dumps({"schemaVersion":1,"state":state,"active":state=="active","ready":state in {"ready","active"},"message":state}).encode(),b"")

    def test_only_validated_config_is_passed_and_temporary_removed(self):
        def run(args, **kwargs):
            self.assertEqual(args[1],"enable")
            path = Path(args[3])
            config = json.loads(path.read_text())
            self.assertEqual(config["target"],"native_fn")
            self.assertEqual(config["source"],{"usagePage":7,"usage":228})
            self.assertEqual(config["device"]["registryEntryId"],"42")
            self.assertNotIn("controllerPid",config)
            self.assertEqual(kwargs["stdin"],subprocess.DEVNULL)
            return self.result()
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",side_effect=run):
            self.assertTrue(self.controller.enable({"registry_entry_id":"42","source_usage":228})["active"])
        self.assertFalse(list(Path(self.tmp.name).glob("mac-fn-*.json")))

    def test_invalid_or_unobservable_source_input_does_not_invoke_native(self):
        with patch("keydous_bridge.macos_fn.subprocess.run") as run:
            for request in ({"registry_entry_id":"0","source_usage":228},{"registry_entry_id":"42","source_usage":57},{"registry_entry_id":"42","source_usage":True},{"registry_entry_id":"42","source_usage":228,"controllerPid":10}):
                with self.assertRaises(ValueError):
                    self.controller.enable(request)
            run.assert_not_called()

    def test_requires_approval_is_not_active_and_cannot_claim_enabled(self):
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",return_value=self.result("requires_approval",1)):
            with self.assertRaises(ValueError):
                self.controller.enable({"registry_entry_id":"42","source_usage":228})
            self.assertFalse(self.controller.snapshot()["active"])
            self.assertEqual(self.controller.snapshot()["state"],"requires_approval")

    def test_removal_uses_bounded_owned_helper_command_and_rejects_active_ack(self):
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",return_value=self.result("not_installed")) as run:
            self.assertFalse(self.controller.remove_helper()["active"])
            self.assertEqual(run.call_args.args[0],[str(self.controller.wrapper),"remove-helper","--json"])
            self.assertEqual(run.call_args.kwargs["timeout"],15)
            run.return_value = self.result("active")
            with self.assertRaises(ValueError):
                self.controller.remove_helper()

    def test_missing_binary_and_timeout_are_truthful(self):
        self.controller.wrapper.unlink()
        self.assertEqual(self.controller.refresh()["state"],"not_installed")
        self.controller.wrapper.write_text("fixture")
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",side_effect=subprocess.TimeoutExpired("status",8)):
            self.assertFalse(self.controller.refresh()["active"])
            self.assertEqual(self.controller.snapshot()["state"],"error")

    def test_lost_status_or_enable_ack_does_not_skip_stop(self):
        operations = []
        def run(args,**kwargs):
            operations.append(args[1])
            if args[1] != "disable":
                raise subprocess.TimeoutExpired(args[1],8)
            return self.result("ready")
        self.controller.status["active"] = True
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",side_effect=run):
            self.controller.refresh()
            self.controller.close()
        self.assertEqual(operations,["status","disable"])

    def test_close_during_enable_retracts_late_enable_and_blocks_new_requests(self):
        operations = []
        def run(args,**kwargs):
            operations.append(args[1])
            if args[1] == "enable":
                self.controller.begin_close()
                return self.result()
            return self.result("ready")
        with patch("keydous_bridge.macos_fn.os.access",return_value=True), patch("keydous_bridge.macos_fn.subprocess.run",side_effect=run):
            with self.assertRaises(ValueError):
                self.controller.enable({"registry_entry_id":"42","source_usage":228})
            self.assertEqual(operations,["enable","disable"])
            with self.assertRaises(ValueError):
                self.controller.enable({"registry_entry_id":"42","source_usage":228})
            self.assertEqual(operations,["enable","disable"])
