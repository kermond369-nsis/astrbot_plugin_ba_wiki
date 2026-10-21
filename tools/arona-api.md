# arona.icu（什亭之匣）API 备忘

> 仅供本机部署使用。**token 与首次请求的 IP 绑定**，所有调试只在那台服务器上做，
> 不要从本地或别的机器请求，否则可能被临时封禁（实测封禁返回 `4005`，24 小时）。
>
> 本文的「转发」形态自 2026-10-18 起已弃用：转发机随云服务器移交下线，插件改直连，
> 见 [docs/MIGRATE-TO-LOCAL.md](../docs/MIGRATE-TO-LOCAL.md)。

## 鉴权

**正确写法（2026-10-18 实测）**：

```
Authorization: ba-token <token>
```

这正是 `clients/arona.py` 与旧转发器 `tools/arona_proxy.py` 用的形式：拿官方测试
token `uuz:uuz` 走这个 header 直接 `code 200` 拿到赛季数据。

实测对照（同一台机器，连续几次请求）：

| 写法 | 结果 |
|---|---|
| 不带 token | `code 4002` |
| `token: <token>` | `code 4002`（服务器没把这个 header 当鉴权） |
| `ba-token: <token>` | `code 4002`（同上） |
| **`Authorization: ba-token <token>`** | **进入鉴权**：有效 200，被封 4005 |
| `Authorization: ba-token uuz:uuz` | `code 200`，正常返回赛季列表 |

> 旧版本文把 `Authorization: ba-token` 记成「4007 校验失败」、把 `token:` 记成「正确写法」，
> 与实际相反。`4002` 也不是「header 写法不对」的诊断——请求没带可识别 token 时就会返回，
> 与未登录同码。

Base URL：`https://api.arona.icu`

## 错误码实测

| 返回 | message | 触发条件 | 处理 |
|---|---|---|---|
| `200` | —— | 鉴权通过 | —— |
| `4002` | 如需使用本站数据，请在最终展示时备注数据来源… | 请求没带服务器认得的 token（未登录同码） | 检查 `arona_token.txt` 与 header 形态；仍报到 arona.icu 补「数据来源备注」 |
| `4005` | 您的账号已被封禁24小时！ | 同一 token 从非绑定 IP 反复请求 | 等 24h；核对 `curl -s https://api.ipify.org` 与申请 token 时的出口 IP；必要时重新申请 |
| `4007` | token 校验失败 | token 格式不对 / 绑到别的 IP | 确认是 `<QQ号>:<密钥>`；换发 token |

> `4002` 曾被当成「数据来源备注」的专属信号，其实它在「请求没带可识别 token」时也会返回；
> 带正确 header 时该码换成 4005/4007/200。header 里塞 `source` / `X-Source` / `Referer`、
> body 里塞 `remark` / `isMark` 一律无效，别再试。

## 区服枚举

```
1 国服   2 B服    3 日服   4 综合   5 全球
6 港澳台 7 韩服   8 亚服   9 北美服
```

## 接口清单（均 POST + JSON）

| 用途 | 路径 | body |
|---|---|---|
| 总力战赛季列表 | `/api/season/list` | `{"server":1}` |
| 大决战赛季列表 | `/api/season/eliminate_raid_season_list` | `{"server":1}` |
| 总力战排名 | `/api/v2/rank/list` | `{"server":1,"season":N,"type":2,"page":1,"size":26}` |
| 总力战榜单前列 | `/api/v2/rank/list_top` | `{"server":1,"season":N}` |
| 总力战排行变化 | `/api/v2/rank/list_by_last_rank` | `{"server":1,"season":N,"dataType":0,"tryNumber":0}` |
| 大决战排名 | `/api/eliminate_raid_rank/list` | `{"server":1,"season":N,...}` |
| 大决战榜单前列 | `/api/eliminate_raid_rank/list_top` | `{"server":1,"season":N}` |
| 大决战 Boss 列表 | `/api/eliminate_raid_rank/boss_list` | `{"server":1}` |
| 按好友码查玩家 | `/api/friends/findRank` | `{"friend":"好友码"}` |
| 查玩家详情 | `/api/friends/find` | `{"server":1,"friend":"好友码"}` |
| 玩家大决战历史 | `/api/friends/eliminate_raid_history` | `{"friend":"好友码",...}` |

> 参数形状来自开源项目 [KimigaiiWuyi/BlueArchiveUID](https://github.com/KimigaiiWuyi/BlueArchiveUID)
> 与站内前端包（`/api/...` 路径由 `arona.icu/assets/index-*.js` 提取）。

## 待确认

1. **按昵称查排名**：`findRank` 收的是好友码（好友 ID），不是昵称。
   「日服星落城心」这类按昵称的问法，需要先确认站内是否有按昵称搜索的接口
   （前端有 `/api/friends/name_history`、`/api/friends/find`，待 4002 解除后实测）。
2. 大决战排名的 `difficulty`（LU/TM/INS）字段名未知，需实测。

## 配额与礼貌

- 结果自己缓存，别对同一 season 反复打
- 同一账号 key 有两个（tavily 那种）这里不适用，token 单发
- 展示数据时必须带来源：`数据来源：什亭之匣 arona.icu`
