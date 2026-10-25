"""SchaleDB 面板数值：等级 / 星级 / 装备 / 专武 / 武器 / 好感。

口径与 SchaleDB（SchaleDB/SchaleDB 的 js/common.js）一致：
  base   ← 由 1 级与 100 级两个锚点按曲线插值，再乘星级系数
  flat   ← 好感、装备(_Base)、专武(_Base)、武器(_Base) 直接相加
  coeff  ← 装备(_Coefficient) 的百分比加成
  total  = round((base + flat) * max(coeff, 0.2))

国服上限取自 SchaleDB data/config.json 的 Regions[Cn]：
  等级 90 / 装备档 (10,10,9) / 武器 50 / 好感 50
区服非国服时用 REGIONS 里的值覆盖即可（本插件只输出国服口径）。
"""

from __future__ import annotations

import math

REGION = {
    "name": "Cn",
    "student_max_level": 90,
    "equipment_max_level": (10, 10, 9),
    "weapon_max_level": 50,
    "bond_max_level": 50,
}

# 装备类别 -> 装备表基础 Id（T1 的 Id），与 SchaleDB 的 gearId 一致
GEAR_ID = {
    "Hat": 1000, "Gloves": 2000, "Shoes": 3000, "Bag": 4000, "Badge": 5000,
    "Hairpin": 6000, "Charm": 7000, "Watch": 8000, "Necklace": 9000,
}

# 星级系数（累加），顺序与 SchaleDB 的 transcendence 数组一致
_STAR_TABLE = {
    "AttackPower": (0, 1000, 1200, 1400, 1700),
    "MaxHP": (0, 500, 700, 900, 1400),
    "HealPower": (0, 750, 1000, 1200, 1500),
}

# 原码里 getRawStat 缺字段时的默认值
_RAW_DEFAULT = {
    "CriticalResistPoint": 100,
    "CriticalDamageResistRate": 5000,
    "StabilityRate": 2000,
    "DamageRatio": 10000,
    "DamagedRatio": 10000,
    "OppressionPower": 100,
    "OppressionResist": 100,
    "MoveSpeed": 200,
    "StreetBattleAdaptation": 2,
    "OutdoorBattleAdaptation": 2,
    "IndoorBattleAdaptation": 2,
}

# 常量初始化的 stat（原码构造函数里直接写死）
_FIXED = {
    "HealEffectivenessRate": 10000,
    "AttackSpeed": 10000,
    "BlockRate": 0,
    "DamageRatio": 10000,
    "DamagedRatio": 10000,
    "EnhanceExplosionRate": 10000,
    "EnhancePierceRate": 10000,
    "EnhanceMysticRate": 10000,
    "EnhanceSonicRate": 10000,
    "ExtendBuffDuration": 10000,
    "ExtendDebuffDuration": 10000,
    "ExtendCCDuration": 10000,
}

# 展示用中文名（取自 SchaleDB zh localization）
STAT_LABEL = {
    "MaxHP": "生命值", "AttackPower": "攻击力", "DefensePower": "防御力", "HealPower": "治愈力",
    "AccuracyPoint": "命中值", "DodgePoint": "闪避值", "CriticalPoint": "暴击值",
    "CriticalDamageRate": "暴击伤害", "StabilityPoint": "稳定值", "Range": "射程",
    "AmmoCount": "载弹量", "RegenCost": "COST 回复力", "DefensePenetration": "防御无视值",
}

BULLET_LABEL = {
    "Explosion": "爆炸", "Pierce": "贯通", "Mystic": "神秘", "Sonic": "振动",
    "Normal": "常规", "Chemical": "分解",
}
ARMOR_LABEL = {
    "LightArmor": "轻型护甲", "HeavyArmor": "重型装甲", "Unarmed": "特殊装甲",
    "ElasticArmor": "弹性装甲", "CompositeArmor": "复合装甲", "Normal": "常规护甲",
    "Structure": "结构物",
}
ROLE_LABEL = {
    "DamageDealer": "输出", "Tanker": "坦克", "Healer": "治疗",
    "Supporter": "辅助", "Vehicle": "战术支援",
}
SCHOOL_LABEL = {
    "Abydos": "阿拜多斯", "Arius": "阿里乌斯", "Gehenna": "格黑娜", "Hyakkiyako": "百鬼夜行",
    "Millennium": "千年", "RedWinter": "红冬", "Shanhaijing": "山海经", "SRT": "SRT",
    "Trinity": "三一", "Valkyrie": "瓦尔基里", "ETC": "其他", "Tokiwadai": "常盘台",
    "Sakugawa": "栅川", "Highlander": "高原众", "WildHunt": "狂猎", "Odyssey": "奥德赛",
}
TERRAIN_LABEL = {"Street": "市区", "Outdoor": "室外", "Indoor": "室内"}

# 好感上限随星级（SchaleDB 的 maxbond）
BOND_MAX_BY_STAR = (10, 10, 20, 20, 50)
# 三个装备槽的解锁等级（SchaleDB 的 gear_minlevelreq）
EQUIP_UNLOCK_LEVEL = (0, 15, 35)
# 潜在能力（能力解放）：只加这三项，且要求等级 90
POTENTIAL_STATS = ("MaxHP", "AttackPower", "HealPower")
POTENTIAL_MAX = 25

# 专武（Gear）阶位 -> 武器等级上限：专1 解锁（30），每阶 +10
WEAPON_CAP_BY_TIER = {0: 0, 1: 30, 2: 40, 3: 50, 4: 60}
WEAPON_TIER_MAX = max(WEAPON_CAP_BY_TIER)


def weapon_tier_for_level(level: int) -> int:
    """由武器等级反推所需专精阶位（30->1, 40->2, 50->3, 60->4）。"""
    level = max(0, int(level or 0))
    if level <= 0:
        return 0
    for tier in (1, 2, 3, 4):
        if level <= WEAPON_CAP_BY_TIER[tier]:
            return tier
    return WEAPON_TIER_MAX


def clamp_weapon_level(level: int, tier: int) -> tuple[int, int]:
    """把武器等级夹到专精阶位允许的上限，返回 (等级, 实际阶位)。"""
    level = max(0, min(int(level or 0), WEAPON_CAP_BY_TIER[WEAPON_TIER_MAX]))
    if level == 0:
        return 0, 0
    tier = max(0, min(int(tier or 0), WEAPON_TIER_MAX))
    if tier == 0:
        tier = weapon_tier_for_level(level)
    cap = WEAPON_CAP_BY_TIER[tier]
    return min(level, cap), tier
TERRAIN_VALUE = {4: "S", 3: "A", 2: "B", 1: "C", 0: "D"}


# ------------------------------------------------------------------ 曲线
def level_scale(level: int, kind: str = "Standard") -> float:
    """等级插值系数。学生统一走 Standard；其余三种仅敌人/召唤物会用。"""
    if level <= 0:
        level = 1
    if kind == "TimeAttack":
        if level <= 1:
            return 0.0
        if level == 2:
            return 0.0101
        if level <= 24:
            return 0.0707
        if level == 25:
            return 0.0808
        if level <= 39:
            return 0.1919
        if level == 40:
            return 0.2020
        if level <= 64:
            return 0.4444
        if level == 65:
            return 0.4545
        if level <= 77:
            return 0.7172
        if level == 78:
            return 0.7273
        return round((level - 1) / 99, 4)
    if kind in ("LateBloom", "Premature"):
        return (level - 1) / 99
    return round((level - 1) / 99, 4)


def _to_fixed4(x: float) -> float:
    """模拟 Number(x.toFixed(4))。"""
    return float(f"{x:.4f}")


def _js_round(x: float) -> int:
    """JS Math.round：.5 向上（Python 的 round 是银行家舍入，不能用）。"""
    return math.floor(x + 0.5)


def interpolate(stat1: float, stat100: float, level: int, transcendence: float = 1.0,
                kind: str = "Standard") -> int:
    scale = level_scale(level, kind)
    raw = round(stat1 + (stat100 - stat1) * scale, 4)
    return math.ceil(round(_js_round(raw) * transcendence, 4))


def star_multiplier(stat: str, star: int) -> float:
    table = _STAR_TABLE.get(stat)
    if not table:
        return 1.0
    star = max(1, min(int(star), 5))
    total = 1.0
    for i in range(star):
        total += table[i] / 10000.0
    return total


# ------------------------------------------------------------------ 数值容器
class Stats:
    """每条 stat 记 [base, flat, coefficient, non_multiplicative_flat]。"""

    def __init__(self) -> None:
        self.data: dict[str, list[float]] = {}

    def set_base(self, stat: str, value: float) -> None:
        self.data[stat] = [float(value), 0.0, 1.0, 0.0]

    def add_buff(self, stat: str, amount: float) -> None:
        if not stat or amount is None:
            return
        head, _, suffix = stat.partition("_")
        slot = self.data.setdefault(head, [0.0, 0.0, 1.0, 0.0])
        if suffix == "Base":
            slot[1] += float(amount)
        elif suffix == "Coefficient":
            slot[2] += float(amount) / 10000.0
        elif suffix == "":
            slot[1] += float(amount)
        # 其它后缀（如 _Rate）原码不处理，同样忽略

    def total(self, stat: str) -> int:
        slot = self.data.get(stat)
        if not slot:
            return 0
        base, flat, coeff, nonmul = slot
        # 与 JS 一致：先 toFixed(4)，再 Math.round（.5 向上），最后加不参与乘算的平坦值
        scaled = _to_fixed4((base + flat) * max(coeff, 0.2))
        value = _js_round(scaled) + nonmul
        return max(int(value), 0) if stat != "DamagedRatio" else int(value)


# ------------------------------------------------------------------ 组装
def _raw(record: dict, stat: str) -> float:
    override = record.get("Stat" + REGION["name"])
    if isinstance(override, dict) and stat in override:
        return override[stat]
    if stat in record:
        return record[stat]
    return _RAW_DEFAULT.get(stat, 0)


def from_record(record: dict, level: int, star: int) -> Stats:
    s = Stats()
    s.set_base("MaxHP", interpolate(_raw(record, "MaxHP1"), _raw(record, "MaxHP100"), level, star_multiplier("MaxHP", star)))
    s.set_base("AttackPower", interpolate(_raw(record, "AttackPower1"), _raw(record, "AttackPower100"), level, star_multiplier("AttackPower", star)))
    s.set_base("DefensePower", interpolate(_raw(record, "DefensePower1"), _raw(record, "DefensePower100"), level, 1.0))
    s.set_base("HealPower", interpolate(_raw(record, "HealPower1"), _raw(record, "HealPower100"), level, star_multiplier("HealPower", star)))

    pen = 0
    if "DefensePenetration100" in record:
        pen = interpolate(_raw(record, "DefensePenetration1"), _raw(record, "DefensePenetration100"), level, 1.0)
    s.set_base("DefensePenetration", pen)

    for stat in ("AccuracyPoint", "DodgePoint", "CriticalPoint", "CriticalDamageRate",
                 "StabilityPoint", "AmmoCount", "AmmoCost", "Range", "RegenCost",
                 "OppressionPower", "OppressionResist", "MoveSpeed"):
        s.set_base(stat, _raw(record, stat))
    s.set_base("CriticalChanceResistPoint", _raw(record, "CriticalResistPoint"))
    s.set_base("CriticalDamageResistRate", _raw(record, "CriticalDamageResistRate"))
    s.set_base("StabilityRate", _raw(record, "StabilityRate"))
    for stat, value in _FIXED.items():
        s.set_base(stat, value)

    # 补齐完整面板里的其余属性（数据没写的用 SchaleDB 的默认值）
    override = record.get("Stat" + REGION["name"])
    for key, default in _DEFAULTS.items():
        if key in s.data:
            continue
        value = record.get(key)
        if value is None and isinstance(override, dict):
            value = override.get(key)
        if value is None and key == "CriticalChanceResistPoint":
            value = record.get("CriticalResistPoint")
        s.set_base(key, float(value) if value is not None else default)
    return s


def max_tier_for_category(equipment_table: dict, category: str, fallback: int = 1) -> int:
    """该装备类别在当前区服（国服=IsReleased[2]）已实装的最高档。"""
    best = 0
    for item in equipment_table.values():
        if item.get("Category") != category:
            continue
        tier = int(item.get("Tier") or 0)
        released = item.get("IsReleased") or []
        if tier and len(released) >= 3 and released[2]:
            best = max(best, tier)
    return best or fallback


def default_equip_tiers(record: dict, equipment_table: dict) -> list[int]:
    """默认装备档 = 全部吃满（数据里该类别存在的最高档，当前是 T10）。

    想要「国服现实口径」（第三槽手表/挂饰/项链的 T10 尚未实装）时显式传 装备10/10/9。
    """
    tiers = []
    for category in (record.get("Equipment") or [])[:3]:
        best = 0
        for item in equipment_table.values():
            if item.get("Category") == category:
                best = max(best, int(item.get("Tier") or 0))
        tiers.append(best or 10)
    while len(tiers) < 3:
        tiers.append(0)
    return tiers


def add_equipment(stats: Stats, equipment_table: dict, category: str, tier: int) -> None:
    """装备：tier 为档位（1..10）；取该档装备在满级时的 StatValue。"""
    if not category or tier is None or int(tier) <= 0:
        return
    base_id = GEAR_ID.get(category)
    if base_id is None:
        return
    item = equipment_table.get(str(base_id + int(tier) - 1)) or equipment_table.get(base_id + int(tier) - 1)
    if not item:
        return
    types = item.get("StatType") or []
    values = item.get("StatValue") or []
    for i, stat in enumerate(types):
        if i < len(values) and values[i]:
            stats.add_buff(stat, values[i][1])


def add_gear(stats: Stats, record: dict) -> bool:
    """爱用品（SchaleDB 的 Gear）：固定平坦值，无等级成长。

    不按区服是否开放过滤——口径就是「全吃满」，有数据即计入。
    """
    gear = record.get("Gear") or {}
    if not (gear.get("StatType") and gear.get("StatValue")):
        return False
    types = gear.get("StatType") or []
    values = gear.get("StatValue") or []
    for i, stat in enumerate(types):
        if i < len(values) and values[i]:
            stats.add_buff(stat, values[i][1])
    return True


def add_weapon(stats: Stats, weapon: dict, level: int) -> None:
    """角色武器：随武器等级插值，加到 _Base。"""
    if not weapon or level is None or int(level) <= 0:
        return
    scale = (level - 1) / 99.0
    if weapon.get("StatLevelUpType") == "Standard":
        scale = round(scale, 4)
    for stat in ("AttackPower", "MaxHP", "HealPower"):
        first = weapon.get(stat + "1") or 0
        last = weapon.get(stat + "100") or 0
        stats.add_buff(stat + "_Base", _js_round(first + (last - first) * scale))


def _stat_keys() -> set[str]:
    return set(DISPLAY_STATS) | {
        "DamageRatio", "DamagedRatio", "EnhanceExDamageRate", "CriticalDamageResistRate",
    }


BULLET_ENHANCE = {
    "Mystic": "EnhanceMysticRate",
    "Explosion": "EnhanceExplosionRate",
    "Pierce": "EnhancePierceRate",
    "Sonic": "EnhanceSonicRate",
}


def add_weapon_tier_stats(stats: Stats, record: dict, ue_tier: int) -> None:
    """专4（属性强化）：主属性克制率 +1000（即 +10%）。"""
    if int(ue_tier or 0) < 4:
        return
    stat = BULLET_ENHANCE.get(record.get("BulletType") or "")
    if stat:
        stats.add_buff(stat, 1000)


def add_skill_stats(stats: Stats, record: dict, level: int = 1, ue_tier: int = 4) -> None:
    """被动技能（Skills.Passive）的常驻属性加成，例如「永不放弃的心」+14% 攻击。

    数值表是按技能等级给的一组数（1400 = 14%），取 level 那一项。
    """
    skills = record.get("Skills") or {}
    allowed = set(FULL_STAT_KEYS) | {
        "DamageRatio", "DamagedRatio", "EnhanceExDamageRate", "ExDamagedRatio",
        "CriticalDamageResistRate", "HealEffectivenessRate",
    }
    slots = ["Passive", "ExtraPassive"]
    if int(ue_tier or 0) >= 2:  # 专2 解锁「被动技能+」
        slots.append("WeaponPassive")
    for slot in slots:
        skill = skills.get(slot) or {}
        for effect in skill.get("Effects") or []:
            if not isinstance(effect, dict) or effect.get("Type") != "Buff":
                continue
            stat = effect.get("Stat") or ""
            base = stat.replace("_Coefficient", "").replace("_Base", "")
            if base not in allowed:
                continue
            values = effect.get("Value") or []
            row = values[0] if values and isinstance(values[0], list) else values
            if not row:
                continue
            value = int(row[max(0, min(int(level), len(row)) - 1)])
            if value:
                stats.add_buff(stat, value)


def potential_bonus(record: dict, stat: str, level: int, potential_level: int) -> int:
    """能力解放：每级 +0.2% 的「1★ 该等级插值基础值」，四舍五入，等级 90 起才生效。"""
    if level < REGION["student_max_level"] or potential_level <= 0:
        return 0
    base = interpolate(_raw(record, stat + "1"), _raw(record, stat + "100"), level, 1.0)
    return _js_round(base * potential_level * 0.002)


def bond_bonus(record: dict, level: int) -> dict[str, int]:
    """好感加成：按 SchaleDB getBondStats 的分段索引。"""
    kinds = record.get("FavorStatType") or []
    values = record.get("FavorStatValue") or []
    if len(kinds) < 2 or len(values) < 5:
        return {}
    stat1 = stat2 = 0
    for i in range(1, min(level, 50)):
        if i < 20:
            idx = i // 5
        elif i < 50:
            idx = 2 + i // 10
        else:
            break
        if idx < len(values):
            stat1 += values[idx][0]
            stat2 += values[idx][1]
    return {kinds[0]: stat1, kinds[1]: stat2}


def add_bond(stats: Stats, record: dict, level: int, students: dict | None = None,
             alt_level: int | None = None) -> int:
    """好感加成：本体按星级上限，延伸皮肤按 BondMaxLevel（SchaleDB 的滑块各管各的）。

    返回实际计入的延伸皮肤数量（不含本体）。
    """
    for stat, value in bond_bonus(record, level).items():
        stats.add_buff(stat, value)
    if not students:
        return 0
    if alt_level is None:
        alt_level = level
    used = 0
    for alt_id in record.get("FavorAlts") or []:
        alt = students.get(alt_id) or students.get(str(alt_id))
        if not alt:
            continue
        used += 1
        for stat, value in bond_bonus(alt, alt_level).items():
            stats.add_buff(stat, value)
    return used


FULL_STATS = [
    # (键, 中文名, 默认值, 是否百分比)
    ("MaxHP", "体力上限", 0, False),
    ("AttackPower", "攻击力", 0, False),
    ("DefensePower", "防御力", 0, False),
    ("HealPower", "治疗力", 0, False),
    ("AccuracyPoint", "命中值", 0, False),
    ("DodgePoint", "闪避值", 0, False),
    ("CriticalPoint", "暴击值", 0, False),
    ("CriticalChanceResistPoint", "暴击抵抗力", 100, False),
    ("CriticalDamageRate", "暴击伤害", 20000, True),
    ("CriticalDamageResistRate", "暴击伤害抵抗率", 5000, True),
    ("StabilityPoint", "稳定值", 0, False),
    ("StabilityRate", "稳定率", 2000, True),
    ("Range", "普通攻击射程", 0, False),
    ("SightPoint", "视野", 0, False),
    ("OppressionPower", "群控强化", 100, False),
    ("OppressionResist", "群控抵抗", 100, False),
    ("HealEffectivenessRate", "受恢复率", 10000, True),
    ("RegenCost", "蓄能值恢复力", 700, False),
    ("AttackSpeed", "攻击速度", 10000, True),
    ("MoveSpeed", "移动速度", 200, False),
    ("BlockRate", "掩体格挡率", 0, True),
    ("DefensePenetration", "防御无视值", 0, False),
    ("DamageRatio", "增伤率", 10000, True),
    ("DamagedRatio", "免伤率", 10000, True),
    ("EnhanceExDamageRate", "EX技能增伤率", 0, True),
    ("ExDamagedRatio", "EX技能免伤率", 10000, True),
    ("EnhanceBasicsDamageRate", "基础熟练度", 10000, True),
    ("HealRate", "回复量加成", 10000, True),
    ("EnhanceExplosionRate", "爆炸克制率", 10000, True),
    ("EnhancePierceRate", "贯通克制率", 10000, True),
    ("EnhanceMysticRate", "神秘克制率", 10000, True),
    ("EnhanceSonicRate", "振动克制率", 10000, True),
    ("ExtendBuffDuration", "增益持续力", 10000, True),
    ("ExtendDebuffDuration", "减益持续力", 10000, True),
    ("AmmoCount", "载弹量", 0, False),
]
FULL_STAT_KEYS = [k for k, _l, _d, _p in FULL_STATS]
PERCENT_STATS = {k for k, _l, _d, p in FULL_STATS if p}
_DEFAULTS = {k: d for k, _l, d, _p in FULL_STATS}


# 这几个属性以 10000 为「0%」基准（游戏里显示 (值-10000)/100 ）
OFFSET_STATS = {"DamageRatio", "DamagedRatio", "HealEffectivenessRate",
                "EnhanceBasicsDamageRate", "HealRate", "ExDamagedRatio"}


def fmt_stat(key: str, value) -> str:
    if key in OFFSET_STATS:
        pct = (value - 10000) / 100
        return f"{pct:.0f}%" if float(pct).is_integer() else f"{pct:.2f}%"
    if key in PERCENT_STATS:
        return f"{value / 100:.0f}%" if value % 100 == 0 else f"{value / 100:.2f}%"
    return f"{int(value):,}"


def defense_reduction(defense: int) -> float:
    """防御伤害减免：1 - 10,000,000 / (防御 × 6000 + 10,000,000)。"""
    return (1 - 10000000 / (max(defense, 0) * 6000 + 10000000)) * 100


def stability_min_damage(stability: int, stability_rate: int) -> float:
    """最低伤害：稳定值/(稳定值+1000) + 稳定率/10000，夹取 0~1。"""
    return min(max(stability / (stability + 1000) + stability_rate / 10000, 0), 1) * 100


def striker_bonus(total: int, stat_key: str, support_count: int = 2) -> int:
    """支援属性值：HP/攻 10%、防/治 5%（>2 个支援时全部 5%），向下取整。"""
    coef = {"MaxHP": 0.1, "AttackPower": 0.1, "DefensePower": 0.05, "HealPower": 0.05}
    rate = 0.05 if support_count > 2 else coef.get(stat_key, 0)
    return int(total * rate // 1)


DISPLAY_STATS = (
    "MaxHP", "AttackPower", "DefensePower", "HealPower",
    "AccuracyPoint", "DodgePoint", "CriticalPoint", "CriticalDamageRate",
    "StabilityPoint", "Range", "AmmoCount", "RegenCost",
)


def compute(record: dict, equipment_table: dict, *, level: int = 90, star: int = 5,
            equip_tiers=None, ue=None, weapon_level: int = 50, bond_level: int = 50,
            potential: int | None = None, skill_level: int = 10, ue_tier: int = 4,
            students: dict | None = None) -> dict:
    """算出最终面板。

    ue=None 表示按数据里是否已实装自动判断；potential=None 表示「90 级时按满级 25、否则 0」。
    """
    star = max(1, min(int(star), 5))
    level = max(1, min(int(level), REGION["student_max_level"]))
    if potential is None:
        potential = POTENTIAL_MAX if level >= REGION["student_max_level"] else 0
    if isinstance(potential, dict):
        levels = {k: max(0, min(int(potential.get(k, 0) or 0), POTENTIAL_MAX)) for k in POTENTIAL_STATS}
    else:
        one = max(0, min(int(potential), POTENTIAL_MAX))
        levels = {k: one for k in POTENTIAL_STATS}
    bond_requested = max(0, int(bond_level))
    bond_level = min(bond_requested, BOND_MAX_BY_STAR[star - 1])
    bond_alt_level = min(bond_requested, REGION["bond_max_level"])

    stats = from_record(record, level, star)
    bond_variants = add_bond(stats, record, bond_level, students, bond_alt_level)

    tiers = list(equip_tiers) if equip_tiers is not None else default_equip_tiers(record, equipment_table)
    equipment = record.get("Equipment") or []
    for i, category in enumerate(equipment[:3]):
        if level < EQUIP_UNLOCK_LEVEL[i]:
            continue
        tier = tiers[i] if i < len(tiers) else 0
        add_equipment(stats, equipment_table, category, tier)

    gear_applied = False
    if ue is not False:
        gear_applied = add_gear(stats, record)
    add_weapon(stats, record.get("Weapon") or {}, weapon_level)

    for stat, lv in levels.items():
        if lv:
            value = potential_bonus(record, stat, level, lv)
            if value:
                stats.add_buff(stat + "_Base", value)

    add_skill_stats(stats, record, skill_level, ue_tier)
    add_weapon_tier_stats(stats, record, ue_tier)

    full = {key: stats.total(key) for key in FULL_STAT_KEYS}
    totals = {stat: stats.total(stat) for stat in DISPLAY_STATS}
    totals["full"] = full
    totals["defense_reduction"] = round(defense_reduction(full["DefensePower"]), 2)
    totals["min_damage"] = round(stability_min_damage(full["StabilityPoint"], full["StabilityRate"]), 2)
    totals["stats"] = stats
    totals["gear"] = gear_applied
    totals["potential"] = levels
    totals["bond"] = bond_level
    totals["bond_alt_level"] = bond_alt_level
    totals["bond_variants"] = bond_variants
    totals["bond_total"] = bond_level + bond_alt_level * bond_variants
    totals["skill_level"] = skill_level if skill_level else 10
    return totals


_TERRAIN_UP = {"D": "C", "C": "B", "B": "A", "A": "S", "S": "SS"}


def labels(record: dict, ue_tier: int = 0) -> dict:
    """攻击类型 / 装甲 / 职业 / 学院 / 地形适性（专3 会把最好的地形升一级）。"""
    def pick(table, key):
        return table.get(key, key or "-")

    terrain = {
        "Street": TERRAIN_VALUE.get(record.get("StreetBattleAdaptation"), str(record.get("StreetBattleAdaptation"))),
        "Outdoor": TERRAIN_VALUE.get(record.get("OutdoorBattleAdaptation"), str(record.get("OutdoorBattleAdaptation"))),
        "Indoor": TERRAIN_VALUE.get(record.get("IndoorBattleAdaptation"), str(record.get("IndoorBattleAdaptation"))),
    }
    if int(ue_tier or 0) >= 3:  # 专3：地形适应性强化（最优地形升一级）
        best = max(terrain, key=lambda k: {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4, "SS": 5}.get(terrain[k], -1))
        terrain[best] = _TERRAIN_UP.get(terrain[best], terrain[best])

    return {
        "bullet": pick(BULLET_LABEL, record.get("BulletType")),
        "armor": pick(ARMOR_LABEL, record.get("ArmorType")),
        "role": pick(ROLE_LABEL, record.get("TacticRole")),
        "squad": "前锋" if record.get("SquadType") == "Main" else "后援",
        "school": pick(SCHOOL_LABEL, record.get("School")),
        "position": {"Front": "前排", "Middle": "中排", "Back": "后排"}.get(record.get("Position"), record.get("Position") or "-"),
        "terrain": terrain,
    }
