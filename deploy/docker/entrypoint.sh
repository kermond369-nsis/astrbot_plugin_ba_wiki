#!/bin/sh
# 启动前确认 token 可读；TLS 与证书不归容器管，由前置反代负责。
set -eu

TOKEN_FILE="${ARONA_TOKEN_FILE:-/run/secrets/arona_token}"
if [ ! -s "$TOKEN_FILE" ]; then
    echo "[entrypoint] 致命：token 文件不存在或为空：$TOKEN_FILE" >&2
    echo "[entrypoint] 请把 <QQ号>:<密钥> 写进宿主机的 secrets/arona_token 再启动" >&2
    exit 1
fi

if [ -z "${PROXY_KEY:-}" ]; then
    echo "[entrypoint] 警告：PROXY_KEY 为空，任何能访问该端口的人都能用这条转发" >&2
fi

# 只监听内网时通常已在 compose 里绑到 127.0.0.1，这里再提示一次
echo "[entrypoint] 监听 ${PROXY_BIND:-0.0.0.0}:${PROXY_PORT:-30303}（HTTP，无 TLS）" >&2

exec python /app/arona_proxy.py
