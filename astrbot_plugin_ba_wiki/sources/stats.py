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
    return s


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
    """专武（Unique Weapon）：数据里是固定值，没有等级成长。"""
    gear = record.get("Gear") or {}
    released = gear.get("Released") or []
    if not released or len(released) < 3 or not released[2]:
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


def add_bond(stats: Stats, record: dict, level: int, students: dict | None = None) -> None:
    for stat, value in bond_bonus(record, level).items():
        stats.add_buff(stat, value)
    if not students:
        return
    for alt_id in record.get("FavorAlts") or []:
        alt = students.get(alt_id) or students.get(str(alt_id))
        if not alt:
            continue
        released = alt.get("IsReleased") or []
        if len(released) < 3 or not released[2]:
            continue
        for stat, value in bond_bonus(alt, level).items():
            stats.add_buff(stat, value)


DISPLAY_STATS = (
    "MaxHP", "AttackPower", "DefensePower", "HealPower",
    "AccuracyPoint", "DodgePoint", "CriticalPoint", "CriticalDamageRate",
    "StabilityPoint", "Range", "AmmoCount", "RegenCost",
)


def compute(record: dict, equipment_table: dict, *, level: int = 90, star: int = 5,
            equip_tiers=None, ue=None, weapon_level: int = 50, bond_level: int = 50,
            potential: int | None = None, students: dict | None = None) -> dict:
    """算出最终面板。

    ue=None 表示按数据里是否已实装自动判断；potential=None 表示「90 级时按满级 25、否则 0」。
    """
    star = max(1, min(int(star), 5))
    level = max(1, min(int(level), REGION["student_max_level"]))
    if potential is None:
        potential = POTENTIAL_MAX if level >= REGION["student_max_level"] else 0
    potential = max(0, min(int(potential), POTENTIAL_MAX))
    bond_level = max(0, min(int(bond_level), BOND_MAX_BY_STAR[star - 1]))

    stats = from_record(record, level, star)
    add_bond(stats, record, bond_level, students)

    tiers = list(equip_tiers) if equip_tiers is not None else list(REGION["equipment_max_level"])
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

    if potential:
        for stat in POTENTIAL_STATS:
            value = potential_bonus(record, stat, level, potential)
            if value:
                stats.add_buff(stat + "_Base", value)

    totals = {stat: stats.total(stat) for stat in DISPLAY_STATS}
    totals["stats"] = stats
    totals["gear"] = gear_applied
    totals["potential"] = potential
    totals["bond"] = bond_level
    return totals


def labels(record: dict) -> dict:
    """攻击类型 / 装甲 / 职业 / 学院 / 地形适性。"""
    def pick(table, key):
        return table.get(key, key or "-")

    return {
        "bullet": pick(BULLET_LABEL, record.get("BulletType")),
        "armor": pick(ARMOR_LABEL, record.get("ArmorType")),
        "role": pick(ROLE_LABEL, record.get("TacticRole")),
        "squad": "前锋" if record.get("SquadType") == "Main" else "后援",
        "school": pick(SCHOOL_LABEL, record.get("School")),
        "position": {"Front": "前排", "Middle": "中排", "Back": "后排"}.get(record.get("Position"), record.get("Position") or "-"),
        "terrain": {
            "Street": TERRAIN_VALUE.get(record.get("StreetBattleAdaptation"), str(record.get("StreetBattleAdaptation"))),
            "Outdoor": TERRAIN_VALUE.get(record.get("OutdoorBattleAdaptation"), str(record.get("OutdoorBattleAdaptation"))),
            "Indoor": TERRAIN_VALUE.get(record.get("IndoorBattleAdaptation"), str(record.get("IndoorBattleAdaptation"))),
        },
    }
