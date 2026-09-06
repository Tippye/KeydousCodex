from __future__ import annotations

import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from PIL import Image, ImageDraw

from keydous_bridge.pets import PetLibrary, _read_asar_assets, _telemetry_line


def sheet_bytes(version: int = 1, *, shifted: bool = False) -> bytes:
    height = 1872 if version == 1 else 2288
    image = Image.new("RGBA", (1536, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for row in range(9 if version == 1 else 11):
        for column in range(8):
            x = column * 192 + (10 + column * 10 if shifted and row == 7 else 35)
            y = row * 208 + 45
            draw.rectangle((x, y, x + 20, y + 30), fill=(220, 40 + row * 8, 80, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


class PetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = PetLibrary(Path(self.temp.name) / "pets")

    def tearDown(self):
        self.temp.cleanup()

    def test_builtin_cat_is_listed_and_all_states_render_at_device_size(self):
        self.assertEqual(self.library.list()[0]["id"], "bridge-cat")
        expected_counts = {
            "idle": 6, "thinking": 6, "working": 6, "waiting": 6,
            "success": 4, "error": 8, "unknown": 6,
        }
        for state, count in expected_counts.items():
            with self.subTest(state=state):
                frames, durations = self.library.render(
                    "bridge-cat", state, "pet", "#102030", {}
                )
                self.assertEqual((len(frames), len(durations)), (count, count))
                self.assertTrue(all(frame.mode == "RGB" and frame.size == (160, 80) for frame in frames))
                self.assertTrue(all(duration > 0 for duration in durations))

    def test_valid_png_chunks_with_corrupt_pixels_are_not_imported(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        broken = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1536, 1872, 8, 6, 0, 0, 0)) + chunk(b"IDAT", b"broken-pixels") + chunk(b"IEND", b"")
        with self.assertRaises(ValueError):
            self.library.import_pet("Broken", {"spritesheetPath": "sheet.png"}, broken)
        self.assertEqual(len(self.library.list()), 1)
        self.assertEqual(list(self.library.directory.iterdir()), [])

    def test_import_uses_safe_generated_id_and_preserves_animation_motion(self):
        imported = self.library.import_pet(
            "My Moving Pet",
            {"id": "source-id", "spriteVersionNumber": 1, "spritesheetPath": "art/sheet.png"},
            sheet_bytes(shifted=True),
        )
        self.assertRegex(imported["id"], r"^my-moving-pet-[a-f0-9]{8}$")
        frames, durations = self.library.render(
            imported["id"], "working", "pet", "#000000", {}
        )
        self.assertEqual((len(frames), durations[-1]), (6, 220))

        def colored_left(frame):
            points = [(x, y) for y in range(80) for x in range(160) if frame.getpixel((x, y)) != (0, 0, 0)]
            return min(x for x, _ in points)

        # One union bbox is used for the whole animation, so source movement is retained.
        self.assertLess(colored_left(frames[0]), colored_left(frames[-1]))

    def test_manifest_rejects_bad_version_path_and_id(self):
        valid = sheet_bytes()
        invalid = [
            {"spriteVersionNumber": 3},
            {"spriteVersionNumber": 1, "spritesheetPath": "../sheet.png"},
            {"id": "../../outside", "spriteVersionNumber": 1},
            {"spriteVersionNumber": 1, "madeUpField": True},
        ]
        for manifest in invalid:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                self.library.import_pet("Unsafe", manifest, valid)
        self.assertEqual(list((Path(self.temp.name) / "pets").iterdir()), [])

    def test_actual_image_dimension_and_extension_are_verified(self):
        wrong = io.BytesIO()
        Image.new("RGB", (16, 16)).save(wrong, format="PNG")
        with self.assertRaisesRegex(ValueError, "1536×1872"):
            self.library.import_pet("Tiny", {"spriteVersionNumber": 1, "spritesheetPath": "sheet.png"}, wrong.getvalue())
        with self.assertRaisesRegex(ValueError, "扩展名"):
            self.library.import_pet("Wrong suffix", {"spriteVersionNumber": 1, "spritesheetPath": "sheet.webp"}, sheet_bytes())

    def test_dashboard_keeps_unknown_telemetry_unknown(self):
        self.assertEqual(_telemetry_line({"locks": {"num": None, "caps": None}, "connection": None, "battery": None}),
                         "NUM:? CAPS:? LINK:? BAT:?")
        self.assertEqual(_telemetry_line({"locks": {"num": True, "caps": False}, "connection": "BT2", "battery": 0}),
                         "NUM:1 CAPS:0 BT2 BAT:0%")
        frames, _ = self.library.render(
            "bridge-cat", "unknown", "dashboard", "#123456",
            {"locks": {"num": None, "caps": None}, "connection": None, "battery": None},
        )
        self.assertEqual(frames[0].size, (160, 80))
        self.assertNotEqual(frames[0].getpixel((0, 0)), (18, 52, 86))

    def test_existing_store_path_escape_is_not_listed(self):
        pet = Path(self.temp.name) / "pets" / "unsafe"
        pet.mkdir()
        (pet / "pet.json").write_text(json.dumps({
            "displayName": "Unsafe", "spriteVersionNumber": 1,
            "spritesheetPath": "../outside.png",
        }), encoding="utf-8")
        self.assertEqual([item["id"] for item in self.library.list()], ["bridge-cat"])
        with self.assertRaises(ValueError):
            self.library.render("unsafe", "idle", "pet", "#000000", {})

    def test_existing_store_symlink_is_not_followed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "pet.json").write_text(json.dumps({
            "displayName": "Linked", "spriteVersionNumber": 1,
            "spritesheetPath": "sheet.png",
        }), encoding="utf-8")
        (outside / "sheet.png").write_bytes(sheet_bytes())
        linked = Path(self.temp.name) / "pets" / "linked"
        try:
            os.symlink(outside, linked, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("此环境不允许创建目录符号链接")
        self.assertEqual([item["id"] for item in self.library.list()], ["bridge-cat"])
        with self.assertRaisesRegex(ValueError, "符号链接|重解析点"):
            self.library.render("linked", "idle", "pet", "#000000", {})

    def test_asar_rejects_malformed_and_out_of_range_indexes(self):
        path = Path(self.temp.name) / "bad.asar"
        raw = b"not-json"
        header_size = len(raw) + 8
        path.write_bytes(struct.pack("<4I", 4, header_size, len(raw) + 4, len(raw)) + raw)
        with self.assertRaisesRegex(ValueError, "JSON"):
            _read_asar_assets(path)

        index = {"files": {"webview": {"files": {"assets": {"files": {}}}}}}
        raw = json.dumps(index, separators=(",", ":")).encode()
        path.write_bytes(struct.pack("<4I", 4, len(raw) + 8, len(raw) + 4, len(raw)) + raw)
        with self.assertRaisesRegex(ValueError, "匹配数量"):
            _read_asar_assets(path)


if __name__ == "__main__":
    unittest.main()
