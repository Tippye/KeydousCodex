"""Validated, atomic user configuration. No device commands live here."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

DEFAULTS = {
    "pet_id": "bridge-cat", "source": "hooks", "session_path": "",
    "layout": "pet", "background": "#101820", "rgb_enabled": False,
    "device_key": "", "slot": 1,
}


def data_directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KeydousCodex"
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeydousCodex"


class ConfigStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "config.json"
        self.value = dict(DEFAULTS)
        self.warning = ""
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                self.value.update(self.validate(value))
            except (OSError, ValueError, TypeError) as exc:
                self.warning = f"配置无法读取，使用默认值：{exc}"
        # Hardware automation is opt-in for each run; a crash must not auto-resume writes.
        self.value["rgb_enabled"] = False

    @staticmethod
    def validate(patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("配置必须是对象")
        if set(patch) - set(DEFAULTS):
            raise ValueError("包含未知配置项")
        for key, value in patch.items():
            if key == "rgb_enabled":
                if type(value) is not bool:
                    raise ValueError("RGB 开关必须是布尔值")
            elif key == "slot":
                if type(value) is not int or not 1 <= value <= 3:
                    raise ValueError("动画槽必须为 1–3")
            elif not isinstance(value, str) or len(value) > 4096:
                raise ValueError(f"无效配置：{key}")
        if "source" in patch and patch["source"] not in {"manual", "hooks", "desktop", "jsonl"}:
            raise ValueError("未知状态来源")
        if "layout" in patch and patch["layout"] not in {"pet", "dashboard"}:
            raise ValueError("未知屏幕布局")
        if "background" in patch and not re.fullmatch(r"#[0-9a-fA-F]{6}", patch["background"]):
            raise ValueError("背景色必须为 #RRGGBB")
        if "pet_id" in patch and not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", patch["pet_id"]):
            raise ValueError("无效宠物标识")
        if "device_key" in patch and not re.fullmatch(r"[a-f0-9]{16}|", patch["device_key"]):
            raise ValueError("无效设备标识")
        return dict(patch)

    def update(self, patch: dict) -> dict:
        result = {**self.value, **self.validate(patch)}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)
        self.value = result
        return dict(result)
