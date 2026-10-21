# arona.icu 鉴权与配置

插件通过 [什亭之匣 arona.icu](https://arona.icu) 的 `/api/*` 接口获取大决战榜单与助战位，需要 token。
本文只讲**鉴权机制、配置方式与错误码**，不涉及具体部署环境。

## token 的形态与语义

| 项 | 事实 |
|---|---|
| 格式 | `<QQ号>:<密钥>`，整行一个 token |
| 请求头 | `Authorization: ba-token <token>`（注意：不是 `token: <token>`） |
| 绑定 | 与**首次请求的出口 IP** 绑定，绑定后不可自行修改；换 IP 需站方处理 |
| 后果 | 从非绑定 IP 请求会失败；反复请求可能触发封禁（`4005`） |
| 公共测试 token | `uuz:uuz`，免申请、不限 IP，但**全局共享 5 次/秒**，仅供试用 |

## 两种鉴权模式

| 模式 | 插件数据目录里的文件 | token 在哪 | 适用 |
|---|---|---|---|
| **直连** | `arona_token.txt` | 插件所在机器 | 出口 IP 稳定（固定 IP / 长期不变的线路） |
| **中转** | `arona_proxy.json` | 一台固定出口 IP 的中转机 | 出口 IP 会变（家宽重播等） |

选择逻辑（`astrbot_plugin_ba_wiki/clients/arona.py`）：

```
读到 arona_proxy.json  → 走中转，请求带 X-Proxy-Key，不带 token
否则读 arona_token.txt → 直连
否则读环境变量 ARONA_TOKEN → 直连
否则用 uuz:uuz（测试 token）
```

> `arona_proxy.json` 的优先级高于 `arona_token.txt`：同时存在时走中转，token 文件被忽略。

## 直连配置

```bash
cd <AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki
printf '%s\n' '<QQ号>:<密钥>' > arona_token.txt
chmod 600 arona_token.txt
```

token 在首次请求时绑定当前出口 IP。**首次使用务必在最终运行的这台机器上发起**，
不要先在笔记本/别的主机上试（会把绑定打到那台机器）。

## 中转配置

插件数据目录写 `arona_proxy.json`：

```json
{"url": "https://你的中转域名", "key": "<中转机配置里的 PROXY_KEY>"}
```

```bash
chmod 600 arona_proxy.json
```

中转服务只需做一件事：用它自己的出口 IP 调 `api.arona.icu` 并注入 token。
可用的镜像与协议说明见 [deploy/docker](../deploy/docker/README.md)。协议要点：

| 项 | 值 |
|---|---|
| 请求 | `POST <url>/api/<path>`，头 `X-Proxy-Key: <key>` |
| 中转行为 | 校验 key → 注入 `Authorization: ba-token <token>` → 转发 |
| 响应 | 上游状态码与 body **原样返回** |

## 错误码

arona 的业务错误是 `HTTP 200 + body.code`，插件按 `code` 分类提示：

| code | 含义 | 处理 |
|---|---|---|
| `4002` | 请求没带可识别的 token（与未登录同码）；也可能未完成「数据来源备注」声明 | 检查配置与请求头形态；仍不行则到站点补声明 |
| `4003` | 限流 / 额度用尽（`uuz:uuz` 为全局 5 次/秒共享） | 降低频率或换自己的 token |
| `4005` | 账号封禁（多为非绑定 IP 反复请求触发） | 停止请求，等封禁结束；先核对出口 IP |
| `4007` | token 无效，或已绑定到别的 IP | 确认格式；必要时重新申请 |

中转层自己产生的错误（不经上游）：

| HTTP | 含义 |
|---|---|
| `401` | `X-Proxy-Key` 缺失或不匹配 |
| `404` / `405` | 路径不是 `/api/*` / 方法不是 `POST` |
| `413` | 请求体超过 `MAX_BODY_BYTES` |
| `502` | 中转连不上上游 |
| `503` | 中转没配 `PROXY_KEY` 或没读到 token |

## 自检

`tools/arona_check.sh` 直接调用插件自己的客户端打一次接口，不依赖 QQ：

```bash
# 指定 AstrBot 的插件目录（数据目录会自动推导）
PLUGINS=<AstrBot>/data/plugins bash tools/arona_check.sh
# 或直接指定插件数据目录
DD=<AstrBot>/data/plugin_data/astrbot_plugin_ba_wiki bash tools/arona_check.sh
```

输出当前生效的模式（直连 / 中转）、赛期与学生助战查询结果；退出码 `0` 正常、`1` 调用失败、`2` 环境不对。

## 选型建议

| 出口 IP | 建议 |
|---|---|
| 固定 IP | 直连，最简单 |
| 会变（家宽 PPPoE 等） | 中转：token 绑中转机，插件侧不再关心 IP |
| 只是临时试用 | `uuz:uuz`（注意 5 次/秒是全局共享的） |

## 安全

- token 永不入库：`arona_token.txt`、`arona_proxy.json` 已在 `.gitignore`
- 文件权限 600；中转机的 `config/` 同样只给服务账号可读
- 出现 `4005` 后不要循环重试，封禁期内重试没有收益
- 换 token 只需替换中转机的 token 文件（镜像按文件 mtime 热加载，无需重启）
