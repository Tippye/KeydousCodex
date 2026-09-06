"""NJ98 matrix acceptance; default read-only. --write briefly changes Calculator.

Requires the application to be closed. Always attempts restoration after a write.
"""
import argparse
import hashlib
import json
from pathlib import Path
import threading

from keydous_bridge.instance import HardwareOwner
from keydous_bridge.iot import IoTClient
from keydous_bridge.mapping import MappingService, FN

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", required=True, type=Path)
parser.add_argument("--write", action="store_true")
parser.add_argument("--bank", choices=("normal", "fn"), default="normal")
args = parser.parse_args()
args.data_dir.mkdir(parents=True, exist_ok=True)
with HardwareOwner():
    client = IoTClient()
    devices = [d for d in client.discover() if d.public()["capabilities"]["mapping"]]
    if len(devices) != 1:
        raise SystemExit("Exactly one supported USB NJ98 required")
    device = devices[0]
    service = MappingService(client,args.data_dir,threading.Event())
    before = service.read(device)
    assert before["normal"][65] == list(FN), "Physical Fn slot disagrees with source; stop"
    assert before["normal"][0] == [0,0,41,0], "Esc slot disagrees with source; stop"
    assert before["normal"][9] == [0,0,4,0], "A slot disagrees with source; stop"
    receipt = {"device_key":device.key, "revision":before["revision"], "lengths":{b:len(before[b])*4 for b in ("normal","fn")},
               "fn_slot":before["normal"][65], "calculator":before[args.bank][90], "bank":args.bank, "write_verified":False,
               "physical_input_verified":False}
    print(json.dumps(receipt),flush=True)
    if args.write:
        if before["recovery"]:
            raise SystemExit("Existing recovery must be handled before acceptance")
        action = "media:mute" if before[args.bank][90] != [3,0,226,0] else "media:calculator"
        try:
            after = service.apply(device,{"revision":before["revision"],"bank":args.bank,"slot":90,"action":action})
            assert after["revision"] != before["revision"]
            print("SINGLE_KEY_READBACK_PASS",flush=True)
        finally:
            if service.path.exists():
                restored = service.restore(device)
                assert restored["normal"] == before["normal"] and restored["fn"] == before["fn"]
                print("FULL_MATRIX_RESTORE_PASS",flush=True)
        receipt["write_verified"] = True
    (args.data_dir / ("mapping-acceptance-" + args.bank + ".json")).write_text(json.dumps(receipt,indent=2),encoding="utf-8")
    print("MAPPING_ACCEPTANCE_PASS",flush=True)
