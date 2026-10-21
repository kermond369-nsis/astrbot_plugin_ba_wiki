# -*- coding: utf-8 -*-
"""常驻自检：T2~T10 的验收点 + 分层回归。

不碰线上 AstrBot，联网只发生在数据缓存缺失时（首次拉 SchaleDB 与 kivo 全量，
之后 24h 内走 tests/.data/ 缓存）。

    python tests/selfcheck.py

覆盖：
  1. 插件按 AstrBot 的方式加载；/ba 注册；5 个工具注册并绑定到实例
  2. 工具契约：docstring / 签名与 T1 前逐字一致（基线取自 backup-pre-t1.zip）
  3. T2 数据源：students() / names()，未到期零请求，ETag 变了要更新
  4. T3 kivo：by_devname('CH0252') 的四套名字、by_schale_id 覆盖率、24h 缓存
  5. T4 名字解析：三套中文名 / 形态前后缀 / 候选 / 错字 / 官方绰号 / 用户别名 / DevName / ID
  6. T4 显示策略：已上线用国服译名，未上线改成「中文全名（日文）」
  7. /ba 五个分支的端到端输出（上游打桩）
  8. 工具调用（绑定后）
"""

import asyncio
import functools
import inspect
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _harness as H

TOOL_NAMES = ["query_ba_skill", "query_ba_stats", "search_ba_guide", "query_ba_raid_team",
              "query_ba_player", "query_ba_assist"]
# 与重构前基线逐字对照的只有这 5 个（query_ba_stats 是后加的，基线里没有）
BASELINE_TOOLS = ["query_ba_skill", "search_ba_guide", "query_ba_raid_team",
                  "query_ba_player", "query_ba_assist"]

FAILS = []
CHECKS = [0]


def check(label, got, want=None):
    CHECKS[0] += 1
    ok = (got == want) if want is not None else bool(got)
    if not ok:
        FAILS.append((label, got, want))


def section(title):
    print("== %s ==" % title, flush=True)


main = H.load_plugin()
DATA_DIR, _ = H.data_paths("new")
inst = H.new_instance(main, DATA_DIR)
H.ensure_ready(inst)

schale = H.plugin_module("sources.schaledb")
kivo = H.plugin_module("sources.kivo")
dir_mod = H.plugin_module("directory")

# ---------------------------------------------------------------- 1. 加载与绑定
section("1) 加载 / 注册 / 绑定")
check("/ba 指令已注册", "ba" in H.COMMANDS)
check("工具数量", len(H.LLM_TOOLS), len(TOOL_NAMES))
check("工具名", sorted(t.name for t in H.LLM_TOOLS), sorted(TOOL_NAMES))
bound = H.bind_tools(inst)
check("都属于本插件且 active", sorted(t.name for t in bound), sorted(TOOL_NAMES))
check("handler 都绑上了 self", all(isinstance(t.handler, functools.partial) for t in bound))

# ---------------------------------------------------------------- 1b. 启动预热
section("1b) 启动预热（initialize）")
warm_dir = os.path.join(H.DATA_ROOT, "warmup")
shutil.rmtree(warm_dir, ignore_errors=True)
os.makedirs(warm_dir)
for f in (schale.STUDENTS_FILE, schale.NAMES_FILE, schale.META_FILE):
    src = os.path.join(DATA_DIR, f)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(warm_dir, f))

warm = H.new_instance(main, warm_dir)
warm_calls = []
real_kivo_records = kivo.records


def fake_kivo_records(dir_path=None, refresh=True, force=False):
    warm_calls.append((str(dir_path), refresh, force))
    return []


kivo.records = fake_kivo_records


async def _warm_scenario():
    await warm.initialize()
    if warm._warm_task is not None:
        await warm._warm_task          # _warm_up 里才会创建 _kivo_task，必须先等它
    if warm._kivo_task is not None:
        await warm._kivo_task


try:
    asyncio.run(_warm_scenario())
finally:
    kivo.records = real_kivo_records

check("initialize 排了预热任务", warm._warm_task is not None, True)
check("启动即触发 kivo 同步", [c for c in warm_calls if c[1] is True], [(warm_dir, True, False)])
check("启动日志有预热记录", any("启动预热" in msg for _lvl, msg in H.LOG), True)
check("kivo 就绪日志", any("kivo 名字缓存就绪" in msg for _lvl, msg in H.LOG), True)

sync_src = open(os.path.join(H.PLUGIN_SRC, "sync_data.py"), encoding="utf-8").read()
check("sync_data 同时同步 kivo", "kivo.records(DATA_DIR, force=True)" in sync_src)

# ---------------------------------------------------------------- 2. 工具契约
section("2) 工具契约（docstring / 签名）")
baseline = H.baseline_dir()
if baseline:
    old = H.load_baseline(baseline)
    for name in BASELINE_TOOLS:
        new_fn = getattr(main.BAWikiPlugin, name)
        old_fn = getattr(old.BAWikiPlugin, name)
        check("docstring 一致 %s" % name, new_fn.__doc__, old_fn.__doc__)
        check("签名一致 %s" % name, str(inspect.signature(new_fn)),
              str(inspect.signature(old_fn)))
    check("/ba docstring 一致", main.BAWikiPlugin.ba_cmd.__doc__,
          old.BAWikiPlugin.ba_cmd.__doc__)
else:
    print("（没有 backup-pre-t1.zip，跳过 docstring/签名对照）")

# ---------------------------------------------------------------- 3. T2 数据源
section("3) T2 数据源 students() / names()")
st = schale.students(DATA_DIR)
nm = schale.names(DATA_DIR)
check("students 非空", len(st) > 200)
check("names 覆盖所有学生", sorted(nm.keys()), sorted(st.keys()))
check("zh 名存在", all((v or {}).get("zh") for v in nm.values()))

calls = []
real_download = schale._download


def _counting(url, etag=None):
    calls.append(url)
    return real_download(url, etag)


schale._download = _counting
try:
    m1 = os.path.getmtime(os.path.join(DATA_DIR, schale.STUDENTS_FILE))
    schale.students(DATA_DIR)
    schale.names(DATA_DIR)
    m2 = os.path.getmtime(os.path.join(DATA_DIR, schale.STUDENTS_FILE))
finally:
    schale._download = real_download
check("未到期不探测上游", calls, [])
check("未到期不动文件", m1, m2)

# ETag 变了要更新：在临时目录里伪造上游
tmp_dir = os.path.join(H.DATA_ROOT, "etag-test")
shutil.rmtree(tmp_dir, ignore_errors=True)
shutil.copytree(DATA_DIR, tmp_dir)
meta_path = os.path.join(tmp_dir, schale.META_FILE)
meta = json.load(open(meta_path, encoding="utf-8"))
meta["checked_at"] = 0
json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False)

fake_students = {"999999": {"Id": 999999, "Name": "测试新生", "DevName": "TEST01",
                            "IsReleased": [True, True, True]}}


def _fake_download(url, etag=None):
    if url == schale.BASE.format(lang=schale.PRIMARY_LANG):
        return 200, json.dumps(fake_students, ensure_ascii=False).encode(), "etag-2"
    return 200, json.dumps({"999999": {"Id": 999999, "Name": "测试新生"}}).encode(), None


schale._download = _fake_download
try:
    changed = schale.refresh(tmp_dir)
    replaced = list(schale.students(tmp_dir))
    rebuilt = (schale.names(tmp_dir).get("999999") or {}).get("zh")
finally:
    schale._download = real_download
check("ETag 变了要更新数据", changed, True)
check("数据已替换", replaced, ["999999"])
check("名称表跟着重建", rebuilt, "测试新生")

# ---------------------------------------------------------------- 4. T3 kivo
section("4) T3 kivo")
check("kivo 缓存文件存在", os.path.exists(kivo.cache_path(DATA_DIR)))
recs = kivo.records(DATA_DIR)          # 首次会抓全量（约 2 分钟），之后 24h 内走缓存
check("kivo 记录数 > 400", len(recs) > 400)
by_dev = kivo.by_devname(DATA_DIR)
entry = by_dev.get("CH0252") or {}
check("CH0252 通用中文", entry.get("zh"), "纺")
check("CH0252 国服译名", entry.get("cn"), "纺")
check("CH0252 国际服繁中", entry.get("tw"), "紬")
check("CH0252 日文", entry.get("jp"), "ツムギ")
check("CH0252 绰号为空", entry.get("nick"), "")
by_id = kivo.by_schale_id(DATA_DIR)
su = schale.students(DATA_DIR)
covered = [sid for sid in su if sid in by_id]
check("kivo 按 SchaleDB Id 全覆盖", len(covered), len(su))

# ---------------------------------------------------------------- 5. T4 解析
section("5) T4 名字解析")
HITS = [
    ("若藻", 10033), ("Wakamo", 10033), ("ワカモ", 10033), ("わかも", 10033),
    ("와카모", 10033), ("10033", 10033),
    ("阿露", 10000), ("爱露", 10000), ("亞瑠", 10000), ("Aru", 10000),
    ("アル", 10000), ("아루", 10000),
    ("椎名纺", 10152), ("ツムギ", 10152), ("紬", 10152), ("Tsumugi", 10152),
    ("星野", 10005), ("白子", 10010), ("アリス", 10015),
    ("泳装星野", 10045), ("星野泳装", 10045), ("泳裝星野", 10045),
    ("水着星野", 10045), ("ホシノ水着", 10045),
    ("水星野", 10045),          # kivo 官方绰号（T4 起精确命中，不再是候选）
    ("大叔", 10005), ("社长", 10000), ("春露", 10031),
    ("CH0252", 10152), ("ch0252", 10152),
]
for kw, want_id in HITS:
    res = dir_mod.resolve(DATA_DIR, kw)
    got = int(res["matches"][0]["id"]) if res.get("ok") else res.get("kind")
    check("命中 %s" % kw, got, want_id)

# 形态词不认识 -> 候选（星野水 不是官方绰号）
VARIANT = dir_mod.resolve(DATA_DIR, "星野水")
check("星野水 走候选", VARIANT.get("kind"), "variant")
check("星野水 候选内容", VARIANT.get("suggest"), ["星野（泳装）", "星野（临战）", "星野"])

# 「星野老师」不剥后缀（golden 第 10 条）
teacher = dir_mod.resolve(DATA_DIR, "星野老师")
check("星野老师 给候选", teacher.get("kind"), "variant")

for kw in ("若澡", "星也"):
    res = dir_mod.resolve(DATA_DIR, kw)
    check("拼写 %s 走 typo" % kw, res.get("kind"), "typo")
    check("拼写 %s 有候选" % kw, bool(res.get("suggest")))

# T9：老文件 nicknames.json 仍然兼容
legacy_dir = os.path.join(H.DATA_ROOT, "alias-legacy")
os.makedirs(legacy_dir, exist_ok=True)
json.dump({"藻哥": "若藻"}, open(os.path.join(legacy_dir, "nicknames.json"), "w",
                                 encoding="utf-8"), ensure_ascii=False)
check("兼容老 nicknames.json", dir_mod.load_aliases(legacy_dir).get("藻哥"), "若藻")

# T9：代码里不再引用已废弃的数据文件
code = ""
for root, _dirs, files in os.walk(H.PLUGIN_SRC):
    if "__pycache__" in root:
        continue
    for f in files:
        if f.endswith(".py"):
            code += open(os.path.join(root, f), encoding="utf-8").read()
check("不再引用 variants.json", "variants.json" in code, False)
check("不再引用 names_kivo.json", "names_kivo.json" in code, False)

# 用户别名表 aliases.json
alias_path = os.path.join(DATA_DIR, dir_mod.ALIAS_FILE)
json.dump({"_说明": "自检用", "藻哥": "若藻", "错名": "查无此人", "石头": "10007"},
          open(alias_path, "w", encoding="utf-8"), ensure_ascii=False)
dir_mod.invalidate(DATA_DIR)
check("用户别名命中", dir_mod.resolve(DATA_DIR, "藻哥").get("matches", [{}])[0].get("id"), "10033")
check("用户别名可用 ID", dir_mod.resolve(DATA_DIR, "石头").get("matches", [{}])[0].get("id"), "10007")
check("坏别名不影响查询", dir_mod.resolve(DATA_DIR, "错名").get("kind"), "typo")

# ---------------------------------------------------------------- 6. T4 显示
section("6) T4 显示策略")
DISPLAY = {
    10000: "爱露",          # 已上线：国服译名
    10033: "若藻",
    10005: "星野",
    10045: "星野（泳装）",   # 已上线形态
    10152: "椎名纺（ツムギ）",  # 国服未上线：中文全名 + 日文
}
for cid, want in DISPLAY.items():
    check("显示名 %s" % cid, dir_mod.display_name(DATA_DIR, cid), want)
check("未上线判定", dir_mod.load_all(DATA_DIR)["profiles"]["10152"]["released_cn"], False)

# ---------------------------------------------------------------- 7. /ba 分支
section("7) /ba 分支（上游打桩）")
arona_mod = H.plugin_module("clients.arona")
bili_mod = H.plugin_module("clients.bilibili")
CALLS = []

ASSIST_RESULT = {
    "ok": True, "server": "国服", "student_id": 10033,
    "filters": {"min_star": 5, "min_level": 90, "min_weapon_star": 2, "min_ex_level": 5},
    "total_players": 168, "total_pages": 17, "page": 1, "size": 10,
    "players": [{"nickname": "甲", "friend_code": "abcd123",
                 "student": {"star": 5, "level": 90, "weapon_star": 2, "ex_skill": 5}}],
    "attribution": "数据来源：什亭之匣 https://arona.icu",
}


def fake_assist(server=1, student_id=None, page=1, size=10, min_star=None, min_level=None,
                min_weapon_star=None, min_ex_level=None, data_dir=None):
    CALLS.append(("assist", server, student_id, page, size, min_star, min_level,
                  min_weapon_star, min_ex_level))
    return json.loads(json.dumps({**ASSIST_RESULT, "page": page}))


def fake_rank(server=1, season=None, tier=1, top=3, data_dir=None):
    CALLS.append(("rank", server, season, tier, top))
    return {
        "ok": True, "server": "国服", "season": 21,
        "season_range": "2026-10-01 04:00 ~ 2026-10-08 04:00",
        "boss_info": [{"group": 0, "armor": "红甲", "max_difficulty_label": "INS"},
                      {"group": 1, "armor": "紫甲", "max_difficulty_label": "TM"}],
        "players": [{"rank": 1, "nickname": "玩家一", "score": 123456, "teams": {
            0: {"characters": [{"id": 10033, "borrowed": False}],
                "support": [{"id": 10020, "borrowed": True}]}}}],
        "attribution": "数据来源：什亭之匣 https://arona.icu",
    }


def fake_search(keyword, limit=5):
    CALLS.append(("bili", keyword, limit))
    return {"ok": True, "keyword": keyword, "videos": [
        {"title": "视频甲", "url": "https://www.bilibili.com/video/BV1", "play": "1.2万",
         "date": "2026-10-01"}]}


arona_mod.assist_players = fake_assist
arona_mod.rank_players = fake_rank
bili_mod.search = fake_search


def run_ba(msg, umo="umo-test"):
    return asyncio.run(H.run_ba(inst, msg, umo))


out = run_ba("")
check("空指令给用法", "用法：/ba <角色> [槽位] [等级]" in out[0])

out = run_ba("若藻")
check("技能概览含槽位", "· EX技能：" in out[0])

out = run_ba("若藻 ns")
check("NS 有数值", "194%" in out[0] and "369%" in out[0])
check("NS 标题", "普通技能(NS)" in out[0])

out = run_ba("椎名纺")
check("未上线学生也能查", out[0].startswith("椎名纺（ツムギ）"))

out = run_ba("若澡")
check("错字提示", out[0].startswith("没查到：") and "你是不是想找：" in out[0])

out = run_ba("借")
check("借的用法", "用法：/ba 借 <学生>" in out[0])

out = run_ba("借 若藻 5星 Lv90 专2 EX5")
check("借：区服+学生", "国服「若藻」助战" in out[0])
check("借：条件回显", "5★以上、Lv90+、专武2+、EX5+" in out[0])
check("借：分页抬头", "第 1/17 页 · 共 168 人 · 每页 10" in out[0])
check("借：上游参数", CALLS[-1], ("assist", 1, 10033, 1, 10, 5, 90, 2, 5))

out = run_ba("下页")
check("翻页到第 2 页", "第 2/17 页" in out[0])
check("新会话没状态", "没有可翻页的查询" in run_ba("下页", umo="umo-other")[0])
check("上页回第 1 页", "第 1/17 页" in run_ba("上页")[0])

out = run_ba("大决战")
check("大决战赛季", "国服 大决战 season 21" in out[0])
check("大决战护甲+上限", "红甲（上限 INS）" in out[0])
check("大决战借人标记", "(借)" in out[0] and "后排：" in out[0])
check("大决战来源行", "数据来源：什亭之匣 https://arona.icu" in out[0])

out = run_ba("攻略 国服 大决战 大蛇")
check("攻略标题", "B 站「国服 大决战 大蛇」相关视频：" in out[0])
check("攻略链接", "https://www.bilibili.com/video/BV1" in out[0])

# ---------------------------------------------------------------- 8. 工具调用
section("8) 工具调用（绑定后）")
skill_tool = next(t for t in bound if t.name == "query_ba_skill")
payload = json.loads(asyncio.run(H.call_tool(skill_tool, "x", student="爱露", skill="ns")))
check("工具 ok", payload.get("ok"), True)
check("工具 name 用显示名", payload.get("name"), "爱露")
check("工具槽位", payload.get("skill", {}).get("slot_cn"), "普通技能(NS)")
check("aliases：SchaleDB zh 标注为通用中文", payload.get("aliases", {}).get("通用中文"), "阿露")
check("aliases：国服译名来自 kivo", payload.get("aliases", {}).get("国服"), "爱露")

assist_tool = next(t for t in bound if t.name == "query_ba_assist")
res = json.loads(asyncio.run(H.call_tool(assist_tool, "x", student="水星野", server="国服")))
check("助战工具 ok", res.get("ok"), True)
check("助战工具用显示名", res.get("student_name"), "星野（泳装）")
check("助战工具带 rendered", "助战" in res.get("rendered", ""))

# ---------------------------------------------------------------- 9) 面板算法
section("9) 面板算法（等级曲线 / 星级 / 概率解放）")
stats_mod = H.plugin_module("sources.stats")

check("等级 90 曲线系数", stats_mod.level_scale(90), 0.899)
check("等级 1 曲线系数", stats_mod.level_scale(1), 0.0)
check("曲线四舍五入到 4 位", stats_mod.level_scale(50), 0.4949)
check("1 级取 stat1", stats_mod.interpolate(2907, 48600, 1, 1.0), 2907)
check("90 级插值 + 星级", stats_mod.interpolate(2907, 48600, 90, stats_mod.star_multiplier("MaxHP", 3)), 49264)
check("5★ 生命系数", stats_mod.star_multiplier("MaxHP", 5), 1.35)
check("5★ 攻击系数", round(stats_mod.star_multiplier("AttackPower", 5), 4), 1.53)
check("防御不吃星级", stats_mod.star_multiplier("DefensePower", 5), 1.0)

REC = {"MaxHP1": 1000, "MaxHP100": 10000, "AttackPower1": 100, "AttackPower100": 1000,
       "DefensePower1": 50, "DefensePower100": 500, "HealPower1": 80, "HealPower100": 800,
       "CriticalDamageRate": 20000, "RegenCost": 700,
       "FavorStatType": ["MaxHP", "AttackPower"],
       "FavorStatValue": [[3, 0], [5, 0], [7, 48], [9, 58], [2, 10], [3, 15], [6, 25]]}

check("能力解放 90 级前不生效", stats_mod.potential_bonus(REC, "MaxHP", 89, 25), 0)
check("能力解放 90 级生效", stats_mod.potential_bonus(REC, "MaxHP", 90, 25), 455)
check("能力解放 0 级为 0", stats_mod.potential_bonus(REC, "MaxHP", 90, 0), 0)
check("好感上限随星级 1★=10", stats_mod.BOND_MAX_BY_STAR[0], 10)
check("好感上限随星级 5★=50", stats_mod.BOND_MAX_BY_STAR[4], 50)
check("装备槽解锁等级", stats_mod.EQUIP_UNLOCK_LEVEL, (0, 15, 35))

check("专1 武器上限 30", stats_mod.WEAPON_CAP_BY_TIER[1], 30)
check("专4 武器上限 60", stats_mod.WEAPON_CAP_BY_TIER[4], 60)
check("等级反推阶位 30", stats_mod.weapon_tier_for_level(30), 1)
check("等级反推阶位 60", stats_mod.weapon_tier_for_level(60), 4)
check("专2 装 60 级会被夹到 40", stats_mod.clamp_weapon_level(60, 2), (40, 2))
check("只给 60 级自动推成专4", stats_mod.clamp_weapon_level(60, 0), (60, 4))

s_basic = stats_mod.from_record(REC, 90, 1)
check("基础面板生命", s_basic.total("MaxHP"), 9091)
check("会心伤害默认值", s_basic.total("CriticalDamageRate"), 20000)
check("COST 回复默认值", s_basic.total("RegenCost"), 700)

# 装备系数叠加：+20% 生命、+5% 攻击
s2 = stats_mod.from_record(REC, 90, 1)
s2.add_buff("MaxHP_Coefficient", 2000)
s2.add_buff("AttackPower_Coefficient", 500)
check("装备百分比：生命", s2.total("MaxHP"), 10909)
check("装备百分比：攻击", s2.total("AttackPower"), 954)

s3 = stats_mod.from_record(REC, 90, 1)
s3.add_buff("MaxHP_Base", 1000)
check("平坦加成先加后乘", s3.total("MaxHP"), 10091)

p = stats_mod.compute(REC, {}, level=90, star=1, equip_tiers=[0, 0, 0], ue=False,
                      weapon_level=0, bond_level=0, potential=0)
check("compute 不装备不专武", p["MaxHP"], 9091)
check("compute 口径回填", (p["potential"]["MaxHP"], p["bond"]), (0, 0))

# 分项能力解放：只解放攻击
p2 = stats_mod.compute(REC, {}, level=90, star=1, equip_tiers=[0, 0, 0], ue=False,
                     weapon_level=0, bond_level=0,
                     potential={"MaxHP": 0, "AttackPower": 25, "HealPower": 0})
check("分项能力解放：生命不变", p2["MaxHP"], 9091)
check("分项能力解放：攻击提升", p2["AttackPower"] > 909, True)
check("分项能力解放：治愈不变", p2["HealPower"], 727)

# ---------------------------------------------------------------- 汇总
print()
print("检查项: %d  失败: %d" % (CHECKS[0], len(FAILS)))
for label, got, want in FAILS:
    print("-" * 60)
    print("FAIL:", label)
    print("  got :", repr(got)[:500])
    print("  want:", repr(want)[:500])
sys.exit(1 if FAILS else 0)
