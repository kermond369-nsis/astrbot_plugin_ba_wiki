# ba-wiki-plugin 上机说明（真机部署 / AstrBot）

- **包**：`ba-wiki-plugin.zip`（约 45 KB，17 个文件，无第三方依赖）
- **版本**：`0.6.1`（metadata.yaml 与插件注册版本一致）
- **适用**：AstrBot 4.x（Python ≥ 3.10），当前线上实例 `<主机名>（<主机IP>）`
- **变更**：本版是 T1~T10 重构后的正式包。5 个工具、`/ba` 的 5 类用法、参数与返回结构不变；
  名字显示与匹配来源有升级（见文末「变更摘要」）

---

## 1. 包里有什么

```
astrbot_plugin_ba_wiki/
  main.py              胶水层：生命周期 / 工具绑定对齐 / /ba 接线
  tools.py             5 个 LLM 工具（docstring 就是模型路由契约）
  commands.py          /ba 的 借 / 翻页 / 大决战 / 攻略 / 技能 分支
  directory.py         名字解析（SchaleDB + kivo + aliases.json，显示策略）
  skills.py            技能槽位与数值（纯函数）
  render.py            所有输出文本（含错误与候选提示）
  sources/schaledb.py  SchaleDB 下载 + ETag 条件刷新 + 七语言名
  sources/kivo.py      kivo 三套中文名 + 官方绰号（24h 磁盘缓存）
  clients/arona.py     什亭之匣（直连/转发双模式、结果缓存、助战筛选）
  clients/bilibili.py  B 站视频搜索
  sync_data.py         手动同步 SchaleDB（一般用不到）
  metadata.yaml        插件元数据（版本 0.6.1）
  README.md            插件自身的功能说明
  arona_token.sample.txt  token 格式示例
```

## 2. 环境和路径

| 项 | 值 |
|---|---|
| 主机 / 面板 | `<主机名>`（<主机IP>）/ http://<主机IP>:6185 |
| 服务 | `sudo systemctl restart astrbot` |
| 插件目录 | `/opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki/` |
| 数据目录 | `/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki/` |
| 出网需求 | `schaledb.com:443`、`api.kivo.wiki:443`、`api.arona.icu:443`、`api.bilibili.com:443`（arona 直连，2026-10-18 起不再经转发机） |

> QQ 侧的 NapCat 接入还没完成，与这个插件无关，不影响先上插件。

## 3. 上线步骤

### 3.0 先备份（必做）

```bash
cd /opt/astrbot-qq/data
sudo tar czf /root/ba-wiki-before-0.6.1-$(date +%F).tgz \
    plugins/astrbot_plugin_ba_wiki plugin_data/astrbot_plugin_ba_wiki
```

> 仓库里还有重构前的完整源码硬存档 `backup-pre-t1.zip`（线上 0.5.0 ≈ 那一版），回滚时可用。

### 3.1 传包并解压

```bash
# 本地把 zip 传到服务器（任选其一）
scp ba-wiki-plugin.zip user@<主机>:/tmp/

# 服务器上替换（先挪走旧的，出问题好回退）
cd /opt/astrbot-qq/data/plugins
sudo rm -rf astrbot_plugin_ba_wiki.old
sudo mv astrbot_plugin_ba_wiki astrbot_plugin_ba_wiki.old
sudo unzip -q /tmp/ba-wiki-plugin.zip -d /opt/astrbot-qq/data/plugins
sudo chown -R astrbot:astrbot /opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki
```

> 也可以在面板「插件 → 安装插件」里直接上传 zip；上传后确认目录是
> `plugins/astrbot_plugin_ba_wiki/main.py`（**不要**多套一层目录）。

### 3.2 处理数据目录（不要清空）

| 文件 | 处理 |
|---|---|
| `students_zh.json` | 保留。首个查询会带 ETag 校验，不会重复下载 |
| `names.json` / `meta.json` | 保留（缺失会自动重建） |
| `kivo_students.json` | 新文件，首次启动后台自动生成（约 350 KB） |
| `nicknames.json` | **改名迁移**：`sudo cp nicknames.json aliases.json && sudo rm nicknames.json`（不迁也能跑，代码兼容读，但会走兼容分支） |
| `names_kivo.json` | 删除。已改为运行时缓存，不再读取 |
| `variants.json` | 删除。组合解析早已废弃 |
| `arona_token.txt` / `arona_proxy.json` | 保留原样 |

```bash
cd /opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki
sudo rm -f names_kivo.json variants.json
if [ -f nicknames.json ]; then sudo cp nicknames.json aliases.json && sudo rm nicknames.json; fi
sudo chown -R astrbot:astrbot .
sudo chmod -R u+rw .
```

### 3.3 确认 arona 鉴权（直连）

```bash
# token 必须是与本机出口 IP 绑定的那一份，格式 <QQ号>:<密钥>，权限 600
ls -l  arona_token.txt && cat arona_token.txt
# 确认没有残留的转发配置：这个文件存在就会压过 token 走转发
ls -l  arona_proxy.json 2>/dev/null || echo "无 arona_proxy.json（正确，直连）"
```

> **2026-10-18 起转发形态已弃用**：云服务器移交，`arona_proxy.json` 已从线上数据目录删除，
> 插件直连 `api.arona.icu`。`deploy/arona-proxy.service` 与 `tools/arona_proxy.py` 只作回滚备件，
> 见 [MIGRATE-TO-LOCAL.md](MIGRATE-TO-LOCAL.md) 第八节。
>
> 现状：真 token 的账号被 arona 封禁 24h（`4005`），线上暂时用官方测试 token 跑（`arona_token.txt`
> 已被改名为 `arona_token.txt.pending`）。解封后执行 `/opt/astrbot-qq/tools/arona_restore_token.sh`
> 一键恢复并自检。

### 3.4 重启并看日志

```bash
sudo systemctl restart astrbot
journalctl -u astrbot -f | grep -E "ba_wiki|astrbot_plugin_ba_wiki"
```

面板 → 插件页应出现「蔚蓝档案数值查询 0.6.1」并处于启用状态；工具列表应出现
`query_ba_skill` / `search_ba_guide` / `query_ba_raid_team` / `query_ba_player` / `query_ba_assist`。

### 3.5 首次部署 / 新环境：直接手动跑一次全量同步（推荐）

插件加载后会自动预热，但 kivo 那部分要 2 分钟、跑在后台，**日志里能看见、文件最后才落盘**。
新环境不想等，就直接跑一次（SchaleDB + kivo 一起同步，kivo 无视 24h 缓存强制重抓）：

```bash
cd /opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki
sudo -u astrbot env BA_DATA_DIR=/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki \
    python sync_data.py
# 期望输出：SchaleDB 就绪，角色数: 278 / kivo 就绪，记录数: 510（约 2 分钟）
```

只补 kivo（不想重下 SchaleDB）时：

```bash
cd /opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki
sudo -u astrbot python -c "import sys; sys.path.insert(0,'.'); from sources import kivo; print(len(kivo.records('/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki', force=True)))"
```

## 4. 启动预热会做什么（耗时预期）

插件实现 `initialize()`（AstrBot 在插件加载完 `await` 它），里面**只排一个后台任务**，立刻返回，
不会拖住 AstrBot 启动。日志里必须能看到这三行（0.6.1 起）：

```
[ba_wiki] 已排入启动预热任务：SchaleDB 检查 + kivo 名字缓存同步
[ba_wiki] 已排入后台任务：同步 kivo 名字缓存（首次约 2 分钟，不阻塞查询）
[ba_wiki] kivo 名字缓存就绪：510 条 -> /opt/astrbot-qq/data/plugin_data/.../kivo_students.json
```

| 时机 | 动作 | 预期 |
|---|---|---|
| 插件加载后（不等查询） | SchaleDB 条件检查 | 有缓存时 304，零下载；新环境下载 5 MB，几秒~几十秒 |
| 同上（紧接着，后台） | 抓 kivo 全量 510 条详情 | 约 2 分钟；期间显示名退回 SchaleDB（会看到「阿露」「䌷」），抓完自动切换 |
| 之后每小时 | kivo 缓存检查 | 24h 内直接复用，不发请求 |
| 之后每 24h | kivo 重抓 | 后台进行 |
| 有查询但没预热过 | 第一次查询仍会兜底触发一次 | 与上面同一套任务，不会重复抓 |

## 5. 验收清单（逐条打勾）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 面板插件页 | 显示 0.6.1，已启用，无加载失败 |
| 2 | 工具列表 | 5 个工具都在，且已启用 |
| 3 | `/ba 若藻 ns` | 「落樱缤纷」，Lv1 194% … Lv10 369% |
| 4 | `/ba 若藻` | 技能概览（EX/NS/PS/SUB/WP + 普通攻击） |
| 5 | `/ba 爱露` 与 `/ba 阿露` | 都命中同一人，标题显示 **爱露** |
| 6 | `/ba 椎名纺` | 标题 **椎名纺（ツムギ）**（刚重启还没抓完 kivo 时可能显示 䌷，等 2 分钟） |
| 7 | `/ba 借 若藻 5星 Lv90 专2 EX5` | 抬头「第 1/N 页 · 共 M 人 · 每页 10」+ 好友码，条件回显 5★以上/Lv90+/专武2+/EX5+ |
| 8 | `/ba 下页` | 页码 +1，条件不变 |
| 9 | `/ba 大决战` | 「国服 大决战 season N」+ 各甲配队 + 来源行 |
| 10 | `/ba 攻略 国服 大决战 大蛇` | 3~4 条 B 站标题+链接 |
| 11 | `ls plugin_data/astrbot_plugin_ba_wiki` | 出现 `kivo_students.json`、`aliases.json` |

## 6. 配置项

| 文件 | 作用 | 备注 |
|---|---|---|
| `aliases.json` | 群里的叫法 → 官方名/角色 ID/显示名 | 键值都是字符串；以 `_` 开头的键当注释；改完重载插件 |
| `arona_token.txt` | arona 直连 token | 与首次请求 IP 绑定，换机即失效 |
| `arona_proxy.json` | arona HTTPS 转发（**已弃用**） | 存在即优先于 token；线上已删除。仅在重新架转发机时写回 |
| `kivo_students.json` | kivo 名字缓存 | 可删，下次启动会重抓（约 2 分钟） |
| `meta.json` | ETag + 上次检查时间 | 删了等于强制重新校验上游 |

## 7. 排障速查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| 插件列表里没有这个插件 | 目录多套了一层 / metadata.yaml 丢了 | 确认 `plugins/astrbot_plugin_ba_wiki/main.py` 存在；看 `journalctl` 里的 ImportError |
| 插件在，但工具列表里没有 | 工具未启用 / 加载异常 | 面板工具页勾选；日志搜 `[ba_wiki]` 与 `llm_tool` |
| 工具在，一调用就报 `missing 1 required positional argument: 'self'` | AstrBot 改了工具绑定规则（只绑定 `__module__` 等于插件主模块的 handler） | 见 `ba-wiki-plugin/README.md` 的结构说明与 `main.py` 顶部那段 `__module__` 对齐循环；必要时把 5 个工具移回 `main.py` |
| 报 `code=4007` | token 无效或绑定到别的 IP | 用 `curl -s https://api.ipify.org` 核对出口 IP，重新申请 token；短期可临时用 `uuz:uuz` 或回滚转发（见 MIGRATE-TO-LOCAL.md 第八节） |
| 报 `code=4005` | 账号被临时封禁 24 小时（同一 token 从非绑定 IP 反复请求的典型后果） | 停手等待，别再重试；到期后核对出口 IP 与申请时一致再试 |
| 报 `code=4002` | 请求没带服务器认得的 token（未登录同码）；也可能未完成数据来源备注 | 确认 `arona_token.txt` 存在且是 `<QQ号>:<密钥>`；无误则到 arona.icu 补「数据来源备注」 |
| 查询报「本地数据缺失且下载失败」 | 服务器出不了网到 schaledb.com | 手工：`BA_DATA_DIR=/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki python sync_data.py`（在插件目录里跑） |
| 重启后一直没出现 `kivo_students.json` | ① 后台任务还没跑完（2 分钟）② AstrBot 没调用 `initialize()`（版本/加载异常）③ 出网失败 | 先看日志三行（见第 4 节）：没有「已排入启动预热任务」→ 说明钩子没被调用，直接按 3.5 手动跑一次；有「已排入」但没「就绪」→ 等 2 分钟或看是否报「kivo 同步失败」 |
| 显示名一直是「阿露 / 䌷」 | kivo 没抓成功 | 日志搜 `kivo 同步失败`；确认能访问 `api.kivo.wiki`；网络恢复后 1 小时内会自动重试 |
| `/ba 下页` 提示「没有可翻页的查询」 | 没先发「借」，或会话已过 10 分钟 | 重新 `/ba 借 …` |
| 别名不生效 | 文件名/键值不对 | 文件名必须是 `aliases.json`；日志会有「别名 'X' 找不到对应学生」的 warning |
| 文字转图片后中文全是方块（□□□），数字/英文/★/URL 正常 | 宿主机没有 CJK 字体，AstrBot 本地 T2I 退回只有拉丁字形的 DejaVuSans | 见下面 **7.1**，装一次中文字体即可，与插件无关 |
| 面板里工具描述是乱码 | 终端/日志编码 | 插件源码是 UTF-8，功能不受影响 |

### 7.1 文字转图片后中文变方块（□□□）

**现象**：开启「文本转图片」后，中文全是 □□□，但数字、英文、`★`、`·`、`—`、好友码、URL 都正常。

**原因**：AstrBot 4.x 的**本地** T2I 是 Pillow 渲染，按固定路径找中文字体；一个都找不到时退回
`DejaVuSans.ttf`（只有拉丁字形）→ 中文缺字形。**与插件无关**：插件返回的文本与日志都是正常
UTF-8（把 T2I 关掉就能看到中文）。AstrBot 的字体查找顺序里，Linux 优先这两条：

```
/opt/astrbot-qq/data/font.ttf          ← AstrBot 数据目录根（最高优先级，可自己放）
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

**修复（先试 ⓪，其余三选一都需要 `sudo systemctl restart astrbot`）**

**⓪ 让插件自己装（推荐，全自动）**

插件已经内置了这套逻辑，**通常你什么都不用做**：

| 时机 | 行为 |
|---|---|
| 插件加载（`initialize`） | 后台检查 `<data>/font.ttf` 与 `font-bold.ttf`：缺失 / 太小 / 头部不对 / 字形位图自检不过 → 才装 |
| 获取顺序 | ①复制系统已有 CJK 字体（Noto / 文泉驿）→ ②按镜像下载 Noto Sans CJK（ghfast.top → jsdelivr → raw.githubusercontent.com → github.com） |
| 手动触发 | **插件设置页 →「字体」标签 → 「下载 / 修复字体」按钮**，页面会显示文件名、大小、缺失字形 |
| 聊天触发 | `/ba 字体`（只检查） / `/ba 字体 修复`（强制重装） |

配置项（`_conf_schema.json` → `font`）：

- `auto_download`：默认开。关掉后只能手动触发。
- `mirror_prefix`：自定义反代前缀，留空用内置顺序。

页面与接口：

```
pages/font/index.html                         插件页：状态表格 + 刷新 + 下载按钮
GET  /astrbot_plugin_ba_wiki/font/status      只读检查（不发网络请求）
POST /astrbot_plugin_ba_wiki/font/download    强制重新获取并校验
```

下面是手动方案，插件自带的逻辑失败时再用：
1. 装 Noto CJK（装完路径正好命中 AstrBot 的候选）：
```bash
sudo apt update && sudo apt install -y fonts-noto-cjk
sudo fc-cache -fv
ls -l /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc   # 确认存在
```
2. 离线 / 不想改系统字体：把任意 CJK 字体放进 AstrBot 数据目录根（第一优先级，支持 .ttc/.otf 内容）
```bash
sudo cp /path/to/NotoSansCJK-Regular.ttc /opt/astrbot-qq/data/font.ttf
sudo cp /path/to/NotoSansCJK-Bold.ttc    /opt/astrbot-qq/data/font-bold.ttf   # 粗体（部分模板用）
sudo systemctl restart astrbot
```
3. 临时规避：关掉文本转图片（AstrBot 配置项 `t2i`），直接发纯文本——此时中文本来就是好的，
说明问题只在渲染端的字体。

**验证**：重启后发 `/ba 借 若藻 5星`，中文恢复，且其余格式（`第 1/N 页 · 共 M 人 · 每页 10`、
编号、好友码、来源行）应完全不变。

> 顺带说明：图上那种「格式全对、只有汉字方块」的表现就是缺字体，不是乱码——
> 乱码会是 `æ‹¥...` 这类看不懂的拉丁字符，方块是字形缺失。

### 7.2 字体自检（不需要发消息就能确认）

`FontManager.get_font()` 是 AstrBot 渲染文章时实际调用的入口，直接看它选中了谁：

```bash
sudo -u codex env ASTRBOT_ROOT=/opt/astrbot-qq \
  python3 - <<'PY'
from astrbot.core.utils.t2i.local_strategy import FontManager
for bold in (False, True):
    f = FontManager.get_font(28, bold=bold)
    print(("[BOLD] " if bold else "[REG ] ") + str(getattr(f, "path", "?")))
PY
```

期望输出（装好仓库字体后）：

```
[REG ] /opt/astrbot-qq/data/font.ttf
[BOLD] /opt/astrbot-qq/data/font-bold.ttf
```

若看到 `/usr/share/fonts/.../DejaVuSans.ttf`，说明字体没生效，中文一定会变方块。

**逐字校验**（比看路径更硬的证据）：把待测字符渲染成位图，与私用区字符 `U+E000`
（必然无字形，即豆腐块）逐一比对，位图相同就说明该字缺字形：

```bash
sudo -u codex env ASTRBOT_ROOT=/opt/astrbot-qq \
  python3 - <<'PY'
from PIL import Image, ImageDraw
from astrbot.core.utils.t2i.local_strategy import FontManager
SAMPLES = ["国服「若藻」助战", "第 1/75 页 · 共 746 人 · 每页 10",
           "椎名纺（ツムギ）", "星野（泳装） 爱露 / 亞瑠",
           "好友码 efgh456  5★ Lv90 专3 EX5", "数据来源：什亭之匣 https://arona.icu"]
def bmp(f, ch, box=48):
    im = Image.new("L", (box, box), 255)
    ImageDraw.Draw(im).text((4, 4), ch, font=f, fill=0)
    return im.tobytes()
for bold in (False, True):
    f = FontManager.get_font(28, bold=bold)
    tofu = bmp(f, "\uE000")
    miss = sorted({c for line in SAMPLES for c in line if not c.isspace() and bmp(f, c) == tofu})
    print(f"[{'BOLD' if bold else 'REG '}] 缺失: {''.join(miss) or '无'}")
PY
```

两行都输出「缺失: 无」即可。

> 现状（线上 `AstrBot主机`）：`data/font.ttf` = Noto Sans CJK Regular，`data/font-bold.ttf` = Noto Sans CJK Bold，
> 两项实测均 **0 缺失**，渲染出的中文正常（`第 1/75 页 · 共 746 人 · 每页 10`、`椎名纺（ツムギ）` 均正确）。

## 8. 回滚

```bash
cd /opt/astrbot-qq/data/plugins
sudo rm -rf astrbot_plugin_ba_wiki
sudo mv astrbot_plugin_ba_wiki.old astrbot_plugin_ba_wiki   # 3.1 步挪走的旧目录
sudo systemctl restart astrbot
```

`plugin_data/` 不受影响；旧版不读 `kivo_students.json` / `aliases.json`，留着也无害。
若旧目录已删，用 `/root/ba-wiki-before-0.6.1-*.tgz` 或 `backup-pre-t1.zip`（解压 `pre-t1/astrbot_plugin_ba_wiki`）。

## 9. 变更摘要（0.5.0 → 0.6.1）

- **结构**：单文件 `main.py` 拆成 8 个模块（工具 / 指令 / 名字 / 技能 / 渲染 / 数据源 / 客户端），
  行为经新旧逐项对比验证（2723 项输出与上游调用参数一致）
- **名字来源升级**：SchaleDB（七语言，权威）+ kivo（通用中文 / 国服译名 / 国际服繁体 + 官方绰号）
  + `aliases.json`；关联主键用 SchaleDB Id（DevName 在 kivo 侧带后缀，只覆盖 187/278）
- **显示策略**：国服已上线 → 国服译名（**爱露**，此前是「阿露」）；
  国服未上线 → 中文全名 + 日文（**椎名纺（ツムギ）**，此前是「䌷」）
- **新增缓存**：`kivo_students.json`（24h，后台刷新，不阻塞查询）
- **配置收口**：`aliases.json`（兼容旧 `nicknames.json`）；不再使用 `names_kivo.json` / `variants.json`
- **不变**：5 个工具名/参数/返回字段、`/ba` 的 5 类用法、助战分页格式、大决战渲染、B 站搜索
- **0.6.1 修复**：kivo 名字缓存的触发点从「第一次查询」挪到**插件加载**（`initialize()` 钩子），
  补了三条启动日志；`sync_data.py` 扩成「SchaleDB + kivo 全量手动同步」。对应现象：
  重启后 2 分钟内没有 `kivo_students.json`、日志里也没有 kivo 记录

## 10. 附：常用命令

```bash
# 强制刷新 SchaleDB（很少需要）
cd /opt/astrbot-qq/data/plugins/astrbot_plugin_ba_wiki
sudo -u astrbot BA_DATA_DIR=/opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki python sync_data.py

# 看数据目录
ls -la /opt/astrbot-qq/data/plugin_data/astrbot_plugin_ba_wiki

# 看插件日志
journalctl -u astrbot -f | grep -E "ba_wiki|kivo|arona"

# 只重启服务
sudo systemctl restart astrbot && sudo systemctl status astrbot --no-pager
```
