# 架构与数据模型

## 分层

| 模块 | 职责 |
|---|---|
| `main.py` | AstrBot 胶水：生命周期、工具注册与绑定、`/ba` 接线 |
| `tools.py` | 5 个 LLM 工具，docstring 即模型路由契约 |
| `commands.py` | `/ba` 分支分发（技能 / 大决战 / 借 / 翻页 / 攻略 / 字体） |
| `directory.py` | 名字解析：别名索引、判定链、显示策略 |
| `skills.py` | 技能槽位与数值，纯函数 |
| `render.py` | 全部输出文本 |
| `sources/schaledb.py` | 数值与七语言名称，ETag 条件刷新 |
| `sources/kivo.py` | 补充中文名与官方绰号，24h 磁盘缓存 |
| `sources/font.py` | T2I 字体检查与获取 |
| `clients/arona.py` | 大决战榜单 / 助战位查询 |
| `clients/bilibili.py` | B 站攻略视频搜索 |

## 数据源与关联键

| 源 | 提供 | 规模（会增长，勿硬编码） |
|---|---|---|
| SchaleDB `students_zh.json` | 技能数值、七语言名称，全量覆盖（含未上线角色） | 约 278 条 |
| kivo.wiki | 通用中文 / 国服译名 / 国际服繁体 / 官方绰号，含皮肤形态 | 约 510 条 |
| arona.icu | 大决战榜单、助战位、好友码 | 按赛期 |

**关联键用 SchaleDB Id**。kivo 的条目没有稳定的 SchaleDB Id，只能通过 `avatar` 路径里的角色代号
（`Student_Portrait_<DevName>_`）关联；而该代号在 SchaleDB 侧只覆盖部分角色，所以 **DevName 不能当主键**，
用名字当主键也不行（同一角色有多套译名）。

## 名称与显示策略

| 来源 | 内容 | 例（Aru） |
|---|---|---|
| SchaleDB `zh` | 通用中文（**不是**国服译名） | 阿露 |
| SchaleDB `tw` | 国际服繁体 | 亞瑠 |
| SchaleDB `en`/`jp`/`kr`/`th`/`vi` | 其他语言 | Aru / アル / 아루 |
| kivo `given_name_cn` | 国服译名（**显示用**） | 爱露 |
| kivo `nick_name` | 官方绰号 | 社长 |
| `aliases.json` | 用户自定义 | 藻哥 → 若藻 |

显示规则：

```
国服已上线（IsReleased[1] 为真） → kivo 国服译名，缺失回落 SchaleDB zh   例：爱露
国服未上线                        → kivo 中文全名 +（日文）                例：椎名纺（ツムギ）
形态（皮肤）                      → SchaleDB 名称里的括号标签             例：星野（泳装）
```

## 匹配判定链

1. **精确**：七语言名 / kivo 三套中文与全名 / 官方绰号 / `aliases.json` / DevName / 角色 ID
2. **形态词 + 基名**：允许跨语言混写（`水着星野`、`ホシノ水着`、`泳裝星野`）
3. **基名命中、形态词不认识**（`星野水`）→ 返回候选，由用户选择
4. **全不中** → `suggest` 拼写建议，禁止模型编造数值

不做「任意子串即命中」：那会把 `星野水` 直接答成「星野」，等于默许拼错。

## 槽位映射

玩家说法与 SchaleDB 字段的对应关系（最容易出错的一层）：

| 说法 | 字段 | 备注 |
|---|---|---|
| EX | `Ex` | 有 cost，5 级 |
| 普通技能（NS） | `Public` | **不是 `Normal`** |
| 普通技能（专武强化） | `GearPublic` | 开专武后 |
| 被动 | `Passive` | —— |
| 辅助（Sub） | `ExtraPassive` | —— |
| 武器被动 | `WeaponPassive` | —— |
| 普通攻击 | `Normal` | 只有帧数据，无数值 |

## 缓存与刷新

| 数据 | 机制 |
|---|---|
| SchaleDB | 距上次检查 ≥1h 才发条件请求（`If-None-Match`）；ETag 变了才下载；超 7 天无条件全量 |
| kivo | 磁盘缓存 24h，后台刷新，不阻塞查询 |
| arona 查询结果 | 进程内滑动 TTL 5 分钟（命中即续期） |
| arona 请求 | 进程内节流 `MIN_INTERVAL` = 0.25s（≤4 次/秒） |

## 设计约束

- 不用「昵称 + 形态词」的字符串拼接解析（已废弃，易错且慢）
- 不用名字或 DevName 当关联主键
- 不硬编码学生数量
- 只保留一种别名机制：`aliases.json`
- 上游没有的数据不要凑（如非国服大决战榜单），明确告知查不到

## 测试

```bash
python -m compileall -q astrbot_plugin_ba_wiki
python tests/selfcheck.py      # 加载 / 绑定 / 契约 / 数据源 / 名称解析 / 显示 / 指令
```

`tests/golden.md` 是人工对照表（真人问法 + 期望要点），`tests/selfcheck.py` 自动化其中可验证的部分。
