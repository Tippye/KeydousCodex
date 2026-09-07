"""Check the shipped EXE's real window, duplicate launch, and WM_CLOSE cleanup.

Uses isolated data. Run on the interactive Windows desktop after quitting the app.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

root = Path(__file__).resolve().parent
exe = root / "dist/KeydousCodex/KeydousCodex.exe"
parent = root / "data/desktop-package-acceptance"
parent.mkdir(parents=True, exist_ok=True)
user32 = ctypes.windll.user32
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
user32.EnumWindows.argtypes = [callback_type,wintypes.LPARAM]
user32.PostMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]

def own_window(pid):
    found = []
    def visit(handle, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle,ctypes.byref(owner))
        text = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(handle,text,256)
        if owner.value == pid and user32.IsWindowVisible(handle) and text.value == "Keyphore · Keydous":
            found.append(handle)
        return True
    user32.EnumWindows(callback_type(visit),0)
    return found[0] if found else None

with tempfile.TemporaryDirectory(prefix="run-",dir=parent,ignore_cleanup_errors=True) as folder:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0)); port = probe.getsockname()[1]
    args = [str(exe),"--data-dir",folder,"--port",str(port)]
    process = subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic()+35
        handle = None
        while time.monotonic() < deadline:
            assert process.poll() is None, "Desktop EXE exited before showing a window"
            handle = own_window(process.pid)
            if handle:
                break
            time.sleep(.1)
        assert handle, "No native desktop window appeared"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=10) as response:
            assert json.load(response)["version"] == "0.3.2"
        duplicate = subprocess.run(args,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        assert duplicate.returncode == 0, "Duplicate launch must activate the first window"
        assert process.poll() is None and own_window(process.pid)
        assert user32.PostMessageW(handle,0x0010,0,0), "WM_CLOSE was not delivered"
        assert process.wait(timeout=30) == 0, "Native close must exit normally"
        print("DESKTOP_EXE_WINDOW_SINGLE_INSTANCE_CLOSE_PASS")
    finally:
        if process.poll() is None:
            # This isolated verifier requested no hardware writes.
            process.kill()
            process.wait(timeout=5)
