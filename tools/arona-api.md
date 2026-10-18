# arona.icu（什亭之匣）API 备忘

> 仅供本机部署使用。**token 与首次请求的 IP 绑定**，所有调试只在那台服务器上做，
> 不要从本地或别的机器请求，否则可能被临时封禁。

## 鉴权

**正确写法（已验证）**：

```
token: <token>
```

或 `ba-token: <token>` 作为 header 名。

踩过的坑：

| 写法 | 结果 |
|---|---|
| `Authorization: <token>` | `code 500` 服务器内部错误 |
| `Authorization: Bearer <token>` | `code 500` |
| `Authorization: ba-token <token>` | `code 4007` token 校验失败 |
| **`token: <token>`** | **通过鉴权**，进入下一步校验 |

Base URL：`https://api.arona.icu`

## 当前阻塞：4002

```
{"code":4002,"message":"如需使用本站数据，请在最终展示时备注数据来源（如本站地址），详细请查看关于页面"}
```

已试过无效：header 里加 `source` / `note` / `Referer` / `X-Source`、
body 里加 `source` / `remark` / `isMark` / `mark`。

**结论：这是账号侧要求**，需要在 arona.icu 的「关于」页或官方 QQ 群（949830458）公告里
完成「数据来源备注」声明后才放行。完成后本接口即可用。

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
