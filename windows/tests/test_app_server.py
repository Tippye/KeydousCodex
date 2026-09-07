import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from keydous_bridge.app import BridgeApp
from keydous_bridge.server import BridgeServer
from keydous_bridge.iot import Device


class AppServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = BridgeApp(Path(self.temp.name))
        self.server = BridgeServer(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.app.close()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            supplied = {"Content-Type": "application/json", "X-Bridge-Token": self.server.token}
            supplied.update(headers or {})
            connection.request("GET" if data is None else "POST", path,
                               body=None if data is None else json.dumps(data), headers=supplied)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.headers)
        finally:
            connection.close()

    def test_http_configuration_and_exact_draft_export(self):
        status, payload, _ = self.request("/api/config", {"source": "manual", "background": "#123456"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["background"], "#123456")
        status, payload, headers = self.request("/api/export.png?state=working&layout=dashboard&background=%23abcdef&pet_id=bridge-cat")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        with Image.open(io.BytesIO(payload)) as image:
            expected = self.app.render("working", options={"layout": "dashboard", "background": "#abcdef", "pet_id": "bridge-cat"})[0][0]
            self.assertEqual(image.convert("RGB").tobytes(), expected.tobytes())
        self.assertEqual(self.app.config.value["background"], "#123456")

    def test_origin_token_and_constrained_routes(self):
        for headers in ({"X-Bridge-Token": "wrong"}, {"Origin": "https://example.com"}, {"Host": "example.com"}):
            self.assertEqual(self.request("/api/config", {"source": "manual"}, headers)[0], 403)
        self.assertEqual(self.app.config.value["source"], "hooks")
        self.assertEqual(self.request("/api/raw-command", {"command": 0})[0], 404)
        self.assertEqual(self.request("/../config.json")[0], 404)
        self.assertEqual(self.request("/api/config", {"slot": False})[0], 400)
        self.assertEqual(self.request("/api/hooks/install", {"digest": "unknown"})[0], 400)

    def test_hooks_review_has_no_codex_side_effects_or_implicit_consent(self):
        self.assertIsNone(self.app.integration._rpc)
        status, payload, _ = self.request("/api/hooks/review", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(payload)["definitions"]), 8)
        self.assertIsNone(self.app.integration._rpc)
        self.assertFalse(self.app.integration.status()["trusted"])

    def test_knob_hotkey_conflict_prevents_firmware_write_and_requires_token(self):
        device = Device("fixture", 1021, 12625, 16405, "USB", True)
        self.app.devices = [device]
        with patch.object(self.app.client, "discover", return_value=[device]), \
             patch.object(self.app.knob, "start", side_effect=OSError("hotkey conflict")), \
             patch.object(self.app.mapping, "configure_knob") as write:
            status, _, _ = self.request("/api/mapping/knob-enable", {"revision": "test"})
            self.assertEqual(status, 503)
            write.assert_not_called()
            self.assertEqual(self.request("/api/mapping/knob-enable", {"revision": "test"},
                                          {"X-Bridge-Token": "wrong"})[0], 403)

    def test_shutdown_rejects_queued_mutations_and_does_not_wait_for_control_forever(self):
        held, release = threading.Event(), threading.Event()
        def operation():
            with self.app.control:
                held.set()
                release.wait(5)
        thread = threading.Thread(target=operation)
        thread.start()
        self.assertTrue(held.wait(1))
        try:
            started = time.monotonic()
            with patch.object(self.app.mac_fn,"close") as native_close:
                self.app.close()
                native_close.assert_called_once()
            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(self.app.integration.cancelled.is_set())
        finally:
            release.set()
            thread.join(2)
        self.assertEqual(self.request("/api/config", {"source": "manual"})[0], 400)
        self.assertEqual(self.app.config.value["source"], "hooks")

    def test_shutdown_during_render_cannot_start_hardware_upload(self):
        self.app.devices = [Device("fixture", 1021, 12625, 16405, "USB", True)]
        def render(**options):
            self.app.begin_close()
            return [Image.new("RGB", (160, 80))] * 2, [100, 100]
        with patch.object(self.app, "render", side_effect=render), patch.object(self.app.client, "upload") as upload:
            with self.assertRaisesRegex(ValueError, "上传准备已取消"):
                self.app.start_upload(3)
            self.assertIsNone(self.app.upload_worker)
            self.assertTrue(self.app.cancel.is_set())
            upload.assert_not_called()

    def test_mapping_rechecks_identity_before_read_and_rejects_upload_overlap(self):
        device = Device("fixture",1021,12625,16405,"USB",True)
        replaced = Device("fixture",1021,12625,20482,"USB",True)
        self.app.devices = [device]
        with patch.object(self.app.client,"discover",return_value=[replaced]), patch.object(self.app.mapping,"read") as read:
            self.assertEqual(self.request("/api/mapping/read",{})[0],400)
            read.assert_not_called()
        self.app.upload["active"] = True
        with patch.object(self.app.client,"discover") as discover:
            self.assertEqual(self.request("/api/mapping/read",{})[0],400)
            discover.assert_not_called()

    def test_native_enable_does_not_hold_firmware_control(self):
        entered, release = threading.Event(), threading.Event()
        def enable(_):
            entered.set()
            release.wait(3)
            return {"active":False}
        result = []
        with patch.object(self.app.mac_fn,"enable",side_effect=enable):
            thread = threading.Thread(target=lambda:result.append(self.request("/api/macos-fn/enable",{})))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                acquired = self.app.control.acquire(timeout=.1)
                self.assertTrue(acquired)
                if acquired:
                    self.app.control.release()
            finally:
                release.set()
                thread.join(3)
        self.assertEqual(result[0][0],200)

    def test_rgb_enable_resolves_candidate_auto_selection_not_old_device(self):
        first = Device("first", 1021, 12625, 16405, "USB", True)
        second = Device("second", 1021, 12625, 16405, "USB", True)
        self.app.devices = [first, second]
        self.app.config.update({"device_key": first.key})
        with patch.object(self.app.rgb, "enable") as enable:
            with self.assertRaisesRegex(ValueError, "选择键盘"):
                self.app.update_config({"device_key": "", "rgb_enabled": True})
            enable.assert_not_called()
        self.assertEqual(self.app.config.value["device_key"], first.key)


@unittest.skipUnless(os.name == "nt", "Windows hardware ownership")
class InstanceTests(unittest.TestCase):
    def test_two_processes_cannot_own_hardware_and_release_allows_next_owner(self):
        from keydous_bridge.instance import HardwareOwner
        script = "from keydous_bridge.instance import HardwareOwner\ntry:\n owner=HardwareOwner()\nexcept OSError:\n raise SystemExit(17)\nowner.close()"
        owner = HardwareOwner()
        try:
            process = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=3)
            self.assertEqual(process.returncode, 17)
        finally:
            owner.close()
        process = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=3)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()
