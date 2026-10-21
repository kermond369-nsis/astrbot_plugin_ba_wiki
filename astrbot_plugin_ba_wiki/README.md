# astrbot_plugin_ba_wiki —— 蔚蓝档案数值查询

给 AstrBot 的 Agent 一个**可信的 BA 数值源**，替代"让模型凭记忆报数字"。

## 它解决什么

BA 群里问「若藻 NS 各等级倍率」，靠联网搜索拿到的是摘要、经常缺表格；靠模型记忆则会编数字。
这个插件把 SchaleDB 的数据落到本地，**逐级取值，不经过模型猜测**。

## 数据来源

- 数值：SchaleDB `students.json`，社区维护，随游戏版本更新
- 名字：kivo.wiki（三套中文名 + 官方绰号），按 SchaleDB Id 挂到每个学生上
- 缓存目录：`data/plugin_data/astrbot_plugin_ba_wiki/`
  - `students_zh.json` —— 国服简体的技能数据（约 5MB）
  - `names.json` —— 七种语言的名称表
  - `meta.json` —— ETag 与上次检查时间
  - `kivo_students.json` —— kivo 全量缓存（24h，约 350KB）
  - `aliases.json` —— 别名/绰号表（可自己编辑）
- 手动全量同步（SchaleDB + kivo）：在插件目录执行 `<python> sync_data.py`

## 追新机制（不止"7 天过期"）

上游 `schaledb.com` 返回 `ETag`，所以可以做到**只在真的变了的时候才下载**：

| 情况 | 行为 | 成本 |
|---|---|---|
| 距上次检查 < 1 小时 | 什么都不做 | 0 |
| 距上次检查 ≥ 1 小时 | 带 `If-None-Match` 条件请求 | 一次 304，**零下载** |
| 上游 ETag 变了（有新角色/改数值） | 下载新数据 + 重建七语言名称表 | 一次 5MB |
| 距文件修改 > 7 天（兜底） | 无条件全量下载 | 一次 5MB |

kivo 是另一条节奏：全量 510 条详情一次拉完（约 2 分钟），磁盘缓存 24h，
**只在后台任务里刷新**，不会卡住查询。

## 启动预热

插件实现 `initialize()` —— AstrBot 在插件加载完会 `await` 它。里面只**排一个后台任务**，
立刻返回，不拖慢 AstrBot 启动：

1. SchaleDB：做一次条件检查（上游没变就是 304，零下载；缺失则下载 5MB）
2. kivo：缓存过期（24h）就重抓，约 2 分钟

日志里能看到三行：

```
[ba_wiki] 已排入启动预热任务：SchaleDB 检查 + kivo 名字缓存同步
[ba_wiki] 已排入后台任务：同步 kivo 名字缓存（首次约 2 分钟，不阻塞查询）
[ba_wiki] kivo 名字缓存就绪：510 条 -> /path/to/plugin_data/.../kivo_students.json
```

不想等这两分钟就手动跑一次全量同步：`python sync_data.py`（会同时同步 SchaleDB 与 kivo）。

## 多区服名称 + 官方绰号（核心特性）

七套 SchaleDB 名称共用同一批角色 ID，再叠加 kivo 的补充名：

| 来源 | 提供什么 | 例（Aru） |
|---|---|---|
| SchaleDB `zh` | 通用中文（**不是**国服译名） | 阿露 |
| SchaleDB `tw` | 国际服繁体 | 亞瑠 |
| SchaleDB `en`/`jp`/`kr`/`th`/`vi` | 英/日/韩/泰/越 | Aru / アル / 아루 |
| kivo `given_name_cn` | **国服译名**（显示用） | 爱露 |
| kivo `nick_name` | 官方绰号（可多个，用「，」分隔） | 社长 |
| `aliases.json` | 群里的私人叫法 | 藻哥 → 若藻 |

**显示策略**

- 国服已上线（`IsReleased[1]` 为真）→ kivo 国服译名，缺则 SchaleDB `zh`，例：**爱露**
- 国服未上线 → kivo 中文全名 + （日文），例：**椎名纺（ツムギ）**
- 形态（皮肤）用 SchaleDB 名字里的括号标签，例：**星野（泳装）**

**匹配规则**（顺序即优先级）

1. 精确 —— 七语言名 / kivo 三套中文与全名 / 官方绰号 / `aliases.json` / DevName / 角色 ID
2. 形态词 + 基名 —— 允许跨语言混写：`水着星野`、`ホシノ水着`、`泳裝星野`
3. 基名对得上、形态词不认识（`星野水`）→ 返回候选让用户选
4. 全不中 → `suggest`，让模型先跟用户确认，**不许编数值**

> 刻意**不做**「任意子串当命中」：那样 `星野水` 会被硬答成「星野」，等于默许拼错。

## 别名表

编辑 `aliases.json`（插件首次启动会自动生成模板）：

```json
{
  "_说明": "键是群里的叫法，值是官方名（任意语言）/ 角色 ID / 显示名",
  "藻哥": "若藻",
  "石头": "10007"
}
```

改完在插件页点「重载插件」生效。以 `_` 开头的键会被忽略，可以用来写注释。
旧的 `nicknames.json` 仍兼容读取，但不再生成。

## 槽位映射（最容易错的地方）

SchaleDB 的槽位名和玩家说法不对应：

| 玩家说法 | SchaleDB 槽位 | 说明 |
|---|---|---|
| EX 技能 | `Ex` | 有 cost，5 级 |
| **普通技能 (NS)** | **`Public`** | ⚠️ **不是 `Normal`** |
| 普通技能（专武强化） | `GearPublic` | 开专武后的加强版 |
| 被动技能 | `Passive` | |
| 辅助技能 (Sub) | `ExtraPassive` | |
| 武器被动（专武） | `WeaponPassive` | |
| 普通攻击 / 平A | `Normal` | 只有帧数据，**无数值** |

写错这一层查出来的就是别的技能，这是本插件最核心的防错点。

## 用法

**模型自动调用**：工具 `query_ba_skill`

| 参数 | 说明 |
|---|---|
| `student` | 任意区服名称/绰号/ID：`若藻` / `Wakamo` / `ワカモ` / `水星野` / `10033` |
| `skill` | `ex` / `ns` / `ns+` / `ps` / `sub` / `wp` / `普通攻击`，留空返回全部技能 |
| `level` | 只返回某一级，0 = 全部 |

**手动指令**

```
/ba 若藻            全部技能
/ba 若藻 ns         普通技能各等级数值
/ba ワカモ ex        用日文名也行
/ba 椎名纺          国服未上线角色也能查（显示为「椎名纺（ツムギ）」）
```

## 结构

```
main.py      胶水（生命周期 / 工具绑定对齐 / /ba 接线）
tools.py     5 个 LLM 工具（docstring 是模型路由契约）
commands.py  /ba 分发
directory.py 名字解析（判定链 + 显示策略）
skills.py    技能数值（纯函数）
render.py    所有输出文本
sources/     schaledb.py（ETag 刷新）、kivo.py（补充名 + 绰号）
clients/     arona.py（什亭之匣）、bilibili.py（B 站搜索）
```

## 自检 / 回归

```bash
python -m compileall -q astrbot_plugin_ba_wiki
python tests/selfcheck.py      # 114 项：加载/绑定/契约/数据源/kivo/解析/显示/指令
```

`tests/golden.md` 是人工对照表，`tests/selfcheck.py` 把其中可自动化的部分都覆盖了。

## 解析示例

```
若藻/Wakamo/ワカモ/わかも/와카모/10033  → 若藻（国服译名）
阿露/爱露/亞瑠/Aru/アル/아루             → 爱露
水星野（kivo 官方绰号）                  → 星野（泳装）
星野水（形态词不认识）                    → 候选：星野（泳装）、星野（临战）、星野
若澡                                     → 未命中，suggest: 若藻、若藻（泳装）
椎名纺 / ツムギ / 紬                     → 椎名纺（ツムギ）
```

## 已知限制

- 只有数值与描述，没有立绘、好感剧情、装备推荐
- kivo 覆盖 278/278（按 Id），但它自己的条目数（510）会随皮肤增长，缓存 24h 内可能落后一天
- 国服未上线角色的数值仍来自 SchaleDB（可能先于国服开放），不判断区服上线状态
- 若开启「文字转图片」，中文显示依赖宿主机 CJK 字体：缺字体会变成 ▯▯▯（数字/英文/符号正常）。
  **插件会自己处理**：启动时后台检查 `<astrbot>/data/font.ttf`（AstrBot 字体候选表第一位），
  缺失或字形不全才下载 Noto Sans CJK 并做位图自检。手动触发：插件页「字体」→「下载 / 修复字体」，
  或 `/ba 字体 修复`。**不要用 `DroidSansFallbackFull.ttf` 这类 fallback 字体**：没有拉丁字形，
  会让数字/英文变方块，自检会拒绝这类字体。与本插件无关，插件输出始终是 UTF-8。
