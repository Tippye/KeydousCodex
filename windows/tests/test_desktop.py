import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from keydous_bridge.desktop import run_desktop


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return any(handler() is False for handler in self.handlers)


class FakeTrayIcon:
    def __init__(self, menu, behavior="normal"):
        self.menu = menu
        self.behavior = behavior
        self.visible = False
        self.stopped = threading.Event()

    def run(self, setup=None):
        if self.behavior == "failure":
            raise OSError("tray unavailable")
        if setup:
            setup(self)
        if self.behavior == "return":
            return
        self.stopped.wait(5)

    def stop(self):
        self.stopped.set()


class FakeTray:
    def __init__(self, behavior="normal"):
        self.behavior = behavior
        self.icon = None

    @staticmethod
    def MenuItem(text, action, default=False):
        return SimpleNamespace(text=text, action=action, default=default)

    @staticmethod
    def Menu(*items):
        return items

    def Icon(self, _name, _image, _title, menu):
        self.icon = FakeTrayIcon(menu, self.behavior)
        return self.icon


class DesktopTests(unittest.TestCase):
    def exercise(self, mode):
        app = Mock()
        app.stop = threading.Event()
        app.begin_close.side_effect = app.stop.set
        done = threading.Event()
        server = Mock(url="http://127.0.0.1:12345")
        server.serve_forever.side_effect = lambda **kwargs: done.wait(5)
        server.shutdown.side_effect = done.set
        events = SimpleNamespace(shown=Event(),closing=Event(),loaded=Event())
        destroyed = threading.Event()
        window = Mock(events=events)
        window.destroy.side_effect = destroyed.set
        hidden = threading.Event()
        reopened = threading.Event()
        window.hide.side_effect = hidden.set
        window.show.side_effect = reopened.set
        webview = Mock(settings={})
        webview.create_window.return_value = window
        behavior = "failure" if mode == "tray-failure" else "return" if mode == "tray-return" else "normal"
        tray = FakeTray(behavior=behavior)
        image = Mock()
        image.open.return_value = Mock()

        def start(**kwargs):
            self.assertEqual(kwargs["gui"], "edgechromium")
            self.assertFalse(kwargs["debug"])
            self.assertFalse(kwargs["private_mode"])
            if mode == "failure":
                raise OSError("WebView2 unavailable")
            events.shown.fire()
            if mode == "blank-window":
                self.assertTrue(destroyed.wait(2))
                return
            events.loaded.fire()
            if mode == "native-close":
                self.assertTrue(events.closing.fire(), "Window close must be cancelled")
                self.assertTrue(hidden.wait(2), "Window close must hide the window")
                self.assertFalse(app.stop.is_set(), "Hidden app must keep running")
                actions = {item.text: item.action for item in tray.icon.menu}
                actions["打开"](tray.icon, None)
                self.assertTrue(reopened.wait(2), "Tray Open must restore the window")
                actions["退出"](tray.icon, None)
                self.assertTrue(destroyed.wait(2), "Tray Quit must close the native window")
            else:
                # Simulate the existing API quit path, not a GUI test-only API.
                app.begin_close()
                server.shutdown()
                self.assertTrue(destroyed.wait(2), "API Quit must close the native window")

        webview.start.side_effect = start
        with tempfile.TemporaryDirectory() as root:
            if mode in {"failure", "blank-window", "tray-failure", "tray-return"}:
                expected = "系统托盘" if mode.startswith("tray-") else "WebView2"
                with self.assertRaisesRegex(RuntimeError, expected):
                    run_desktop(server, app, Path(root), webview_module=webview,
                                tray_module=tray, image_module=image,
                                page_timeout=.1, tray_timeout=.1)
            else:
                run_desktop(server, app, Path(root), webview_module=webview,
                            tray_module=tray, image_module=image)
            self.assertEqual(webview.create_window.call_args.args[1], server.url + "/?desktop=1")
            self.assertTrue(webview.settings["ALLOW_DOWNLOADS"])
            self.assertTrue(app.stop.is_set())
            self.assertTrue(done.is_set())
            self.assertTrue(tray.icon.stopped.is_set())
            self.assertFalse(any(t.name in {"desktop-service", "desktop-close", "desktop-tray"}
                                 for t in threading.enumerate()))

    def test_window_close_hides_and_tray_open_and_quit_control_lifecycle(self):
        self.exercise("native-close")

    def test_api_quit_closes_desktop_window(self):
        self.exercise("api-quit")

    def test_engine_failure_stops_service_without_browser_fallback(self):
        self.exercise("failure")

    def test_async_engine_failure_cannot_leave_blank_window_running(self):
        self.exercise("blank-window")

    def test_tray_failure_stops_instead_of_leaving_unreachable_background_app(self):
        self.exercise("tray-failure")

    def test_unexpected_tray_exit_stops_instead_of_leaving_unreachable_background_app(self):
        self.exercise("tray-return")
