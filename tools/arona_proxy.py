#!/usr/bin/env python3
"""arona.icu API 转发器（HTTPS 端点）。

为什么需要：arona.icu 的 token 与首次请求的 IP 绑定，绑定在这台云服务器上。
AstrBot 跑在家里局域网，出口 IP 不同，直接用 token 会校验失败。
所以让请求绕一圈：家里 AstrBot --HTTPS--> 这台机器 --HTTPS--> arona。
出口 IP 仍是这台机器，token 校验通过。

设计：
- HTTPS 监听（自签证书，SAN 绑定本机 IP），客户端在 AstrBot主机 上信任该证书
- 共享密钥头 X-Proxy-Key，防止被扫到就白用
- token 只存在本机 /root/.arona_token，不下发给客户端
- 只转发 /api/* 的 POST
"""

import json
import os
import ssl
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://api.arona.icu"
BIND = os.environ.get("PROXY_BIND", "0.0.0.0")
PORT = int(os.environ.get("PROXY_PORT", "8443"))
KEY = os.environ.get("PROXY_KEY", "")
TOKEN_FILE = os.environ.get("ARONA_TOKEN_FILE", "/root/.arona_token")
CERT = os.environ.get("PROXY_CERT", "/opt/astrbot-qq/arona-proxy.crt")
KEYFILE = os.environ.get("PROXY_KEYFILE", "/opt/astrbot-qq/arona-proxy.key")


def load_token() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        print("[proxy] " + (fmt % args), flush=True)

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        # 健康检查：客户端可先探这个确认链路通
        if self.path == "/healthz":
            self._send_json(200, {"ok": True, "upstream": UPSTREAM})
        else:
            self._send_json(404, {"ok": False, "message": "only /healthz and POST /api/*"})

    def do_POST(self):  # noqa: N802
        if KEY and self.headers.get("X-Proxy-Key") != KEY:
            self._send_json(401, {"code": 401, "message": "invalid proxy key"})
            return
        if not self.path.startswith("/api/"):
            self._send_json(404, {"code": 404, "message": "only /api/* is forwarded"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else b""

        token = load_token()
        if not token:
            self._send_json(500, {"code": 500, "message": "upstream token missing on proxy host"})
            return

        headers = {
            "Authorization": f"ba-token {token}",
            "Content-Type": "application/json",
            "User-Agent": "astrbot-ba-wiki/0.6 (via https proxy)",
            "Accept": "application/json",
        }
        req = urllib.request.Request(
            UPSTREAM + self.path, data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body, status = resp.read(), resp.status
                ctype = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
            ctype = e.headers.get("Content-Type", "application/json")
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"code": 502, "message": f"upstream error: {type(e).__name__}: {e}"})
            return

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    if not KEY:
        print("[proxy] 警告：PROXY_KEY 为空，任何扫到端口的人都能用", flush=True)
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT, KEYFILE)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"[proxy] https://{BIND}:{PORT} -> {UPSTREAM}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
