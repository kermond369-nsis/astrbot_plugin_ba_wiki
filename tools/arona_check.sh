#!/usr/bin/env bash
# arona 链路自检：不依赖 QQ，直接用插件自己的客户端打一次接口（直连 / 中转都适用）。
#
# 用法（二选一，另一个会自动推导）：
#   PLUGINS=<AstrBot>/data/plugins bash tools/arona_check.sh
#   DD=<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki bash tools/arona_check.sh
# 退出码：0 = 正常；1 = 调用失败（看打印的错误码）；2 = 环境不对（缺插件/缺解释器）
set -u

PLUGINS=${PLUGINS:-}
DD=${DD:-}
if [ -z "$DD" ] && [ -n "$PLUGINS" ]; then DD=$(dirname "$PLUGINS")/plugin_data/astrbot_plugin_ba_wiki; fi
if [ -z "$PLUGINS" ] && [ -n "$DD" ]; then PLUGINS=$(cd "$(dirname "$DD")/.." 2>/dev/null && pwd)/plugins; fi
if [ -z "$PLUGINS" ] || [ -z "$DD" ]; then
  echo "用法: PLUGINS=<AstrBot>/data/plugins bash $0   （或指定 DD=<...>/plugin_data/astrbot_plugin_ba_wiki）"
  exit 2
fi
export PLUGINS
# 插件客户端只用标准库，系统 python3 就够；有专用解释器时用 PY=... 覆盖
PY=${PY:-$(command -v python3 || command -v python || true)}

[ -d "$PLUGINS/astrbot_plugin_ba_wiki" ] || { echo "缺插件目录: $PLUGINS/astrbot_plugin_ba_wiki"; exit 2; }
[ -n "$PY" ] || { echo "找不到 python3，请用 PY=/path/to/python 指定"; exit 2; }
[ -x "$PY" ] || { echo "PY 不可执行: $PY"; exit 2; }

cd "$PLUGINS" || exit 2
exec "$PY" - "$DD" <<'PY'
import os, sys
dd = sys.argv[1]
sys.path.insert(0, os.environ['PLUGINS'])
from astrbot_plugin_ba_wiki.clients import arona

proxy = arona._proxy_cfg(dd)
print('数据目录 :', dd)
if proxy:
    print('转发配置 : %s（token 由中转机持有，客户端不读 arona_token.txt）' % proxy[0])
else:
    tok, is_test = arona._token(dd)
    print('转发配置 : None（直连）')
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
