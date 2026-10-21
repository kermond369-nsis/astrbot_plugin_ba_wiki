# deploy/

部署产物。只放**可以进版本库**的文件，token、密钥、证书一律不入库。

## 内容

| 路径 | 用途 | 状态 |
|---|---|---|
| `docker/` | arona 中转镜像（token 注入，纯 HTTP，TLS 交给前置反代） | **推荐**，见 [docker/README.md](docker/README.md) |
| `backup.sh` | 数据备份（停服打包再拉起） | 可用 |
| `compose-lan.yml` | 早期用 Docker 跑 AstrBot 的 compose | 历史方案；推荐 systemd + venv/uv 安装 |
| `arona-proxy.service` | systemd 版 arona 转发器 | **LEGACY**，仅作回滚备件（配合 `tools/arona_proxy.py`） |
| `arona-token-retry.service` / `.timer` | 定时尝试恢复 token | **LEGACY / 默认不启用**：封禁会随请求重新计时，反复尝试会一直触发 |

## AstrBot 的 systemd 单元（模板）

```ini
[Unit]
Description=AstrBot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<运行用户>
WorkingDirectory=<AstrBot根目录>
Environment=ASTRBOT_ROOT=<AstrBot根目录>
Environment=PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ExecStart=/home/<运行用户>/.local/bin/astrbot run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> `ASTRBOT_ROOT` 指向的目录里必须有 `.astrbot` 标记文件，否则 CLI 报 "not a valid AstrBot root"。

## 需要自备（不进仓库）

| 文件 | 内容 | 位置 |
|---|---|---|
| `arona_token.txt` | `<QQ号>:<密钥>` | 插件数据目录（直连模式），权限 600 |
| `arona_proxy.json` | `{"url": "https://<中转域名>", "key": "<共享密钥>"}` | 插件数据目录（中转模式） |
| `config/proxy.env` | 中转的 `PROXY_KEY` 等 | 中转部署目录 |
| `config/arona_token.txt` | `<QQ号>:<密钥>` | 中转部署目录 |

## 备注

- Docker Hub 在国内常不可达：基础镜像可用 `docker.1panel.live/library/<image>`，或给 docker 配 `registry-mirrors`
- PyPI 走镜像（如 `mirrors.aliyun.com/pypi/simple`）可显著提速
- 备份脚本会短暂停服，生产环境请在低峰期执行
