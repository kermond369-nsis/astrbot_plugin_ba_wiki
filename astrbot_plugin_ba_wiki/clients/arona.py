"""arona.icu（什亭之匣）大决战榜单查询。

鉴权两种模式（默认直连，转发是历史方案）：

1) 直连（当前线上形态，token 与首次请求的 IP 绑定）
   `Authorization: ba-token <token>`，token 格式必须是 `<QQ号>:<密钥>`。
   注意：token 绑定首次请求的 IP 且不可更改；同一 token 从非绑定 IP 反复请求
   会被封 24h（`4005`）。AstrBot 换了出口 IP 后要重新申请 token。

2) 经 HTTPS 转发（**已弃用**，仅在家宽出口 IP 不稳定、需要回滚时用）
   在插件数据目录放 `arona_proxy.json`：
       {"url": "https://<转发机IP>:8443", "key": "<共享密钥>"}
   转发机用自己（已绑定的）IP 去调 arona，客户端不需要持有 token。
   证书为自签，需在客户端把该证书装进系统信任库（update-ca-certificates）。
   转移时机与回滚步骤见 docs/MIGRATE-TO-LOCAL.md。

token 读取顺序（仅直连模式）：data 目录 `arona_token.txt` → 环境变量 ARONA_TOKEN → 测试 token。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

BASE = "https://api.arona.icu"
TEST_TOKEN = "uuz:uuz"          # 公告提供的开发测试 token，限 5 req/s
MIN_INTERVAL = 0.25             # 本地节流：不超过 4 请求/秒
PROXY_FILE = "arona_proxy.json"

ASSIST_PAGE_SIZE = 10          # 助战分页每页人数（请求参数 size 的默认值）

SERVER_NAME = {
    1: "国服", 2: "B服", 3: "日服", 4: "综合", 5: "国际服",
    6: "港澳台", 7: "韩服", 8: "亚服", 9: "北美服",
}

# arona 自己的难度枚举（实测校准）：国服 season 21 三甲为 5/5/6，
# 正好对应大决战规则「一个甲开 TM，另外两个甲开 INS」，故 5=INS、6=TM。
DIFFICULTY_LABEL = {
    1: "Normal", 2: "Hard", 3: "VeryHard", 4: "HardCore",
    5: "INS", 6: "TM", 7: "LU", 8: "LU+",
}

_lock = threading.Lock()
_last_call = 0.0
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300

# 助战查询结果缓存（跨会话共享）：同一条件在 5 分钟内被再次查询时直接复用，
# 且每次命中都把过期时间往后推 5 分钟（滑动过期），避免热门条件反复打上游。
_assist_cache: dict[str, tuple[float, dict]] = {}
_ASSIST_TTL = 300


def _assist_key(server: int, student_id, page: int, size: int,
                min_star, min_level, min_weapon_star, min_ex_level) -> str:
    return json.dumps(
        [int(server), student_id, int(page), int(size),
         min_star, min_level, min_weapon_star, min_ex_level],
        ensure_ascii=False,
    )


def _token(data_dir: str | None = None) -> tuple[str, bool]:
    """返回 (token, 是否为测试 token)。"""
    if data_dir:
        p = os.path.join(data_dir, "arona_token.txt")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    v = f.read().strip()
                if v:
                    return v, False
            except Exception:  # noqa: BLE001
                pass
    v = (os.environ.get("ARONA_TOKEN") or "").strip()
    if v:
        return v, False
    return TEST_TOKEN, True


def _proxy_cfg(data_dir: str | None) -> tuple[str, str] | None:
    """读取 HTTPS 转发配置，存在则走转发、不持有 token。"""
    if not data_dir:
        return None
    p = os.path.join(data_dir, PROXY_FILE)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        url = str(cfg.get("url") or "").rstrip("/")
        if url:
            return url, str(cfg.get("key") or "")
    except Exception:  # noqa: BLE001
        return None
    return None


def _post(path: str, body: dict, data_dir: str | None = None) -> dict:
    global _last_call
    key = path + json.dumps(body, sort_keys=True, ensure_ascii=False)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        _cache[key] = (time.time(), hit[1])  # 命中即续期（滑动过期）
        return hit[1]  # type: ignore[return-value]

    payload = json.dumps(body).encode()
    proxy = _proxy_cfg(data_dir)
    if proxy:
        url = proxy[0] + path
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "astrbot-ba-wiki/0.6",
            "X-Proxy-Key": proxy[1],
        }
    else:
        token, _is_test = _token(data_dir)
        url = BASE + path
        headers = {
            "Authorization": f"ba-token {token}",
            "Content-Type": "application/json",
            "User-Agent": "astrbot-ba-wiki/0.6",
        }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with _lock:
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = json.loads(resp.read().decode("utf-8", "ignore"))
    finally:
        _last_call = time.time()

    if raw.get("code") != 200:
        msg = raw.get("message") or f"code={raw.get('code')}"
        if raw.get("code") == 4002:
            msg += "（需在 arona.icu 完成「数据来源备注」声明）"
        if raw.get("code") == 4007:
            msg += "（token 无效，或已绑定到别的 IP）"
        raise RuntimeError(msg)

    _cache[key] = (time.time(), raw)
    return raw


# ------------------------------------------------------------------ 查询
def eliminate_seasons(server: int = 1, data_dir: str | None = None) -> list[dict]:
    raw = _post("/api/season/eliminate_raid_season_list", {"server": int(server)}, data_dir)
    return raw.get("data") or []


def current_season(server: int = 1, data_dir: str | None = None) -> dict | None:
    seasons = eliminate_seasons(server, data_dir)
    if not seasons:
        return None
    now = time.strftime("%Y-%m-%d %H:%M")
    for s in reversed(seasons):
        if str(s.get("startTime", "")) <= now <= str(s.get("endTime", "9999")):
            return s
    return seasons[-1]


# armorType → 玩家习惯叫法
#   0 / 2 / 5：由用户在真实榜单队伍上人工确认（红 / 蓝 / 紫）
#   1        ：由数据反推 —— 国服 23 期大决战只出现过 0/1/2/5 四个值，
#              大决战三色恰好是 红/黄/蓝/紫，扣掉已确认的三个，1 只能是黄甲。
#              交叉验证：type=0 的队伍输出为 Explosion、type=2 为 Mystic、type=5 为 Sonic。
#   其余值   ：回落成「甲N」，宁可不写也不写错。
ARMOR_LABEL = {
    0: "红甲",
    1: "黄甲",
    2: "蓝甲",
    5: "紫甲",
}


def _armor_name(armor_type) -> str:
    return ARMOR_LABEL.get(armor_type, f"甲{armor_type}")


def assist_players(
    server: int = 1,
    student_id: int | None = None,
    page: int = 1,
    size: int = 10,
    min_star: int | None = None,
    min_level: int | None = None,
    min_weapon_star: int | None = None,
    min_ex_level: int | None = None,
    data_dir: str | None = None,
) -> dict:
    """查「谁把这个学生挂在助战位」，返回好友码，可按练度下限筛选。

    实测要点（2026-10）：
    - 端点 `/api/friends/assist_query`，**必须带 server**
    - 过滤学生用 `uniqueId`（`studentId` 会被静默忽略）
    - 练度过滤参数是 **>= 语义**（`level:80` 会返回 Lv80~90 的玩家）：
        starGrade / level / weaponStarGrade / exSkillLevel
    - 好友码是**字母数字串**（如 `abcd123`），不是纯数字 QQ 号
    """
    body: dict = {"server": int(server), "page": int(page), "size": int(size)}
    if student_id is not None:
        body["uniqueId"] = int(student_id)
    if min_star:
        body["starGrade"] = int(min_star)
    if min_level:
        body["level"] = int(min_level)
    if min_weapon_star:
        body["weaponStarGrade"] = int(min_weapon_star)
    if min_ex_level:
        body["exSkillLevel"] = int(min_ex_level)

    # 结果级缓存：同一条件被多次查询（多人/多群）时直接复用，并滑续 5 分钟
    ck = _assist_key(server, student_id, page, size,
                     min_star, min_level, min_weapon_star, min_ex_level)
    hit = _assist_cache.get(ck)
    if hit and time.time() - hit[0] < _ASSIST_TTL:
        _assist_cache[ck] = (time.time(), hit[1])      # 续期
        cached = json.loads(json.dumps(hit[1], ensure_ascii=False))
        cached["cached"] = True
        return cached

    raw = _post("/api/friends/assist_query", body, data_dir)
    data = raw.get("data") or {}
    records = data.get("records") or []

    players = []
    for r in records:
        mine = None
        for a in r.get("assistInfoList") or []:
            if student_id is not None and a.get("uniqueId") == int(student_id):
                mine = a
                break
        players.append({
            "nickname": r.get("nickname"),
            "friend_code": r.get("friendCode"),
            "player_level": r.get("level"),
            "comment": (r.get("comment") or "")[:40],
            "server": SERVER_NAME.get(int(server), str(server)),
            "student": None if not mine else {
                "id": mine.get("uniqueId"),
                "star": mine.get("starGrade"),
                "level": mine.get("level"),
                "weapon_star": mine.get("weaponStarGrade"),
                "weapon_level": mine.get("weaponLevel"),
                "ex_skill": mine.get("exSkillLevel"),
                "passive": mine.get("passiveSkillLevel"),
                "extra_passive": mine.get("extraPassiveSkillLevel"),
                "public_skill": mine.get("publicSkillLevel"),
            },
        })

    result = {
        "ok": True,
        "server": SERVER_NAME.get(int(server), str(server)),
        "student_id": student_id,
        "filters": {
            k: v for k, v in {
                "min_star": min_star,
                "min_level": min_level,
                "min_weapon_star": min_weapon_star,
                "min_ex_level": min_ex_level,
            }.items() if v
        },
        "total_players": data.get("totalData"),
        "total_pages": data.get("totalPages"),
        "page": data.get("page"),
        "size": data.get("size"),
        "players": players,
        "attribution": "数据来源：什亭之匣 https://arona.icu",
        "cached": False,
    }
    _assist_cache[ck] = (time.time(), json.loads(json.dumps(result, ensure_ascii=False)))
    return result


def player_rank(friend_code: str, server: int = 1, data_dir: str | None = None) -> dict:
    """按好友码查玩家。注意：**不支持昵称**，只认好友码。"""
    code = str(friend_code or "").strip()
    if not code:
        return {"ok": False, "reason": "缺少好友码"}
    raw = _post("/api/friends/findRank", {"server": int(server), "friend": code}, data_dir)
    return {
        "ok": True,
        "server": SERVER_NAME.get(int(server), str(server)),
        "friend_code": code,
        "data": raw.get("data"),
        "attribution": "数据来源：什亭之匣 https://arona.icu",
    }


def _extract_teams(record: dict) -> dict[int, dict]:
    """从一条玩家记录里抽出每个甲最优一次尝试的配队（前排 4 + 后排支援 2）。"""
    out: dict[int, dict] = {}
    for group in record.get("tryNumberInfos") or []:
        gi = group.get("bossGroupIndex")
        best = None
        for attempt in group.get("tryNumberInfos") or []:
            mains = attempt.get("mainCharacters") or []
            if not mains:
                continue
            score = group.get("bestRankingPoint") or 0
            if best is None or score > best[0]:
                best = (score, mains, attempt.get("supportCharacters") or [], attempt.get("tryNumber"))
        if best:
            def pack(chars):
                return [
                    {
                        "id": c.get("uniqueId"),
                        "star": c.get("starGrade"),
                        "level": c.get("level"),
                        "weapon_star": c.get("weaponStarGrade"),
                        "borrowed": bool(c.get("isAssist")),
                        "slot": c.get("slotIndex"),
                    }
                    for c in chars
                ]
            out[gi] = {
                "best_point": best[0],
                "try": best[3],
                "characters": pack(best[1]),
                "support": pack(best[2]),
            }
    return out


def rank_players(
    server: int = 1,
    season: int | None = None,
    tier: int = 1,
    top: int = 3,
    data_dir: str | None = None,
) -> dict:
    """取某一档（1=一档，20001=二档…）前 top 名玩家及其各甲配队。"""
    if season is None:
        cur = current_season(server, data_dir)
        if not cur:
            raise RuntimeError("拿不到大决战赛期")
        season = int(cur["season"])

    path = "/api/eliminate_raid_rank/list_1" if tier == 1 else f"/api/eliminate_raid_rank/list_{tier}"
    raw = _post(path, {"server": int(server), "season": int(season)}, data_dir)
    data = raw.get("data") or {}

    # 实测：list_N 返回的 data 以「期数」为 key，值是那一期第 N 名的记录
    if isinstance(data, dict):
        rec = data.get(str(season))
        records = [rec] if isinstance(rec, dict) else [v for v in data.values() if isinstance(v, dict)]
    else:
        records = list(data)
    records = [r for r in records if r.get("rank")]
    records.sort(key=lambda r: r.get("rank", 10**9))

    seasons = eliminate_seasons(server, data_dir)
    meta = next((s for s in seasons if int(s.get("season", -999)) == season), None)
    boss_info = []
    if meta:
        for b in meta.get("bossInfo") or []:
            boss_info.append({
                "group": b.get("groupIndex"),
                "name": b.get("name"),
                "armor": _armor_name(b.get("armorType")),
                "max_difficulty": b.get("maxDifficulty"),
                "max_difficulty_label": DIFFICULTY_LABEL.get(b.get("maxDifficulty"), str(b.get("maxDifficulty"))),
                "map": (b.get("map") or {}).get("value"),
            })

    players = []
    for r in records[:top]:
        teams = _extract_teams(r)
        players.append({
            "rank": r.get("rank"),
            "nickname": r.get("nickname"),
            "score": r.get("bestRankingPoint"),
            "level": r.get("level"),
            "teams": teams,
        })

    return {
        "ok": True,
        "server": SERVER_NAME.get(int(server), str(server)),
        "season": season,
        "season_range": f"{meta.get('startTime')} ~ {meta.get('endTime')}" if meta else None,
        "season_name": meta.get("seasonName") if meta else None,
        "boss_info": boss_info,
        "players": players,
        "attribution": "数据来源：什亭之匣 https://arona.icu",
    }


# ------------------------------------------------------------------ 区服解析
# 区服关键词 -> arona server id（实测 1/2/3/5/6/7/8/9 都有数据，4=综合 为空）
SERVER_KEYWORDS = {
    "国服": 1, "官服": 1, "b服": 2, "bilibili服": 2,
    "日服": 3, "日文服": 3,
    "全球": 5, "国际服": 5, "国际": 5, "global": 5,
    "港澳台": 6, "繁中": 6, "台服": 6, "tw": 6,
    "韩服": 7, "kr": 7,
    "亚服": 8, "亚洲服": 8, "asia": 8,
    "北美服": 9, "北美": 9, "na": 9,
}


def extract_server(text: str) -> tuple[str, int | None]:
    """从文本里摘出区服关键词，返回 (剩余文本, server_id)。"""
    t = text or ""
    low = t.lower()
    for kw in sorted(SERVER_KEYWORDS, key=len, reverse=True):
        k = kw.lower()
        if k in low:
            idx = low.index(k)
            t = (t[:idx] + " " + t[idx + len(kw):]).strip()
            return " ".join(t.split()), SERVER_KEYWORDS[kw]
    return " ".join(t.split()), None
