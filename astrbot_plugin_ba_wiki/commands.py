"""指令分发层：/ba 的 借 / 翻页 / 大决战 / 攻略 / 技能 五个分支。

入口只有 handle_ba(plugin, event)。它复用插件实例上的 _resolve_student /
_assist_page / _state_set / _state_get / _raid_team / _query / _name_of，
自己不持有状态，也不保存任何输出文案（文案全在 render.py）。
"""

from __future__ import annotations

import asyncio
import re

from astrbot.api.event import AstrMessageEvent

from . import render
from .clients import arona, bilibili


def parse_assist_query(text: str) -> tuple[str, dict]:
    """从自由文本里拆出练度下限与剩余的学生名。

    支持（任意顺序、可任意组合）：
        5星 / 5★    -> min_star
        Lv90 / 90级 -> min_level
        专2 / 专武2  -> min_weapon_star
        EX5         -> min_ex_level

    这些都是「至少」语义，由接口原生支持（不是拿回来自行过滤）。
    """
    t = text or ""
    out: dict = {}

    m = re.search(r"(\d)\s*[星★]", t)
    if m:
        out["min_star"] = int(m.group(1))
        t = t.replace(m.group(0), " ")

    m = re.search(r"[Ll][Vv]\.?\s*(\d{1,3})", t)
    if m:
        out["min_level"] = int(m.group(1))
        t = t.replace(m.group(0), " ")
    else:
        m = re.search(r"(\d{1,3})\s*级", t)
        if m:
            out["min_level"] = int(m.group(1))
            t = t.replace(m.group(0), " ")

    m = re.search(r"专(?:武)?\s*(\d)", t)
    if m:
        out["min_weapon_star"] = int(m.group(1))
        t = t.replace(m.group(0), " ")

    m = re.search(r"[Ee][Xx]\s*(\d)", t)
    if m:
        out["min_ex_level"] = int(m.group(1))
        t = t.replace(m.group(0), " ")

    return " ".join(t.split()), out


def parse_stats_query(text: str) -> tuple[str, dict]:
    """从「面板」参数里拆出口径：Lv90 / 5星 / T10 / 能力解放25 / 无专武。

    未给出的项不放进 opts，由插件默认口径决定（Lv90、5★、国服上限装备、专武开、能力解放 25）。
    """
    t = text or ""
    out: dict = {}

    m = re.search(r"[Ll][Vv]\.?\s*(\d{1,3})", t)
    if not m:
        m = re.search(r"(\d{1,3})\s*级", t)
    if m:
        out["level"] = max(1, min(int(m.group(1)), 90))
        t = t.replace(m.group(0), " ")

    m = re.search(r"(\d)\s*[星★]", t)
    if m:
        out["star"] = max(1, min(int(m.group(1)), 5))
        t = t.replace(m.group(0), " ")

    m = re.search(r"\b[Tt]\s*(\d{1,2})\b", t)
    if m:
        out["equip_tier"] = max(1, min(int(m.group(1)), 10))
        t = t.replace(m.group(0), " ")

    m = re.search(r"能力解放\s*([\d/]{1,12})", t)
    if m:
        out["potential"] = m.group(1)
        t = t.replace(m.group(0), " ")

    m = re.search(r"装备\s*([\d/]{1,12})", t)
    if m:
        out["equip_tiers"] = m.group(1)
        t = t.replace(m.group(0), " ")

    m = re.search(r"好感\s*(\d{1,2})", t)
    if m:
        out["bond_level"] = max(0, min(int(m.group(1)), 50))
        t = t.replace(m.group(0), " ")

    m = re.search(r"武器\s*(\d{1,2})", t)
    if m:
        out["weapon_level"] = max(0, min(int(m.group(1)), 90))
        t = t.replace(m.group(0), " ")

    # 专武星级/技能等级只影响技能，不影响面板，接受但忽略
    for pat in (r"专\s*\d", r"技能全满", r"全满"):
        t = re.sub(pat, " ", t)

    if "无专武" in t or "不带专武" in t:
        out["unique_weapon"] = False
        t = t.replace("无专武", " ").replace("不带专武", " ")

    return " ".join(t.split()), out


async def handle_ba(plugin, event: AstrMessageEvent):
    """把一条 /ba 指令翻译成要回给用户的消息（async generator）。"""
    text = (event.message_str or "").strip()
    if text.lower().startswith("ba"):
        text = text[2:].strip()
    parts = text.split()
    if not parts:
        yield event.plain_result(render.main_help())
        return

    head = parts[0]

    # 字体：检查/修复文本转图片用的 CJK 字体
    if head in ("字体", "font", "字体修复"):
        from .sources import font as font_src

        want_fix = any(p in ("修复", "下载", "fix", "download", "install") for p in parts[1:]) or head == "字体修复"
        try:
            res = await asyncio.to_thread(font_src.ensure, getattr(plugin, "font_dir", plugin.data_dir), want_fix, None)
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"字体检查失败：{exc}")
            return
        yield event.plain_result(render.font_report(res))
        return

    # 借学生模式：查谁把这个学生挂助战，支持练度下限 + 分页 + 区服
    if head in ("借", "助战", "assist"):
        rest, srv = arona.extract_server(" ".join(parts[1:]))
        kw, filt = parse_assist_query(rest)
        if not kw:
            yield event.plain_result(render.assist_usage())
            return
        stu, err = await plugin._resolve_student(kw)
        if err:
            yield event.plain_result(err)
            return
        st = {
            "sid": int(stu["id"]), "name": stu["name"], "server": srv or 1,
            "filters": filt, "page": 1, "total_pages": 1,
        }
        try:
            res, new_st = await plugin._assist_page(st, 1)
            plugin._state_set(event.unified_msg_origin, new_st)
            yield event.plain_result(render.assist_page(res, arona.ASSIST_PAGE_SIZE))
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"查询失败：{exc}")
        return

    # 面板：角色自身数值（等级/星级/装备/专武/能力解放）
    if head in ("面板", "属性", "数值", "stats", "stat"):
        kw, opts = parse_stats_query(" ".join(parts[1:]))
        if not kw:
            yield event.plain_result(render.stats_usage())
            return
        res = await plugin._stats(kw, **opts)
        if not res.get("ok"):
            yield event.plain_result(render.skill_not_found(res.get("reason"), res.get("suggest")))
            return
        yield event.plain_result(render.stats_text(res))
        return

    # 翻页
    if head in ("下页", "下一页", "next", "上页", "上一页", "prev"):
        umo = event.unified_msg_origin
        st = plugin._state_get(umo)
        if not st:
            yield event.plain_result(render.no_page_state())
            return
        delta = -1 if head in ("上页", "上一页", "prev") else 1
        cur = int(st.get("page") or 1)
        tp = int(st.get("total_pages") or 1)
        target = cur + delta
        if target < 1 or target > tp:
            yield event.plain_result(render.page_edge(delta, tp))
            return
        try:
            res, new_st = await plugin._assist_page(st, target)
            plugin._state_set(umo, new_st)
            yield event.plain_result(render.assist_page(res, arona.ASSIST_PAGE_SIZE))
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"翻页失败：{exc}")
        return

    # 大决战榜单模式：真实榜单前几名的配队
    if head in ("大决战", "榜单", "raid"):
        server_name = "国服"
        top_n = 3
        for p in parts[1:]:
            if p in arona.SERVER_NAME.values():
                server_name = p
            elif p.isdigit():
                top_n = max(1, min(int(p), 5))
        sid = {v: k for k, v in arona.SERVER_NAME.items()}.get(server_name, 1)
        res = await plugin._raid_team(sid, None, top_n, 1)
        if not res.get("ok"):
            yield event.plain_result(render.raid_failed(res.get("reason")))
            return
        yield event.plain_result(render.raid_teams(res, plugin._name_of))
        return

    # 攻略模式：只给 B 站视频链接，不自己编排配队
    if head in ("攻略", "作业", "guide"):
        kw = " ".join(parts[1:]).strip()
        if not kw:
            yield event.plain_result(render.guide_usage())
            return
        res = await asyncio.to_thread(bilibili.search, kw, 4)
        if not res.get("ok"):
            yield event.plain_result(render.search_failed(res.get("reason")))
            return
        yield event.plain_result(render.guide_text(kw, res.get("videos", [])))
        return

    keyword = parts[0]
    skill = parts[1] if len(parts) > 1 and not parts[1].isdigit() else ""
    level = next((int(p) for p in parts[1:] if p.isdigit()), None)

    result = await plugin._query(keyword, skill, level)
    if not result.get("ok"):
        yield event.plain_result(
            render.skill_not_found(result.get("reason", "未知原因"), result.get("suggest"))
        )
        return

    yield event.plain_result(render.skill_text(result))
