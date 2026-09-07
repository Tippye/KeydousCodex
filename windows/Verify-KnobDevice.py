"""Explicit NJ98 hardware acceptance: write three knob slots, read back, restore.

Requires exclusive ownership. Never uploads images or changes lights/Hooks.
An interrupted run leaves its recovery journal in data/knob-device-acceptance.
"""
import json
from pathlib import Path
import threading

from keydous_bridge.instance import HardwareOwner
from keydous_bridge.iot import IoTClient
from keydous_bridge.mapping import KNOB_ACTIONS, MappingService, action_token

directory = Path(__file__).resolve().parent / "data" / "knob-device-acceptance"
directory.mkdir(parents=True, exist_ok=True)
with HardwareOwner():
    client = IoTClient()
    devices = [d for d in client.discover() if d.online and d.identifier == 1021 and d.connection == "USB"]
    assert len(devices) == 1, "Expected exactly one NJ98 USB device"
    device = devices[0]
    service = MappingService(client, directory, threading.Event())
    if service.knob_saved():
        service.restore_knob(device)
    before = service.read(device)
    try:
        after = service.configure_knob(device, before["revision"])
        changes = [(bank, slot) for bank in ("normal", "fn") for slot in range(128)
                   if before[bank][slot] != after[bank][slot]]
        assert set(changes) <= {("normal", slot) for slot in KNOB_ACTIONS}, changes
        for slot, action in KNOB_ACTIONS.items():
            assert bytes(after["normal"][slot]) == action_token(action)
        print("NJ98_KNOB_WRITE_READBACK_PASS", flush=True)
    finally:
        if service.knob_saved():
            restored = service.restore_knob(device)
            assert restored["normal"] == before["normal"] and restored["fn"] == before["fn"]
            print("NJ98_KNOB_EXACT_RESTORE_PASS", flush=True)
    evidence = {"device_key": device.key, "changed_slots": changes,
                "original_knob": {str(s): before["normal"][s] for s in KNOB_ACTIONS},
                "configured_knob": {str(s): after["normal"][s] for s in KNOB_ACTIONS},
                "both_layers_restored": True, "physical_rotation_verified": False}
    (directory / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
