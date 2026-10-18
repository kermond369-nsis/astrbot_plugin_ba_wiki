#!/bin/sh
# 启动前确保：
#   1. 证书存在（没有就按 CERT_CN 自签一张，SAN 里带上 PUBLIC_IP）
#   2. token 文件可读（否则直接退出，别让它静默 401）
set -eu

CERT="${PROXY_CERT:-/app/certs/server.crt}"
KEYFILE="${PROXY_KEYFILE:-/app/certs/server.key}"
CERT_DIR="$(dirname "$CERT")"
CN="${CERT_CN:-arona-proxy}"
PUBLIC_IP="${PUBLIC_IP:-}"

mkdir -p "$CERT_DIR"

if [ ! -f "$CERT" ] || [ ! -f "$KEYFILE" ]; then
    echo "[entrypoint] 未找到证书，自签一张（CN=$CN${PUBLIC_IP:+, IP=$PUBLIC_IP}）" >&2
    SAN="DNS:$CN"
    if [ -n "$PUBLIC_IP" ]; then
        SAN="$SAN,IP:$PUBLIC_IP"
    fi
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout "$KEYFILE" -out "$CERT" \
        -subj "/CN=$CN" \
        -addext "subjectAltName=$SAN" 2>/dev/null
    chmod 600 "$KEYFILE"
    echo "[entrypoint] 证书已生成：$CERT" >&2
    echo "[entrypoint] 客户端需要信任它（或改用正规证书挂进来）" >&2
else
    echo "[entrypoint] 复用已有证书：$CERT" >&2
fi

TOKEN_FILE="${ARONA_TOKEN_FILE:-/run/secrets/arona_token}"
if [ ! -s "$TOKEN_FILE" ]; then
    echo "[entrypoint] 致命：token 文件不存在或为空：$TOKEN_FILE" >&2
    echo "[entrypoint] 请把 <QQ号>:<密钥> 写进宿主机的 secrets/arona_token 再启动" >&2
    exit 1
fi

if [ -z "${PROXY_KEY:-}" ]; then
    echo "[entrypoint] 警告：PROXY_KEY 为空，任何能扫到端口的人都能用这条转发" >&2
fi

exec python /app/arona_proxy.py
