#!/usr/bin/env bash
# 升级前存档。跑一次即可，不需要挂 cron。
#
# 用法：
#   docker compose pull && ./backup.sh && docker compose up -d
#   玩坏了：rm -rf data && tar xzf backups/astrbot-<时间戳>.tar.gz
#
# 为什么要停服：data_v4.db 是 SQLite，运行中直接 tar 可能拷到写了一半的页，
# 恢复时会坏。停 10 秒换一个可靠的存档，值。

set -euo pipefail
cd "$(dirname "$0")"

STAMP=$(date +%F-%H%M)
KEEP_DAYS=${KEEP_DAYS:-14}
mkdir -p backups

echo "[$(date '+%F %T')] 备份开始"

# 不管成功失败，退出时一定把服务拉起来
trap 'docker compose start >/dev/null 2>&1 || true' EXIT

docker compose stop astrbot >/dev/null
tar czf "backups/astrbot-${STAMP}.tar.gz" data
docker compose start astrbot >/dev/null

SIZE=$(du -h "backups/astrbot-${STAMP}.tar.gz" | cut -f1)
echo "[$(date '+%F %T')] 完成: backups/astrbot-${STAMP}.tar.gz (${SIZE})"

find backups -name 'astrbot-*.tar.gz' -mtime "+${KEEP_DAYS}" -print -delete

# 可选：同步到异地。别只留在同一台机器上——机器挂了备份一起没
# rsync -az backups/ user@另一台机器:/backup/astrbot/
