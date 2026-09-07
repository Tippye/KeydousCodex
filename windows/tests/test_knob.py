import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from keydous_bridge.knob import HOTKEYS, KnobController, WindowsKnob


class Backend:
    def __init__(self, conflict=None):
        self.conflict = conflict
        self.registered, self.removed, self.actions = [], [], []
        self.events = queue.Queue()
        self.observed = threading.Event()

    def register(self, identifier, key):
        if identifier == self.conflict:
            raise OSError("hotkey conflict")
        self.registered.append(identifier)

    def unregister(self, identifier):
        self.removed.append(identifier)

    def poll(self):
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def dispatch(self, action, stopped):
        self.actions.append(action)
        self.observed.set()


class KnobTests(unittest.TestCase):
    def test_conflict_unregisters_partial_set_and_can_retry(self):
        backend = Backend(conflict=2)
        controller = KnobController(lambda: backend)
        with self.assertRaisesRegex(OSError, "conflict"):
            controller.start()
        self.assertEqual(backend.removed, [1])
        backend.conflict = None
        controller.start()
        controller.close()
        self.assertFalse(controller.snapshot()["running"])
        self.assertEqual(backend.removed[-3:], [1, 2, 3])

    def test_all_three_actions_dispatch_and_count_without_repeat_registration(self):
        backend = Backend()
        controller = KnobController(lambda: backend)
        self.addCleanup(controller.close)
        controller.start()
        controller.start()
        self.assertEqual(backend.registered, [1, 2, 3])
        for _, action in HOTKEYS.values():
            backend.events.put(action)
        deadline = time.monotonic() + 2
        while sum(controller.snapshot()["counts"].values()) < 3 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(controller.snapshot()["counts"], {"previous": 1, "next": 1, "focus": 1})
        controller.close()
        self.assertFalse(controller.thread.is_alive())

    def test_navigation_targets_and_focus_only(self):
        backend = WindowsKnob.__new__(WindowsKnob)
        backend.focus = Mock(return_value=42)
        backend.user = Mock()
        backend.user.GetForegroundWindow.return_value = 42
        backend.user.GetAsyncKeyState.return_value = 0
        backend.send_navigation = Mock()
        backend.dispatch("previous", threading.Event())
        backend.dispatch("next", threading.Event())
        backend.dispatch("focus", threading.Event())
        self.assertEqual([call.args for call in backend.send_navigation.call_args_list], [(42, 0x21), (42, 0x22)])
        self.assertEqual([call.kwargs for call in backend.focus.call_args_list],
                         [{"toggle": False}, {"toggle": False}, {"toggle": True}])

    def window_backend(self, foreground=42, minimized=False):
        backend = WindowsKnob.__new__(WindowsKnob)
        backend.codex_windows = Mock(return_value=[42, 43])
        backend.user = Mock()
        backend.user.GetForegroundWindow.return_value = foreground
        backend.user.IsIconic.return_value = minimized
        backend.send_navigation = Mock()
        return backend

    def test_press_minimizes_foreground_codex_without_navigation(self):
        backend = self.window_backend(foreground=43)
        backend.user.IsIconic.side_effect = [False, True]
        backend.dispatch("focus", threading.Event())
        backend.user.ShowWindow.assert_called_once_with(43, 6)
        backend.user.SetForegroundWindow.assert_not_called()
        backend.send_navigation.assert_not_called()

    def test_press_restores_minimized_codex(self):
        backend = self.window_backend(foreground=99, minimized=True)
        self.assertEqual(backend.focus(toggle=True), 42)
        backend.user.ShowWindow.assert_called_once_with(42, 9)
        backend.user.SetForegroundWindow.assert_called_once_with(42)

    def test_background_visible_codex_is_focused_not_minimized(self):
        backend = self.window_backend(foreground=99)
        self.assertEqual(backend.focus(toggle=True), 42)
        backend.user.ShowWindow.assert_not_called()
        backend.user.SetForegroundWindow.assert_called_once_with(42)

    def test_rotation_does_not_minimize_foreground_window(self):
        backend = self.window_backend()
        self.assertEqual(backend.focus(), 42)
        backend.user.ShowWindow.assert_not_called()

    def test_failed_minimize_and_shutdown_do_not_report_success(self):
        backend = self.window_backend()
        with self.assertRaisesRegex(OSError, "最小化"):
            backend.dispatch("focus", threading.Event())
        backend.user.ShowWindow.reset_mock()
        stopped = threading.Event()
        stopped.set()
        with self.assertRaisesRegex(OSError, "停止"):
            backend.dispatch("focus", stopped)
        backend.user.ShowWindow.assert_not_called()

    def test_focus_failure_and_held_modifier_never_send_navigation(self):
        backend = WindowsKnob.__new__(WindowsKnob)
        backend.focus = Mock(return_value=42)
        backend.user = Mock()
        backend.user.GetForegroundWindow.return_value = 99
        backend.user.GetAsyncKeyState.return_value = 0x8000
        backend.send_navigation = Mock()
        with patch("keydous_bridge.knob.time.monotonic", side_effect=[0, 0, 1]):
            with self.assertRaises(OSError):
                backend.dispatch("next", threading.Event())
        backend.send_navigation.assert_not_called()
