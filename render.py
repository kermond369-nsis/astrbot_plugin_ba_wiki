"""渲染层：所有给人看的文本集中在这里（含错误与候选提示）。

规则：
  - 数据类输出统一带来源行「数据来源：什亭之匣 https://arona.icu」
  - 助战分页固定格式「第 X/Y 页 · 共 N 人 · 每页 10」
  - 措辞即行为（tests/golden.md 逐条核对），改动这里等于改用户看到的结果

只做字符串拼装，不发请求、不读磁盘；需要角色名时由调用方传 name_of(id)。
"""

from __future__ import annotations

from typing import Callable

ATTRIBUTION = "数据来源：什亭之匣 https://arona.icu"
ATTRIBUTION_SCHALE = "数据来源：SchaleDB https://schaledb.com"


# ------------------------------------------------------------------ 用法与提示
def main_help() -> str:
    return (
        "用法：/ba <角色> [槽位] [等级]\n"
        "例：/ba 若藻        查看全部技能\n"
        "     /ba 若藻 ns     普通技能各等级数值\n"
        "     /ba ワカモ ex   用日文名也行\n"
        "     /ba 若藻 ex 3   只看 EX 技能 3 级\n"
        "     /ba 面板 若藻     角色面板（生命/攻击/防御…）\n"
        "     /ba 测评 若藻     测评卡（强度/就业/抽取建议）\n"
        "     /ba 攻略 国服 大决战 大蛇   搜 B 站作业视频"
    )


def stats_usage() -> str:
    return (
        "用法：/ba 面板 <学生> [Lv90] [5星] [专4] [武器60] [装备10/10/9] [能力解放25/25/25]\n"
        "例：/ba 面板 爱丽丝（临战）\n"
        "默认就是满配：Lv90 · 5★ · 专4/武器60 · T10/T10/T10 · 爱用品 · 好感吃满（含全部皮肤） · 能力解放25 · 技能10\n"
        "技能加成按 技能N 取对应等级（1~10，默认满级），例：/ba 面板 爱丽丝（临战） 技能1"
        "\n不按区服是否实装过滤；想改口径直接写参数，例：/ba 面板 ツムギ 装备10/9/9 好感50"
    )


def _potential_text(value) -> str:
    """能力解放：三项各自独立，全同则只写一个数字。"""
    if isinstance(value, dict):
        nums = [int(value.get(k, 0) or 0) for k in ("MaxHP", "AttackPower", "HealPower")]
        if len(set(nums)) == 1:
            return str(nums[0])
        return "生命%d/攻击%d/治愈%d" % tuple(nums)
    try:
        return str(int(value or 0))
    except (TypeError, ValueError):
        return "0"



def stats_text(payload: dict) -> str:
    """面板输出：口径行 + 类型行 + 数值表 + 来源行。"""
    build = payload.get("build") or {}
    profile = payload.get("profile") or {}
    stats = payload.get("stats") or {}
    tiers = build.get("equipment_tiers") or []
    tier_txt = "/".join(f"T{t}" for t in tiers) if tiers else "-"
    weapon = int(build.get("weapon_level", 0) or 0)
    ue_tier = int(build.get("ue_tier", 0) or 0)
    bits = [
        f"Lv{build.get('level', '-')}",
        f"{build.get('star', '-')}★",
        (f"专{ue_tier}/武器{weapon}" if ue_tier else f"武器{weapon}"),
        tier_txt,
        f"好感{int(build.get('bond_total', build.get('bond_level', 0)) or 0)}",
        "爱用品" if build.get("favorite_item") else "无爱用品",
        "能力解放" + _potential_text(build.get("potential")),
        f"技能{build.get('skill_level', 10)}",
    ]
    terrain = profile.get("terrain") or {}
    type_line = (
        f"攻击类型 {profile.get('bullet', '-')}   装甲 {profile.get('armor', '-')}"
        f"   职业 {profile.get('role', '-')}"
    )
    type_line2 = (
        f"学院 {profile.get('school', '-')}   站位 {profile.get('position', '-')}"
        f"   地形 市区{terrain.get('Street', '-')}/室外{terrain.get('Outdoor', '-')}/室内{terrain.get('Indoor', '-')}"
    )
    from .sources.stats import FULL_STATS

    full = payload.get("stats_full_text") or {}
    derived = payload.get("derived") or {}
    FULL_STAT_ROWS = [(label, full.get(label, "-")) for _k, label, _d, _p in FULL_STATS]
    pairs = []
    for i in range(0, len(FULL_STAT_ROWS), 2):
        left = FULL_STAT_ROWS[i]
        right = FULL_STAT_ROWS[i + 1] if i + 1 < len(FULL_STAT_ROWS) else None
        pairs.append((left, right))

    def cell(row) -> str:
        if not row:
            return ""
        label, text = row
        width = 10 if len(label) <= 5 else 12
        return f"{label:<{width}}{text}"

    lines = []
    for left, right in pairs:
        extra = {"防御力": derived.get("防御伤害减免"), "稳定值": derived.get("最低伤害")}
        left_label, left_value = left
        if extra.get(left_label):
            left_value = f"{left_value} ({extra[left_label]})"
        row_l = (left_label, left_value)
        row_r = right
        if row_r and extra.get(row_r[0]):
            row_r = (row_r[0], f"{row_r[1]} ({extra[row_r[0]]})")
        lines.append((cell(row_l) + "    " + cell(row_r)).rstrip())

    support = payload.get("support_bonus") or {}
    if support:
        lines.append("")
        lines.append(
            "作为支援时给前排："
            + "  ".join(f"{k}+{v:,}" for k, v in support.items())
        )

    return (
        f"「{payload.get('name', '?')}」面板\n"
        f"{' · '.join(bits)}\n"
        f"{type_line}\n{type_line2}\n\n"
        + "\n".join(lines)
        + f"\n\n{ATTRIBUTION_SCHALE}"
    )


def assist_usage() -> str:
    return (
        "用法：/ba 借 <学生> [区服] [5星] [Lv90] [专2] [EX5]\n"
        "例：/ba 借 若藻\n"
        "    /ba 借 泳装星野 国际服 5星 Lv90 专3 EX5\n"
        "区服：国服 / B服 / 日服 / 国际服 / 港澳台 / 韩服 / 亚服 / 北美服\n"
        "翻页：/ba 下页  /  /ba 上页"
    )


def guide_usage() -> str:
    return "用法：/ba 攻略 <关键词>，例：/ba 攻略 国服 大决战 大蛇"


def no_page_state() -> str:
    return "没有可翻页的查询。先发 /ba 借 <学生> [条件]"


def page_edge(direction: int, total_pages: int) -> str:
    """direction<0 越下界，>0 越上界。"""
    if direction < 0:
        return f"已经是第一页了（共 {total_pages} 页）"
    return f"已经是最后一页了（共 {total_pages} 页）"


def raid_failed(reason) -> str:
    return f"查询失败：{reason}"


def search_failed(reason) -> str:
    return f"搜索失败：{reason}"


def resolve_failed(kind: str | None, suggest: list[str] | None) -> str:
    """名字没解析出来时给用户的话。

    - 形态词不认识（kind=variant）-> 「你是否想找：...」
    - 连基名都对不上（typ / typo）-> 「没有查询到此学生，建议检查拼写」
    """
    sug = suggest or []
    if kind == "variant":
        return "你是否想找：" + "、".join(sug) if sug else "没有查询到此学生，建议检查拼写"
    msg = "没有查询到此学生，建议检查拼写"
    if sug:
        msg += "\n你是不是想找：" + "、".join(sug)
    return msg


def skill_not_found(reason, suggest: list[str] | None) -> str:
    text = str(reason or "")
    msg = text if text.startswith("没查到") else f"没查到：{text}"
    if suggest:
        msg += "\n你是不是想找：" + "、".join(suggest)
    return msg


# ------------------------------------------------------------------ 技能
def skill_text(result: dict) -> str:
    """技能概览或某个槽位逐级数值。"""
    lines = [f"{result['name']}"]
    aliases = result.get("aliases") or {}
    others = [f"{k}:{v}" for k, v in aliases.items() if v and v != result["name"]]
    if others:
        lines.append("（" + " / ".join(others) + "）")

    skill_info = result.get("skill")
    if not skill_info:
        for s in result.get("skills", []):
            flag = "" if s.get("has_numbers") else "（无数值）"
            lines.append(f"· {s['slot_cn']}：{s['name']}{flag}")
        lines.append("加槽位看数值，例：/ba 若藻 ns")
        return "\n".join(lines)

    lines.append(f"【{skill_info['slot_cn']}】{skill_info['name']}")
    for lv, desc in skill_info.get("levels", {}).items():
        lines.append(f"Lv{lv}: {desc}")
    return "\n".join(lines)


# ------------------------------------------------------------------ 大决战榜单
def raid_teams(result: dict, name_of: Callable[[object], str]) -> str:
    boss = {b["group"]: b for b in result.get("boss_info") or []}
    lines = [
        f"{result['server']} 大决战 season {result['season']}"
        + (f"（{result['season_range']}）" if result.get("season_range") else "")
    ]
    for p in result.get("players") or []:
        lines.append(f"#{p['rank']} {p['nickname']} — {p['score']}")
        for gi in sorted(p.get("teams") or {}):
            t = p["teams"][gi]
            b = boss.get(gi, {})
            head = f"  {b.get('armor', '甲' + str(gi))}"
            if b.get("max_difficulty_label"):
                head += f"（上限 {b['max_difficulty_label']}）"
            who = "、".join(
                name_of(c["id"]) + ("(借)" if c.get("borrowed") else "")
                for c in t["characters"]
            )
            lines.append(f"{head}：{who}")
            if t.get("support"):
                back = "、".join(
                    name_of(c["id"]) + ("(借)" if c.get("borrowed") else "")
                    for c in t["support"]
                )
                if back:
                    lines.append(f"    后排：{back}")
    lines.append("")
    lines.append(ATTRIBUTION)
    lines.append("作业主观性大，box/练度/手法都不同，仅供参考。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 助战分页
def describe_filters(f: dict) -> str:
    if not f:
        return ""
    parts = []
    if f.get("min_star"):
        parts.append(f"{f['min_star']}★以上")
    if f.get("min_level"):
        parts.append(f"Lv{f['min_level']}+")
    if f.get("min_weapon_star"):
        parts.append(f"专武{f['min_weapon_star']}+")
    if f.get("min_ex_level"):
        parts.append(f"EX{f['min_ex_level']}+")
    return "、".join(parts)


def assist_page(res: dict, default_size: int) -> str:
    if not res.get("ok"):
        return f"查询失败：{res.get('reason', '未知')}"

    cond = describe_filters(res.get("filters") or {})
    page = int(res.get("page") or 1)
    total_pages = int(res.get("total_pages") or 1)
    total = int(res.get("total_players") or 0)
    size = int(res.get("size") or default_size)

    head = f"{res['server']}「{res.get('student_name')}」助战"
    if cond:
        head += f"（{cond}）"
    lines = [
        head,
        f"第 {page}/{total_pages} 页 · 共 {total} 人 · 每页 {size}",
    ]

    players = res.get("players") or []
    if not players:
        lines.append("（没有满足条件的玩家，放宽练度要求试试）")
    for i, p in enumerate(players, start=1):
        s = p.get("student") or {}
        detail = ""
        if s:
            detail = f"  {s.get('star')}★ Lv{s.get('level')}"
            if s.get("weapon_star"):
                detail += f" 专{s['weapon_star']}"
            if s.get("ex_skill"):
                detail += f" EX{s['ex_skill']}"
        lines.append(f"{i}. {p['nickname']} — 好友码 {p['friend_code']}{detail}")

    if total_pages > 1:
        hint = []
        if page < total_pages:
            hint.append("/ba 下页")
        if page > 1:
            hint.append("/ba 上页")
        if hint:
            lines.append("翻页：" + "  ".join(hint))

    lines.append("")
    lines.append(ATTRIBUTION)
    return "\n".join(lines)


# ------------------------------------------------------------------ 攻略视频
def guide_text(keyword: str, videos: list[dict]) -> str:
    lines = [f"B 站「{keyword}」相关视频："]
    for v in videos:
        lines.append(f"· {v['title']}")
        lines.append(f"  {v['url']}（{v['play']}播放 · {v['date']}）")
    if not videos:
        lines.append("（没搜到，换个说法试试）")
    lines.append("")
    lines.append("作业主观性很大，box、练度、手法都不一样，建议自己看几个再挑。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 测评卡
def review_usage() -> str:
    return "\n".join([
        "用法：/ba 测评 <角色>",
        "",
        "例：/ba 测评 康娜（泳装）   /ba 测评 水局   /ba 测评 星野泳装",
        "",
        "会发一张校委会攻略组做的测评卡（强度评级 / 就业场合 / 抽取建议）。",
        "想直接问也行：「康娜泳装值得抽吗」「若藻强不强」。",
    ])


def review_caption(res: dict) -> str:
    """卡片下面跟的那一行：角色名 + 角评版本 + 来源。"""
    name = res.get("name") or "这个角色"
    ver = res.get("version")
    head = f"{name} 的测评卡"
    if isinstance(ver, (int, float)) and ver > 0:
        head += f"（角评 {ver:.1f} 版）"
    lines = [f"{head}：{res.get('attribution') or ''}".rstrip("：")]
    if res.get("remote"):
        lines.append("（本地缓存失败，先用原图链接顶着）")
    return "\n".join(lines)


def review_failed(res: dict) -> str:
    reason = res.get("reason") or "查不到测评卡"
    name = res.get("name")
    lines = [f"✗ {reason}" + (f"：{name}" if name else "")]
    suggest = res.get("suggest") or []
    if suggest:
        lines.append("你是不是想找：" + "、".join(suggest))
    lines.append("")
    lines.append("测评卡按学园分篇发布，新角色要等攻略组补卡；也可以先 /ba 面板 或 /ba 攻略。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 字体
def font_report(res: dict) -> str:
    """把 font.ensure() 的结果转成群里能看懂的一段话。"""
    ok = bool(res.get("ok"))
    files = res.get("files") or {}
    lines = ["字体检查：" + ("✓ 已就绪，文字转图片不会出现方块" if ok else "✗ 未就绪，中文会渲染成方块（□□□）")]
    for name, info in files.items():
        if not info.get("exists"):
            lines.append(f"· {name}: 缺失")
            continue
        miss = info.get("missing_chars") or "无"
        lines.append(f"· {name}: {info.get('size_mb')} MB，缺失字形 {miss}")
    for a in res.get("actions") or []:
        lines.append(f"  {a}")
    for e in res.get("errors") or []:
        lines.append(f"  ✗ {e}")
    if not ok:
        lines.append("")
        lines.append("修复：插件页 →「字体」→ 点「下载 / 修复字体」；或再发一次 /ba 字体 修复")
    return "\n".join(lines)
