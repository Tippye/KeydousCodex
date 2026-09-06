"""Opt-in state lighting, rate limited with durable original-setting recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from .iot import Device, IoTClient

COLORS = {"thinking": (151, 113, 255), "working": (58, 189, 231), "waiting": (255, 193, 64),
          "success": (71, 208, 128), "error": (245, 84, 99)}


class RGBLink:
    def __init__(self, client: IoTClient, directory: Path):
        self.client = client
        self.path = directory / "rgb-recovery.json"
        self.original = None
        self.enabled = False
        self.error = ""
        self.last_state = None
        self.last_write = 0.0
        if self.path.exists():
            try:
                original = json.loads(self.path.read_text(encoding="utf-8"))
                settings = bytes.fromhex(original["settings"])
                if len(settings) != 7 or not isinstance(original["device_key"], str):
                    raise ValueError("invalid recovery record")
                self.original = original
            except (OSError, ValueError, KeyError, TypeError):
                self.error = "RGB 恢复记录不可读，联动已停用"

    def enable(self, device: Device):
        if self.enabled:
            return
        if self.path.exists() and not self.original:
            raise ValueError("RGB 恢复记录不可读；请先保存并检查该记录，不能覆盖原设置")
        if self.original:
            if self.original["device_key"] != device.key:
                raise ValueError("存在另一设备的 RGB 恢复记录，请先连接原设备恢复")
            self.restore(device)
        settings = self.client.read_rgb(device)
        original = {"device_key": device.key, "settings": settings.hex()}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(original), encoding="utf-8")
        os.replace(temp, self.path)
        self.original = original
        self.enabled, self.error = True, ""
        self.last_write, self.last_state = 0.0, None

    def restore(self, device: Device | None):
        self.enabled = False
        if not self.original:
            return
        if device is None or device.key != self.original["device_key"]:
            self.error = "原键盘不在线，RGB 恢复记录已保留；重连后点击恢复"
            raise ValueError(self.error)
        try:
            self.client.write_rgb(device, bytes.fromhex(self.original["settings"]))
            actual = self.client.read_rgb(device)
            # Clear recovery only after all seven original fields match.
            expected = bytes.fromhex(self.original["settings"])
            if actual != expected:
                raise OSError("RGB 读回与原设置不一致，已保留恢复记录")
            self.path.unlink(missing_ok=True)
            self.original, self.error = None, ""
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            raise

    def update(self, device: Device | None, state: str, now: float | None = None):
        if not self.enabled:
            return
        if device is None or device.key != self.original["device_key"] or not device.online:
            self.enabled = False
            self.error = "键盘连接已变化，联动停止；原 RGB 恢复记录已保留"
            return
        now = time.monotonic() if now is None else now
        if state == self.last_state or now - self.last_write < 10:
            return
        if state in COLORS:
            red, green, blue = COLORS[state]
            settings = bytes([1, 4, 2, 7, red, green, blue])
        else:
            settings = bytes.fromhex(self.original["settings"])
        try:
            self.client.write_rgb(device, settings)
            self.last_state, self.last_write, self.error = state, now, ""
        except (OSError, ValueError) as exc:
            self.enabled = False
            self.error = "RGB 更新失败，已停止联动并保留恢复记录：" + str(exc)

    def snapshot(self) -> dict:
        return {"enabled": self.enabled, "pending_restore": self.original is not None, "error": self.error}
