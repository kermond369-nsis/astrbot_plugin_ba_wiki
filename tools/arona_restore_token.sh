#!/usr/bin/env bash
# 封禁解除后一键恢复真 token：挪回 -> 重启 -> 自检；自检不过就自动退回测试 token 状态。
#
# 用法：bash /opt/astrbot-qq/tools/arona_restore_token.sh
# 退出码：0 = 真 token 已生效；1 = 自检失败已自动退回；2 = 环境不对（没有待恢复的 token 等）
set -u

echo "=== arona token 恢复尝试：$(date -Is) ==="

DD=${DD:-/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki}
TOOLS=${TOOLS:-/opt/astrbot-qq/tools}
PENDING="$DD/arona_token.txt.pending"
LIVE="$DD/arona_token.txt"

if [ ! -f "$PENDING" ]; then
  echo "没有待恢复的 token：$PENDING 不存在。"
  [ -f "$LIVE" ] && echo "（$LIVE 已在，可能早就恢复过了）"
  exit 2
fi
if [ -f "$LIVE" ]; then
  echo "$LIVE 已存在，先确认是不是旧文件再手工处理，这里不覆盖。"
  exit 2
fi

echo "== 1/3 恢复 token"
cp -p "$PENDING" "$LIVE"
chmod 600 "$LIVE"
ls -l "$LIVE"

if [ "${NO_RESTART:-0}" = "1" ]; then
  echo "== 2/3 重启 AstrBot（已跳过，NO_RESTART=1）"
else
  echo "== 2/3 重启 AstrBot"
  sudo -n systemctl restart astrbot.service && sleep 5 && systemctl is-active astrbot.service
fi

if [ "${NO_CHECK:-0}" = "1" ]; then
  echo "== 3/3 自检（已跳过，NO_CHECK=1）"
  exit 0
fi

echo "== 3/3 自检"
if bash "$TOOLS/arona_check.sh"; then
  echo
  echo "真 token 已生效。备份文件仍在：$PENDING（确认无事后可删）"
  # 定时器只在真 token 未生效时有意义，成功即自停，避免以后每 25h 空跑
  if [ -f /etc/systemd/system/arona-token-retry.timer ]; then
    sudo -n systemctl disable --now arona-token-retry.timer >/dev/null 2>&1 \
      && echo "已停用 arona-token-retry.timer（不再自动重试）"
  fi
  exit 0
fi

rc=$?
echo
echo "自检失败（exit=$rc），自动退回测试 token 状态..."
mv "$LIVE" "$PENDING"
if [ "${NO_RESTART:-0}" != "1" ]; then
  sudo -n systemctl restart astrbot.service >/dev/null 2>&1 || true
fi
echo "已回退：$LIVE 不存在，插件回落 uuz:uuz。"
echo "若自检报 4005 说明还在封禁期，等满 24h 再跑一次本脚本。"
echo "若自检报 4007 说明 token 与当前出口 IP 不匹配，需要用本机出口 IP 重新申请。"
exit 1
