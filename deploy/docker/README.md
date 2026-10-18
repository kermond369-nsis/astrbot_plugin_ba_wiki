# arona 转发器（纯 HTTP + 反代接管 TLS）

> 只在**家宽出口 IP 不稳定**时才需要它。正常情况下插件直连 `api.arona.icu` 就够了，
> 见 [docs/MIGRATE-TO-LOCAL.md](../../docs/MIGRATE-TO-LOCAL.md)。

## 它解决什么

arona 的 token 与**首次请求的 IP 绑定且不可改**。如果 AstrBot 所在网络出口 IP 会变，
直连就会 `4007`。这时找一台有固定 IP 的机器跑这个转发器：

```
AstrBot ──HTTPS──▶ 反代（nginx / caddy，终止 TLS）──HTTP──▶ 转发器:30303 ──▶ api.arona.icu
```

**容器不碰证书**。自签、Let's Encrypt、域名、HSTS 全部交给反代；容器只在内网回环上听一个 HTTP 口。

## 端口约定

```
宿主机  127.0.0.1:3030   ← 只绑回环，公网摸不到
容器            30303   ← 容器内固定端口
反代    443 → 127.0.0.1:3030
```

## 三分钟跑起来

```bash
cd deploy/docker

cp .env.example .env
sed -i "s/^PROXY_KEY=.*/PROXY_KEY=$(openssl rand -hex 16)/" .env

mkdir -p secrets
printf '%s\n' '<QQ号>:<密钥>' > secrets/arona_token
chmod 600 secrets/arona_token

docker compose up -d
docker compose ps                        # 应显示 healthy
curl -s http://127.0.0.1:3030/healthz    # {"ok": true, "upstream": "https://api.arona.icu"}
```

## 反代示例

### Caddy（最省事，自动签证书）

`/etc/caddy/Caddyfile`：

```caddy
arona.example.com {
    reverse_proxy 127.0.0.1:3030
}
```

```bash
sudo systemctl reload caddy
```

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name arona.example.com;

    ssl_certificate     /etc/letsencrypt/live/arona.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/arona.example.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:3030;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

> 反代**不要**加访问认证（Basic Auth 之类）——插件只带 `X-Proxy-Key`，
> 加别的会 401。要收紧就换强一点的 `PROXY_KEY`。

## 接到插件上

AstrBot 那边在插件数据目录写 `arona_proxy.json`：

```json
{"url": "https://arona.example.com", "key": "<.env 里的 PROXY_KEY>"}
```

如果 AstrBot 和转发器在**同一台机器**，可以省掉反代，直接：

```json
{"url": "http://127.0.0.1:3030", "key": "<PROXY_KEY>"}
```

重启 AstrBot。这个文件存在时插件就走转发，**不需要** `arona_token.txt`。

## 换 token

```bash
vi secrets/arona_token
docker compose restart arona-proxy
```

## 变量表

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROXY_KEY` | 必填 | 客户端调用凭证，`openssl rand -hex 16` |
| `HOST_PORT` | 3030 | 宿主机回环端口（容器内固定 30303） |
| `PROXY_PORT` | 容器内固定 30303 | 一般不用改 |
| `PROXY_TLS` | 镜像里固定 `0` | 容器不终止 TLS |
| `ARONA_TOKEN_FILE` | `/run/secrets/arona_token` | compose 已固定 |

## 注意

- 容器**只**转发 `POST /api/*` 与 `GET /healthz`，其余 404
- `PROXY_KEY` 为空会打警告但继续跑——别让它空着，尤其别把端口暴露到公网
- `secrets/`、`certs/`、`.env` 都在 `.gitignore` 里，别提交
- 想自己终止 TLS（不挂反代）也可以：`PROXY_TLS=1` 并把证书挂进容器，
  但既然有反代，就没必要
