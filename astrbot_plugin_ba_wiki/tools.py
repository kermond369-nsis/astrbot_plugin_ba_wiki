"""工具层：5 个 LLM 工具的定义 + 工具返回结果的组装。

docstring 就是模型路由契约（模型判断该不该调哪个工具全靠它），改动前先跑
tests/selfcheck.py —— 它会核对 docstring / 签名与基线逐字一致。

注意：AstrBot 只把 __module__ 等于插件主模块的 handler 绑定到插件实例
（star_manager: ft.handler.__module__ == metadata.module_path），所以 main.py
里把这 5 个函数的 __module__ 对齐到了主模块。本类必须由 BAWikiPlugin 混入
（BAToolsMixin），工具体依赖实例上的 _query / _resolve_student / _name_of。
"""

from __future__ import annotations

import asyncio
import json

from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent

from . import directory, render, skills
from .clients import arona, bilibili
from .sources import schaledb, stats as stats_src


def build_skill_payload(data_dir: str, keyword: str, skill: str = "", level: int | None = None) -> dict:
    """关键词 -> 学生记录 -> 技能数值，组装成工具返回的 dict。

    字段与重构前 ba_data.query 一致（键的插入顺序也一致）：这是喂给模型的 JSON，
    形状变了就等于改了行为。
    """
    bundle = directory.load_all(data_dir)
    students, names = bundle["students"], bundle["names"]
    r = directory.resolve(data_dir, keyword)
    if not r.get("ok"):
        if r.get("kind") == "variant":
            return {
                "ok": False,
                "reason": "没查到该学生：形态词或叫法不认识",
                "suggest": r.get("suggest") or [],
                "hint": "用户给的形态词不认识，把 suggest 念给用户让他选，不要自己猜是哪一个。",
            }
        return {
            "ok": False,
            "reason": "没有查询到此学生，建议检查拼写",
            "suggest": r.get("suggest") or [],
            "hint": "用户可能拼错了学生名。把 suggest（若有）给用户确认；不要凭记忆编造数值。",
        }
    hits = r["matches"]

    top = hits[0]
    sid = top["id"]
    student = students.get(sid) or next((s for s in students.values() if str(s.get("Id")) == sid), {})
    by_lang = names.get(sid, {})
    # 标签要说真话：SchaleDB 的 zh 是「通用中文」，国服译名只有 kivo 有（T4 实测）
    aliases = {}
    for lang, name in by_lang.items():
        if not name:
            continue
        label = "通用中文" if lang == schaledb.PRIMARY_LANG else schaledb.LANG_CN.get(lang, lang)
        aliases[label] = name
    kivo_entry = (bundle["profiles"].get(sid) or {}).get("kivo") or {}
    if kivo_entry.get("cn") and kivo_entry["cn"] != aliases.get("通用中文"):
        aliases["国服"] = kivo_entry["cn"]

    base = {
        "ok": True,
        "name": top.get("display") or by_lang.get(schaledb.PRIMARY_LANG)
                or by_lang.get("en") or student.get("Name"),
        "name_note": "name 字段是国服译名，回答时优先用它",
        "aliases": aliases,
        "matched_as": f"{top['matched_alias']}（{schaledb.LANG_CN.get(top['matched_lang'], top['matched_lang'])}）",
        "id": student.get("Id"),
        "school": student.get("School"),
        "star": student.get("StarGrade"),
        "role": student.get("TacticRole"),
        "other_matches": [h["name"] for h in hits[1:]],
    }

    slot_key = skills.resolve_slot(skill)
    if not slot_key:
        base["skills"] = skills.overview(student)
        base["hint"] = (
            "未指定技能槽位，返回全部技能概览。"
            "可用槽位：ex(EX技能)、ns(普通技能)、ns+(专武强化普通技能)、"
            "ps(被动)、sub(辅助技能)、wp(武器被动)、普通攻击。"
        )
        return base

    slot = (student.get("Skills") or {}).get(slot_key)
    if not isinstance(slot, dict):
        base["ok"] = False
        base["reason"] = f"该角色没有「{skills.SLOT_CN.get(slot_key, slot_key)}」这一槽位"
        base["skills"] = skills.overview(student)
        return base

    base["skill"] = skills.describe_skill(slot_key, slot, [level] if level else None)
    return base


def _parse_levels(text: str, size: int, lo: int, hi: int) -> list[int] | None:
    """把 "10/9/9"、"9"、"0/25/0" 这类参数解析成长度 size 的列表。"""
    if not text:
        return None
    parts = [p for p in str(text).replace("-", "/").split("/") if p.strip() != ""]
    try:
        nums = [max(lo, min(int(p), hi)) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums * size
    return (nums + [nums[-1]] * size)[:size]


def build_stats_payload(data_dir: str, keyword: str, *, level: int = 90, star: int = 5,
                        equip_tier: int = 0, equip_tiers: str = "", unique_weapon: bool = True,
                        weapon_level: int | None = None, ue_tier: int = 0,
                        bond_level: int = 50, potential: str | int = "") -> dict:
    """关键词 -> 学生记录 -> 完整面板（含装备/专武/武器/好感）。

    与 build_skill_payload 一样返回喂给模型的 JSON，形状稳定。
    数值口径来自 SchaleDB 的算法（等级曲线 + 星级系数 + 装备/专武/武器/好感叠加），
    唯一未计入的是「潜在能力」（数据里只有材料表，没有加成数值）。
    """
    bundle = directory.load_all(data_dir)
    students, names = bundle["students"], bundle["names"]
    r = directory.resolve(data_dir, keyword)
    if not r.get("ok"):
        if r.get("kind") == "variant":
            return {
                "ok": False,
                "reason": "没查到该学生：形态词或叫法不认识",
                "suggest": r.get("suggest") or [],
                "hint": "用户给的形态词不认识，把 suggest 念给用户让他选，不要自己猜是哪一个。",
            }
        return {
            "ok": False,
            "reason": "没有查询到此学生，建议检查拼写",
            "suggest": r.get("suggest") or [],
            "hint": "用户可能拼错了学生名。把 suggest（若有）给用户确认；不要凭记忆编造数值。",
        }

    top = r["matches"][0]
    sid = top["id"]
    student = students.get(sid) or next((s for s in students.values() if str(s.get("Id")) == sid), {})
    level = max(1, min(int(level or 90), stats_src.REGION["student_max_level"]))
    star = max(1, min(int(star or 5), 5))

    tiers = _parse_levels(equip_tiers, 3, 0, 10)
    if tiers is None:
        tiers = list(stats_src.REGION["equipment_max_level"])
        if equip_tier:
            tiers = [max(0, min(int(equip_tier), 10))] * 3

    if isinstance(potential, int):
        pot = None if potential < 0 else potential
    else:
        parsed = _parse_levels(potential, 3, 0, stats_src.POTENTIAL_MAX)
        pot = None if parsed is None else {
            "MaxHP": parsed[0], "AttackPower": parsed[1], "HealPower": parsed[2],
        }

    if weapon_level is None:
        weapon_level = stats_src.REGION["weapon_max_level"]
    weapon_level, ue_tier = stats_src.clamp_weapon_level(weapon_level, ue_tier)
    weapon_cap = stats_src.WEAPON_CAP_BY_TIER.get(ue_tier, 0)
    bond_level = max(0, min(int(bond_level), stats_src.REGION["bond_max_level"]))

    table = schaledb.equipment(data_dir)
    totals = stats_src.compute(
        student, table, level=level, star=star, equip_tiers=tiers,
        ue=unique_weapon, weapon_level=weapon_level, bond_level=bond_level,
        potential=pot, students=students,
    )
    profile = stats_src.labels(student)
    by_lang = names.get(sid, {})
    aliases = {}
    for lang, name in by_lang.items():
        if not name:
            continue
        label = "通用中文" if lang == schaledb.PRIMARY_LANG else schaledb.LANG_CN.get(lang, lang)
        aliases[label] = name
    return {
        "ok": True,
        "id": sid,
        "name": directory.display_name(data_dir, sid),
        "aliases": aliases,
        "profile": profile,
        "build": {
            "level": level,
            "star": star,
            "equipment_tiers": tiers,
            "unique_weapon": bool(totals.get("gear")),
            "weapon_level": weapon_level,
            "weapon_cap": weapon_cap,
            "ue_tier": ue_tier,
            "bond_level": totals.get("bond", 0),
            "potential": totals.get("potential", {}),
        },
        "stats": {stats_src.STAT_LABEL[k]: totals[k] for k in stats_src.DISPLAY_STATS},
        "note": "数值含等级/星级/装备/专武/武器/好感/能力解放（潜在能力）；地形适性 S~D 对应 4~0。",
        "attribution": "数据来源：SchaleDB https://schaledb.com",
    }


class BAToolsMixin:
    """5 个 LLM 工具。需要与 BAWikiPlugin 混入同一个实例。"""

    @llm_tool(name="query_ba_stats")
    async def query_ba_stats(
        self,
        event: AstrMessageEvent,
        student: str,
        level: int = 90,
        star: int = 5,
        equip_tier: int = 0,
        equip_tiers: str = "",
        unique_weapon: bool = True,
        weapon_level: int = -1,
        ue_tier: int = 0,
        potential: str = "",
    ) -> str:
        """查询《蔚蓝档案》角色的完整面板数值（生命值 / 攻击力 / 防御力 / 治愈力 / 命中 / 闪避 / 暴击 / 射程等）。

        当用户问「XX 90 级多少血」「XX 的面板」「攻击力多少」「防御多少」「满级多少」时调用。
        与 query_ba_skill 的分工：技能倍率问 query_ba_skill；角色自身面板用本工具。

        数值口径与 SchaleDB 一致：等级曲线 + 星级系数 + 装备 + 专武 + 武器 + 好感，
        不含潜在能力（上游没有加成数值）。

        名称支持：国服简体名、繁中名、英文名、日文名、韩文名、泰文名、角色 ID 与绰号。

        Args:
            student(string): 角色名，任何区服说法都行，如「若藻」「ワカモ」「ツムギ」「10033」。
            level(int): 等级，默认 90（国服上限）。
            star(int): 星级 1~5，默认 5（专武需要 5★ 才有）。
            equip_tier(int): 三个装备槽统一档位 1~10；0 表示按国服上限（10/10/9）。
            equip_tiers(string): 分槽档位，如「10/9/9」（按装备槽顺序），优先级高于 equip_tier。
            weapon_level(int): 专武等级；-1 表示按国服上限（50）。上限由专精阶位决定：
                专1=30、专2=40、专3=50、专4=60。
            ue_tier(int): 专精阶位 0~4（专1~专4）。0 表示由 weapon_level 自动推导，
                超出该阶上限的等级会被夹到上限。
            potential(string): 能力解放等级，三项各自独立，如「0/25/0」=生命0/攻击25/治愈0；
                单个数字表示三项同级；留空表示 90 级时按满级 25、否则 0。
            unique_weapon(bool): 是否计入专武，默认 True；角色未实装专武时自动忽略。

        Returns:
            JSON。stats 是中文名到数值的映射；profile 是攻击类型/装甲/职业/学院/站位/地形适性；
            build 记录本次口径（等级、星级、装备档、专武、武器等级、好感等级）。
            展示时请把口径一并说明，并保留 attribution 的来源行。
        """
        await self._ensure_ready()
        try:
            result = await asyncio.to_thread(
                build_stats_payload, self.data_dir, student,
                level=level, star=star, equip_tier=equip_tier, equip_tiers=equip_tiers,
                unique_weapon=unique_weapon, ue_tier=ue_tier,
                weapon_level=None if weapon_level < 0 else weapon_level, potential=potential,
            )
        except FileNotFoundError:
            return json.dumps({"ok": False, "reason": "本地装备数据缺失且下载失败，请检查能否访问 schaledb.com"},
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "reason": f"查询出错：{exc}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    @llm_tool(name="query_ba_skill")
    async def query_ba_skill(
        self,
        event: AstrMessageEvent,
        student: str,
        skill: str = "",
        level: int = 0,
    ) -> str:
        """查询《蔚蓝档案》(Blue Archive) 角色的技能描述与各等级具体数值。

        当用户询问某个角色的技能、数值、倍率、冷却、专武强化效果时调用。
        数据来自 SchaleDB，比凭记忆回答可靠；**不要自己编数值**。

        **工具分工（重要）**：
        - 具体数值 / 倍率 / 技能描述 → **优先用本工具**。不要改用联网搜索，
          搜索返回的是摘要，经常缺分档数值，反而更容易答错。
        - 「怎么打」「这期作业」「一档怎么上」这类需要配队手法的 → 用 search_ba_guide 搜 B 站视频，
          **不要自己编排配队**。
        - 复刻时间、版本讨论 → 联网搜索。

        名称支持：国服简体名、繁中名、英文名、日文名（片假名/平假名）、韩文名、
        泰文名、越南文名、角色 ID，以及绰号表里的自定义叫法。轻微的错别字也能命中。

        Args:
            student(string): 角色名，任何区服的说法都行，例如「若藻」「Wakamo」「ワカモ」「10033」。
            skill(string): 技能槽位，留空则返回该角色全部技能概览。
                常用对应：ex=EX技能，ns=普通技能(NS)，ns+=专武强化版普通技能，
                ps=被动技能，sub=辅助技能，wp=武器被动(专武)，普通攻击=平A。
            level(int): 只返回某一级（1 起）。0 表示返回全部等级。

        Returns:
            JSON 字符串。`name` 是**国服译名**，回答时优先使用它；`aliases` 里是其他区服叫法，
            当用户用的是日文名/英文名时可以顺带说明对应关系。
            逐级展开的完整描述在 `skill.levels`，原始分档数值在 `skill.parameters`。
            没找到时返回 ok=false 与 suggest（可疑候选），请让用户确认，不要凭空回答。
        """
        result = await self._query(student, skill, level or None)
        return json.dumps(result, ensure_ascii=False)

    @llm_tool(name="search_ba_guide")
    async def search_ba_guide(self, event: AstrMessageEvent, keyword: str) -> str:
        """搜索 B 站上的《蔚蓝档案》攻略 / 作业视频。

        当用户问「XX 大决战怎么打」「这期作业」「一档怎么上」「配队推荐」这类
        需要具体配队和手法的问题时调用。**不要自己编排配队和作业**，
        也不要用联网搜索去猜——直接搜 B 站，把视频标题和链接给用户。

        Args:
            keyword(string): 搜索关键词，带上区服和玩法，例如
                「国服 大决战 大蛇」「日服 总力战 若藻」「国际服 大决战 街区 大蛇」。

        Returns:
            JSON。`videos` 是标题/链接/播放量/日期；`reply_hint` 是要转达给用户的说明
            （作业主观性大，让用户自己挑，不要照抄）。
        """
        res = await asyncio.to_thread(bilibili.search, keyword, 5)
        res["reply_hint"] = (
            "作业主观性很大，受 box、练度、手法影响，不要照着别人的队硬套。"
            "把 2~3 个视频的标题和链接给用户，让用户自己挑，并说明这点。"
        )
        return json.dumps(res, ensure_ascii=False)

    @llm_tool(name="query_ba_raid_team")
    async def query_ba_raid_team(
        self,
        event: AstrMessageEvent,
        server: str = "国服",
        season: int = 0,
        top: int = 3,
        tier: int = 1,
    ) -> str:
        """查询《蔚蓝档案》大决战榜单前列玩家的实际配队（用了哪些角色）。

        当用户问「XX 大决战一档怎么打」「第一名用的什么队」「这期作业」时调用。
        返回的是真实榜单数据里各期第一名的角色阵容，不是编的。

        注意：目前只能拿到「各期第 1 名」和「各期第 20001 名」两个固定点位，
        拿不到第 2~5 名。如果用户要「前几名」，说明只有榜首数据可用。

        **区服覆盖**：大决战榜单只有**国服**有数据。日服 / 全球 / 港澳台等区服
        返回空数据，遇到这类区服的问法要直接说明「日服大决战数据查不到」，
        不要拿国服榜单凑答案。

        Args:
            server(string): 区服，可选 国服 / B服 / 日服 / 全球 / 港澳台 / 韩服 / 亚服 / 北美服。
            season(int): 大决战期数。0 表示自动取当前进行中（或最近一期）。
            top(int): 取前几名玩家，默认 3，建议不超过 5。
            tier(int): 档位。1=一档，20001=二档，120001=三档。

        Returns:
            JSON。`players[].teams` 按甲分组，每组的 characters 是角色 ID/星级/是否借人；
            另外附 boss_info（各甲名称、护甲类型、难度上限）。展示时必须带上 attribution 里的来源。
        """
        name_map = {v: k for k, v in arona.SERVER_NAME.items()}
        sid = name_map.get(server.strip(), 1)
        result = await self._raid_team(sid, season or None, max(1, min(top, 10)), tier)
        if result.get("ok"):
            result["rendered"] = render.raid_teams(result, self._name_of)
        return json.dumps(result, ensure_ascii=False)

    @llm_tool(name="query_ba_player")
    async def query_ba_player(
        self,
        event: AstrMessageEvent,
        friend_code: str = "",
        server: str = "国服",
    ) -> str:
        """按好友码查询玩家在《蔚蓝档案》的总力战/大决战排名信息。

        **重要：只支持好友码（纯数字好友 ID），不支持昵称查询。**

        当用户说「查一下『星落城心』的排名」这类用昵称的问法时：
        不要猜测、不要编造，也不要直接调用本工具。
        先反问用户：「能给我他的好友码吗？这个查询只认好友码，昵称查不到。」
        拿到好友码后再调用。

        Args:
            friend_code(string): 好友码，纯数字（一般 8~9 位）。为空时本工具会提示缺少参数。
            server(string): 区服，可选 国服 / B服 / 日服 / 全球 / 港澳台 / 韩服 / 亚服 / 北美服。

        Returns:
            JSON。`data` 是原始返回；`attribution` 是必须一起给出的数据来源。
            若返回好友码错误，说明用户给的码不对，让对方再确认一次。
        """
        if not str(friend_code or "").strip():
            return json.dumps({
                "ok": False,
                "reason": "没有提供好友码",
                "ask_user": "能给我他的好友码吗？这个查询只认好友码（纯数字），昵称查不到。",
            }, ensure_ascii=False)
        name_map = {v: k for k, v in arona.SERVER_NAME.items()}
        sid = name_map.get(server.strip(), 1)
        try:
            res = await asyncio.to_thread(arona.player_rank, friend_code, sid, self.data_dir)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "好友码" in msg or "3025" in msg:
                msg = "好友码不对，请让对方再确认一次（纯数字的好友 ID）。"
            return json.dumps({"ok": False, "reason": msg}, ensure_ascii=False)
        return json.dumps(res, ensure_ascii=False)

    @llm_tool(name="query_ba_assist")
    async def query_ba_assist(
        self,
        event: AstrMessageEvent,
        student: str,
        server: str = "国服",
        limit: int = 5,
        min_star: int = 0,
        min_level: int = 0,
        min_weapon_star: int = 0,
        min_ex_level: int = 0,
    ) -> str:
        """查「谁把这个学生挂在助战位」，返回好友码，可按练度下限筛选。

        当用户问「谁挂了若藻可以借」「借个 XX」「有没有大佬挂 XX 助战」时调用。
        用户若给了练度要求（如「5星 Lv90 专2 EX5」），把对应数字填进参数，
        **这些是「至少」语义**，不是精确匹配。

        返回的好友码是**字母数字串**（如 abcd123），不是纯数字 QQ 号。

        Args:
            student(string): 学生名，任意区服叫法/绰号/形态都行（「泳装星野」也能认）。
            server(string): 区服，国服 / B服 / 日服 / 国际服(全球) / 港澳台 / 韩服 / 亚服 / 北美服。
            limit(int): 返回几玩家，默认 5，最多 10。
            min_star(int): 最低星级，0 表示不限。
            min_level(int): 最低等级，0 表示不限。
            min_weapon_star(int): 最低专武星级，0 表示不限。
            min_ex_level(int): 最低 EX 技能等级，0 表示不限。

        Returns:
            JSON。players[] 含 nickname、friend_code 与该学生的星级/专武/技能；
            filters 回显生效的筛选条件；展示时带上 attribution 来源。
        """
        await self._ensure_ready()
        stu, err = await self._resolve_student(student)
        if err:
            return json.dumps({"ok": False, "reason": err}, ensure_ascii=False)

        sid = int(stu["id"])
        name = stu["name"]
        _rest, srv_id = arona.extract_server(server or "")
        srv = srv_id or 1
        n = max(1, min(int(limit or 5), 10))
        try:
            res = await asyncio.to_thread(
                arona.assist_players, srv, sid, 1, n,
                min_star or None, min_level or None,
                min_weapon_star or None, min_ex_level or None,
                self.data_dir,
            )
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False)
        res["student_name"] = name
        res["rendered"] = render.assist_page(res, arona.ASSIST_PAGE_SIZE)
        return json.dumps(res, ensure_ascii=False)
