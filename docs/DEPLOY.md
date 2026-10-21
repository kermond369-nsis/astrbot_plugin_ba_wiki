# 部署

## 环境要求

| 项 | 要求 |
|---|---|
| AstrBot | 4.x |
| Python | ≥ 3.10 |
| 出网 | `schaledb.com:443`、`api.kivo.wiki:443`、`api.arona.icu:443`（或用中转）、`api.bilibili.com:443` |
| 磁盘 | 数据目录约需 6 MB（`students_zh.json` 约 5 MB） |

插件只用 AstrBot 自带的 `aiohttp` / `Pillow`，无需额外安装依赖。

## 安装

**方式一：插件市场** —— AstrBot 面板 → 插件 → 插件市场，搜索 `ba_wiki`。

**方式二：手动**

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/kermond369-nsis/astrbot_plugin_ba_wiki.git
# 目录名必须是 astrbot_plugin_ba_wiki
sudo systemctl restart astrbot     # 或在面板里重载插件
```

**方式三：发布包** —— 从 Releases 下载 zip，解压到 `<AstrBot>/data/plugins/`，
确认存在 `<AstrBot>/data/plugins/astrbot_plugin_ba_wiki/main.py`（不要多套一层目录）。

## 两个目录

| 目录 | 内容 | 是否随插件替换 |
|---|---|---|
| `<AstrBot>/data/plugins/astrbot_plugin_ba_wiki/` | 代码 | 是（升级时整体替换） |
| `<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki/` | 数据、缓存、鉴权配置 | **否**（升级时保留） |

数据目录里的文件：

| 文件 | 作用 | 可删 |
|---|---|---|
| `students_zh.json` | SchaleDB 技能与名称（约 5 MB） | 可（下次启动重下） |
| `names.json` | 七语言名称表 | 可（随 SchaleDB 重建） |
| `meta.json` | ETag 与上次检查时间 | 可（等于强制重新校验） |
| `kivo_students.json` | kivo 补充名缓存（24h） | 可（下次启动重抓，约 2 分钟） |
| `equipment_zh.json` | 装备表（面板计算用，约 76 KB，7 天） | 可（首次查面板时重下） |
| `aliases.json` | 用户别名/绰号 | 可（会重建模板，自定义内容丢失） |
| `arona_token.txt` / `arona_proxy.json` | arona 鉴权 | 见 [ARONA-AUTH.md](ARONA-AUTH.md) |

## arona 鉴权

两种模式（直连 / 中转）、优先级、错误码与自检方式见 [ARONA-AUTH.md](ARONA-AUTH.md)。

## 启动与预热

插件 `initialize()` 只排后台任务，不阻塞 AstrBot 启动。加载后日志应出现：

```
[ba_wiki] 已排入启动预热任务：SchaleDB 检查 + kivo 名字缓存同步
[ba_wiki] 已排入后台任务：同步 kivo 名字缓存（首次约 2 分钟，不阻塞查询）
[ba_wiki] kivo 名字缓存就绪：<N> 条 -> <data>/kivo_students.json
```

| 时机 | 动作 | 预期 |
|---|---|---|
| 插件加载 | SchaleDB 条件检查（`If-None-Match`） | 上游未变则一次 304，零下载 |
| 插件加载后（后台） | kivo 全量抓取 | 约 2 分钟；期间显示名回落 SchaleDB |
| 每 24h | kivo 重抓 | 后台进行，不阻塞查询 |

不想等预热可手动全量同步（SchaleDB + kivo）：

```bash
cd <AstrBot>/data/plugins/astrbot_plugin_ba_wiki
<python> sync_data.py
```

`<python>` 用运行 AstrBot 的解释器（例如 venv 里的 `python`）。

## 验收

| # | 操作 | 期望 |
|---|---|---|
| 1 | 面板插件页 | 插件已启用，无加载失败 |
| 2 | 工具列表 | `query_ba_skill` / `query_ba_raid_team` / `query_ba_assist` / `query_ba_player` / `search_ba_guide` 都在 |
| 3 | `/ba 若藻 ns` | 普通技能各等级数值 |
| 4 | `/ba 大决战` | 当前赛期 + 各甲配队 + 来源行 |
| 5 | `/ba 借 若藻 5星` | 分页抬头 + 好友码 |
| 5b | `/ba 面板 若藻` | Lv90/5★ 口径 + 生命/攻击/防御等数值 |
| 6 | `/ba 下页` | 页码 +1，条件不变 |
| 7 | `/ba 攻略 国服 大决战 大蛇` | B 站标题 + 链接 |

## 配置项

`<AstrBot>/data/config/astrbot_plugin_ba_wiki_config.json`，或面板插件页修改：

| 项 | 默认 | 说明 |
|---|---|---|
| `font.auto_download` | 开 | 启动时检查 CJK 字体，缺失自动补 |
| `font.mirror_prefix` | 空 | 字体下载反代前缀 |

别名表见插件 README 的「别名表」一节。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 插件列表里没有它 | 目录多套了一层 / `metadata.yaml` 丢失 | 确认 `plugins/astrbot_plugin_ba_wiki/main.py` 存在，看日志里的 ImportError |
| 插件在但工具没注册 | 加载异常 | 日志搜 `[ba_wiki]`；确认 AstrBot 版本支持工具绑定 |
| 报 `code 4002` / `4003` / `4005` / `4007` | arona 侧 | 见 [ARONA-AUTH.md](ARONA-AUTH.md) 的错误码表 |
| 日服 / 国际服查不到大决战 | 上游只有国服有榜单 | 赛期列表全服通用，榜单不做跨服凑数 |
| `/ba 下页` 提示没有可翻页查询 | 会话超时（10 分钟） | 重新发 `/ba 借 ...` |
| 本地数据缺失且下载失败 | 出不了网到 `schaledb.com` | 检查网络；或先跑 `sync_data.py` |
| 重启后一直没生成 `kivo_students.json` | 后台任务未完成 / `initialize()` 未触发 / 出网失败 | 看上面三行日志；缺失就手动跑 `sync_data.py` |
| 中文变方块（▯▯▯），数字英文正常 | 宿主机无 CJK 字体 | 见下节 |

## 文本转图片时的中文字体

AstrBot 的本地 T2I 用 Pillow 渲染，按固定候选路径找 CJK 字体；一个都找不到时退回 `DejaVuSans.ttf`
（只有拉丁字形），中文即变方块。**与插件无关**：插件输出始终是 UTF-8。

优先候选路径：

```
<AstrBot data>/font.ttf          # 数据目录根，优先级最高
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

插件自带自愈：启动时检查 `<data>/font.ttf` 与 `<data>/font-bold.ttf`，缺失或字形不全才装；
也可手动触发（插件页「字体」标签，或 `/ba 字体 修复`）。

手动方案（自愈失败时）：

```bash
sudo apt install -y fonts-noto-cjk && sudo fc-cache -fv
# 或直接把字体放进 AstrBot 数据目录
sudo cp /path/to/NotoSansCJK-Regular.ttc <AstrBot>/data/font.ttf
sudo cp /path/to/NotoSansCJK-Bold.ttc    <AstrBot>/data/font-bold.ttf
sudo systemctl restart astrbot
```

> 不要用 `DroidSansFallbackFull.ttf` 这类只有 CJK、没有拉丁的 fallback 字体：数字与英文会变方块。

校验当前生效的字体：

```bash
<python> - <<PY
from astrbot.core.utils.t2i.local_strategy import FontManager
for bold in (False, True):
    f = FontManager.get_font(28, bold=bold)
    print(("[BOLD] " if bold else "[REG ] ") + str(getattr(f, "path", "?")))
PY
```

两行都应指向 Noto Sans CJK 或 `<AstrBot>/data/font.ttf`；指向 `DejaVuSans.ttf` 就会出方块。

## 升级与回滚

```bash
# 升级：替换代码目录，保留数据目录
cd <AstrBot>/data/plugins
mv astrbot_plugin_ba_wiki astrbot_plugin_ba_wiki.old
unzip -q astrbot_plugin_ba_wiki-<版本>.zip -d .
sudo systemctl restart astrbot

# 回滚
rm -rf astrbot_plugin_ba_wiki && mv astrbot_plugin_ba_wiki.old astrbot_plugin_ba_wiki
sudo systemctl restart astrbot
```

`plugin_data/` 不受影响，回滚无需处理。

## 版本

版本号以 `astrbot_plugin_ba_wiki/metadata.yaml` 为准，与 Releases 的 tag 对应。
