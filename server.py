#!/usr/bin/env python3
"""Loopback-only server for 吉吉编辑软件. No telemetry or external document upload."""
from __future__ import annotations
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import threading
import urllib.parse
import webbrowser

from jiji.engine import Workspace, UserError, sample_pdf

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.workspace = Workspace()
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args):
        pass  # Never log request URLs, document names, or session secrets.

    def respond(self, data, status=200, kind="application/json; charset=utf-8", extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self, api=True):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.respond({"error": "仅允许从本机打开。"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self.respond({"error": "请求来源不正确。"}, 403)
            return False
        if api and not secrets.compare_digest(self.headers.get("X-Jiji-Token", ""), self.server.token):
            self.respond({"error": "会话已失效，请从吉吉启动器重新打开。"}, 401)
            return False
        return True

    def do_GET(self):
        route = urllib.parse.urlsplit(self.path)
        if not self.allowed(route.path.startswith("/api/")):
            return
        try:
            with self.server.workspace.lock:
                work = self.server.workspace
                query = urllib.parse.parse_qs(route.query)
                if route.path == "/api/state":
                    self.respond(work.state())
                elif route.path == "/api/render":
                    self.respond(work.render(int(query.get("page", [0])[0]), float(query.get("scale", [1])[0])), kind="image/png")
                elif route.path == "/api/blocks":
                    self.respond(work.blocks(int(query.get("page", [0])[0])))
                elif route.path == "/api/export":
                    pages = query.get("pages", [None])[0]
                    selected = [int(p) for p in pages.split(",")] if pages is not None else None
                    self.respond(work.export(selected), kind="application/pdf")
                elif route.path in {"/", "/index.html", "/style.css", "/app.js", "/icon.svg"}:
                    file = ROOT / "web" / ("index.html" if route.path == "/" else route.path.lstrip("/"))
                    self.respond(file.read_bytes(), kind=mimetypes.guess_type(file)[0] or "application/octet-stream")
                else:
                    self.respond({"error": "未找到页面。"}, 404)
        except UserError as e:
            self.respond({"error": str(e)}, 400)
        except (ValueError, TypeError, KeyError):
            self.respond({"error": "输入不正确，请重试。"}, 400)
        except Exception as e:
            print(f"Request failed: {type(e).__name__}", file=sys.stderr)
            self.respond({"error": "操作未成功，原文件未改变。请重新打开文件后重试。"}, 500)

    def do_POST(self):
        if not self.allowed():
            self.close_connection = True
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 180 * 1024 * 1024:
                self.close_connection = True
                self.respond({"error": "单次导入总大小请控制在 128 MB 以内。"}, 413)
                return
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError()
            with self.server.workspace.lock:
                work = self.server.workspace
                if self.path == "/api/open":
                    result = work.load(data.get("files"), data.get("password", ""), data.get("append", False))
                elif self.path == "/api/edit":
                    result = work.edit(data)
                elif self.path == "/api/sample":
                    result = work.load([{"name": "自由一点_示例.pdf", "data": base64.b64encode(sample_pdf()).decode()}])
                else:
                    self.respond({"error": "未找到操作。"}, 404)
                    return
                self.respond(result)
        except UserError as e:
            self.respond({"error": str(e)}, 400)
        except (ValueError, KeyError, TypeError):
            self.respond({"error": "输入不正确，请重试。"}, 400)
        except Exception as e:
            print(f"Edit failed: {type(e).__name__}", file=sys.stderr)
            self.respond({"error": "处理失败，未保存本次操作。请检查文件后重试。"}, 500)


def main():
    parser = argparse.ArgumentParser(description="吉吉编辑软件 · 本地免费 PDF 编辑器")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--url-file")
    args = parser.parse_args()
    server = LocalServer(args.port)
    url = server.origin + "/#token=" + server.token
    if args.url_file:
        path = Path(args.url_file)
        path.write_text(url)
        os.chmod(path, 0o600)
    print(url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.url_file:
            Path(args.url_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
