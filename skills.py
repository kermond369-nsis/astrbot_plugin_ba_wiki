"""技能层：SchaleDB 记录里的技能槽位 -> 名称、描述与逐级数值。

纯函数，不碰名字解析（directory.py），也不生成给人看的整段文本（render.py）。

槽位映射最容易错：SchaleDB 的 Public 才是 BA 的「普通技能(NS)」，
Normal 只是普通攻击（只有帧数据，无数值）。
"""

from __future__ import annotations

import re

# 用户说法 -> SchaleDB 槽位
SLOT_ALIASES = {
    "ex": "Ex", "ex技能": "Ex", "大招": "Ex",
    "ns": "Public", "normal_skill": "Public", "普通技能": "Public", "1技能": "Public",
    "public": "Public", "技能1": "Public",
    "ns+": "GearPublic", "普通技能+": "GearPublic", "专武普通技能": "GearPublic",
    "gearpublic": "GearPublic",
    "ps": "Passive", "被动": "Passive", "被动技能": "Passive", "passive": "Passive",
    "sub": "ExtraPassive", "辅助": "ExtraPassive", "辅助技能": "ExtraPassive",
    "extrapassive": "ExtraPassive", "extra": "ExtraPassive",
    "wp": "WeaponPassive", "武器被动": "WeaponPassive", "专武": "WeaponPassive",
    "weaponpassive": "WeaponPassive",
    "普通攻击": "Normal", "平a": "Normal", "平A": "Normal", "normal": "Normal",
}

SLOT_CN = {
    "Ex": "EX技能",
    "Public": "普通技能(NS)",
    "GearPublic": "普通技能·专武强化",
    "Passive": "被动技能",
    "ExtraPassive": "辅助技能(Sub)",
    "WeaponPassive": "武器被动(专武)",
    "Normal": "普通攻击",
}

STAT_LABELS = {
    "ATK": "攻击力", "HEAL": "治疗力", "HP": "生命值", "DEF": "防御力",
    "CRITDMG": "暴击伤害", "CRIT": "暴击值", "COST": "费用", "SHIELD": "护盾",
    "DODGE": "闪避值", "ACC": "命中值",
}


def resolve_slot(skill: str) -> str | None:
    key = (skill or "").strip().lower().replace(" ", "")
    if not key:
        return None
    if key in SLOT_ALIASES:
        return SLOT_ALIASES[key]
    for alias_name, slot in SLOT_ALIASES.items():
        if alias_name in key:
            return slot
    return None


# ------------------------------------------------------------------ 渲染素材
def clean(text: str) -> str:
    if not text:
        return ""
    t = str(text)
    t = re.sub(r"<b:([A-Za-z]+)>", lambda m: STAT_LABELS.get(m.group(1).upper(), m.group(1)), t)
    t = re.sub(r"<s:([^>]+)>", lambda m: m.group(1), t)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def level_count(slot: dict) -> int:
    params = slot.get("Parameters") or []
    return max((len(p) for p in params if isinstance(p, list)), default=0)


def render_level(slot: dict, level: int) -> str:
    desc = clean(slot.get("Desc", ""))
    params = slot.get("Parameters") or []

    def sub(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(params):
            row = params[idx]
            if isinstance(row, list) and row:
                return str(row[min(level - 1, len(row) - 1)])
        return "?"

    return re.sub(r"<\?(\d+)>", sub, desc)


def params_table(slot: dict) -> list[dict]:
    rows = []
    for i, row in enumerate(slot.get("Parameters") or [], start=1):
        if isinstance(row, list) and row:
            rows.append({"param": i, "values": [str(v) for v in row]})
    return rows


def describe_skill(slot_key: str, slot: dict, levels: list[int] | None = None) -> dict:
    total = level_count(slot)
    if levels is None:
        levels = list(range(1, total + 1)) if total else [1]
    result = {
        "slot": slot_key,
        "slot_cn": SLOT_CN.get(slot_key, slot_key),
        "name": clean(slot.get("Name", "")),
        "description_template": clean(slot.get("Desc", "")),
        "level_count": total,
        "levels": {str(lv): render_level(slot, lv) for lv in levels},
        "parameters": params_table(slot),
    }
    if slot_key == "Ex" and slot.get("Cost") is not None:
        result["cost"] = slot.get("Cost")
    return result


def overview(student: dict) -> list[dict]:
    out = []
    for slot_key, slot in (student.get("Skills") or {}).items():
        if not isinstance(slot, dict):
            continue
        out.append({
            "slot": slot_key,
            "slot_cn": SLOT_CN.get(slot_key, slot_key),
            "name": clean(slot.get("Name", "")),
            "level_count": level_count(slot),
            "has_numbers": bool(slot.get("Parameters")),
        })
    return out
