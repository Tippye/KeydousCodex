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
        for handler in self.handlers:
            handler()


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
        webview = Mock(settings={})
        webview.create_window.return_value = window

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
                events.closing.fire()
            else:
                # Simulate the existing API quit path, not a GUI test-only API.
                app.begin_close()
                server.shutdown()
                self.assertTrue(destroyed.wait(2), "API Quit must close the native window")

        webview.start.side_effect = start
        with tempfile.TemporaryDirectory() as root:
            if mode in {"failure", "blank-window"}:
                with self.assertRaisesRegex(RuntimeError, "WebView2"):
                    run_desktop(server, app, Path(root), webview_module=webview, page_timeout=.1)
            else:
                run_desktop(server, app, Path(root), webview_module=webview)
            self.assertEqual(webview.create_window.call_args.args[1], server.url + "/?desktop=1")
            self.assertTrue(webview.settings["ALLOW_DOWNLOADS"])
            self.assertTrue(app.stop.is_set())
            self.assertTrue(done.is_set())
            self.assertFalse(any(t.name in {"desktop-service","desktop-close"} for t in threading.enumerate()))

    def test_window_close_stops_service_without_second_destroy(self):
        self.exercise("native-close")

    def test_api_quit_closes_desktop_window(self):
        self.exercise("api-quit")

    def test_engine_failure_stops_service_without_browser_fallback(self):
        self.exercise("failure")

    def test_async_engine_failure_cannot_leave_blank_window_running(self):
        self.exercise("blank-window")
