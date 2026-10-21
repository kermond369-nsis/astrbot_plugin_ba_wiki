#!/usr/bin/env python3
"""arona.icu 中转（token 注入）—— 极简 HTTP 转发。

职责只有一个：**把请求用本机出口 IP 转给 api.arona.icu，并注入 token**。
- 不处理 TLS：证书 / HTTPS / 域名都交给前置反代，本服务只监听内网明文 HTTP。
- 不认识业务字段：请求体、响应体原样透传，插件侧的错误码映射（4002/4005/4007）不受影响。
- 不落业务数据：只打一行访问日志（不含 token、不含响应体）。

配置目录（容器内 /config，只读挂载）：
    /config/proxy.env        键值对，见 proxy.env.example
    /config/arona_token.txt  <QQ号>:<密钥>（改完不用重启，按 mtime 热加载）
"""

from __future__ import annotations

import hmac
import http.client
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
CONFIG_DIR = os.environ.get("PROXY_CONFIG_DIR", "/config")
ENV_FILE = os.path.join(CONFIG_DIR, "proxy.env")


# ----------------------------------------------------------------- 配置
def load_env_file(path: str) -> dict[str, str]:
    """读 KEY=VALUE 形式的配置文件（支持 # 注释、引号、export 前缀）。"""
    cfg: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                cfg[k.strip()] = v
    except FileNotFoundError:
        pass
    return cfg


_FILE_CFG = load_env_file(ENV_FILE)


def conf(name: str, default: str = "") -> str:
    """环境变量优先，其次 /config/proxy.env，最后默认值。"""
    return (os.environ.get(name) or _FILE_CFG.get(name) or default).strip()


BIND = conf("PROXY_BIND", "0.0.0.0")
PORT = int(conf("PROXY_PORT", "30303"))
SHARED_KEY = conf("PROXY_KEY")
UPSTREAM = conf("UPSTREAM", "https://api.arona.icu").rstrip("/")
TOKEN_FILE = conf("TOKEN_FILE", os.path.join(CONFIG_DIR, "arona_token.txt"))
MAX_BODY = int(conf("MAX_BODY_BYTES", str(128 * 1024)))
TIMEOUT = float(conf("UPSTREAM_TIMEOUT", "25"))

# 上游是域名 + 需固定出口 IP：环境里有 http_proxy 之类的变量会破坏绑定，直接忽略代理
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ----------------------------------------------------------------- token 热加载
_token_lock = threading.Lock()
_token_value = ""
_token_mtime = -1.0


def current_token() -> str:
    """按文件 mtime 热加载：改 token 不需要重启容器。"""
    global _token_value, _token_mtime
    with _token_lock:
        try:
            mtime = os.stat(TOKEN_FILE).st_mtime
        except OSError:
            _token_value, _token_mtime = "", -1.0
            return ""
        if mtime != _token_mtime:
            try:
                with open(TOKEN_FILE, encoding="utf-8") as f:
                    _token_value = f.read().strip()
                _token_mtime = mtime
                sys.stderr.write("[config] 已加载 token（%d 字符，来源 %s）\n" % (len(_token_value), TOKEN_FILE))
            except OSError as e:
                sys.stderr.write("[config] 读 token 失败：%s\n" % e)
                _token_value = ""
        return _token_value


# ----------------------------------------------------------------- HTTP
def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode()


def _json_ctype(value: str | None) -> str:
    """上游只接受 JSON：不认的 Content-Type 一律兜成 application/json。"""
    ct = (value or "").strip()
    return ct if "json" in ct.lower() else "application/json"


class Handler(BaseHTTPRequestHandler):
    server_version = "arona-relay/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # 访问日志自己打，屏蔽 BaseHTTPRequestHandler 的 stderr 噪音
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        pass

    # ------------------------------------------------------------ 工具
    def _client_ip(self) -> str:
        xff = self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or ""
        first = xff.split(",")[0].strip()
        return first or self.client_address[0]

    def _access_log(self, status: int, extra: str = "") -> None:
        sys.stderr.write(
            "%s %s host=%s %s %s -> %d%s\n"
            % (
                time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                self._client_ip(),
                self.headers.get("Host", "-"),
                self.command,
                self.path,
                status,
                (" " + extra) if extra else "",
            )
        )
        sys.stderr.flush()

    def _send(self, status: int, payload: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(self, status: int, obj) -> None:
        self._send(status, _json_bytes(obj))

    # ------------------------------------------------------------ 路由
    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0].rstrip("/") in ("/healthz", "/health"):
            token = current_token()
            self._send_json(
                200,
                {
                    "ok": bool(SHARED_KEY) and bool(token),
                    "version": VERSION,
                    "upstream": UPSTREAM,
                    "token_loaded": bool(token),
                    "shared_key_set": bool(SHARED_KEY),
                },
            )
            self._access_log(200, "healthz")
            return
        self._send_json(404, {"code": 404, "message": "只提供 GET /healthz 与 POST /api/*"})
        self._access_log(404)

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        started = time.monotonic()
        if not SHARED_KEY:
            self._send_json(503, {"code": 503, "message": "中转未配置 PROXY_KEY，拒绝服务"})
            self._access_log(503, "no-shared-key")
            return

        given = self.headers.get("X-Proxy-Key", "")
        if not hmac.compare_digest(given.strip(), SHARED_KEY):
            self._send_json(401, {"code": 401, "message": "X-Proxy-Key 缺失或不匹配"})
            self._access_log(401, "bad-key")
            return

        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            self._send_json(404, {"code": 404, "message": "只转发 /api/*"})
            self._access_log(404)
            return

        token = current_token()
        if not token:
            self._send_json(503, {"code": 503, "message": "中转侧没有可用的 arona token（%s）" % TOKEN_FILE})
            self._access_log(503, "no-token")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._send_json(411, {"code": 411, "message": "需要 Content-Length"})
            self._access_log(411)
            return
        if length > MAX_BODY:
            self._send_json(413, {"code": 413, "message": "请求体超过 %d 字节" % MAX_BODY})
            self._access_log(413)
            return
        body = self.rfile.read(length) if length else b""

        req = urllib.request.Request(
            UPSTREAM + path,
            data=body,
            method="POST",
            headers={
                # 关键：只带 token，不转发客户端的 Authorization / Cookie 之类
                "Authorization": "ba-token " + token,
                # arona 只吃 JSON：客户端漏发或发错 Content-Type 时兜成 application/json，
                # 否则上游会以 HTTP 200 + code 500 的形式报错，看起来像中转的问题
                "Content-Type": _json_ctype(self.headers.get("Content-Type")),
                "Accept": "application/json",
                "User-Agent": "arona-relay/" + VERSION,
            },
        )
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as resp:
                status, ctype, raw = resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib.error.HTTPError as e:                      # 上游非 2xx：原样带回
            status, ctype, raw = e.code, e.headers.get("Content-Type", ""), e.read()
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            self._send_json(502, {"code": 502, "message": "上游不可达：%s" % e})
            self._access_log(502, "upstream-error")
            return

        self._send(status, raw, ctype or "application/json; charset=utf-8")
        cost = int((time.monotonic() - started) * 1000)
        # 上游业务码（200/4002/4005/4007）打在日志里，方便一眼看出是不是封禁
        code = ""
        try:
            code = " upstream_code=%s" % json.loads(raw.decode("utf-8", "ignore")).get("code")
        except Exception:  # noqa: BLE001
            pass
        self._access_log(status, "%dms%s" % (cost, code))

    def do_PUT(self) -> None:  # noqa: N802
        self._not_allowed()

    do_DELETE = do_PATCH = do_PUT

    def _not_allowed(self) -> None:
        self._send_json(405, {"code": 405, "message": "只支持 GET /healthz、POST /api/*"})
        self._access_log(405)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    if not SHARED_KEY:
        sys.stderr.write("[warn] PROXY_KEY 未设置：所有 /api/* 请求都会被 503 拒绝\n")
    if current_token():
        sys.stderr.write("[boot] token 就绪，上游 %s\n" % UPSTREAM)
    else:
        sys.stderr.write("[warn] %s 不存在或为空：现在只有 /healthz 可用\n" % TOKEN_FILE)

    srv = Server((BIND, PORT), Handler)
    sys.stderr.write("[boot] arona-relay %s 监听 %s:%d（HTTP，TLS 交给前置反代）\n" % (VERSION, BIND, PORT))

    def _stop(signum, _frame):
        sys.stderr.write("[boot] 收到信号 %d，退出\n" % signum)
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
