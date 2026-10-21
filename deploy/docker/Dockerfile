# arona 中转（token 注入）—— 最小镜像
#
# 只做一件事：用本机出口 IP 去调 api.arona.icu，并注入 token。
# 容器**不处理 TLS**：域名、证书、HTTPS 全部交给前置反代；这里只听内网明文 HTTP。
#
# 构建（镜像里不含任何密钥，配置一律运行时挂载）：
#   docker compose build
# 国内拉不动 Docker Hub 时：
#   docker compose build --build-arg BASE_IMAGE=docker.1panel.live/library/python:3.12-alpine
ARG BASE_IMAGE=python:3.12-alpine
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="arona-relay" \
      org.opencontainers.image.description="arona.icu token-injecting relay (HTTP only, TLS by reverse proxy)" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="AGPL-3.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROXY_CONFIG_DIR=/config \
    PROXY_PORT=30303

WORKDIR /app
COPY proxy.py /app/proxy.py
RUN chmod 0555 /app/proxy.py && mkdir -p /config

EXPOSE 30303

HEALTHCHECK --interval=30s --timeout=5s --start-period=3s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PROXY_PORT','30303'), timeout=4)"

# 刻意不指定 USER：容器要读 /config 里的密钥文件，跑成 root 最省事；
# 隔离靠 compose 的 read_only / cap_drop: ALL / no-new-privileges。
# 注意（rootless docker）：容器内 root 会映射到子 uid，宿主机上 600 的配置文件读不到，
# 那种环境下 config/ 里的文件要给 644（README 排障表有记）。
ENTRYPOINT ["python", "/app/proxy.py"]
