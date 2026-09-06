"""Windows desktop host for the existing application; owns no device commands."""
from __future__ import annotations

import ctypes
from pathlib import Path
import threading
import time

TITLE = "Keyphore · Keydous"


def activate_existing_window() -> bool:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    handle = user32.FindWindowW(None, TITLE)
    if not handle:
        return False
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.ShowWindow(handle, 9)
    user32.SetForegroundWindow(handle)
    return True


def run_desktop(server, app, directory: Path, *, webview_module=None, page_timeout=30):
    # Lazy import: Hooks and headless acceptance never initialize .NET or a GUI.
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError as exc:
            raise RuntimeError("缺少桌面组件，请重新运行 Setup.ps1 或使用完整的桌面安装包") from exc
    webview = webview_module
    profile = directory / "desktop-profile"
    profile.mkdir(parents=True, exist_ok=True)
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(TITLE, server.url + "/?desktop=1", width=580, height=800,
                                   min_size=(420, 520), background_color="#ececef",
                                   text_select=True, confirm_close=False)
    stopped = threading.Event()
    shown = threading.Event()
    gui_finished = threading.Event()
    closing = threading.Event()
    loaded = threading.Event()
    load_error = []

    def serve():
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            stopped.set()

    def close_requested():
        closing.set()
        app.begin_close()

    def watch_shutdown():
        # API Quit / SIGTERM must also close the desktop window. Never destroy a
        # not-yet-created native handle if startup fails or shutdown arrives early.
        deadline = None
        while not gui_finished.is_set():
            if not shown.wait(0.1):
                continue
            if deadline is None:
                deadline = time.monotonic() + page_timeout
            if not loaded.is_set() and time.monotonic() >= deadline:
                load_error.append("WebView2 未能加载应用界面，请检查运行时或桌面数据目录")
                app.begin_close()
            if app.stop.is_set() or stopped.is_set():
                if not closing.is_set():
                    window.destroy()
                return
            gui_finished.wait(0.1)

    window.events.shown += shown.set
    window.events.loaded += loaded.set
    window.events.closing += close_requested
    service = threading.Thread(target=serve, name="desktop-service", daemon=True)
    watcher = threading.Thread(target=watch_shutdown, name="desktop-close", daemon=True)
    service.start()
    watcher.start()
    try:
        # Explicit engine: an unavailable WebView2 runtime is a startup error,
        # never a silent fallback to IE or an external browser.
        webview.start(gui="edgechromium", debug=False, private_mode=False, storage_path=str(profile))
        if load_error:
            raise RuntimeError(load_error[0])
    except Exception as exc:
        raise RuntimeError("无法打开桌面窗口，请确认已安装 Microsoft Edge WebView2 Runtime：" + str(exc)) from exc
    finally:
        gui_finished.set()
        app.begin_close()
        server.shutdown()
        service.join(timeout=5)
        watcher.join(timeout=2)
