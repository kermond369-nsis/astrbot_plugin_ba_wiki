# arona 中转（token 注入）

> 最小职责：**用本机出口 IP 去调 `api.arona.icu`，并注入 token**。
> 不管 TLS、不管域名、不管鉴权 —— 那些交给你自己的反代。

## 它做什么 / 不做什么

| 做 | 不做 |
|---|---|
| 校验 `X-Proxy-Key` | 不终止 TLS、不签证书 |
| 给上游注入 `Authorization: ba-token <token>` | 不做域名/Host 白名单（你的反代管） |
| 把 `/api/*` 的请求体、响应体原样转发 | 不解析业务字段、不落数据 |
| 一行访问日志（不含 token） | 不缓存、不重试、不改写响应 |

```
AstrBot（家宽，IP 会变）
   │  HTTPS + X-Proxy-Key      ← 域名 / 证书 / 鉴权都是你自己的反代
   ▼
你的反代  ──HTTP 127.0.0.1:3030──▶  arona-relay  ──固定出口 IP──▶  api.arona.icu
                                     └ token 只存在这台机器
```

## 镜像怎么用（推荐）

这是**打包好的镜像**，服务器上不需要源码、不需要构建：

```bash
# 1) 把镜像文件传上去（文件名以你拿到的为准）
scp arona-relay-1.0.0.tar.gz root@你的服务器:/root/

# 2) 导入（gzip 的 tar 包，docker load 直接认）
docker load -i /root/arona-relay-1.0.0.tar.gz
docker images | grep arona-relay          # 应看到 arona-relay  1.0.0
```

> 镜像是 **linux/amd64**。目标机不是 amd64 时，用下面的"自己构建"在本机编译。

## 部署（三条命令 + 两个配置文件）

```bash
mkdir -p /opt/aronaproxy/config
cd /opt/aronaproxy
# 把本目录的 compose.yml 放到这里；把 proxy.env.example / arona_token.txt.example 当模板

cp /path/to/proxy.env.example     config/proxy.env
cp /path/to/arona_token.txt.example config/arona_token.txt
vi config/proxy.env            # 必填 PROXY_KEY（openssl rand -hex 16），其余默认即可
vi config/arona_token.txt      # 只写一行 <QQ号>:<密钥>
# 权限：容器以 root 运行，需要能读到这两个文件
#  - rootful docker：chmod 600 即可
#  - rootless docker（docker info 里有 rootless）：容器内 root 映射到子 uid，600 会 PermissionError -> 用 644
chmod 644 config/proxy.env config/arona_token.txt

docker compose up -d
```

部署目录最终长这样：

```
/opt/aronaproxy/
├── compose.yml
└── config/
    ├── proxy.env          # PROXY_KEY / PROXY_PORT / UPSTREAM / TOKEN_FILE / 限额
    └── arona_token.txt    # <QQ号>:<密钥>
```

验证：

```bash
docker compose ps                                  # 期望 (healthy)
curl -s http://127.0.0.1:3030/healthz              # 期望 ok: true
docker compose logs --tail=20
```

`config/proxy.env` 里可改的项：

| 键 | 默认 | 说明 |
|---|---|---|
| `PROXY_KEY` | 空（**必填**） | 客户端要带的共享密钥，`openssl rand -hex 16` |
| `PROXY_PORT` | `30303` | 容器内监听端口（改了要同步改 compose 的端口映射） |
| `UPSTREAM` | `https://api.arona.icu` | 上游 |
| `TOKEN_FILE` | `/config/arona_token.txt` | token 文件 |
| `MAX_BODY_BYTES` | `131072` | 单请求体上限 |
| `UPSTREAM_TIMEOUT` | `25` | 上游超时（秒） |

## 自己构建（可选，改了代码或非 amd64 时用）

```bash
cd deploy/docker
docker build -t arona-relay:1.0.0 .

# 国内拉不动 Docker Hub：
docker build --build-arg BASE_IMAGE=docker.1panel.live/library/python:3.12-alpine -t arona-relay:1.0.0 .
```

导出成可传输的包：`docker save arona-relay:1.0.0 | gzip > arona-relay-1.0.0.tar.gz`

## 接口（协议）

两个端点，请求/响应体都是 JSON，**原样透传**。

### 1) `GET /healthz` —— 就绪检查，不需要密钥

```json
{"ok": true, "version": "1.0.0", "upstream": "https://api.arona.icu",
 "token_loaded": true, "shared_key_set": true}
```

`ok=false` 一般是 `PROXY_KEY` 没填或 token 文件没读到。

### 2) `POST /api/*` —— 唯一业务端点

| 项 | 值 |
|---|---|
| 路径 | 必须 `/api/` 开头，否则 404 |
| 方法 | 只允许 `POST`，其它 405 |
| `X-Proxy-Key` | **必填**，等于 `PROXY_KEY`，否则 401 |
| body | 原样转发，上限 `MAX_BODY_BYTES`，超了 413 |
| `Content-Type` | 发 JSON 就原样带；不带或非 JSON 会被兜成 `application/json`（arona 只吃 JSON） |
| `Host` | 不检查（域名/鉴权是你的反代的事） |

转发时只加一个头，客户端的 `Authorization` / `Cookie` 一律不透传：

```
Authorization: ba-token <token>
User-Agent:    arona-relay/1.0.0
```

响应：**状态码 + body 原样返回**。arona 的业务错误是 `HTTP 200 + body.code`，所以插件原有的
错误映射不受影响：

| `code` | 含义 | 谁的 |
|---|---|---|
| `200` | 正常 | 上游 |
| `4002` | 没带可识别的 token（与未登录同码）/ 未完成数据来源备注 | 上游 |
| `4003` | `您的tokens额度已用完`（测试 token `uuz:uuz` 的额度打满） | 上游 |
| `4005` | 账号封禁（非绑定 IP 请求的后果） | 上游 |
| `4007` | token 无效或绑到了别的 IP | 上游 |
| `401` | `X-Proxy-Key` 缺失/不匹配 | 中转 |
| `404` / `405` | 路径或方法不对 | 中转 |
| `413` | 请求体过大 | 中转 |
| `502` | 连不上上游（DNS/超时） | 中转 |
| `503` | 没配 `PROXY_KEY` 或没读到 token | 中转 |

> 区分谁的问题：`401/404/405/413/502/503` 是中转或网络；`4002/4003/4005/4007` 是 arona 侧。

## 接反代（域名 + HTTPS，你自己那套）

容器只说明文 HTTP，只绑 `127.0.0.1:3030`。反代把它当普通后端点就行：

<details>
<summary>Caddy</summary>

```caddy
arona.example.com {
    reverse_proxy 127.0.0.1:3030
}
```
</details>

<details>
<summary>nginx</summary>

```nginx
location / {
    proxy_pass       http://127.0.0.1:3030;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```
</details>

鉴权、限流、IP 白名单都放你反代上做——插件只会带 `X-Proxy-Key`，反代别在前置再要求别的凭证，
否则插件会 401。

反代在**另一个容器**里时，把 compose 的 `ports` 删掉、接入同一个 docker 网络，
反代里用 `http://arona-relay:30303`（容器名 + 容器内端口）。

## 接到插件上（AstrBot 侧）

在 AstrBot 插件数据目录写 `arona_proxy.json`（填**域名**）：

```json
{"url": "https://arona.example.com", "key": "<config/proxy.env 里的 PROXY_KEY>"}
```

```bash
cd /opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki
printf '%s\n' '{"url": "https://arona.example.com", "key": "<PROXY_KEY>"}' > arona_proxy.json
chmod 600 arona_proxy.json
sudo systemctl restart astrbot
```

这个文件存在时插件走中转，**不再读** `arona_token.txt`（回滚直连就删它）。自检：

```bash
bash /opt/astrbot-qq/tools/arona_check.sh     # 期望 赛期: N / 借人: True <人数>
```

## 排障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 容器起来就退出，日志 `PermissionError: '/config/proxy.env'` | 配置文件 600，而容器内 root 读不到（rootless docker / 非 root uid） | `chmod 644 config/proxy.env config/arona_token.txt`，或把这台机器的 docker 换成 rootful |
| `docker compose ps` 一直 `unhealthy` | 同上（healthz 打不开）；或 3030 被占用 | 先 `docker logs arona-relay`；再 `ss -lntp`（看 3030 是否被占） |
| 插件报 `401` | 两边 `PROXY_KEY` 不一致 | 比对 `config/proxy.env` 与 `arona_proxy.json` 的 `key` |
| 插件报 `503` | 没读到 token | 看 `curl 127.0.0.1:3030/healthz` 的 `token_loaded`；确认 `arona_token.txt` 存在且只有一行 |
| 日志 `upstream_code=4005` | arona 封禁（非绑定 IP） | 停手，见下节"关于 IP 绑定" |
| 日志 `upstream_code=4003` | 测试 token 额度用尽 | 等额度恢复或换自己的 token |

## 运维

| 场景 | 做法 |
|---|---|
| 换 token | 改 `config/arona_token.txt`，**不用重启**（按 mtime 热加载，日志会打一行 `[config] 已加载 token`） |
| 改 key / 端口 | 改 `config/proxy.env`，`docker compose restart` |
| 看日志 | `docker compose logs -f`，每行一请求：`时间 客户端IP host=... POST /api/xxx -> 200 87ms upstream_code=200` |
| 判断封禁 | 日志里 `upstream_code=4005` = arona 侧封禁；`4003` = 额度用尽 |
| 升级镜像 | `docker load` 新包并把 compose 的 `image` 换成新 tag，`docker compose up -d` |

日志**不含 token、不含响应体**。

## 关于 IP 绑定（务必看）

- token 绑定的是**首次请求的 IP**，也就是这台中转机的**公网出口 IP**。
- **token 一定要在这台机器上第一次用**；先在别处试一次，就绑到别处了。
- 换机器 / 换 IP = 必须**报备 arona 管理手动迁移**，本镜像不做任何绕过。
- 反复从非绑定 IP 请求会被封（`4005`，24 小时起，每次试探可能重新计时）；封禁期间停手。

## 安全清单

- [ ] `PROXY_KEY` 用 `openssl rand -hex 16` 以上，别用弱口令，两边保持一致
- [ ] 3030 只绑 `127.0.0.1`，公网只经你的反代
- [ ] `config/` 权限 600，别提交进 git
- [ ] 反代上的鉴权方式不要要求插件额外带凭证（它会 401）

## 与其它实现的关系

| 文件 | 状态 |
|---|---|
| `deploy/docker/`（本目录） | **当前方案**：容器化、配置集中、零第三方依赖、加固运行 |
| `tools/arona_proxy.py` + `deploy/arona-proxy.service` | **LEGACY**：旧 systemd 版转发器，仅作回滚备件；协议兼容（`X-Proxy-Key` + `POST /api/*`） |
