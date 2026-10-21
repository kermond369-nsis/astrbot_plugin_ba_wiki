# arona.icu API 参考

插件用到的什亭之匣接口约定，便于排障与二次开发。

## 基础

| 项 | 值 |
|---|---|
| Base URL | `https://api.arona.icu` |
| 方法 | 全部 `POST`，请求体与响应体均为 JSON |
| 鉴权 | `Authorization: ba-token <token>`（`token` 形如 `<QQ号>:<密钥>`） |
| 业务状态 | HTTP 200 + body 的 `code`；`code == 200` 才算成功 |

## 接口清单

| 用途 | 路径 | body |
|---|---|---|
| 总力战赛季列表 | `/api/season/list` | `{"server":1}` |
| 大决战赛季列表 | `/api/season/eliminate_raid_season_list` | `{"server":1}` |
| 大决战 Boss 列表 | `/api/eliminate_raid_rank/boss_list` | `{"server":1}` |
| 大决战榜首 | `/api/eliminate_raid_rank/list_top` | `{"server":1,"season":N}` |
| 大决战排名 | `/api/eliminate_raid_rank/list` | `{"server":1,"season":N,...}` |
| 总力战排名 | `/api/v2/rank/list` | `{"server":1,"season":N,"type":2,"page":1,"size":26}` |
| 总力战榜首 | `/api/v2/rank/list_top` | `{"server":1,"season":N}` |
| 排名变化 | `/api/v2/rank/list_by_last_rank` | `{"server":1,"season":N,"dataType":0,"tryNumber":0}` |
| 助战位查询 | `/api/friends/assist_query` | `{"server":1,"uniqueId":<角色ID>,"page":1,"size":10}` |
| 按好友码查玩家 | `/api/friends/findRank` | `{"friend":"<好友码>"}` |
| 玩家详情 | `/api/friends/find` | `{"server":1,"friend":"<好友码>"}` |
| 玩家大决战历史 | `/api/friends/eliminate_raid_history` | `{"friend":"<好友码>",...}` |

## 参数要点

**区服枚举**

```
1 国服   2 B服   3 日服   4 综合   5 国际服
6 港澳台 7 韩服  8 亚服   9 北美服
```

**大决战难度**（按国服某赛期三甲 5/5/6 校准）

```
1 Normal  2 Hard  3 VeryHard  4 HardCore  5 INS  6 TM  7 LU  8 LU+
```

**大决战装甲类型**（`armorType`）

```
0 红甲  1 黄甲  2 蓝甲  5 紫甲      其余值显示为「甲N」，不做猜测
```

**助战查询**

- 过滤学生用 `uniqueId`；传 `studentId` 会被静默忽略
- 练度过滤是 **>= 语义**（`level:80` 返回 Lv80~90）
- 可用过滤字段：`starGrade` / `level` / `weaponStarGrade` / `exSkillLevel`
- 结果里的好友码是**字母数字串**（如 `abc1234`），不是 QQ 号

## 错误码

| code | 含义 | 处理 |
|---|---|---|
| `200` | 正常 | —— |
| `4002` | 没带可识别的 token（与未登录同码）；也可能未完成「数据来源备注」 | 检查鉴权头与配置；仍不行到站点补声明 |
| `4003` | 限流 / 额度用尽（公共 token 为全局 5 次/秒共享） | 降频或换自己的 token |
| `4005` | 账号封禁（非绑定 IP 请求的后果） | 停止请求，核对出口 IP 后再试 |
| `4007` | token 无效或已绑定到别的 IP | 确认格式，必要时重新申请 |

## 使用约束

- **不要在别处直连调试 token**：绑定首次请求的出口 IP，调试要用最终运行环境的出口
- 结果自行缓存，避免同一条件反复请求（插件内已有 5 分钟滑动缓存与 0.25s 节流）
- 展示数据必须带来源行：`数据来源：什亭之匣 https://arona.icu`
- 使用前在站点完成「数据来源备注」声明

## 参考

接口形状取自站内前端包与开源项目 [KimigaiiWuyi/BlueArchiveUID](https://github.com/KimigaiiWuyi/BlueArchiveUID)，
并经实际调用验证；字段名以上游实际返回为准。
