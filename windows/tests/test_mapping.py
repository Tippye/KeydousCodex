import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from keydous_bridge.iot import Device, IoTClient
from keydous_bridge.mapping import CONTROLS, FN, KNOB_ACTIONS, MappingService, action_token

D = Device("fixture", 1021, 12625, 16405, "USB", True)


class FakeClient:
    def __init__(self):
        self.lock = threading.RLock()
        normal = bytearray(512)
        normal[260:264] = FN
        normal[36:40] = bytes([0,0,4,0])
        normal[300:304] = bytes([0,0,50,0])  # invisible slot must survive
        self.matrices = {"normal": bytes(normal), "fn": bytes(512)}
        self.writes = []
        self.fail_after_write = False

    def read_key_matrix(self, device, bank, cancelled=None):
        if cancelled and cancelled.is_set():
            raise InterruptedError()
        return self.matrices[bank]

    def write_key(self, device, bank, slot, token):
        self.writes.append((bank,slot,token))
        raw = self.matrices[bank]
        self.matrices[bank] = raw[:slot*4] + token + raw[slot*4+4:]
        if self.fail_after_write:
            raise OSError("lost response after successful write")


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = FakeClient()
        self.stop = threading.Event()
        self.service = MappingService(self.client, Path(self.tmp.name), self.stop)

    def change(self, bank="normal", slot=9, action="key:5", snapshot=None):
        snapshot = snapshot or self.service.read(D)
        return self.service.apply(D, dict(revision=snapshot["revision"], bank=bank, slot=slot, action=action))

    def test_layout_unique_and_fn_is_firmware_only(self):
        self.assertEqual(len(CONTROLS), 101)
        self.assertEqual(len({c["slot"] for c in CONTROLS}),101)
        self.assertEqual(action_token("firmware-fn"),FN)
        self.assertEqual(action_token("combo:224:6"),bytes([0,224,6,0]))
        with self.assertRaises(ValueError):
            action_token("mac-fn")

    def test_apply_multiple_layers_and_restore_original_unknown_slots(self):
        before = dict(self.client.matrices)
        self.change()
        self.change("fn",18,"media:play")
        self.assertEqual(self.client.matrices["normal"][300:304],before["normal"][300:304])
        after = self.service.restore(D)
        self.assertEqual(self.client.matrices,before)
        self.assertFalse(after["recovery"])
        self.assertEqual(len(self.client.writes),4)

    def test_noop_has_no_write_or_journal(self):
        self.change(action="key:4")
        self.assertEqual(self.client.writes,[])
        self.assertFalse(self.service.path.exists())

    def test_stale_revision_and_unknown_slot_never_write(self):
        stale = self.service.read(D)
        self.change()
        with self.assertRaises(ValueError):
            self.change(action="key:6",snapshot=stale)
        with self.assertRaises(ValueError):
            self.change(slot=75)
        self.assertEqual(len(self.client.writes),1)

    def test_last_firmware_fn_cannot_be_removed(self):
        with self.assertRaises(ValueError):
            self.change(slot=65,action="disabled")
        self.assertEqual(self.client.writes,[])

    def test_lost_write_response_can_restore_after_restart(self):
        before = dict(self.client.matrices)
        self.client.fail_after_write = True
        with self.assertRaises(OSError):
            self.change()
        self.assertTrue(json.loads(self.service.path.read_text())["pending"])
        self.client.fail_after_write = False
        restarted = MappingService(self.client,Path(self.tmp.name),self.stop)
        with self.assertRaises(ValueError):
            self.change()
        restarted.restore(D)
        self.assertEqual(self.client.matrices,before)

    def test_external_change_aborts_restore_without_writes(self):
        self.change()
        raw = bytearray(self.client.matrices["normal"])
        raw[300] = 7
        self.client.matrices["normal"] = bytes(raw)
        with self.assertRaises(ValueError):
            self.service.restore(D)
        self.assertEqual(len(self.client.writes),1)
        self.assertTrue(self.service.path.exists())

    def test_short_matrix_and_corrupt_journal_never_write(self):
        self.client.matrices["fn"] = bytes(504)
        with self.assertRaises(OSError):
            self.change()
        self.client.matrices["fn"] = bytes(512)
        self.service.path.write_text('{}')
        with self.assertRaises(ValueError):
            self.change()
        self.assertEqual(self.client.writes,[])

    def test_restore_other_device_rejected(self):
        self.change()
        other = Device("other",1021,12625,16405,"USB",True)
        with self.assertRaises(ValueError):
            self.service.restore(other)

    def test_knob_restore_preserves_other_mapping_and_fn_layer(self):
        self.change()
        before = dict(self.client.matrices)
        configured = self.service.configure_knob(D, self.service.read(D)["revision"])
        self.assertTrue(configured["knob_configured"])
        self.assertEqual(self.client.matrices["fn"], before["fn"])
        for slot, action in KNOB_ACTIONS.items():
            self.assertEqual(self.client.matrices["normal"][slot*4:slot*4+4], action_token(action))
        with self.assertRaises(ValueError):
            self.change(slot=102)
        self.change(slot=12)
        before["normal"] = before["normal"][:48] + action_token("key:5") + before["normal"][52:]
        restored = self.service.restore_knob(D)
        self.assertFalse(restored["knob_configured"])
        self.assertEqual(self.client.matrices, before)

    def test_interrupted_knob_transaction_restores_only_knob_after_restart(self):
        self.change()
        before = dict(self.client.matrices)
        self.client.fail_after_write = True
        with self.assertRaises(OSError):
            self.service.configure_knob(D, self.service.read(D)["revision"])
        self.client.fail_after_write = False
        restarted = MappingService(self.client, Path(self.tmp.name), self.stop)
        self.assertTrue(restarted.knob_saved())
        restarted.restore_knob(D)
        self.assertEqual(self.client.matrices, before)

    def test_knob_conflict_and_stale_revision_do_not_write(self):
        before = self.service.read(D)
        self.change()
        with self.assertRaises(ValueError):
            self.service.configure_knob(D, before["revision"])
        self.service.configure_knob(D, self.service.read(D)["revision"])
        self.client.matrices["fn"] = b'\x07' + self.client.matrices["fn"][1:]
        count = len(self.client.writes)
        with self.assertRaises(ValueError):
            self.service.restore_knob(D)
        self.assertEqual(len(self.client.writes), count)

    def test_repeated_enable_preserves_knob_preimage(self):
        original = dict(self.client.matrices)
        for _ in range(2):
            self.service.configure_knob(D, self.service.read(D)["revision"])
        self.assertEqual(len(self.client.writes), 3)
        self.service.restore_knob(D)
        self.assertEqual(self.client.matrices, original)

    def test_interrupted_selective_restore_can_resume_after_restart(self):
        original = dict(self.client.matrices)
        self.service.configure_knob(D, self.service.read(D)["revision"])
        self.client.fail_after_write = True
        with self.assertRaises(OSError):
            self.service.restore_knob(D)
        self.client.fail_after_write = False
        restarted = MappingService(self.client, Path(self.tmp.name), self.stop)
        restarted.restore_knob(D)
        self.assertEqual(self.client.matrices, original)
        self.assertFalse(restarted.knob_saved())

    def test_length_preserving_backup_corruption_rejected(self):
        self.change()
        record = json.loads(self.service.path.read_text())
        record["original"]["normal"] = "ff" + record["original"]["normal"][2:]
        self.service.path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.service.restore(D)
        self.assertEqual(len(self.client.writes),1)


class MatrixProtocolTests(unittest.TestCase):
    def test_full_raw_blocks_and_exact_single_key_wire(self):
        client = IoTClient()
        packets = []
        client._send = lambda dev,payload,checksum=0,**kw: packets.append((payload,checksum))
        client._read = lambda *a,**kw: bytes(range(64))
        pauses = []
        client._rpc = lambda method,payload=b"",**kw: pauses.append((method,payload)) or b""
        with patch("keydous_bridge.iot.time.sleep"):
            self.assertEqual(client.read_key_matrix(D,"normal"),bytes(range(64))*8)
            self.assertEqual(client.read_key_matrix(D,"fn"),bytes(range(64))*8)
            client.write_key(D,"normal",9,bytes([0,0,5,0]))
        self.assertEqual(packets[0],(bytes([0x89,0,0])+bytes(61),0))
        self.assertEqual(packets[15],(bytes([0x90,0,7])+bytes(61),0))
        expected = bytearray(64)
        expected[:3] = bytes([0x13,0,9])
        expected[8:12] = bytes([0,0,5,0])
        self.assertEqual(packets[16],(bytes(expected),0))
        self.assertEqual([p[1] for p in pauses],[b'\x08\x01',b'\x08\x00'])

    def test_short_response_rejected_and_unknown_model_write_denied(self):
        client = IoTClient()
        client._send = lambda *a,**kw: None
        client._read = lambda *a,**kw: bytes(63)
        with patch("keydous_bridge.iot.time.sleep"), self.assertRaises(OSError):
            client.read_key_matrix(D,"normal")
        other = Device("other",1259,12625,16405,"USB",True)
        with self.assertRaises(ValueError):
            client.write_key(other,"normal",9,bytes(4))
