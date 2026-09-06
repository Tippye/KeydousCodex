"""Exercise the built EXEs and real Codex lifecycle in an isolated CODEX_HOME.

Reads device discovery only. No screen or RGB writes. Does not modify user Hooks.
"""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
from PIL import Image

root = Path(__file__).resolve().parent
executable = root / "dist" / "KeydousCodex" / "KeydousCodex.exe"
assert executable.is_file(), "Run Build.ps1 first"
parent = root / "data" / "package-acceptance"
parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="run-", dir=parent) as folder:
    base = Path(folder)
    home = base / "codex-home"
    home.mkdir()
    environment = {**os.environ, "CODEX_HOME": str(home)}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    token = ""
    def api(path, data=None):
        req = urllib.request.Request(url + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json", "X-Bridge-Token": token})
        with opener.open(req, timeout=90) as response:
            payload = response.read()
            return json.loads(payload) if response.headers.get_content_type() == "application/json" else payload
    process = subprocess.Popen([str(executable), "--data-dir", str(base / "bridge"), "--port", str(port), "--no-browser"],
                               env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                bootstrap = api("/api/bootstrap")
                break
            except OSError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Packaged application did not become ready")
                time.sleep(.1)
        token = bootstrap["token"]
        assert b"Keyphore" in api("/")
        with Image.open(io.BytesIO(api("/api/export.png"))) as image:
            assert image.size == (160, 80)
        review = api("/api/hooks/review", {})
        assert Path(review["runtime"]["executable"]).name == "KeydousCodexHook.exe"
        assert len(review["definitions"]) == 8
        installed = api("/api/hooks/install", {"digest": review["digest"], "consent": True})
        assert installed["installed"] and installed["trusted"]
        payload = {"hook_event_name": "PermissionRequest", "session_id": "package-test", "turn_id": "turn-test", "prompt": "private-placeholder"}
        started = time.monotonic()
        result = subprocess.run(review["definitions"][0]["command_windows"], shell=True,
                                input=json.dumps(payload).encode(), capture_output=True, timeout=3,
                                env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
        assert result.stdout == b"" and result.stderr == b""
        assert time.monotonic() - started < 2
        deadline = time.monotonic() + 5
        while api("/api/status")["state"] != "waiting":
            assert time.monotonic() < deadline, "Hook status was not observed"
            time.sleep(.1)
        assert "private-placeholder" not in (base / "bridge" / "hook-state.json").read_text()
        assert api("/api/hooks/refresh", {})["trusted"]
        assert not api("/api/hooks/disable", {})["trusted"]
        assert not api("/api/hooks/remove", {})["installed"]
        print("PACKAGED_EXE_HOOK_LIFECYCLE_PASS", flush=True)
    finally:
        if process.poll() is None:
            try:
                api("/api/shutdown", {})
                process.wait(timeout=25)
            except Exception:
                process.terminate()
                process.wait(timeout=5)
        assert process.returncode == 0, f"Packaged shutdown exit {process.returncode}"
    print("PACKAGED_SHUTDOWN_PASS", flush=True)
