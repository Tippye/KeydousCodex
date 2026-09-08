"""Windows desktop host for the existing application; owns no device commands."""
from __future__ import annotations

import ctypes
from pathlib import Path
import threading
import time

TITLE = "Keyphore · Keydous"


def _tray_icon_path() -> Path:
    bundled = Path(__file__).resolve().parent / "icon_256x256.png"
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / "app/Resources/Assets.xcassets/AppIcon.appiconset/icon_256x256.png"


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


def run_desktop(server, app, directory: Path, *, webview_module=None, tray_module=None,
                image_module=None, page_timeout=30, tray_timeout=10):
    # Lazy import: Hooks and headless acceptance never initialize .NET or a GUI.
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError as exc:
            raise RuntimeError("缺少桌面组件，请重新运行 Setup.ps1 或使用完整的桌面安装包") from exc
    webview = webview_module
    if tray_module is None:
        try:
            import pystray as tray_module
        except ImportError as exc:
            raise RuntimeError("缺少系统托盘组件，请重新运行 Setup.ps1 或使用完整的桌面安装包") from exc
    if image_module is None:
        from PIL import Image as image_module
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
    quitting = threading.Event()
    loaded = threading.Event()
    tray_ready = threading.Event()
    load_error = []
    tray_error = []
    tray_holder = []

    def serve():
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            stopped.set()

    def close_requested():
        if quitting.is_set():
            return True
        # The closing event is synchronous on WinForms. Cancel it first and
        # marshal the actual Hide call through pywebview from another thread.
        def hide_window():
            if not quitting.is_set():
                window.hide()
        threading.Thread(target=hide_window, name="desktop-hide", daemon=True).start()
        return False

    def show_window(*_):
        window.show()

    def quit_app(icon, *_):
        quitting.set()
        app.begin_close()
        icon.stop()

    def run_tray():
        image = None
        try:
            image = image_module.open(_tray_icon_path())
            menu = tray_module.Menu(
                tray_module.MenuItem("打开", show_window, default=True),
                tray_module.MenuItem("退出", quit_app),
            )
            icon = tray_module.Icon("keyphore-keydous", image, TITLE, menu)
            tray_holder.append(icon)

            def setup(ready_icon):
                ready_icon.visible = True
                tray_ready.set()

            icon.run(setup=setup)
            if not quitting.is_set():
                tray_error.append("托盘事件循环意外停止")
                app.begin_close()
        except Exception as exc:
            tray_error.append(str(exc))
            app.begin_close()
        finally:
            tray_ready.set()
            if image is not None and hasattr(image, "close"):
                image.close()

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
                quitting.set()
                window.destroy()
                return
            gui_finished.wait(0.1)

    window.events.shown += shown.set
    window.events.loaded += loaded.set
    window.events.closing += close_requested
    service = threading.Thread(target=serve, name="desktop-service", daemon=True)
    watcher = threading.Thread(target=watch_shutdown, name="desktop-close", daemon=True)
    tray_thread = threading.Thread(target=run_tray, name="desktop-tray", daemon=True)
    service.start()
    watcher.start()
    tray_thread.start()
    try:
        if not tray_ready.wait(tray_timeout) or tray_error:
            detail = tray_error[0] if tray_error else "启动超时"
            raise RuntimeError("无法启动 Windows 系统托盘：" + detail)
        # Explicit engine: an unavailable WebView2 runtime is a startup error,
        # never a silent fallback to IE or an external browser.
        webview.start(gui="edgechromium", debug=False, private_mode=False, storage_path=str(profile))
        if load_error:
            raise RuntimeError(load_error[0])
        if tray_error:
            raise RuntimeError("Windows 系统托盘已停止：" + tray_error[0])
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("无法打开桌面窗口，请确认已安装 Microsoft Edge WebView2 Runtime：" + str(exc)) from exc
    finally:
        gui_finished.set()
        quitting.set()
        app.begin_close()
        server.shutdown()
        if tray_holder:
            tray_holder[0].stop()
        service.join(timeout=5)
        watcher.join(timeout=2)
        tray_thread.join(timeout=5)
