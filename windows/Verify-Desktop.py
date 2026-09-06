"""Real WebView2 render/navigation/export/quit check using isolated app data.

Run with the source Python environment, after closing any existing app.
No Hooks are installed and no device writes are requested.
"""
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.request

import webview
from keydous_bridge.app import BridgeApp
from keydous_bridge.desktop import run_desktop
from keydous_bridge.instance import HardwareOwner
from keydous_bridge.server import BridgeServer

root = Path(__file__).resolve().parent
parent = root / "data" / "desktop-acceptance"
parent.mkdir(parents=True, exist_ok=True)
failures = []
observations = []
original_create = webview.create_window

with tempfile.TemporaryDirectory(prefix="run-", dir=parent, ignore_cleanup_errors=True) as folder, HardwareOwner():
    directory = Path(folder)
    app = BridgeApp(directory)
    server = BridgeServer(app, 0)

    def inspect(window):
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = window.evaluate_js("({host:document.documentElement.dataset.host,ready:document.querySelector('#bridge-label').textContent,image:document.querySelector('#preview-image').naturalWidth})")
                if state.get("host") == "desktop" and state.get("image") == 160:
                    break
                time.sleep(.1)
            assert state.get("host") == "desktop" and state.get("image") == 160, state
            window.evaluate_js("document.querySelector('#settings-button').click()")
            assert window.evaluate_js("!document.querySelector('#settings-view').hidden")
            assert not window.evaluate_js("document.documentElement.scrollWidth > innerWidth")
            # Fetch the rendered export through the real page's current URL.
            export = window.evaluate_js("document.querySelector('#export-png').href")
            with urllib.request.urlopen(export, timeout=10) as response:
                assert response.read(8) == b"\x89PNG\r\n\x1a\n"
            observations.append("WEBVIEW2_RENDER_SETTINGS_EXPORT_PASS")
            # Existing in-page Quit button traverses the production token/API path.
            window.evaluate_js("window.confirm = () => true; document.querySelector('#shutdown-button').click()")
        except Exception as exc:
            failures.append(repr(exc))
            window.destroy()

    def create(*args, **kwargs):
        window = original_create(*args, **kwargs)
        window.events.loaded += lambda: threading.Thread(target=inspect,args=(window,),daemon=True).start()
        return window

    webview.create_window = create
    try:
        app.start()
        run_desktop(server, app, directory)
    finally:
        server.server_close()
        app.close()
        webview.create_window = original_create
assert observations and not failures, failures
print(*observations, "DESKTOP_API_QUIT_PASS", sep="\n")
