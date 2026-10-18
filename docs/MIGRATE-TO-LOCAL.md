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
AstrBot主机 (AstrBot)  ──HTTPS + X-Proxy-Key──▶  云服务器 :8443  ──固定 IP──▶  api.arona.icu
```

云服务器只做一件事：用**它自己的固定 IP** 去调 arona，顺便注入 token。

## 二、现在的目标

```
AstrBot主机 (AstrBot)  ──HTTPS──▶  api.arona.icu
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
curl -s https://api.ipify.org; echo
```

记下这个 IP，下一步要用。**注意：这是"整台机器出网"的 IP，如果 AstrBot 走代理，要填代理的出口 IP。**

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

### 5. 移交云服务器前清理

这台上原本存着 arona token、转发密钥和自签证书。**在交出去之前**：

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
| `4002` | 未声明数据来源 | 到 arona.icu 补「数据来源备注」 |
| `4007` | token 无效，或已绑定到别的 IP | 换发 token；确认出口 IP 与申请时一致 |
| `200` | 正常 | —— |

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

- [ ] 新出口 IP 已确认，且与申请 token 时一致
- [ ] `arona_token.txt` 内容是 `<QQ号>:<密钥>`，权限 600
- [ ] `arona_proxy.json` 已删除
- [ ] 重启后 `current_season(1)` 返回赛期，`assist_players` 返回 `ok=True`
- [ ] 群里 `/ba 大决战`、`/ba 借 若藻` 正常
- [ ] arona.icu 侧已完成「数据来源备注」
- [ ] 旧服务器上的 token / 证书 / 密钥 / service 已清除
