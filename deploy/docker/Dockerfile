# arona 转发器（纯 HTTP 版）
#
# 只做一件事：用本机固定出口 IP 去调 api.arona.icu，并注入 token。
# 容器本身**不处理 TLS** —— 证书、HTTPS、域名都交给前置反代，容器只监听内网 HTTP 端口。
FROM python:3.12-slim

WORKDIR /app

# 构建上下文是**仓库根目录**（见 compose.yml 的 context: ../..）
COPY tools/arona_proxy.py /app/arona_proxy.py
COPY deploy/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PROXY_BIND=0.0.0.0 \
    PROXY_PORT=30303 \
    PROXY_TLS=0 \
    ARONA_TOKEN_FILE=/run/secrets/arona_token

EXPOSE 30303

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:30303/healthz',timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
