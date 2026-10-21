# deploy/ —— 部署产物

这里只放**可以进版本库**的部署文件，密钥一律不进。

## 组件

| 文件 | 用途 |
|---|---|
| `docker/` | **arona 中转镜像**（token 注入，纯 HTTP，TLS 交给前置反代）：配置集中在 `docker/config/`，`docker compose up -d --build` 即起；见 [docker/README.md](docker/README.md) |
| `compose-lan.yml` | AstrBot 主机上的早期 Docker 方案（**当前线上不是用它**，线上是 systemd + PyPI 安装） |
| `arona-proxy.service` | 云服务器上的 arona HTTPS 转发器 —— **LEGACY / 已弃用**，2026-10-18 起插件直连（见 [docs/MIGRATE-TO-LOCAL.md](../docs/MIGRATE-TO-LOCAL.md)），仅作回滚备件 |
| `backup.sh` | 数据备份（停服打包再拉起） |
| `arona-token-retry.service/.timer` | 定期尝试恢复 arona 真 token —— **当前已 `disable`**：实测每次试探都可能把 24h 封禁重新计时，别开着（见 MIGRATE-TO-LOCAL.md 第十节） |

## 线上实际形态

```
<主机名>（<主机IP>）
  AstrBot      systemd: astrbot      （uv tool install astrbot，非 Docker）
  数据          /opt/astrbot-qq/data
  面板          http://<主机IP>:6185
  arona        直连 https://api.arona.icu
              实际用官方测试 token uuz:uuz（真 token 被 arona 封禁 + 家宽出口 IP 已变，暂不可用）
```

> 2026-10-18：原来的云服务器转发器（`https://<转发机公网IP>:8443`）随服务器移交下线，
> 插件改为直连。数据目录里的 `arona_proxy.json` 已删除，旧的 token / 密钥随云服务器重置作废。
>
> 2026-10-21：真 token 仍处封禁、家宽出口 IP 也已变化，插件继续直连用 `uuz:uuz`。
> 另一台固定 IP 的机器准备接手时，用 `deploy/docker/` 起中转、在插件侧写回
> `arona_proxy.json`（填域名），就不用再依赖家宽 IP 了。注意 token 的绑定 IP 迁移要报备 arona 管理。

AstrBot 的 systemd 单元（新会话重建环境时用）：

```ini
[Unit]
Description=AstrBot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=codex
WorkingDirectory=/opt/astrbot-qq
Environment=ASTRBOT_ROOT=/opt/astrbot-qq
Environment=PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ExecStart=/home/<用户>/.local/bin/astrbot run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 需要自己准备的（不在仓库里）

| 文件 | 内容 | 放哪 |
|---|---|---|
| `arona_token.txt` | `<QQ号>:<密钥>`（与 该主机出口 IP 绑定） | 插件数据目录，权限 600 |
| `.env` | `NAPCAT_UID/GID`、`NAPCAT_WEBUI_TOKEN` | 部署目录 |

> 只有重新架转发机（回滚方案）时才还需要 `arona_proxy.json` + 自签证书 `arona-proxy.crt/.key`。

## 踩过的坑

- `get.docker.com` 在国内被 reset → 用 Debian/Ubuntu 官方源装 `docker.io`
- Docker Hub 不通 → 镜像走 `docker.1panel.live` / `m.daocloud.io`（daocloud 偶发 502）
- PyPI 走阿里云镜像可到 350~500 KB/s，比镜像源稳
- `ASTRBOT_ROOT` 目录必须有 `.astrbot` 标记文件，否则 CLI 报 "not a valid AstrBot root"
- arona token 格式是 `<QQ号>:<密钥>`，裸密钥报 4007
- `Authorization: ba-token <token>` 才是被认的鉴权形态（`token:` 作 header 名不生效，只回 4002）
- token 绑首次请求的 IP：换机/换出口 IP 后旧 token 报废；同一 token 从非绑定 IP 反复请求会被封 24h（`4005`）
- 转发器本身不是必需品：出口 IP 稳定时直连即可（当前线上形态）
