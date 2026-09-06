"""Windows port of Keyphore's app-server lifecycle client (GPL-3.0-only).

Based on src/app_server.rs, Copyright (c) 2026 Barry Barry Wu.
Only configuration RPCs are used; this client never resumes or starts tasks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import sys

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def find_codex() -> Path:
    if sys.platform == "darwin":
        for bundle in (Path("/Applications/Codex.app"), Path.home() / "Applications/Codex.app"):
            candidate = bundle / "Contents/Resources/codex"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        executable = shutil.which("codex")
        if executable:
            return Path(executable)
        raise FileNotFoundError("未找到 Codex，请先安装 Codex 桌面应用或 CLI")
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = sorted(base.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
    if candidates:
        return candidates[0]
    executable = shutil.which("codex.exe") or shutil.which("codex")
    if executable:
        return Path(executable)
    raise FileNotFoundError("未找到支持 Plugin/Hook 的 Codex，请先安装 Codex")


class CodexRPC:
    def __init__(self, executable: Path | None = None, environment: dict | None = None):
        self.executable = executable or find_codex()
        self.environment = environment

    def cli(self, args: list[str]) -> dict:
        result = subprocess.run([str(self.executable), *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30,
                                env=self.environment, creationflags=FLAGS)
        if result.returncode:
            raise OSError("Codex 插件操作失败：" + (result.stderr.strip() or result.stdout.strip())[-1200:])
        try:
            return json.loads(result.stdout)
        except ValueError:
            return {"message": result.stdout.strip()[-500:]}

    def request(self, method: str, params: dict) -> dict:
        if method not in {"hooks/list", "config/batchWrite"}:
            raise ValueError("Unsupported lifecycle RPC")
        process = subprocess.Popen([str(self.executable), "app-server", "--stdio"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=self.environment, creationflags=FLAGS)
        messages = queue.Queue(maxsize=128)
        stop = threading.Event()

        def read():
            try:
                while not stop.is_set():
                    line = process.stdout.readline(1024 * 1024 + 1)
                    if not line:
                        break
                    if len(line) > 1024 * 1024:
                        break
                    messages.put(line, timeout=0.2)
            except (OSError, queue.Full):
                pass
            finally:
                try:
                    messages.put_nowait(None)
                except queue.Full:
                    pass
        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def write(value):
            process.stdin.write(json.dumps(value).encode() + b"\n")
            process.stdin.flush()

        def result(identifier):
            deadline = time.monotonic() + 8
            while True:
                try:
                    line = messages.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty as exc:
                    raise TimeoutError("Codex 配置接口超时") from exc
                if line is None:
                    raise OSError("Codex 配置接口已关闭")
                payload = json.loads(line)
                if payload.get("id") != identifier:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Codex 配置接口超时")
                    continue
                if "error" in payload:
                    raise OSError("Codex 拒绝配置请求：" + str(payload["error"].get("message", "未知错误")))
                return payload.get("result", {})
        try:
            write({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "keyphore-keydous", "version": "0.1.0"}}})
            result(1)
            write({"method": "initialized"})
            write({"id": 2, "method": method, "params": params})
            return result(2)
        finally:
            stop.set()
            process.stdin.close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            reader.join(timeout=1)
            process.stdout.close()
