"""Loopback-only HTTP UI. Mutations require same-origin requests and a per-run token."""
from __future__ import annotations

import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
from .integration import IntegrationError
from . import __version__

MAX_BODY = 18 * 1024 * 1024
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app, port: int = 47698):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        self.webroot = Path(__file__).parent / "web"
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: BridgeServer
    server_version = "KeydousBridge/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        pass

    def _authorized_origin(self) -> bool:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host for host in hosts}:
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return True

    def _send(self, payload: bytes, kind: str, status: int = 200, attachment: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: object, status: int = 200):
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self):
        if not self._authorized_origin():
            return self._json({"error": "只允许本机同源访问"}, 403)
        try:
            route = urlsplit(self.path)
            path = route.path
            app = self.server.app
            if path in STATIC:
                filename, mime = STATIC[path]
                return self._send((self.server.webroot / filename).read_bytes(), mime)
            if path == "/api/health":
                return self._json({"ok": True, "version": __version__})
            if path == "/api/bootstrap":
                return self._json({**app.bootstrap(), "token": self.server.token})
            if path == "/api/status":
                return self._json(app.snapshot())
            if path == "/api/pets":
                return self._json({"pets": app.pets.list()})
            if path == "/api/sessions":
                return self._json({"sessions": app.sessions()})
            if path in {"/api/preview.gif", "/api/export.gif", "/api/export.png"}:
                query = parse_qs(route.query, max_num_fields=12)
                options = {key: query[key][0] for key in ("pet_id", "background", "layout") if key in query}
                format = "gif" if path.endswith(".gif") else "png"
                data = app.preview(format, state=query.get("state", [None])[0], options=options)
                return self._send(data, "image/" + format,
                                  attachment="keydous-pet." + format if path.startswith("/api/export") else None)
            return self._json({"error": "接口不存在"}, 404)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        except OSError as exc:
            self._json({"error": str(exc)}, 503)
        except Exception:
            self._json({"error": "读取失败，请查看配置和资源文件"}, 500)

    def do_POST(self):
        if not self._authorized_origin() or not hmac.compare_digest(self.headers.get("X-Bridge-Token", ""), self.server.token):
            self.close_connection = True
            return self._json({"error": "请求来源或会话令牌无效，请刷新本地页面"}, 403)
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("不支持分块请求")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请求必须是 JSON")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("请求大小超出限制")
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise ValueError("请求内容不完整")
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("请求必须是 JSON 对象")
            path = urlsplit(self.path).path
            app = self.server.app
            if path == "/api/config":
                result = app.update_config(data)
            elif path == "/api/state":
                result = app.set_state(data.get("state"))
            elif path == "/api/connect":
                result = app.connect()
            elif path == "/api/input/select":
                result = app.update_config({"source": "jsonl", "session_path": data.get("path", "")})
            elif path == "/api/upload":
                result = app.start_upload(data.get("slot"), data.get("render"), data.get("state"))
            elif path == "/api/cancel-upload":
                app.cancel.set()
                result = {"ok": True}
            elif path == "/api/rgb/restore":
                result = app.restore_rgb()
            elif path in {"/api/mapping/read", "/api/mapping/apply", "/api/mapping/restore",
                          "/api/mapping/knob-enable", "/api/mapping/knob-restore"}:
                result = app.key_mapping(path.rsplit("/", 1)[1], data)
            elif path == "/api/macos-fn/status":
                if app.stop.is_set():
                    raise ValueError("程序正在退出")
                result = app.mac_fn.refresh()
            elif path == "/api/macos-fn/enable":
                if app.stop.is_set():
                    raise ValueError("程序正在退出")
                result = app.mac_fn.enable(data)
            elif path == "/api/macos-fn/disable":
                result = app.mac_fn.disable()
            elif path == "/api/macos-fn/remove-helper":
                if data:
                    raise ValueError("移除组件不接受额外参数")
                result = app.mac_fn.remove_helper()
            elif path == "/api/hooks/review":
                with app.mutation():
                    result = app.integration.review()
            elif path == "/api/hooks/install":
                if data.get("consent") is not True:
                    raise ValueError("请先审阅八条 Hook 并确认启用")
                with app.mutation():
                    result = app.integration.install(data.get("digest"))
                    app.update_config({"source": "hooks"})
            elif path == "/api/hooks/refresh":
                with app.mutation():
                    result = app.integration.status(refresh=True)
            elif path == "/api/hooks/disable":
                with app.mutation():
                    result = app.integration.disable()
            elif path == "/api/hooks/remove":
                with app.mutation():
                    result = app.integration.remove()
            elif path == "/api/pet/import":
                text = data.get("spritesheet", "")
                if not isinstance(text, str):
                    raise ValueError("宠物图片必须为 base64")
                image = base64.b64decode(text, validate=True)
                with app.mutation():
                    result = app.pets.import_pet(data.get("name", ""), data.get("manifest"), image)
            elif path == "/api/pets/import-codex":
                with app.mutation():
                    result = {"pets": app.pets.import_codex()}
            elif path == "/api/shutdown":
                app.begin_close()
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, name="bridge-stop", daemon=True).start()
                return
            else:
                return self._json({"error": "接口不存在"}, 404)
            self._json(result)
        except (ValueError, TypeError, IntegrationError) as exc:
            self.close_connection = True
            self._json({"error": str(exc)}, 400)
        except OSError as exc:
            self._json({"error": str(exc)}, 503)
        except Exception:
            self._json({"error": "操作失败，请检查设备与本地资源"}, 500)
