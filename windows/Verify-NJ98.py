"""Explicit reversible RGB acceptance check. No screen/firmware writes."""
import argparse
from pathlib import Path
from keydous_bridge.iot import IoTClient
from keydous_bridge.rgb import RGBLink

parser = argparse.ArgumentParser()
parser.add_argument("--rgb", action="store_true", required=True)
parser.add_argument("--data-dir", type=Path, required=True)
args = parser.parse_args()
args.data_dir.mkdir(parents=True, exist_ok=True)
client = IoTClient()
devices = [item for item in client.discover() if item.public()["capabilities"]["rgb"]]
if len(devices) != 1:
    raise SystemExit("Exactly one supported USB NJ98 required")
device = devices[0]
original = client.read_rgb(device)
link = RGBLink(client, args.data_dir)
print("Original:", list(original), flush=True)
link.enable(device)
try:
    link.update(device, "working")
    print("Link status:", link.snapshot(), flush=True)
    actual = client.read_rgb(device)
    print("Working readback:", list(actual), flush=True)
    assert actual == bytes([1, 4, 2, 7, 58, 189, 231]), "Working RGB readback mismatch"
finally:
    link.restore(device)
restored = client.read_rgb(device)
print("Restored:", list(restored), flush=True)
assert restored == original, "Original RGB readback mismatch"
print("RGB_TEST_PASS", flush=True)
