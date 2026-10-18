# arona 转发器（Docker）

> 只在**家宽出口 IP 不稳定**时才需要它。正常情况下插件直连 `api.arona.icu` 就够了，
> 见 [docs/MIGRATE-TO-LOCAL.md](../../docs/MIGRATE-TO-LOCAL.md)。

## 它解决什么

arona 的 token 与**首次请求的 IP 绑定且不可改**。如果 AstrBot 所在网络的出口 IP 会变，
直连就会 `4007`。这时找一台有固定 IP 的机器跑这个转发器：

```
AstrBot ──HTTPS + X-Proxy-Key──▶ 转发器（固定出口 IP）──▶ api.arona.icu
```

转发器持有 token，客户端只持有共享密钥，token 不下发。

## 三分钟跑起来

```bash
cd deploy/docker

# 1. 配置
cp .env.example .env
sed -i "s/^PROXY_KEY=.*/PROXY_KEY=$(openssl rand -hex 16)/" .env
sed -i "s/^PUBLIC_IP=.*/PUBLIC_IP=$(curl -s https://api.ipify.org)/" .env

# 2. token（不进镜像、不进 git）
mkdir -p secrets
printf '%s\n' '<QQ号>:<密钥>' > secrets/arona_token
chmod 600 secrets/arona_token

# 3. 起
docker compose up -d
docker compose logs -f
```

首次启动会自动在 `certs/` 里自签一张证书（SAN 带上 `.env` 里的 `PUBLIC_IP`）。

健康检查：

```bash
docker compose ps                       # 应显示 healthy
curl -k https://127.0.0.1:8443/healthz  # {"ok": true, "upstream": "https://api.arona.icu"}
```

## 接到插件上

AstrBot 那边在插件数据目录写 `arona_proxy.json`：

```json
{"url": "https://<转发器地址>:8443", "key": "<.env 里的 PROXY_KEY>"}
```

重启 AstrBot。这个文件存在时插件就走转发，**不需要** `arona_token.txt`。

自签证书需要客户端信任，否则只能 `-k`。两种做法：

- 把 `certs/server.crt` 拷到 AstrBot 机器，装进系统信任库：
  ```bash
  sudo cp server.crt /usr/local/share/ca-certificates/arona-proxy.crt
  sudo update-ca-certificates
  ```
- 或者用 Let's Encrypt / 自己签的正规证书挂到 `certs/server.crt` 与 `certs/server.key`

## 换 token

改 `secrets/arona_token` 后：

```bash
docker compose restart arona-proxy
```

## 变量表

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROXY_KEY` | 必填 | 客户端调用凭证，`openssl rand -hex 16` |
| `PROXY_PORT` | 8443 | 宿主机端口 |
| `PUBLIC_IP` | 空 | 自签证书 SAN 里的 IP，填对外可达的地址 |
| `CERT_CN` | arona-proxy | 证书 CN |
| `ARONA_TOKEN_FILE` | `/run/secrets/arona_token` | compose 已固定 |
| `PROXY_CERT` / `PROXY_KEYFILE` | `/app/certs/server.*` | 挂载到 `./certs` |

## 注意

- **不要**把 `secrets/` 和 `certs/` 提交进仓库（`.gitignore` 已覆盖 `*.key` / `*.pem`，另见下方）
- 容器只暴露 HTTPS，内部不做鉴权以外的任何逻辑；`PROXY_KEY` 为空时会打警告，别让它空着
- 只转发 `POST /api/*` 与 `GET /healthz`，其余一律 404
