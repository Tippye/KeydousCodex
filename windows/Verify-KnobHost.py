"""Interactive input fixture: exercise production Win32 hotkeys against our window.

Press Ctrl+F9, Ctrl+F10, Ctrl+F11 in this window. The test never controls Codex.
It checks Windows message delivery, navigation input and hotkey cleanup.
"""
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import tkinter as tk

from keydous_bridge.knob import KnobController, WindowsKnob

root = tk.Tk()
root.title("Keydous 旋钮输入测试")
root.geometry("540x250")
root.update()
user = ctypes.WinDLL("user32")
user.GetAncestor.argtypes, user.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
handle = user.GetAncestor(root.winfo_id(), 2)
backend = WindowsKnob()
backend.codex_windows = lambda: [handle]  # Only the target lookup changes; real input path is used.
controller = KnobController(lambda: backend)
received = {"previous": 0, "next": 0}
root.bind("<Control-Prior>", lambda event: received.update(previous=received["previous"] + 1))
root.bind("<Control-Next>", lambda event: received.update(next=received["next"] + 1))
tk.Label(root, text="仅测试此窗口，不操作 Codex\n依次按 Ctrl+F9、Ctrl+F10、Ctrl+F11", font=("Microsoft YaHei UI", 12)).pack(pady=15)
status = tk.Label(root, text="等待输入", font=("Microsoft YaHei UI", 11))
status.pack(pady=10)
tk.Button(root, text="关闭测试", command=root.destroy).pack()
controller.start()
complete = False


def update():
    global complete
    snapshot = controller.snapshot()
    status.config(text=f"热键接收：{snapshot['counts']}\n导航接收：{received}\n{snapshot['error']}")
    if all(v >= 1 for v in snapshot["counts"].values()) and all(v >= 1 for v in received.values()):
        complete = True
        root.after(1500, root.destroy)
        return
    root.after(100, update)


root.after(100, update)
root.after(180000, root.destroy)
try:
    root.mainloop()
finally:
    controller.close()
assert complete, "Native input acceptance not completed"
check = KnobController()
check.start()
check.close()
directory = Path(__file__).resolve().parent / "data" / "knob-host-acceptance"
directory.mkdir(parents=True, exist_ok=True)
evidence = {"hotkeys": controller.snapshot()["counts"], "navigation_received": received,
            "hotkeys_released": True, "codex_ui_tested": False}
(directory / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
print("WINDOWS_KNOB_INPUT_AND_CLEANUP_PASS", json.dumps(evidence), flush=True)
