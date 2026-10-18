# arona 转发的容器镜像
#
# 只做一件事：用本机固定出口 IP 去调 api.arona.icu，并注入 token。
# token 不写进镜像、不写进 compose，挂载进 /run/secrets 即可。
FROM python:3.12-slim

# 证书在容器启动时自签，需要 openssl
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 构建上下文是**仓库根目录**（见 compose.yml 的 context: ../..）
COPY tools/arona_proxy.py /app/arona_proxy.py
COPY deploy/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PROXY_BIND=0.0.0.0 \
    PROXY_PORT=8443 \
    ARONA_TOKEN_FILE=/run/secrets/arona_token \
    PROXY_CERT=/app/certs/server.crt \
    PROXY_KEYFILE=/app/certs/server.key \
    CERT_DIR=/app/certs

VOLUME ["/app/certs"]

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import ssl,urllib.request;ctx=ssl._create_unverified_context();urllib.request.urlopen('https://127.0.0.1:8443/healthz',context=ctx,timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
