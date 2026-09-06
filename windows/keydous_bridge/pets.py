"""Validated Codex pet storage and 160x80 screen rendering.

Only the sprite formats verified in ``docs/codex-research.md`` are accepted.
Codex application assets are read from their packed ASAR entries in place; the
application package is never extracted, executed, or modified.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import struct
import subprocess
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError


CELL = (192, 208)
SHEET_SIZES = {1: (1536, 1872), 2: (1536, 2288)}
MAX_RESOURCE_BYTES = 12 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ASAR_INDEX_BYTES = 16 * 1024 * 1024
PET_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
BACKGROUND_RE = re.compile(r"#[0-9A-Fa-f]{6}\Z")
ALLOWED_MANIFEST_FIELDS = {
    "id", "displayName", "description", "spriteVersionNumber", "spritesheetPath"
}

# The row mapping is a bridge policy. Rows, counts and timings are the locally
# verified Codex format, and deliberately exclude unused tail cells.
ANIMATIONS = {
    "idle": (0, [280, 110, 110, 140, 140, 320]),
    "thinking": (8, [150, 150, 150, 150, 150, 280]),
    "working": (7, [120, 120, 120, 120, 120, 220]),
    "waiting": (6, [150, 150, 150, 150, 150, 260]),
    "success": (3, [140, 140, 140, 280]),
    "error": (5, [140, 140, 140, 140, 140, 140, 140, 240]),
    "unknown": (0, [280, 110, 110, 140, 140, 320]),
}
STATE_TAGS = {
    "idle": "IDLE", "thinking": "THINK", "working": "WORK",
    "waiting": "WAIT", "success": "DONE", "error": "ERROR",
    "unknown": "UNKNOWN",
}
CODEX_PETS = {
    "codex": "Codex", "dewey": "Dewey", "fireball": "Fireball",
    "hoots": "Hoots", "rocky": "Rocky", "seedy": "Seedy",
    "stacky": "Stacky", "bsod": "BSOD", "null-signal": "Null Signal",
}


def _is_link(path: Path) -> bool:
    """Recognize symlinks and Windows reparse points without following them."""
    try:
        stat = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or "\0" in value:
        raise ValueError("spritesheetPath 必须是安全的相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("spritesheetPath 不能离开宠物目录")
    if ":" in path.parts[0]:
        raise ValueError("spritesheetPath 不能包含驱动器")
    return path


def _clean_manifest(manifest: object, fallback_name: str | None = None) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("宠物 manifest 必须是对象")
    unknown = set(manifest) - ALLOWED_MANIFEST_FIELDS
    if unknown:
        raise ValueError("宠物 manifest 包含未支持字段")
    manifest_id = manifest.get("id")
    if manifest_id is not None and (not isinstance(manifest_id, str) or not PET_ID_RE.fullmatch(manifest_id)):
        raise ValueError("宠物 manifest id 无效")
    display = manifest.get("displayName", fallback_name)
    if not isinstance(display, str) or not display.strip() or len(display.strip()) > 120:
        raise ValueError("宠物名称无效")
    description = manifest.get("description")
    if description is not None:
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError("宠物说明无效")
        description = description.strip() or None
    version = manifest.get("spriteVersionNumber", 1)
    if type(version) is not int or version not in SHEET_SIZES:
        raise ValueError("spriteVersionNumber 必须是 1 或 2")
    sheet_path = _safe_relative_path(manifest.get("spritesheetPath", "spritesheet.webp"))
    return {
        "displayName": display.strip(),
        "description": description,
        "spriteVersionNumber": version,
        "spritesheetPath": sheet_path.as_posix(),
    }


def _validate_image(data: bytes, version: int) -> tuple[str, tuple[int, int]]:
    if not isinstance(data, bytes) or not data or len(data) > MAX_RESOURCE_BYTES:
        raise ValueError("精灵图必须存在且不超过 12 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            size = image.size
            frames = getattr(image, "n_frames", 1)
            if image_format not in {"PNG", "WEBP"} or frames != 1:
                raise ValueError("精灵图必须是单帧 PNG 或 WebP")
            if size != SHEET_SIZES[version]:
                expected = "×".join(map(str, SHEET_SIZES[version]))
                raise ValueError(f"版本 {version} 的精灵图尺寸必须为 {expected}")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("精灵图不是有效的 PNG 或 WebP") from exc
    return image_format.lower(), size


def _slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48]
    return normalized or "pet"


def _resolved_member(root: Path, path: Path, *, require_file: bool = False) -> Path:
    """Resolve an existing store member and reject every reparse component."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("宠物资源路径越界") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise ValueError("宠物资源不能使用符号链接或重解析点")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("宠物资源路径无效或越界") from exc
    if require_file and not resolved.is_file():
        raise ValueError("宠物精灵图不存在")
    return resolved


def _fit_rgba(source: Image.Image, canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if source.width < 1 or source.height < 1 or width < 1 or height < 1:
        return
    scale = min(width / source.width, height / source.height)
    target = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    sprite = source.resize(target, Image.Resampling.NEAREST)
    x = left + (width - target[0]) // 2
    y = top + (height - target[1]) // 2
    canvas.paste(sprite, (x, y), sprite)


def _font(size: int = 8):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before the scalable default font option.
        return ImageFont.load_default()


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, width: int = 160) -> None:
    font = _font(8)
    bounds = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (bounds[2] - bounds[0])) // 2, y), text, font=font, fill=(235, 244, 240))


def _telemetry_line(telemetry: object) -> str:
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    locks = telemetry.get("locks")
    locks = locks if isinstance(locks, dict) else {}

    def lock(name: str) -> str:
        value = locks.get(name)
        return "1" if value is True else "0" if value is False else "?"

    raw_connection = telemetry.get("connection")
    connection = "LINK:?"
    if isinstance(raw_connection, str):
        compact = raw_connection.strip().upper().replace(" ", "")
        if compact == "USB":
            connection = "USB"
        elif compact in {"2.4G", "2.4", "24G"}:
            connection = "2.4G"
        elif re.fullmatch(r"BT(?:[1-3])?", compact):
            connection = compact
    battery = telemetry.get("battery")
    battery_label = f"BAT:{battery}%" if type(battery) is int and 0 <= battery <= 100 else "BAT:?"
    return f"NUM:{lock('num')} CAPS:{lock('caps')} {connection} {battery_label}"


def _decorate(frame: Image.Image, state: str, layout: str, telemetry: object) -> Image.Image:
    if layout == "dashboard":
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, 159, 11), fill=(9, 15, 18))
        draw.rectangle((0, 68, 159, 79), fill=(9, 15, 18))
        draw.text((2, 1), _telemetry_line(telemetry), font=_font(7), fill=(210, 231, 225))
        _draw_centered(draw, STATE_TAGS[state], 69)
    elif state == "unknown":
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 68, 159, 79), fill=(9, 15, 18))
        _draw_centered(draw, "UNKNOWN", 69)
    return frame


def _cat_frame(state: str, index: int, count: int) -> Image.Image:
    """Draw the bridge's own small black cat; no Codex artwork is embedded."""
    image = Image.new("RGBA", (64, 56), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    bob = (index % 2) if state in {"working", "thinking", "waiting"} else 0
    if state == "success":
        bob = -((index + 1) % 2)
    body = (18, 20, 28, 255)
    edge = (74, 217, 190, 255) if state != "error" else (244, 92, 92, 255)
    # Tail movement, body, head and two pointed ears are deliberately chunky.
    tail_y = 31 + ((index % 3) - 1) * 3
    draw.line((47, 37 + bob, 57, tail_y, 61, 23 + (index % 2) * 4), fill=body, width=6)
    draw.rectangle((16, 29 + bob, 49, 45 + bob), fill=body, outline=edge, width=2)
    draw.rectangle((20, 13 + bob, 45, 34 + bob), fill=body, outline=edge, width=2)
    draw.polygon(((21, 14 + bob), (24, 5 + bob), (30, 14 + bob)), fill=body, outline=edge)
    draw.polygon(((35, 14 + bob), (42, 5 + bob), (44, 15 + bob)), fill=body, outline=edge)
    eye = (255, 219, 90, 255)
    if state == "error":
        draw.line((25, 20 + bob, 29, 24 + bob), fill=edge, width=2)
        draw.line((29, 20 + bob, 25, 24 + bob), fill=edge, width=2)
        draw.line((36, 20 + bob, 40, 24 + bob), fill=edge, width=2)
        draw.line((40, 20 + bob, 36, 24 + bob), fill=edge, width=2)
    elif not (state == "idle" and index == count - 1):
        draw.rectangle((26, 21 + bob, 28, 24 + bob), fill=eye)
        draw.rectangle((37, 21 + bob, 39, 24 + bob), fill=eye)
    draw.rectangle((30, 27 + bob, 35, 29 + bob), fill=(226, 130, 149, 255))
    if state == "thinking":
        draw.ellipse((49, 4, 53, 8), fill=edge)
        draw.ellipse((56, 0, 62, 6), outline=edge, width=2)
    elif state == "success":
        draw.line((9, 20, 14, 25, 9, 30), fill=(255, 219, 90, 255), width=2)
    elif state == "waiting":
        draw.text((3, 3), "." * (index % 4), font=_font(8), fill=edge)
    elif state == "working":
        leg = 2 if index % 2 else -2
        draw.line((23, 45 + bob, 20 + leg, 51), fill=body, width=5)
        draw.line((43, 45 + bob, 46 - leg, 51), fill=body, width=5)
    return image


def _common_crops(sheet: Image.Image, row: int, count: int) -> list[Image.Image]:
    cells = []
    union = None
    for column in range(count):
        cell = sheet.crop((column * CELL[0], row * CELL[1], (column + 1) * CELL[0], (row + 1) * CELL[1])).convert("RGBA")
        alpha_box = cell.getchannel("A").getbbox()
        if alpha_box:
            union = alpha_box if union is None else (
                min(union[0], alpha_box[0]), min(union[1], alpha_box[1]),
                max(union[2], alpha_box[2]), max(union[3], alpha_box[3]),
            )
        cells.append(cell)
    if union is None:
        union = (0, 0, CELL[0], CELL[1])
    return [cell.crop(union) for cell in cells]


def _asar_files(node: object) -> dict:
    if not isinstance(node, dict) or not isinstance(node.get("files"), dict):
        raise ValueError("ASAR 索引目录结构无效")
    return node["files"]


def _read_asar_assets(path: Path) -> dict[str, bytes]:
    """Read exactly the nine allowlisted spritesheets from a validated ASAR."""
    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(16)
            if len(header) != 16:
                raise ValueError("ASAR 文件头不完整")
            marker, header_size, _index_pickle_size, index_size = struct.unpack("<4I", header)
            data_start = 8 + header_size
            if (marker != 4 or index_size < 2 or index_size > MAX_ASAR_INDEX_BYTES
                    or header_size < index_size + 8 or data_start > file_size
                    or 16 + index_size > data_start):
                raise ValueError("ASAR 文件头或索引范围无效")
            raw_index = stream.read(index_size)
            try:
                index = json.loads(raw_index.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("ASAR 索引 JSON 无效") from exc
            files = _asar_files(index)
            for part in ("webview", "assets"):
                node = files.get(part)
                files = _asar_files(node)

            result = {}
            for pet_id in CODEX_PETS:
                pattern = re.compile(rf"{re.escape(pet_id)}-spritesheet-[A-Za-z0-9._-]+\.webp\Z")
                matches = [(name, entry) for name, entry in files.items()
                           if isinstance(name, str) and pattern.fullmatch(name)]
                if len(matches) != 1:
                    raise ValueError(f"ASAR 中 {pet_id} 精灵图匹配数量不是 1")
                name, entry = matches[0]
                if not isinstance(entry, dict) or "link" in entry or entry.get("unpacked") is not None:
                    raise ValueError(f"ASAR 中 {name} 不是普通打包资源")
                offset, size = entry.get("offset"), entry.get("size")
                if not isinstance(offset, str) or not offset.isdecimal():
                    raise ValueError(f"ASAR 中 {name} 偏移无效")
                if type(size) is not int or size < 1 or size > MAX_RESOURCE_BYTES:
                    raise ValueError(f"ASAR 中 {name} 大小无效")
                absolute = data_start + int(offset)
                if absolute < data_start or absolute > file_size or size > file_size - absolute:
                    raise ValueError(f"ASAR 中 {name} 数据范围越界")
                stream.seek(absolute)
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError(f"ASAR 中 {name} 数据不完整")
                _validate_image(data, 2)
                result[pet_id] = data
            return result
    except OSError as exc:
        raise ValueError(f"无法读取 Codex ASAR：{exc}") from exc


def _find_codex_asar() -> Path:
    if sys.platform == "darwin":
        candidates = [bundle / "Contents/Resources/app.asar" for bundle in
                      (Path("/Applications/Codex.app"), Path.home() / "Applications/Codex.app")]
        found = [path for path in candidates if path.is_file()]
        if len(found) != 1:
            raise ValueError("未找到唯一 Codex.app 资源；请保留一个安装位置或手动导入宠物")
        return found[0]
    if os.name != "nt":
        raise ValueError("此系统请手动导入宠物资源")
    command = (
        "$p = @(Get-AppxPackage -Name 'OpenAI.Codex' | "
        "Where-Object { $_.Name -eq 'OpenAI.Codex' }); "
        "if ($p.Count -eq 1) { $p[0].InstallLocation }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            check=False, shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("无法查询 OpenAI.Codex Appx 安装位置") from exc
    locations = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(locations) != 1:
        raise ValueError("未找到唯一的 OpenAI.Codex Appx 安装包")
    install = Path(locations[0])
    asar = install / "app" / "resources" / "app.asar"
    if not asar.is_file():
        raise ValueError("OpenAI.Codex Appx 中没有 app/resources/app.asar")
    return asar


class PetLibrary:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if _is_link(self.directory):
            raise ValueError("宠物存储目录不能是符号链接或重解析点")
        self.directory = self.directory.resolve(strict=True)

    def _asset(self, pet_id: str) -> dict:
        if pet_id == "bridge-cat":
            return {"id": pet_id, "name": "Bridge Cat", "description": "本程序原创的黑猫像素动画", "builtin": True}
        if not isinstance(pet_id, str) or not PET_ID_RE.fullmatch(pet_id):
            raise ValueError("宠物标识无效")
        pet_dir = _resolved_member(self.directory, self.directory / pet_id)
        if not pet_dir.is_dir():
            raise ValueError("宠物不存在")
        manifest_path = _resolved_member(self.directory, pet_dir / "pet.json", require_file=True)
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("宠物 manifest 过大")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("宠物 manifest 无效") from exc
        clean = _clean_manifest(manifest)
        relative = _safe_relative_path(clean["spritesheetPath"])
        sheet_path = _resolved_member(self.directory, pet_dir.joinpath(*relative.parts), require_file=True)
        # The resolved image must remain inside this exact pet directory as well.
        try:
            sheet_path.relative_to(pet_dir)
        except ValueError as exc:
            raise ValueError("宠物精灵图路径越界") from exc
        if sheet_path.stat().st_size < 1 or sheet_path.stat().st_size > MAX_RESOURCE_BYTES:
            raise ValueError("精灵图必须存在且不超过 12 MB")
        return {
            "id": pet_id, "name": clean["displayName"],
            "description": clean["description"], "version": clean["spriteVersionNumber"],
            "sheet": sheet_path, "builtin": False,
        }

    def list(self) -> list[dict]:
        pets = [{"id": "bridge-cat", "name": "Bridge Cat", "description": "本程序原创的黑猫像素动画"}]
        try:
            entries = sorted(self.directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return pets
        for entry in entries:
            if entry.name.startswith(".") or not PET_ID_RE.fullmatch(entry.name):
                continue
            try:
                asset = self._asset(entry.name)
            except (OSError, ValueError):
                continue
            pets.append({key: asset[key] for key in ("id", "name", "description")})
        return pets

    def import_pet(self, name: str, manifest: dict, spritesheet: bytes) -> dict:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError("宠物名称无效")
        clean = _clean_manifest(manifest, name.strip())
        # The explicit import name is the UI's chosen name; the manifest remains
        # the authority for format, description and path.
        clean["displayName"] = name.strip()
        image_format, _ = _validate_image(spritesheet, clean["spriteVersionNumber"])
        path_value = _safe_relative_path(clean["spritesheetPath"])
        expected_suffix = ".png" if image_format == "png" else ".webp"
        if path_value.suffix.lower() not in {".png", ".webp"}:
            raise ValueError("spritesheetPath 必须使用 .png 或 .webp")
        if path_value.suffix.lower() != expected_suffix:
            raise ValueError("spritesheetPath 扩展名与图片格式不一致")

        base = _slug(name.strip())
        for _ in range(16):
            pet_id = f"{base}-{secrets.token_hex(4)}"
            final = self.directory / pet_id
            if not final.exists():
                break
        else:
            raise ValueError("无法分配唯一宠物标识")
        stage = self.directory / f".{pet_id}.tmp"
        stage.mkdir()
        try:
            image_path = stage.joinpath(*path_value.parts)
            image_path.parent.mkdir(parents=True, exist_ok=True)
            with image_path.open("xb") as stream:
                stream.write(spritesheet)
                stream.flush()
                os.fsync(stream.fileno())
            manifest_path = stage / "pet.json"
            payload = json.dumps(clean, ensure_ascii=False, indent=2).encode("utf-8")
            with manifest_path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if final.exists():
                raise FileExistsError("宠物标识发生冲突")
            os.rename(stage, final)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise
        return {"id": pet_id, "name": clean["displayName"], "description": clean["description"]}

    def import_codex(self) -> list[dict]:
        assets = _read_asar_assets(_find_codex_asar())
        # _read_asar_assets validates the complete allowlist before any writes.
        return [self.import_pet(
            display_name,
            {
                "id": pet_id,
                "displayName": display_name,
                "description": "从本机 OpenAI Codex 桌面应用导入",
                "spriteVersionNumber": 2,
                "spritesheetPath": "spritesheet.webp",
            },
            assets[pet_id],
        ) for pet_id, display_name in CODEX_PETS.items()]

    def render(self, pet_id: str, state: str, layout: str, background: str,
               telemetry: dict) -> tuple[list[Image.Image], list[int]]:
        if state not in ANIMATIONS:
            raise ValueError("未知宠物状态")
        if layout not in {"pet", "dashboard"}:
            raise ValueError("未知屏幕布局")
        if not isinstance(background, str) or not BACKGROUND_RE.fullmatch(background):
            raise ValueError("背景色必须为 #RRGGBB")
        row, durations = ANIMATIONS[state]
        asset = self._asset(pet_id)
        if asset["builtin"]:
            visual_state = "idle" if state == "unknown" else state
            sprites = [_cat_frame(visual_state, index, len(durations)) for index in range(len(durations))]
        else:
            data = asset["sheet"].read_bytes()
            _validate_image(data, asset["version"])
            try:
                with Image.open(io.BytesIO(data)) as sheet:
                    sheet.load()
                    sprites = _common_crops(sheet, row, len(durations))
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("无法解码宠物精灵图") from exc

        area = (0, 12, 160, 68) if layout == "dashboard" else ((0, 0, 160, 68) if state == "unknown" else (0, 0, 160, 80))
        frames = []
        for sprite in sprites:
            frame = Image.new("RGB", (160, 80), background)
            _fit_rgba(sprite, frame, area)
            frames.append(_decorate(frame, state, layout, telemetry))
        return frames, list(durations)
