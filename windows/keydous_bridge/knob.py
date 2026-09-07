"""Application-owned Windows hotkeys for the NJ98 Codex knob preset.

Only three chords are registered; ordinary keyboard input is never captured.
Firmware emits Ctrl+F9/F10/F11. Navigation uses Codex's default Ctrl+PageUp/Down.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import sys
import threading
import time

HOTKEYS = {1: (0x78, "previous"), 2: (0x79, "next"), 3: (0x7A, "focus")}
LABELS = {"previous": "上一个任务", "next": "下一个任务", "focus": "显示／隐藏 Codex"}


class WindowsKnob:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        declarations = (
            (self.user, "RegisterHotKey", [W.HWND, ctypes.c_int, W.UINT, W.UINT], W.BOOL),
            (self.user, "UnregisterHotKey", [W.HWND, ctypes.c_int], W.BOOL),
            (self.user, "PeekMessageW", [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
            (self.user, "EnumWindows", [self.callback_type, W.LPARAM], W.BOOL),
            (self.user, "IsWindowVisible", [W.HWND], W.BOOL),
            (self.user, "GetWindow", [W.HWND, W.UINT], W.HWND),
            (self.user, "GetWindowThreadProcessId", [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            (self.user, "GetForegroundWindow", [], W.HWND),
            (self.user, "SetForegroundWindow", [W.HWND], W.BOOL),
            (self.user, "IsIconic", [W.HWND], W.BOOL),
            (self.user, "ShowWindow", [W.HWND, ctypes.c_int], W.BOOL),
            (self.user, "GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
            (self.kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            (self.kernel, "CloseHandle", [W.HANDLE], W.BOOL),
            (self.kernel, "GetApplicationUserModelId", [W.HANDLE, ctypes.POINTER(W.UINT), W.LPWSTR], W.LONG),
        )
        for dll, name, args, result in declarations:
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result

    def register(self, identifier, key):
        if not self.user.RegisterHotKey(None, identifier, 0x4002, key):
            raise OSError(f"Ctrl+F{key - 0x6F} 已被占用，旋钮未启用")

    def unregister(self, identifier):
        self.user.UnregisterHotKey(None, identifier)

    def poll(self):
        msg = W.MSG()
        if self.user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1) and msg.message == 0x312:
            return HOTKEYS.get(int(msg.wParam), (None, None))[1]
        return None

    def codex_windows(self):
        windows = []

        @self.callback_type
        def visit(handle, _):
            if not self.user.IsWindowVisible(handle) or self.user.GetWindow(handle, 4):
                return True
            pid = W.DWORD()
            self.user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            process = self.kernel.OpenProcess(0x1000, False, pid)
            if not process:
                return True
            try:
                size = W.UINT(512)
                app_id = ctypes.create_unicode_buffer(512)
                if self.kernel.GetApplicationUserModelId(process, ctypes.byref(size), app_id) == 0:
                    # Match the installed desktop app identity, never a window title or the CLI.
                    if app_id.value.startswith("OpenAI.Codex_") and app_id.value.endswith("!App"):
                        windows.append(handle)
            finally:
                self.kernel.CloseHandle(process)
            return True

        self.user.EnumWindows(visit, 0)
        return windows

    def focus(self, toggle=False):
        windows = self.codex_windows()
        if not windows:
            raise OSError("未找到已打开的 Codex 桌面窗口，请先打开 Codex")
        foreground = self.user.GetForegroundWindow()
        target = foreground if foreground in windows else windows[0]
        if toggle and foreground == target and not self.user.IsIconic(target):
            # Minimize instead of SW_HIDE: the window remains discoverable and accessible in the taskbar.
            self.user.ShowWindow(target, 6)
            if not self.user.IsIconic(target):
                raise OSError("Codex 窗口未能最小化，请重试")
            return None
        if self.user.IsIconic(target):
            self.user.ShowWindow(target, 9)
        if foreground != target:
            self.user.SetForegroundWindow(target)
        return target

    def dispatch(self, action, stopped):
        if action not in LABELS:
            raise ValueError("未知旋钮动作")
        if stopped.is_set():
            raise OSError("旋钮服务正在停止")
        target = self.focus(toggle=action == "focus")
        if target is None:
            return
        deadline = time.monotonic() + 0.4
        # Let the firmware's Ctrl/function-key pair release; never force-release a user's keys.
        keys = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0x78, 0x79, 0x7A)
        while time.monotonic() < deadline and not stopped.is_set():
            if self.user.GetForegroundWindow() == target and not any(self.user.GetAsyncKeyState(k) & 0x8000 for k in keys):
                if action != "focus":
                    self.send_navigation(target, 0x21 if action == "previous" else 0x22)
                return
            stopped.wait(0.01)
        raise OSError("窗口未聚焦或按键尚未释放，本次旋钮动作已跳过")

    def send_navigation(self, target, key):
        class Keyboard(ctypes.Structure):
            _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                        ("time", W.DWORD), ("extra", ctypes.c_size_t)]

        class Mouse(ctypes.Structure):
            _fields_ = [("x", W.LONG), ("y", W.LONG), ("data", W.DWORD),
                        ("flags", W.DWORD), ("time", W.DWORD), ("extra", ctypes.c_size_t)]

        class Payload(ctypes.Union):
            _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]

        class Input(ctypes.Structure):
            _fields_ = [("type", W.DWORD), ("payload", Payload)]

        def event(vk, flags):
            return Input(1, Payload(keyboard=Keyboard(vk, 0, flags, 0, 0)))

        sequence = (Input * 4)(event(0x11, 0), event(key, 1), event(key, 3), event(0x11, 2))
        send = self.user.SendInput
        send.argtypes, send.restype = [W.UINT, ctypes.POINTER(Input), ctypes.c_int], W.UINT
        if self.user.GetForegroundWindow() != target:
            raise OSError("焦点已离开 Codex，本次切换已跳过")
        count = send(4, sequence, ctypes.sizeof(Input))
        if count != 4:
            # Release only keys this batch successfully pressed, even if focus changed.
            releases = []
            if count == 2:
                releases.append(event(key, 3))
            if count:
                releases.append(event(0x11, 2))
            if releases:
                send(len(releases), (Input * len(releases))(*releases), ctypes.sizeof(Input))
            raise OSError("Windows 未完整接收快捷键，请检查 Codex 与桥接程序的运行权限")


class KnobController:
    def __init__(self, backend_factory=None):
        self.supported = sys.platform == "win32" or backend_factory is not None
        self.factory = backend_factory or WindowsKnob
        self.thread = None
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.RLock()
        self.running = False
        self.error = ""
        self.last_action = ""
        self.counts = dict.fromkeys(LABELS, 0)

    def start(self):
        if not self.supported:
            raise ValueError("Codex 旋钮快捷操作目前仅支持 Windows")
        if self.thread and self.thread.is_alive():
            if self.running:
                return
            raise OSError("旋钮热键仍在停止，请稍后重试")
        self.stop.clear()
        self.ready.clear()
        self.error = ""
        self.thread = threading.Thread(target=self._run, name="codex-knob", daemon=True)
        self.thread.start()
        if not self.ready.wait(2):
            self.close()
            raise OSError("旋钮热键启动超时")
        if not self.running:
            self.close()
            raise OSError(self.error or "旋钮热键启动失败")

    def _run(self):
        registered = []
        backend = None
        try:
            backend = self.factory()
            for identifier, (key, _) in HOTKEYS.items():
                backend.register(identifier, key)
                registered.append(identifier)
            self.running = True
            self.ready.set()
            while not self.stop.is_set():
                action = backend.poll()
                if action:
                    try:
                        backend.dispatch(action, self.stop)
                        with self.lock:
                            self.counts[action] += 1
                            self.last_action = LABELS[action]
                            self.error = ""
                    except (OSError, ValueError) as exc:
                        self.error = str(exc)
                else:
                    self.stop.wait(0.01)
        except Exception as exc:
            self.error = str(exc)
        finally:
            for identifier in registered:
                backend.unregister(identifier)
            self.running = False
            self.ready.set()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def snapshot(self):
        with self.lock:
            return {"supported": self.supported, "running": self.running, "error": self.error,
                    "last_action": self.last_action, "counts": dict(self.counts)}
