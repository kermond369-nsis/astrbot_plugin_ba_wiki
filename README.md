<div align="center">

# astrbot_plugin_ba_wiki

**蔚蓝档案（Blue Archive）查询插件 · 给 AstrBot 的可信数据源**

数值不靠模型编，配队不靠猜

[![AstrBot](https://img.shields.io/badge/AstrBot-4.x-4A90D9?style=flat-square)](https://github.com/AstrBotDevs/AstrBot)
[![Version](https://img.shields.io/badge/version-0.6.2-16a34a?style=flat-square)](https://github.com/kermond369-nsis/astrbot_plugin_ba_wiki)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange?style=flat-square)](LICENSE)

技能数值 · 大决战配队 · 助战好友码 · B 站攻略

<img src="docs/preview.png" alt="输出预览" width="860" />

</div>

---

## 它解决什么问题

BA 群里最常问的几件事，靠模型记忆全是编的，靠联网搜索又拿不到表格：

| 群友问 | 别的 bot | 这个插件 |
|---|---|---|
| 「若藻 NS 各等级倍率」 | 甩一段模糊概括 | SchaleDB 逐级取值，1~10 级全列 |
| 「大蛇大决战蓝甲怎么配」 | 编一队出来 | 什亭之匣真实榜首三甲配队 + 上限难度 |
| 「谁挂了泳装星野能借」 | 不知道 | 逐个区服助战位 + **好友码** + 练度筛选 |
| 「有没有作业可以抄」 | 空口建议 | B 站实际视频标题与链接 |

## 功能

| 工具 | 能力 | 数据源 |
|---|---|---|
| `query_ba_skill` | 技能描述 + 各等级数值（EX / NS / NS+ / PS / SUB / WP） | SchaleDB |
| `query_ba_raid_team` | 大决战各期榜首三甲真实配队 | 什亭之匣 |
| `query_ba_assist` | 谁把某学生挂助战 → 好友码，可按星级/等级/专武/EX 下限筛 | 什亭之匣 |
| `query_ba_player` | 好友码查玩家 | 什亭之匣 |
| `search_ba_guide` | B 站攻略视频标题 + 链接 | Bilibili |

## 安装

**方式一：插件市场**
AstrBot 面板「插件 → 插件市场」搜索 `ba_wiki` 安装。

**方式二：手动**

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/kermond369-nsis/astrbot_plugin_ba_wiki.git
# 目录名必须是 astrbot_plugin_ba_wiki
sudo systemctl restart astrbot     # 或面板里重载插件
```

无需额外依赖（只用 AstrBot 自带的 aiohttp / Pillow）。

## 使用

### 直接说话

```
若藻的 NS 各等级是多少
这期大蛇大决战蓝甲榜上怎么配的
谁挂了泳装星野能借，要 5 星满级专二
国服大决战有没有低配作业
```

模型会自动选工具，不用记指令。

### 手动指令

```
/ba 若藻              全部技能概览
/ba 若藻 ns           普通技能各等级数值
/ba ワカモ ex          用日文名也行
/ba 椎名纺            国服未上线角色也能查
/ba 大决战            当前赛期 + 各甲榜单配队
/ba 借 若藻 5星 Lv90 专2 EX5
/ba 借 泳装星野 国际服 5星
/ba 下页              保留条件翻页
/ba 攻略 国服 大决战 大蛇
```

### 输出示例

```
国服「若藻」助战（5★以上、Lv90+、专武2+、EX5+）
第 1/17 页 · 共 168 人 · 每页 10
1. 玩家甲 — 好友码 abcd123  5★ Lv90 专2 EX5
2. 玩家乙 — 好友码 efgh456  5★ Lv90 专3 EX5
翻页：/ba 下页

数据来源：什亭之匣 https://arona.icu
```

## 多区服名称

同一学生三套中文译名互不相同，插件全部认：

| 输入 | 命中 |
|---|---|
| `阿露` / `爱露` / `亞瑠` | 同一人（通用中文 / 国服 / 国际服） |
| `Aru` / `アル` / `아루` | 同一人 |
| `泳装星野` / `星野泳装` / `水着星野` | 星野（泳装） |
| `大叔` / `社长` / `藻子姐` | 官方绰号表 |
| `水星野` | 不认识 → 列出候选让你选 |

国服未上线角色（如椎名纺）显示为 **椎名纺（ツムギ）**，不显示 SchaleDB 的占位字。

## 配置

`data/config/astrbot_plugin_ba_wiki_config.json`，或面板插件页修改：

| 项 | 默认 | 说明 |
|---|---|---|
| `font.auto_download` | 开 | 启动时检查文本转图片所需 CJK 字体，缺了自动补 |
| `font.mirror_prefix` | 空 | 自定义下载反代 |
| `aliases.json` | 见下 | 群里的私人叫法，如 `{"藻哥": "若藻"}` |

### 字体（文本转图片变方块时）

中文变 □□□ 是宿主机缺 CJK 字体，插件自带修复：

- 插件页「字体」标签 → **下载 / 修复字体**
- 或发 `/ba 字体`
- 或手动把任意 CJK 字体放到 `<AstrBot data>/font.ttf`

> ⚠️ 不要用 `DroidSansFallbackFull.ttf` 这类 fallback 字体：只有 CJK 没有拉丁，数字和英文会变方块。

## 目录结构

```
astrbot_plugin_ba_wiki/
├── main.py            胶水：生命周期 / 工具绑定 / 指令接线
├── tools.py           5 个 LLM 工具（docstring 即路由契约）
├── commands.py        /ba 的借 / 翻页 / 大决战 / 攻略 / 技能分支
├── directory.py       名字解析：多语言索引 + 判定链 + 显示策略
├── skills.py          技能槽位与数值（纯函数）
├── render.py          所有输出文本
├── sources/           schaledb.py（ETag 刷新）、kivo.py（补充名）、font.py（字体）
├── clients/           arona.py（什亭之匣）、bilibili.py（B 站）
├── pages/font/        插件页：字体管理
└── sync_data.py       手动全量同步
```

## 数据来源与合规

| 来源 | 用途 | 说明 |
|---|---|---|
| [SchaleDB](https://schaledb.com) | 技能数值、七语言名称 | 权威数值源，社区维护；按 ETag 增量刷新 |
| [kivo.wiki](https://kivo.wiki) | 通用中文 / 国服 / 国际服译名、官方绰号 | 仅作名称补充 |
| [什亭之匣 arona.icu](https://arona.icu) | 大决战榜单、助战位、好友码 | 需自行申请 token（`<QQ号>:<密钥>`，与首次请求 IP 绑定）；插件默认直连，见 [部署与迁移](docs/MIGRATE-TO-LOCAL.md) |
| [Bilibili](https://www.bilibili.com) | 攻略视频 | 仅标题与链接，不转载内容 |

**数据版权归各来源站所有**，本插件只做聚合查询与格式化展示，输出均附带来源行。使用 arona 接口前请在 [arona.icu](https://arona.icu) 完成「数据来源备注」声明。

## 常见问题

<details>
<summary>报 <code>code 4007</code></summary>

arona 的 token 必须是 `<QQ号>:<密钥>`，且与**首次请求的 IP 绑定、绑死后不可改**。换网络或换机器需重新申请。家宽动态 IP 的处理方案见 [docs/MIGRATE-TO-LOCAL.md](docs/MIGRATE-TO-LOCAL.md)。
</details>

<details>
<summary>报 <code>code 4002</code></summary>

请求里没有服务器认得的 token（默认落到提示语，与未登录同码）。先确认数据目录下有 `arona_token.txt`、内容是 `<QQ号>:<密钥>`；确认无误仍报到 arona.icu 补「数据来源备注」声明。
</details>

<details>
<summary>报 <code>code 4005</code></summary>

账号被临时封禁（24 小时）。常见诱因是同一个 token 从**非绑定 IP** 反复请求。等封禁到期后先用 `curl -s https://api.ipify.org` 核对出口 IP 与申请 token 时是否一致，再重试；这段时间可以临时用官方测试 token `uuz:uuz`（5 req/s）。
</details>

<details>
<summary>技能数值查错槽位</summary>

玩家说的「普通技能」对应 SchaleDB 的 `Public`，**不是** `Normal`（`Normal` 只有帧数据）。
</details>

<details>
<summary>日服/全球的大决战查不到</summary>

上游只有国服有榜单，赛期列表才是全服通用。插件遇到别的区服会直说查不到，不拿国服数据凑。
</details>

## 文档

| 文档 | 内容 |
|---|---|
| [docs/MIGRATE-TO-LOCAL.md](docs/MIGRATE-TO-LOCAL.md) | **arona 鉴权怎么配、怎么从远端转发迁回本地直连** |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 部署手册（插件安装、数据目录、排障） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 重构任务与设计取舍记录 |

## 开发

```bash
python -m compileall -q astrbot_plugin_ba_wiki
python tests/selfcheck.py     # 114 项自检：加载/绑定/契约/数据源/解析/显示/指令
```

`tests/golden.md` 是人工对照表，`tests/selfcheck.py` 覆盖其中可自动化部分。

## 许可证

[AGPL-3.0](LICENSE) —— 与 AstrBot 生态一致。二次开发或分发请保留来源与许可证。

<div align="center">

如果这个插件帮到了你，给个 ⭐ 就行

</div>
