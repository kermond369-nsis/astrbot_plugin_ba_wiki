# 重构目标与任务清单

> 给下一个会话直接用。当前代码能跑，但可维护性已被反复打补丁破坏，
> 需要按功能重新分层。**不要在这份清单之外顺手改行为**。

## 一句话目标

把「名字解析」从散落各处的临时逻辑，收敛成**一个数据权威层**：
SchaleDB 为基准，kivo 为补充，按 `DevName` 关联，运行时合并，新学生自动生效。

---

## 已确认的事实（不要重新验证，除非怀疑数据变了）

| 事实 | 证据 |
|---|---|
| **SchaleDB 是权威源**，且**全覆盖**（连日服刚出、国服/国际服未上线的都有） | `IsReleased: [true, false, false]` 的记录存在 |
| SchaleDB 的 `students_zh.json` 共 **278** 条（会随时间增长，**不要硬编码数量**） | 实测 |
| 未上线角色的中文名**不可靠**（例：椎名纺在 SchaleDB 里 `Name='䌷'`，U+43F7） | Id 10152 / `PathName: tsumugi` / `DevName: CH0252` |
| **kivo 提供三套中文名 + 官方绰号** | `given_name`(通用中文) / `given_name_cn`(国服) / `given_name_zh_tw`(国际服) / `nick_name` |
| kivo 的 `avatar` 路径里含游戏角色代号 | `.../Student_Portrait_CH0252_...` → 与 SchaleDB 的 `DevName` 同源 |
| 简繁差异极大：278 人中 **227 人**简繁不同（阿露/亞瑠、日奈/陽奈） | 实测 |
| kivo 学生列表 51 页 × 10 条 ≈ **510** 条（含形态），也会增长 | 实测 |
| arona token 与首次请求 IP 绑定，AstrBot 换机后必须走转发 | 公告 + 实测 4007 |

## 名称显示策略（已定）

```
匹配用：SchaleDB 全语言名 + kivo 补充名 + 用户别名表 + 官方绰号
显示用：SchaleDB 的 zh（国服名）
        └─ 若 IsReleased[1] == false（国服未上线）
           → 用 kivo 的中文名（不用 SchaleDB 的占位名）
           → **并且必须附带日文名**，例如「椎名纺（ツムギ）」
```

---

## 任务清单

### T1 建分层骨架（先做，不改行为）
- 目录：`sources/`、`directory.py`、`skills.py`、`clients/`、`render.py`、`main.py`
- `main.py` 只保留 AstrBot 胶水（工具注册 + 指令分发），目标 ≤250 行
- **验收**：`python -m compileall` 通过；插件能加载；现有 5 个工具仍注册

### T2 `sources/schaledb.py`
- 拉 `students.json`（保留现有 ETag 条件刷新逻辑）
- 暴露：`students() -> dict[id, record]`、`names() -> dict[id, {lang: name}]`
- **验收**：ETag 未变时零下载；变时自动更新

### T3 `sources/kivo.py`
- 分页拉全量（`/api/v1/data/students/` + 详情），**磁盘缓存 24h**
- 从 `avatar` 提取 `DevName`（`Student_Portrait_([A-Za-z0-9]+)`）
- 暴露：`by_devname() -> dict['CH0252', record]`
- **验收**：`CH0252` → `{zh: 纺, cn: 纺, tw: 紬, jp: ツムギ, nick: ''}`

### T4 `directory.py`（核心）
- 以 SchaleDB 为主表，按 `DevName` 挂 kivo 补充
- 建别名索引：所有语言名 + kivo 三套中文 + 绰号 + 用户 `aliases.json`
- `resolve(keyword)` 保留现有判定链：**精确 → 形态词组合 → 基名候选 → 拼写提示**
- `display_name(schale_id)`：按上面的显示策略
- **验收**：
  - `爱露` / `亞瑠` / `Aru` / `アル` / `아루` → 同一人，显示「爱露」
  - `椎名纺` / `ツムギ` / `紬` → 同一人，显示「椎名纺（ツムギ）」
  - `水星野` → 候选「星野（泳装）/星野（临战）/星野」
  - `若澡` → 「没有查询到此学生，建议检查拼写」+ 候选

### T5 `skills.py`
- 从 SchaleDB 记录里取技能（现有 `describe_skill` / `render_level` 逻辑）
- 纯函数，不碰名字解析
- **验收**：`/ba 若藻 ns` 输出与现在逐字一致

### T6 `clients/arona.py`
- 保留双模式：直连 token / HTTPS 转发（`arona_proxy.json`）
- 保留结果缓存（滑动 TTL 5 分钟）
- 保留 `assist_query` 的 `uniqueId` 过滤 + 四个练度下限参数
- **验收**：`/ba 借 若藻 5星 Lv90 专2 EX5` 仍返回 168 人档

### T7 `clients/bilibili.py`
- 现状直接搬（带 cookie 才不被风控）
- **验收**：`/ba 攻略 国服 大决战 大蛇` 返回视频标题+链接

### T8 `render.py`
- 所有输出集中：技能 / 大决战配队 / 助战分页 / 错误与候选提示
- 统一带来源行（`数据来源：什亭之匣 https://arona.icu`）
- **验收**：输出格式与此前一致（分页 `第 X/Y 页 · 共 N 人 · 每页 10`）

### T9 配置与数据文件收口
- 只保留：`aliases.json`（用户维护）、`arona_proxy.json`、`arona_token.txt`
- **删除**：`variants.json`（组合解析已废弃）、`names_kivo.json`（改为运行时缓存）
- **验收**：删掉这两个文件后功能不退化

### T10 回归测试脚本
- `tests/golden.md` 列出 20 条真人问法 + 期望输出要点
- 覆盖：三套中文名、形态前后缀、错字、跨服、未上线角色
- **验收**：新会话照表跑一遍即可判断重构有没有破坏行为

---

## 环境现状（新会话接手用）

```
AstrBot 运行在 AstrBot 主机（<主机IP>），systemd 服务名 astrbot
  数据目录    /opt/astrbot-qq/data
  插件目录    /opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki
  插件数据    /opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki
  面板        http://<AstrBot主机IP>:6185
  重启        sudo systemctl restart astrbot

arona 转发（云服务器 <转发机公网IP>，因 token 与 IP 绑定）
  https://<转发机公网IP>:8443  systemd: arona-proxy
  证书已装入 AstrBot主机 信任库；插件侧配置 arona_proxy.json

QQ 侧：计划在 Windows 上用 NapCat 接入，尚未完成（文件在 napcat-win/）
```

## 不要做

- ❌ 不要再写「昵称 + 形态词」的组合解析（已废弃，且拖慢查询）
- ❌ 不要用**名字**当关联主键（两次踩坑都是这个原因）
- ❌ 不要硬编码学生数量（278 是快照）
- ❌ 不要新增第四种"配置别名"的机制，配置只留 `aliases.json`
