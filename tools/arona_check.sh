#!/usr/bin/env bash
# arona.icu 直连自检：不依赖 QQ，直接用插件自己的客户端打一次接口。
#
# 用法：bash /opt/astrbot-qq/tools/arona_check.sh
# 退出码：0 = 直连正常；1 = 调用失败（看打印的错误码）；2 = 环境不对（缺插件/缺解释器）
set -u

PLUGINS=${PLUGINS:-/opt/astrbot-qq/data/plugins}
DD=${DD:-/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki}
PY=${PY:-python3}

[ -d "$PLUGINS/astrbot_plugin_ba_wiki" ] || { echo "缺插件目录: $PLUGINS/astrbot_plugin_ba_wiki"; exit 2; }
[ -x "$PY" ] || { echo "缺 python: $PY（可用 PY=... 覆盖）"; exit 2; }

cd "$PLUGINS" || exit 2
exec "$PY" - "$DD" <<'PY'
import os, sys
dd = sys.argv[1]
sys.path.insert(0, os.environ.get('PLUGINS', '/opt/astrbot-qq/data/plugins'))
from astrbot_plugin_ba_wiki.clients import arona

proxy = arona._proxy_cfg(dd)
tok, is_test = arona._token(dd)
print('数据目录 :', dd)
print('转发配置 :', proxy if proxy else 'None（直连）')
if is_test:
    print('token    : 官方测试 token uuz:uuz（未找到 arona_token.txt / ARONA_TOKEN）')
else:
    print('token    : %s...（%d 字符）' % (tok[:12], len(tok)))

rc = 0
try:
    s = arona.current_season(1, dd)
    print('赛期     :', (s or {}).get('season'))
except Exception as e:
    rc = 1
    print('赛期     : 失败 ->', type(e).__name__, e)
try:
    r = arona.assist_players(1, 10033, 1, 2, data_dir=dd)
    print('借人     :', r.get('ok'), r.get('total_players'))
except Exception as e:
    rc = 1
    print('借人     : 失败 ->', type(e).__name__, e)
sys.exit(rc)
PY
