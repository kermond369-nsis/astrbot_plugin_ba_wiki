# deploy/ —— 部署产物

这里只放**可以进版本库**的部署文件，密钥一律不进。

## 组件

| 文件 | 用途 |
|---|---|
| `compose-lan.yml` | AstrBot主机 上的 AstrBot（早期 Docker 方案，**当前线上不是用它**，线上是 systemd + PyPI 安装） |
| `arona-proxy.service` | 云服务器上的 arona HTTPS 转发器 |
| `backup.sh` | 数据备份（停服打包再拉起） |

## 线上实际形态

```
AstrBot主机 <AstrBot主机IP>
  AstrBot      systemd: astrbot      （uv tool install astrbot，非 Docker）
  数据          /opt/astrbot-qq/data
  面板          http://<AstrBot主机IP>:6185

云服务器 <转发机公网IP>
  arona-proxy  systemd: arona-proxy  https://<转发机公网IP>:8443
  用途          arona token 与 IP 绑定，请求必须从这台机器出网
```

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
| `arona_token.txt` | `<QQ号>:<密钥>` | 插件数据目录 |
| `arona_proxy.json` | `{"url": "https://<转发机IP>:8443", "key": "<共享密钥>"}` | 插件数据目录 |
| `.env` | `NAPCAT_UID/GID`、`NAPCAT_WEBUI_TOKEN` | 部署目录 |
| 自签证书 | `arona-proxy.crt` / `.key`（SAN 绑 IP），且需装进调用方信任库 | 转发机 |

## 踩过的坑

- `get.docker.com` 在国内被 reset → 用 Debian/Ubuntu 官方源装 `docker.io`
- Docker Hub 不通 → 镜像走 `docker.1panel.live` / `m.daocloud.io`（daocloud 偶发 502）
- PyPI 走阿里云镜像可到 350~500 KB/s，比镜像源稳
- `ASTRBOT_ROOT` 目录必须有 `.astrbot` 标记文件，否则 CLI 报 "not a valid AstrBot root"
- arona token 格式是 `<QQ号>:<密钥>`，裸密钥报 4007；AstrBot 换机后必须走 HTTPS 转发
