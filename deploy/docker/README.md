# arona 中转镜像

一个最小的中转服务：用**本机出口 IP** 调 `api.arona.icu` 并注入 token，
TLS / 域名 / 鉴权交给前置反代。适用于 AstrBot 所在网络出口 IP 会变的场景。

| 做 | 不做 |
|---|---|
| 校验 `X-Proxy-Key` | 不处理 TLS、不签证书 |
| 注入 `Authorization: ba-token <token>` | 不做 Host/域名校验（交给反代） |
| 原样转发 `/api/*` 的请求与响应 | 不解析业务字段、不落数据、不缓存 |
| 一行访问日志（不含 token） | 不做重试与响应改写 |

```
AstrBot（出口 IP 可能变动）
   │  HTTPS + X-Proxy-Key
   ▼
前置反代（域名 / 证书 / 鉴权）
   │  HTTP 127.0.0.1:3030
   ▼
arona-relay  ──固定出口 IP──▶  api.arona.icu     token 只存在这台机器
```

## 获取镜像

已发布到 GHCR（public，amd64 + arm64 双架构）：

```bash
docker pull ghcr.io/kermond369-nsis/arona-relay:1.0.0
```

`compose.yml` 里默认就是该镜像，`docker compose up -d` 会自动拉取。

也可以本地构建：

```bash
cd deploy/docker
docker build -t arona-relay:1.0.0 .
# Docker Hub 不可达时换基础镜像源
docker build --build-arg BASE_IMAGE=docker.1panel.live/library/python:3.12-alpine -t arona-relay:1.0.0 .
```

## 部署

```bash
mkdir -p /opt/aronaproxy/config && cd /opt/aronaproxy
cp compose.yml .                       # 仓库里的 deploy/docker/compose.yml
cp config/proxy.env.example     config/proxy.env
cp config/arona_token.txt.example config/arona_token.txt

vi config/proxy.env          # 必填 PROXY_KEY（openssl rand -hex 16）
vi config/arona_token.txt    # 只写一行 <QQ号>:<密钥>
chmod 644 config/proxy.env config/arona_token.txt

docker compose up -d
docker compose ps                        # 期望 healthy
curl -s http://127.0.0.1:3030/healthz    # 期望 ok: true
```

目录结构：

```
/opt/aronaproxy/
├── compose.yml
└── config/
    ├── proxy.env          # PROXY_KEY / PROXY_PORT / UPSTREAM / TOKEN_FILE / 限额
    └── arona_token.txt    # <QQ号>:<密钥>
```

> 权限：容器以 root 运行。rootful Docker 下 600 即可；**rootless Docker** 下容器内 root 映射到子 uid，
> 600 会 `PermissionError: /config/proxy.env`，此时用 644。

## 配置项（config/proxy.env）

| 键 | 默认 | 说明 |
|---|---|---|
| `PROXY_KEY` | 空（必填） | 客户端要带的共享密钥 |
| `PROXY_PORT` | `30303` | 容器内监听端口（改了要同步 compose 端口映射） |
| `UPSTREAM` | `https://api.arona.icu` | 上游 |
| `TOKEN_FILE` | `/config/arona_token.txt` | token 文件 |
| `MAX_BODY_BYTES` | `131072` | 单请求体上限 |
| `UPSTREAM_TIMEOUT` | `25` | 上游超时（秒） |

## 接口

| 端点 | 说明 |
|---|---|
| `GET /healthz` | 无需密钥，返回 `{ok, version, upstream, token_loaded, shared_key_set}` |
| `POST /api/*` | 唯一业务端点 |

请求要求：`X-Proxy-Key` 必须匹配；路径必须 `/api/` 开头；方法必须是 `POST`；
`Content-Type` 非 JSON 时按 `application/json` 转发（上游只吃 JSON）。

响应：上游状态码与 body **逐字节原样返回**，因此 arona 的业务错误码（`4002/4003/4005/4007`）
会原样传到插件。中转自身产生的错误：

| HTTP | 含义 |
|---|---|
| `401` | key 缺失或不匹配 |
| `404` / `405` | 路径 / 方法不对 |
| `413` | 请求体超过上限 |
| `502` | 上游不可达 |
| `503` | 未配置 `PROXY_KEY` 或未读到 token |

## 反代

容器只说 HTTP，只绑 `127.0.0.1:3030`。反代把域名转到该地址即可（鉴权/限流放反代上）：

```caddy
arona.example.com {
    reverse_proxy 127.0.0.1:3030
}
```

```nginx
location / {
    proxy_pass       http://127.0.0.1:3030;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

> 反代不要再叠加其他凭证（如 Basic Auth）：插件只会带 `X-Proxy-Key`。
> 反代在另一个容器里时，删掉 compose 的 `ports`，接入同一 docker 网络，用 `http://arona-relay:30303`。

## 接入插件

插件数据目录写 `arona_proxy.json`（填**域名**）：

```json
{"url": "https://arona.example.com", "key": "<config/proxy.env 里的 PROXY_KEY>"}
```

```bash
chmod 600 arona_proxy.json
```

该文件存在时插件走中转，忽略 `arona_token.txt`。自检：

```bash
PLUGINS=<AstrBot>/data/plugins bash tools/arona_check.sh
```

## 运维

| 场景 | 做法 |
|---|---|
| 换 token | 改 `config/arona_token.txt`，**无需重启**（按 mtime 热加载，日志会打印加载记录） |
| 改 key / 端口 | 改 `config/proxy.env`，`docker compose restart` |
| 看日志 | `docker compose logs -f`：`时间 客户端IP host=... POST /api/xxx -> 200 87ms upstream_code=200` |
| 判断故障位置 | 日志里 `upstream_code` 是 arona 的业务码；`401/404/413/502/503` 才是中转侧 |

排障：

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即退出，日志 `PermissionError: /config/proxy.env` | 配置 600 且 docker 为 rootless | `chmod 644 config/proxy.env config/arona_token.txt` |
| `docker compose ps` 一直 unhealthy | 同上，或宿主机端口被占用 | 先看 `docker logs`，再查 3030 占用 |
| 插件报 `401` | 两边 `PROXY_KEY` 不一致 | 比对 `proxy.env` 与 `arona_proxy.json` |
| 插件报 `503` | 没读到 token | 看 `/healthz` 的 `token_loaded`；确认 token 文件只有一行 |

## token 与出口 IP

- token 与**首次请求的出口 IP** 绑定，绑定后不可自行修改；换 IP 需站方处理
- 因此 token 应当在这台中转机的环境下首次使用，不要先在别处试
- 从非绑定 IP 反复请求会触发封禁（`4005`），封禁期间停止请求

## 安全清单

- [ ] `PROXY_KEY` 用 `openssl rand -hex 16` 以上
- [ ] 3030 只绑 `127.0.0.1`，公网只经反代
- [ ] `config/` 权限收紧，且不提交进任何仓库（`.gitignore` 已覆盖）
- [ ] 镜像构建上下文已排除 `config/`（`.dockerignore`）

## 与 systemd 版转发器的关系

`deploy/arona-proxy.service` + `tools/arona_proxy.py` 是等价的 systemd 实现，协议兼容
（`X-Proxy-Key` + `POST /api/*`），已标 LEGACY，仅作回滚备件。
