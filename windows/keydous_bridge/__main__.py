from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import os
import signal
import threading
import webbrowser

from .config import data_directory
from .iot import IoTClient


def report_error(message: str):
    if sys.stderr:
        print(message, file=sys.stderr)
    elif os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "Keyphore · Keydous", 0x40)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Codex Pet → Keydous 本地桥接")
    parser.add_argument("--data-dir", type=Path, default=data_directory(), help="配置和导入宠物保存目录")
    parser.add_argument("--port", type=int, default=47698, help="本机页面端口；0 自动分配")
    ui_mode = parser.add_mutually_exclusive_group()
    ui_mode.add_argument("--no-browser", action="store_true", help="无窗口运行，供后台模式和自动验收使用")
    ui_mode.add_argument("--browser", action="store_true", help="显式使用旧浏览器控制台")
    parser.add_argument("--diagnose", action="store_true", help="只读列举 IoT 设备并退出")
    parser.add_argument("--hook", action="store_true", help="读取一个 Codex Hook，只保存状态，不控制硬件")
    args = parser.parse_args(argv)
    if args.hook:
        from .hook_core import HookStore, MAX_INPUT_BYTES
        try:
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("Hook input exceeds 1 MiB")
            HookStore(args.data_dir / "hook-state.json").handle(json.loads(raw))
            return 0
        except (OSError, ValueError, TypeError) as exc:
            if sys.stderr:
                print("Keyphore Keydous hook: " + str(exc), file=sys.stderr)
            return 1
    if args.diagnose:
        try:
            result = {"iot": "connected", "devices": [device.public() for device in IoTClient().discover()]}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, EOFError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 1
    if not 0 <= args.port <= 65535:
        parser.error("端口必须为 0–65535")
    from .app import BridgeApp
    from .server import BridgeServer
    from .instance import HardwareOwner
    try:
        owner = HardwareOwner()
    except OSError as exc:
        if sys.platform == "win32" and not args.no_browser and not args.browser:
            from .desktop import activate_existing_window
            if activate_existing_window():
                return 0
        report_error(str(exc))
        return 1
    app = None
    try:
        app = BridgeApp(args.data_dir)
        server = BridgeServer(app, args.port)
    except (OSError, ValueError) as exc:
        try:
            if app is not None:
                app.close()
        finally:
            owner.close()
        message = f"无法启动应用服务：{exc}\n程序可能已在运行，请先关闭原程序再启动。"
        report_error(message)
        return 1
    previous_signal = None
    def terminate(*_):
        app.begin_close()
        threading.Thread(target=server.shutdown, daemon=True).start()
    try:
        if threading.current_thread() is threading.main_thread():
            previous_signal = signal.signal(signal.SIGTERM, terminate)
        app.start()
        if sys.stdout:
            print(server.url, flush=True)
        if sys.platform == "win32" and not args.no_browser and not args.browser:
            from .desktop import run_desktop
            try:
                run_desktop(server, app, args.data_dir)
            except (RuntimeError, OSError) as exc:
                report_error(str(exc))
                return 1
        else:
            if not args.no_browser:
                webbrowser.open(server.url)
            server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.server_close()
        finally:
            try:
                app.close()
            finally:
                try:
                    owner.close()
                finally:
                    if previous_signal is not None:
                        signal.signal(signal.SIGTERM, previous_signal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
