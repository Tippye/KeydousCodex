"""Single application owner: configuration, input, preview and serialized hardware work."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time

from .config import ConfigStore
from .display import device_animation, gif_bytes, png_bytes
from .events import FileSource, STATES, recent_sessions
from .iot import IoTClient
from .models import model_list
from .pets import PetLibrary
from .rgb import RGBLink
from .hook_core import HookStore
from .integration import Integration
from .mapping import MappingService
from .macos_fn import MacFnController
from .knob import KnobController


def locks() -> dict:
    if os.name != "nt":
        return {"num": None, "caps": None}
    return {"num": bool(ctypes.windll.user32.GetKeyState(0x90) & 1),
            "caps": bool(ctypes.windll.user32.GetKeyState(0x14) & 1)}


class BridgeApp:
    def __init__(self, directory: Path, client: IoTClient | None = None):
        self.config = ConfigStore(directory)
        self.pets = PetLibrary(directory / "pets")
        self.client = client or IoTClient()
        self.rgb = RGBLink(self.client, directory)
        self.hooks = HookStore(directory / "hook-state.json")
        self.integration = Integration(directory)
        self.lock = threading.RLock()
        self.control = threading.RLock()
        self.stop = threading.Event()
        self.mapping = MappingService(self.client, directory, self.stop)
        self.mac_fn = MacFnController(directory)
        self.knob = KnobController()
        self.cancel = threading.Event()
        self.devices = []
        self.iot = {"connected": False, "error": "尚未连接"}
        self.upload = {"active": False, "progress": 0.0, "message": ""}
        self.notice = self.config.warning
        self.state = "idle"
        self.source_status = {"state": "idle", "source": "manual", "source_detail": "手动预览", "validity": "manual"}
        self.file_source = None
        self.worker = None
        self.upload_worker = None
        self._configure_input(self.config.value)

    def _configure_input(self, config: dict):
        if config["source"] == "manual":
            self.file_source = None
            self.source_status = {"state": self.state, "source": "manual", "source_detail": "手动预览", "validity": "manual"}
        elif config["source"] == "hooks":
            self.file_source = None
            self.source_status = self.hooks.snapshot()
        elif config["session_path"]:
            try:
                self.file_source = FileSource(Path(config["session_path"]), config["source"])
                self.source_status = self.file_source.poll()
            except (OSError, ValueError) as exc:
                self.file_source = None
                self.source_status = {"state": "unknown", "source": config["source"], "source_detail": str(exc), "validity": "unknown"}
        else:
            self.file_source = None
            self.source_status = {"state": "unknown", "source": config["source"], "source_detail": "请选择一个任务 JSONL 文件", "validity": "unknown"}

    def start(self):
        self.mac_fn.start()
        try:
            if self.knob.supported and self.mapping.knob_saved():
                self.knob.start()
        except (OSError, ValueError) as exc:
            self.notice = "旋钮快捷操作未启动：" + str(exc)
        self.worker = threading.Thread(target=self._work, name="bridge-monitor", daemon=True)
        self.worker.start()

    @contextmanager
    def mutation(self):
        with self.control:
            if self.stop.is_set():
                raise ValueError("程序正在退出，不能开始新操作")
            yield

    def selected_device(self, key: str | None = None):
        key = self.config.value["device_key"] if key is None else key
        available = [device for device in self.devices if device.online]
        if key:
            return next((device for device in available if device.key == key), None)
        return available[0] if len(available) == 1 else None

    def connect(self) -> dict:
        with self.mutation():
            if self.upload["active"]:
                raise ValueError("上传中，请等待完成后重新连接")
            try:
                devices = self.client.discover()
                with self.lock:
                    self.devices = devices
                    self.iot = {"connected": True, "error": ""}
            except (OSError, ValueError, EOFError) as exc:
                with self.lock:
                    self.devices = []
                    self.iot = {"connected": False, "error": "无法连接官方 IoT 驱动：" + str(exc)}
            return self.snapshot()

    def _work(self):
        next_discovery = 0.0
        while not self.stop.is_set():
            try:
                if time.monotonic() >= next_discovery and not self.upload["active"]:
                    self.connect()
                    next_discovery = time.monotonic() + 5
                with self.lock:
                    if self.file_source:
                        self.source_status = self.file_source.poll()
                    elif self.config.value["source"] == "hooks":
                        self.source_status = self.hooks.snapshot()
                    self.state = self.source_status["state"]
                if not self.upload["active"]:
                    with self.mutation():
                        if self.upload["active"]:
                            continue
                        self.rgb.update(self.selected_device(), self.state)
                        if self.config.value["rgb_enabled"] and not self.rgb.enabled:
                            self.config.update({"rgb_enabled": False})
            except Exception as exc:
                with self.lock:
                    self.notice = "后台更新暂停：" + str(exc)
            self.stop.wait(0.5)

    def snapshot(self) -> dict:
        with self.lock:
            device = self.selected_device()
            return {**self.source_status, "state": self.state, "device": device.public() if device else None,
                    "devices": [item.public() for item in self.devices], "locks": locks(),
                    "iot": dict(self.iot), "upload": dict(self.upload), "notice": self.notice,
                    "rgb": self.rgb.snapshot(), "integration": self.integration.status(), "macos_fn": self.mac_fn.snapshot(),
                    "knob": self.knob.snapshot()}

    def bootstrap(self) -> dict:
        with self.lock:
            return {"config": dict(self.config.value), "status": self.snapshot(),
                    "pets": self.pets.list(), "models": model_list()}

    def update_config(self, patch: dict) -> dict:
        patch = ConfigStore.validate(patch)
        with self.mutation():
            candidate = {**self.config.value, **patch}
            if candidate["pet_id"] not in {pet["id"] for pet in self.pets.list()}:
                raise ValueError("所选宠物不存在，请重新选择")
            if "session_path" in patch and patch["session_path"]:
                path = Path(patch["session_path"])
                if path.suffix.lower() != ".jsonl" or not path.is_file():
                    raise ValueError("请选择存在的 .jsonl 文件")
            if self.upload["active"] and any(key in patch for key in ("device_key", "rgb_enabled")):
                raise ValueError("上传期间不能切换设备或 RGB 联动")
            if "device_key" in patch and patch["device_key"] != self.config.value["device_key"] and self.rgb.enabled:
                self.rgb.restore(self.selected_device())
                candidate["rgb_enabled"] = False
            enabled = candidate["rgb_enabled"]
            if enabled and not self.rgb.enabled:
                device = self.selected_device(candidate["device_key"])
                if device is None:
                    raise ValueError("请先连接并选择键盘")
                self.rgb.enable(device)
            elif not enabled and self.rgb.enabled:
                self.rgb.restore(self.selected_device())
            with self.lock:
                result = self.config.update(candidate)
                if {"source", "session_path"} & patch.keys():
                    self._configure_input(result)
                    self.state = self.source_status["state"]
            return result

    def set_state(self, state: str) -> dict:
        if state not in STATES:
            raise ValueError("未知宠物状态")
        with self.mutation(), self.lock:
            self.config.update({"source": "manual"})
            self.file_source = None
            self.state = state
            self.source_status = {"state": state, "source": "manual", "source_detail": "手动预览", "validity": "manual"}
        return self.snapshot()

    def render(self, state: str | None = None, layout: str | None = None, options: dict | None = None):
        with self.lock:
            config = dict(self.config.value)
            status = self.snapshot()
        options = options or {}
        if set(options) - {"pet_id", "layout", "background"}:
            raise ValueError("未知渲染选项")
        config.update(ConfigStore.validate(options))
        state = state or status["state"]
        layout = layout or config["layout"]
        if state not in STATES or layout not in {"pet", "dashboard"}:
            raise ValueError("未知预览状态或布局")
        telemetry = {"locks": status["locks"], "connection": (status["device"] or {}).get("connection"),
                     "battery": (status["device"] or {}).get("battery")}
        return self.pets.render(config["pet_id"], state, layout, config["background"], telemetry)

    def preview(self, format: str, state=None, layout=None, options=None) -> bytes:
        frames, durations = self.render(state, layout, options)
        return gif_bytes(frames, durations) if format == "gif" else png_bytes(frames[0])

    def start_upload(self, slot: int, options: dict | None = None, state: str | None = None) -> dict:
        if type(slot) is not int or not 1 <= slot <= 3:
            raise ValueError("动画槽必须为 1–3")
        with self.mutation():
            if self.upload["active"]:
                raise ValueError("已有上传正在进行")
            self.cancel.clear()
            if self.stop.is_set():
                raise ValueError("程序正在退出，不能开始上传")
            device = self.selected_device()
            if device is None:
                raise ValueError("请先选择已连接的键盘")
            self.client._require(device, "upload")
            if self.rgb.enabled:
                self.rgb.restore(device)
                self.config.update({"rgb_enabled": False})
            frames, durations = self.render(state=state, options=options)
            encoded, delay = device_animation(frames, durations)
            if self.stop.is_set():
                raise ValueError("程序正在退出，上传准备已取消")
            with self.lock:
                self.upload = {"active": True, "progress": 0.0,
                               "message": f"正在写入动画槽 {slot}，请勿操作键盘或官方网页"}

            def run():
                try:
                    def progress(value):
                        with self.lock:
                            self.upload["progress"] = value
                    self.client.upload(device, encoded, (160, 80), slot, delay, progress, self.cancel)
                    message = f"动画槽 {slot} 已传输。请用 Fn+Delete 切换查看；需观察实屏确认。状态栏为上传时快照。"
                except Exception as exc:
                    message = str(exc)
                with self.lock:
                    self.upload["active"] = False
                    self.upload["message"] = message
            self.upload_worker = threading.Thread(target=run, name="bridge-upload", daemon=True)
            self.upload_worker.start()
            return self.snapshot()

    def restore_rgb(self) -> dict:
        with self.mutation():
            if self.upload["active"]:
                raise ValueError("请等待上传完成")
            self.config.update({"rgb_enabled": False})
            self.rgb.restore(self.selected_device())
        return self.snapshot()

    def key_mapping(self, operation: str, request: dict) -> dict:
        with self.mutation():
            if self.upload["active"]:
                raise ValueError("屏幕上传中，请等待完成后操作按键")
            device = self.selected_device()
            if device is None:
                raise ValueError("请先连接并选择 NJ98 USB 键盘")
            key = device.key
            identity = (device.identifier, device.vid, device.pid, device.path, device.connection)
            with self.client.lock:
                fresh = self.client.discover()
                with self.lock:
                    self.devices = fresh
                device = next((d for d in fresh if d.online and d.key == key), None)
                if device is None or (device.identifier, device.vid, device.pid, device.path, device.connection) != identity:
                    raise ValueError("键盘连接或型号已变化，请重新连接后再读取")
                self.client._require(device, "mapping")
                if operation == "read":
                    return self.mapping.read(device)
                if operation == "apply":
                    return self.mapping.apply(device, request)
                if operation == "restore":
                    result = self.mapping.restore(device)
                    self.knob.close()
                    return result
                if operation == "knob-enable":
                    if set(request) != {"revision"}:
                        raise ValueError("请先读取当前旋钮配置")
                    self.knob.start()
                    try:
                        return self.mapping.configure_knob(device, request["revision"])
                    except Exception:
                        if not self.mapping.knob_saved():
                            self.knob.close()
                        raise
                if operation == "knob-restore":
                    if request:
                        raise ValueError("恢复旋钮不接受额外参数")
                    result = self.mapping.restore_knob(device)
                    self.knob.close()
                    return result
                raise ValueError("未知改键操作")

    def sessions(self) -> list[dict]:
        return recent_sessions(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))

    def begin_close(self):
        self.stop.set()
        self.knob.stop.set()
        self.mac_fn.begin_close()
        self.integration.cancelled.set()
        self.cancel.set()

    def close(self):
        self.begin_close()
        self.knob.close()
        self.mac_fn.close()  # Independent from potentially busy firmware/RGB operations.
        if self.upload_worker and self.upload_worker.ident is not None:
            self.upload_worker.join(timeout=12)
        if self.worker and self.worker.ident is not None:
            self.worker.join(timeout=5)
        if not self.control.acquire(timeout=2):
            self.notice = "退出时操作仍在结束；RGB 恢复记录已保留，请下次启动后恢复"
            return
        try:
            if self.rgb.enabled:
                try:
                    self.rgb.restore(self.selected_device())
                except (OSError, ValueError):
                    pass  # The durable journal and error remain for next launch.
        finally:
            self.control.release()
