"""Behavioral checks for the Windows renderer, source, and hardware boundary."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from keydous_bridge.config import ConfigStore
from keydous_bridge.display import rgb565, device_animation
from keydous_bridge.events import EventState, FileSource, MAX_LINE
from keydous_bridge.iot import Device, IoTClient, parse_devices
from keydous_bridge.proto import field, frame, read_frame, decode, first, check_trailer
from keydous_bridge.rgb import RGBLink


DEVICE = Device("local-fixture", 1021, 12625, 16405, "USB", True)


class ProtocolTests(unittest.TestCase):
    def test_nj98_rgb_uses_final_inherited_constants_not_report_rate_commands(self):
        client = IoTClient()
        sent = []
        client._send = lambda device, message, checksum=0, **kw: sent.append((message, checksum))
        original = bytes([66, 8, 255, 0, 0, 0, 0])
        client._read = lambda *a, **kw: b"\x87" + original + bytes(56)
        with patch("keydous_bridge.iot.time.sleep"):
            self.assertEqual(client.read_rgb(DEVICE), original)
            client.write_rgb(DEVICE, original)
        self.assertEqual(sent, [(b"\x87" + bytes(63), 0), (b"\x07" + original + bytes(56), 1)])

    def test_rgb565_uses_column_major_big_endian(self):
        image = Image.new("RGB", (2, 2))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])
        self.assertEqual(rgb565(image), bytes.fromhex("f800001f07e0ffff"))

    def test_animation_duration_and_frame_limit(self):
        frames = [Image.new("RGB", (160, 80), color) for color in ("red", "blue")]
        encoded, delay = device_animation(frames, [280, 120])
        self.assertEqual((len(encoded), delay), (4, 100))
        self.assertEqual(encoded[0], encoded[2])
        self.assertNotEqual(encoded[2], encoded[3])
        self.assertTrue(all(len(item) == 25600 for item in encoded))
        with self.assertRaises(ValueError):
            device_animation(frames, [10000, 10000])

    def test_wire_framing_and_unavailable_battery(self):
        device = field(3, "fixture") + field(4, 1021) + field(6, 1) + field(7, 12625) + field(8, 16405)
        payload = field(1, field(1, device))
        self.assertEqual(read_frame(io.BytesIO(frame(payload))), (0, payload))
        _, devices = parse_devices(payload)
        self.assertIsNone(devices[0].battery)
        self.assertTrue(devices[0].public()["capabilities"]["upload"])
        receiver = field(1, field(2, field(1, 75) + field(2, 1))) + field(3, "receiver") + field(5, 2147484669) + field(7, 12625) + field(8, 16401)
        _, devices = parse_devices(field(1, field(2, receiver)))
        self.assertEqual((devices[0].identifier, devices[0].battery, devices[0].connection), (-2147484669, 75, "2.4G"))
        self.assertFalse(devices[0].public()["capabilities"]["upload"])
        with self.assertRaises((ValueError, OSError)):
            check_trailer(b"grpc-status: 7\r\n")
        with self.assertRaises((ValueError, EOFError)):
            read_frame(io.BytesIO(b"\x00\x00\x10\x00\x01"))

    def test_upload_packet_layout_and_final_padding(self):
        client = IoTClient()
        packets, pauses, progress = [], [], []
        client._rpc = lambda method, payload=b"", **kw: pauses.append(first(decode(payload), 1)) or b""
        client._send = lambda device, message, **kw: packets.append(message)
        client._read = lambda *a, **kw: b"\xa5\x01"
        with patch("keydous_bridge.iot.time.sleep"):
            client.upload(DEVICE, [b"\xaa" * 25600, b"\xbb" * 25600], (160, 80), 3, 100, progress.append, threading.Event())
        self.assertEqual(pauses, [1, 0])
        self.assertEqual(packets[0], bytes.fromhex("a5000264006400000000a05000000000000002"))
        self.assertEqual(len(packets), 1 + 458 * 2)
        self.assertEqual(packets[458][:8], bytes([0x25, 0, 2, 100, 201, 1, 8, 0]))
        self.assertEqual(packets[458][8:], b"\xaa" * 8 + bytes(48))
        self.assertEqual(progress[-1], 1)

    def test_uncertain_pause_and_cancel_always_resume_polling(self):
        client = IoTClient()
        calls = []
        def rpc(method, payload=b"", **kw):
            calls.append(first(decode(payload), 1))
            if len(calls) == 1:
                raise OSError("uncertain pause")
            return b""
        client._rpc = rpc
        with self.assertRaisesRegex(OSError, "uncertain pause"):
            client.upload(DEVICE, [bytes(25600)] * 2, (160, 80), 1, 100, lambda p: None, threading.Event())
        self.assertEqual(calls, [1, 0])
        with self.assertRaises(ValueError):
            client.read_rgb(Device("similar", 1259, 12625, 16405, "USB", True))


class SourceTests(unittest.TestCase):
    def test_desktop_turn_binding_staleness_and_late_events(self):
        state = EventState("desktop")
        def accept(kind, turn, stamp):
            from datetime import datetime, timezone
            state.accept({"timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(), "type": "event_msg", "payload": {"type": kind, "turn_id": turn}}, 1000)
        accept("task_started", "current", 900)
        accept("task_complete", "old", 910)
        self.assertEqual(state.snapshot(911)["state"], "working")
        accept("task_started", "old", 800)
        self.assertEqual(state.active_turn, "current")
        self.assertEqual(state.snapshot(1081)["state"], "unknown")
        accept("task_complete", "current", 920)
        self.assertEqual(state.snapshot(921)["state"], "success")
        self.assertEqual(state.snapshot(927)["state"], "idle")

    def test_cli_bootstrap_uses_file_time_and_handles_partial_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.write_text('{"type":"turn.started"}\n')
            os.utime(path, (time.time() - 1000, time.time() - 1000))
            source = FileSource(path, "jsonl")
            self.assertEqual(source.poll()["state"], "unknown")
            with path.open("ab") as file:
                file.write(b'{"type":"item.started","item":{"type":"command_execution"}}')
            self.assertEqual(source.poll()["state"], "unknown")
            with path.open("ab") as file:
                file.write(b'\n')
            self.assertEqual(source.poll()["state"], "working")
            path.write_text('{"type":"turn.started"}\n{"type":"error"}\n')
            self.assertEqual(source.poll()["state"], "idle")

    def test_oversized_line_is_discarded_until_next_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.write_bytes(b"x" * (MAX_LINE + 50))
            source = FileSource(path, "jsonl")
            with path.open("ab") as file:
                file.write(b'\n{"type":"turn.started"}\n')
            self.assertEqual(source.poll()["state"], "thinking")
            self.assertLessEqual(len(source.buffer), MAX_LINE)


class RGBTests(unittest.TestCase):
    def test_journal_before_first_write_and_exact_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            original = bytes([0, 1, 0, 0, 0, 0, 123])
            class Client:
                value = original
                writes = []
                def read_rgb(self, device): return self.value
                def write_rgb(self, device, value):
                    assert (Path(folder) / "rgb-recovery.json").exists()
                    self.value = value
                    self.writes.append(value)
            client = Client()
            link = RGBLink(client, Path(folder))
            link.enable(DEVICE)
            self.assertEqual(client.writes, [])
            link.update(DEVICE, "working", now=100)
            link.update(DEVICE, "waiting", now=105)
            self.assertEqual(len(client.writes), 1)
            link.restore(DEVICE)
            self.assertEqual(client.value, original)
            self.assertFalse(link.path.exists())

    def test_disconnect_retains_journal_and_corruption_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rgb-recovery.json"
            path.write_text('{"device_key":"' + DEVICE.key + '","settings":"0001000000007b"}')
            link = RGBLink(None, Path(folder))
            with self.assertRaises(ValueError): link.restore(None)
            self.assertTrue(path.exists())
            path.write_text("broken")
            link = RGBLink(None, Path(folder))
            with self.assertRaisesRegex(ValueError, "不能覆盖"): link.enable(DEVICE)
            self.assertEqual(path.read_text(), "broken")

    def test_restart_never_enables_hardware_automatically(self):
        with tempfile.TemporaryDirectory() as folder:
            config = ConfigStore(Path(folder))
            config.update({"rgb_enabled": True, "source": "hooks"})
            restarted = ConfigStore(Path(folder))
            self.assertFalse(restarted.value["rgb_enabled"])
            self.assertEqual(restarted.value["source"], "hooks")
            with self.assertRaises(ValueError): restarted.update({"slot": True})


if __name__ == "__main__":
    unittest.main()
