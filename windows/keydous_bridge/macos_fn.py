"""Unprivileged control of the app's signed macOS Fn helper, never raw input IPC."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


class MacFnController:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()
        self.closing = threading.Event()
        self.worker = None
        self.supported = sys.platform == "darwin"
        self.wrapper = (Path(sys.executable).resolve().parent / "keydous-macos-fn" if getattr(sys,"frozen",False)
                        else Path(__file__).resolve().parents[2] / "macos/build/keydous-macos-fn")
        self.status = {"supported": self.supported, "state": "not_installed", "active": False, "ready": False,
                       "installed": False, "candidates": [], "message": "Mac Fn 仅在 macOS 上可用" if not self.supported else "尚未检查 Mac Fn 组件"}

    def snapshot(self):
        # Cached status only: UI reads must not wait for system-approval commands.
        return dict(self.status)

    def _call(self, operation: str, *arguments: str):
        if self.closing.is_set() and operation != "disable":
            raise ValueError("程序正在退出，不能启用或刷新 Mac Fn")
        if not self.supported:
            raise ValueError("原生 Fn/Globe 仅在 macOS 上可用；Windows 可使用键盘 Fn 层改键")
        if not self.wrapper.is_file() or not os.access(self.wrapper, os.X_OK):
            self.status.update(state="not_installed", active=False, ready=False, installed=False,
                               candidates=[], message="安装包中缺少可运行的 Mac Fn 组件，请先完成 Mac 构建和签名")
            if operation != "status":
                raise ValueError(self.status["message"])
            return dict(self.status)
        try:
            process = subprocess.run([str(self.wrapper), operation, *arguments, "--json"],
                                     capture_output=True, timeout={"status":8,"disable":5,"enable":30,"remove-helper":15}[operation],
                                     stdin=subprocess.DEVNULL)
            if len(process.stdout) > 65536:
                self.status.update(state="error",active=False,ready=False)
                raise ValueError("Mac Fn 状态响应过大")
            result = json.loads(process.stdout)
            if not isinstance(result, dict) or result.get("schemaVersion") != 1 or type(result.get("active")) is not bool or type(result.get("ready")) is not bool:
                self.status.update(state="error",active=False,ready=False)
                raise ValueError("无法识别 Mac Fn 状态")
            if result.get("state") not in {"not_installed","requires_approval","ready","active","error"} or (result["active"] and (not result["ready"] or result["state"] != "active")):
                self.status.update(state="error",active=False,ready=False)
                raise ValueError("Mac Fn 组件状态不一致")
            self.status = {**result, "supported":True}
            if self.closing.is_set() and operation == "enable":
                self._call("disable")
                raise ValueError("程序退出期间的 Mac Fn 启用已撤销")
            if process.returncode and operation != "status":
                raise ValueError(result.get("message") or "Mac Fn 未完成操作，请查看系统授权状态")
            if operation == "enable" and not result["active"]:
                raise ValueError(result.get("message") or "Mac Fn 尚未实际运行")
            if operation in {"disable", "remove-helper"} and result["active"]:
                raise ValueError("Mac Fn 组件尚未确认停止")
            return dict(self.status)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            self.status.update(state="error",active=False,ready=False,message="无法取得 Mac Fn 组件状态："+str(exc))
            raise OSError(self.status["message"]) from exc

    def refresh(self):
        with self.lock:
            if not self.supported:
                return dict(self.status)
            try:
                return self._call("status")
            except (OSError,ValueError) as exc:
                self.status.update(state="error", active=False, ready=False, message=str(exc))
                return dict(self.status)

    def start(self):
        if not self.supported or self.worker is not None:
            return
        def poll():
            while not self.closing.is_set():
                self.refresh()
                self.closing.wait(5)
        self.worker = threading.Thread(target=poll,name="mac-fn-health",daemon=True)
        self.worker.start()

    def begin_close(self):
        self.closing.set()

    def enable(self, request: dict):
        if set(request) != {"registry_entry_id", "source_usage"}:
            raise ValueError("请选择具体的 USB 键盘和一个可见按键")
        registry, usage = request["registry_entry_id"], request["source_usage"]
        if not isinstance(registry,str) or not registry.isascii() or not registry.isdecimal() or not 0 < int(registry) < 2**64:
            raise ValueError("无效设备标识")
        if type(usage) is not int or not (4 <= usage <= 231) or usage == 57:
            raise ValueError("请选择可见普通按键；Caps Lock 不能用于此映射")
        with self.lock:
            config = {"schemaVersion":1, "device":{"registryEntryId":registry,"vendorId":12625,"productId":16405,"transport":"USB"},
                      "source":{"usagePage":7,"usage":usage}, "target":"native_fn"}
            self.directory.mkdir(parents=True,exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix="mac-fn-",suffix=".json",dir=self.directory)
            try:
                with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
                    json.dump(config,stream)
                return self._call("enable","--config",filename)
            finally:
                Path(filename).unlink(missing_ok=True)

    def disable(self):
        with self.lock:
            return self._call("disable")

    def remove_helper(self):
        with self.lock:
            return self._call("remove-helper")

    def close(self):
        self.begin_close()
        # A lost enable/status response does not prove interception stopped.
        if self.supported and self.wrapper.is_file():
            try:
                self.disable()
            except (OSError,ValueError):
                pass  # Native helper also binds interception to the controller process.
