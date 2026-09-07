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
