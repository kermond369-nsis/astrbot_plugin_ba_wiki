# 从「远端转发」迁回本地直连

> 背景：原先 arona.icu 的 token 与**首次请求的 IP 绑定且不可更改**，而 AstrBot 跑在家里、
> 出口 IP 会变，所以在云服务器上架了一个 HTTPS 转发器顶着。现在云服务器要移交，
> 转发链路失效，改为**本地直连、不再拆分**。

## TL;DR

```
1. 在 arona.icu 用新出口 IP 申请/换发 token
2. 插件数据目录写 arona_token.txt（格式 <QQ号>:<密钥>）
3. 删掉 arona_proxy.json
4. 重启 AstrBot，跑一遍验证
5. 移交云服务器前，把它上面的 token / 证书 / 密钥清干净
```

---

## 一、为什么以前要转发

| 事实 | 后果 |
|---|---|
| token 与**首次请求 IP 绑定**，且绑死后不可改 | AstrBot 换网络/换机器，token 立刻 `4007` |
| 家宽出口 IP 是动态的 | 重播、换路由器都会变 |

于是有了这套：

```
AstrBot 主机  ──HTTPS + X-Proxy-Key──▶  云服务器 :8443  ──固定 IP──▶  api.arona.icu
```

云服务器只做一件事：用**它自己的固定 IP** 去调 arona，顺便注入 token。

## 二、现在的目标

```
AstrBot 主机  ──HTTPS──▶  api.arona.icu
```

直连，中间什么都不留。插件本身**已经支持直连**，不需要改代码——切换只靠数据目录里两个文件。

## 三、插件怎么选模式（代码事实）

`astrbot_plugin_ba_wiki/clients/arona.py`：

```python
BASE = "https://api.arona.icu"
TEST_TOKEN = "uuz:uuz"          # 官方公告提供的开发测试 token，限 5 req/s

proxy = _proxy_cfg(data_dir)    # 读 arona_proxy.json
if proxy:                       # 有 → 走转发，不带 token
    url = proxy[0] + path
    headers = {"X-Proxy-Key": proxy[1], ...}
else:                           # 没有 → 直连
    token, _ = _token(data_dir) # arona_token.txt → 环境变量 ARONA_TOKEN → 测试 token
    url = BASE + path
    headers = {"Authorization": f"ba-token {token}", ...}
```

**结论：删掉 `arona_proxy.json` 就自动回直连**，`arona_token.txt` 生效。

token 读取优先级：

```
<插件数据目录>/arona_token.txt
  ↓ 没有
环境变量 ARONA_TOKEN
  ↓ 没有
uuz:uuz（测试 token，5 req/s）
```

数据目录通常是：

```
<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki/
```

## 四、迁移步骤

### 1. 确认新出口 IP

在本机（跑 AstrBot 的那台）执行：

```bash
curl -s https://api.ipify.org; echo     # 国内常被挡，见下面备选
curl -s https://myip.ipip.net; echo     # 备选 1，返回归属地
curl -s http://cip.cc | head -3         # 备选 2
```

记下这个 IP，下一步要用。**注意：这是"整台机器出网"的 IP，如果 AstrBot 走代理，要填代理的出口 IP。**

> 实测（AstrBot 主机，2026-10-18）：`api.ipify.org` 解析得到 Cloudflare 地址但连不上，
> `myip.ipip.net` / `cip.cc` 都正常。家宽出口 IP 是**动态**的，申请 token 前务必现测一次，
> 别用旧记录里的值（本文不记录具体 IP）。

### 2. 换发 token（关键，不能跳过）

旧 token 绑在云服务器的 IP 上，服务器一移交就废。到 [arona.icu](https://arona.icu) 用上面那个 IP 重新申请，
并按公告要求完成「数据来源备注」声明（不备注会返回 `4002`）。

拿到的形式是：

```
<QQ号>:<密钥>
```

### 3. 写到插件数据目录

```bash
cd <AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki
printf '%s\n' '你的QQ号:密钥' > arona_token.txt
chmod 600 arona_token.txt

# 关键：删掉转发配置，否则插件继续走已经不存在的转发机
rm -f arona_proxy.json
```

### 4. 重启并验证

```bash
sudo systemctl restart astrbot
```

验证（不依赖 QQ，直接用插件自己的代码打一次接口）：

```bash
cd <AstrBot>/data/plugins
sudo -u <运行用户> env BA_DATA_DIR=<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki \
  <python> - <<'PY'
import sys
sys.path.insert(0, "<AstrBot>/data/plugins")
from astrbot_plugin_ba_wiki.clients import arona
DD = "<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki"
s = arona.current_season(1, DD)
print("赛期:", (s or {}).get("season"))
r = arona.assist_players(1, 10033, 1, 2, data_dir=DD)
print("借人:", r.get("ok"), r.get("total_players"))
PY
```

期望输出类似：

```
赛期: 21
借人: True 747
```

再在群里发一次 `/ba 大决战` 和 `/ba 借 若藻`，确认链路。

### 5. 旧转发机清理（本次已随服务器重置，留作参考）

原转发机已整机重置，上面的 token / 密钥 / 证书自然失效，**这一步本次可跳过**。
以后再拆一台转发机时，按下面清理：

```bash
systemctl disable --now arona-proxy
shred -u /root/.arona_token 2>/dev/null || rm -f /root/.arona_token
rm -f /etc/arona-proxy.env
rm -f /opt/astrbot-qq/arona-proxy.crt /opt/astrbot-qq/arona-proxy.key
rm -f /opt/astrbot-qq/arona_proxy.py
rm -f /etc/systemd/system/arona-proxy.service
systemctl daemon-reload
```

> 旧 token 本身就绑死在这台机器的 IP 上，机器易主后用不了；但**删掉不费事，别赌**。

## 五、错误码对照

| 返回 | 含义 | 处理 |
|---|---|---|
| `200` | 正常 | —— |
| `4002` | 请求没带服务器认得的 token（未登录同码）；也可能未完成「数据来源备注」 | 先确认 token 文件与 `Authorization: ba-token <token>` 形态；无误再到 arona.icu 补备注 |
| `4005` | **账号被封禁 24 小时**（非绑定 IP 请求的后果）。实测静默近三天仍未解禁：每次试探都可能把 24h 重新计时 | **立刻停手**，别再试；先核对 `curl -s https://myip.ipip.net` 与申请 token 时是否一致，不一致就重新申请 |
| `4003` | `您的tokens额度已用完` —— 测试 token `uuz:uuz` 的额度打满（2026-10-21 实测） | 等额度恢复，或换自己的 token；别拿它跑批量 |
| `4007` | token 无效，或已绑定到别的 IP | 换发 token；确认出口 IP 与申请时一致 |

> 封禁是**账号级**、期间换 header 写法、换 token 都没用；官方测试 token `uuz:uuz` 不受影响。
> 但别把它当「等 24h 就自动好」：2026-10-18 到 10-21 静默近三天后请求仍是 4005，见第十节。
> 同一账号的另一个 token（绑在旧 IP 上）返回的是 4007 而不是 4005 —— 说明 4007 在封禁判定**之前**
> 就被绑定校验挡下，**不能用它推断账号有没有被封**。

> 如果之后想再把转发捡回来，仓库里有现成的容器化方案：
> [deploy/docker](../deploy/docker/README.md) —— `docker compose up -d` 起一个**纯 HTTP** 的转发器
> （容器内 30303，宿主机只绑 `127.0.0.1:3030`），TLS / 证书 / 域名交给前置反代，不用手动装 systemd 单元。

## 六、家宽动态 IP 怎么办

直连的前提是**出口 IP 稳定**。四种应对，按成本排序：

| 方案 | 说明 | 代价 |
|---|---|---|
| **① 申请固定/公网 IP** | 找宽带运营商要固定 IP，或确认现有公网 IP 是否会变 | 可能加钱 |
| **② 观察实际稳定性** | 很多家宽 PPPoE 只要不重播就长期不变；先直连跑一两周 | 0，但重播就掉 |
| **③ 保留一台小机器做转发** | 就是原来的方案，只是换成便宜 VPS | 低（约 ¥5/月） |
| **④ 用官方测试 token** | `uuz:uuz`，公开、无需申请、不限 IP，但 **5 req/s** 且可能随时变 | 0，稳定性差 |

> 日常使用量（几个人查查数值、翻翻榜）远低于 5 req/s，方案 ④ 其实够用；
> 插件内部本来就有 `MIN_INTERVAL` 限速和 5 分钟结果缓存，不会打满。

## 七、仓库里要跟着一起清理

迁完之后，这些就是历史遗留，建议标注为 legacy（或直接移到 `docs/legacy/`）：

| 路径 | 处理 |
|---|---|
| `deploy/arona-proxy.service` | 已改为读 `/etc/arona-proxy.env`，可用于自建转发；不用就标 legacy |
| `tools/arona_proxy.py` | 转发器源码，同上 |
| `tools/arona-api.md` | 接口备忘，其中「转发」一节标为历史方案 |
| `docs/DEPLOY.md` | 里面对转发机的描述需要加一条「已弃用」 |
| `README.md` | 合规表里 arona 那行的「走转发」说明改为「直连」 |

插件代码**不需要改**：`_proxy_cfg()` 返回空就走直连，两条路都留着没坏处。

## 八、回滚

万一本地直连走不通（例如 IP 一直变），把转发恢复即可：

1. 在一台固定 IP 的机器上跑 `tools/arona_proxy.py`（环境变量见 `deploy/arona-proxy.service`）
2. 插件数据目录写回 `arona_proxy.json`：

```json
{"url": "https://<转发机IP>:8443", "key": "<PROXY_KEY>"}
```

3. 重启 AstrBot

`arona_proxy.json` 的优先级高于 `arona_token.txt`，不用删 token。

## 九、检查清单

- [x] 新出口 IP 已确认（2026-10-18 测得）→ 三天后重测**已经变了**，家宽动态坐实，见第十节
- [x] `arona_token.txt` 内容是 `<QQ号>:<密钥>`，权限 600
- [x] `arona_proxy.json` 已删除（备份在 `/opt/astrbot-qq/rollback/arona-direct-20251018/`）
- [ ] 重启后 `current_season(1)` 返回赛期，`assist_players` 返回 `ok=True` —— **被 4005 卡住**，见第十节
- [ ] 群里 `/ba 大决战`、`/ba 借 若藻` 正常 —— 同上
- [ ] arona.icu 侧已完成「数据来源备注」
- [x] 旧服务器上的 token / 证书 / 密钥 / service 已清除（整机移交：`:8443` 拒连、SSH 已不可登录）

## 十、执行记录（2026-10-18，AstrBot 主机）

配置侧已经切完，卡在账号封禁上，记录在此免得下次重新排查。

| 项 | 结果 |
|---|---|
| `arona_proxy.json` | 已删；旧内容（旧转发机的 `https://<旧转发机>:8443` + `X-Proxy-Key`）备份在 `/opt/astrbot-qq/rollback/arona-direct-20251018/arona_proxy.json.disabled` |
| `arona_token.txt` | 已换成新 token（73 字节、权限 600、属主 codex）；旧 token 备份为同目录 `arona_token.txt.old` |
| 旧转发机 | 原 `:8443` 端口连接被拒（服务已不存在），SSH 报 `publickey` 拒绝 —— 确属整机移交，无需再清 |
| `astrbot.service` | 已重启，插件加载正常；实测 `proxy cfg: None`，token 走直连分支 |
| 鉴权实测 | `Authorization: ba-token uuz:uuz` → `200`（直连链路通）；`Authorization: ba-token <新 token>` → `4005 您的账号已被封禁24小时！` |
| 结论 | 直连**链路**已验证可用；阻塞点不在插件、不在转发配置，而在 arona 账号本身被禁。没有 `4002`（数据来源备注）问题 |

复验命令（**只在对的时机跑一次**，`arona_check.sh` 会连打两个接口）：

```bash
ssh <主机> 'bash /opt/astrbot-qq/tools/arona_check.sh'
```

脚本在服务器上（`/opt/astrbot-qq/tools/arona_check.sh`），仓库副本是
[tools/arona_check.sh](../tools/arona_check.sh)。期望输出 `赛期: N` + `借人: True <人数>`。

⚠️ **不要拿它当心跳去轮询**：这份 token 每被从非绑定 IP 请求一次，都可能把 24h 封禁重新计时
（10-18 起静默近三天仍是 4005 的实测见下一小节）。宁可一次都不试，也别隔几小时试一次。

### 当前运行状态（临时）：官方测试 token

封禁期间按「先凑活」的处理，线上**正在跑 `uuz:uuz`**：

| 项 | 状态 |
|---|---|
| `arona_token.txt` | 不存在（插件回落测试 token） |
| `arona_token.txt.pending` | 真 token，权限 600，等解封后恢复 |
| 自检结果 | `赛期: 21` + `借人: True 747`，exit 0 —— 群里的 `/ba 大决战`、`/ba 借` 现在就能用 |

插件每次请求都重读 token 文件，所以换回不需要重启；恢复脚本仍会重启一次，把内存里 5 分钟的
结果缓存也一并清掉。全程不碰被封的账号，因此不会把封禁拖长。

解封后一键恢复（挪回 -> 重启 -> 自检；**自检不过会自动退回测试 token 状态**，不会把线上搞挂）：

```bash
ssh <主机> 'bash /opt/astrbot-qq/tools/arona_restore_token.sh'
```

脚本在服务器上（`/opt/astrbot-qq/tools/arona_restore_token.sh`），仓库副本是
[tools/arona_restore_token.sh](../tools/arona_restore_token.sh)。自检失败时的判读见上节；
确认真 token 生效后再删 `arona_token.txt.pending`。

> 测试 token 的代价：**5 req/s**、可能随时变。插件本来就有 `MIN_INTERVAL`（4/s）和
> 5 分钟结果缓存，日常几个人查数值打不满，但别用它跑批量。

### 10-21 复核：这份真 token 在 AstrBot 主机上基本无解

隔了近三天（线上一直跑 `uuz:uuz`，真 token 只在临时目录里被试了两三次）再试，仍然是 `4005`：

| 时间（UTC） | 动作 | 返回 |
|---|---|---|
| 2026-10-18 16:07 | 第一次带真 token 的请求 | `4005` |
| 2026-10-18 16:2x | 单次复测 | `4005` |
| 2026-10-21 11:05 | 静默约 2.8 天后再试 | `4005` |
| 2026-10-21 11:0x | 同账号的老 token（绑在旧云服务器 IP） | `4007` |

两条结论（按观测，不是猜）：

1. **不是一次性的 24h 倒计时。** 静默近三天仍是 4005，最符合「每次从非绑定 IP 请求一次就把这 24h
   重挂一遍」。所以*每多试一次都在往回拖*，本仓库那个 `arona-token-retry.timer` 因此**不启用**
   （unit 文件留在 `deploy/`，需要时手动 `enable`）。
2. **直连 + 家宽动态 IP 本身不可持续。** 这三天出口 IP 就换了：

```
2026-10-18  myip.ipip.net -> 出口 IP A
2026-10-21  myip.ipip.net -> 出口 IP B    （A != B）
```

家宽重播一次，绑在旧 IP 上的 token 立刻失效（4007/4005）。所以真要用 token，就得先解决 IP 稳定性：
第六节的**方案①（固定 IP）**或**方案③（自建固定 IP 转发，token 绑转发机）**；否则就停在**方案④**
——也就是当前实际形态：直连 + `uuz:uuz`，够日常用，别再为这份 token 折腾。

### 当前最终形态（2026-10-21）

| 项 | 值 |
|---|---|
| 插件数据目录 | 无 `arona_token.txt`、无 `arona_proxy.json` → 直连 + `uuz:uuz` |
| 真 token | 停在 `arona_token.txt.pending`（600），仅当以后重新申请到**可用**的 token 才有意义 |
| 恢复脚本 | `/opt/astrbot-qq/tools/arona_restore_token.sh`（挪回→重启→自检；失败自动退回） |
| 自动重试 | `arona-token-retry.timer` 已 `disable`（避免每天重新计时） |
| 实测（10-21 11:4x） | `赛期: 21` 正常；**`借人` 报 `4003 您的tokens额度已用完`** —— 测试 token 的助战查询额度被打满（大决战/赛季接口仍可用） |

> `uuz:uuz` 不是无限量：助战查询（`/api/friends/assist_query`）有额度，打满就 `4003`，
> 且恢复窗口未知。所以它只能应急；真要稳定用 `/ba 借`，还是得等自己的 token（或中转机方案）落地。
