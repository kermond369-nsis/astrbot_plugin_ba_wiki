"""名字解析层（GOALS T4 的核心）。

数据来源（运行时合并，新学生自动生效）：
  - SchaleDB：七语言官方名 + DevName + IsReleased（权威、全覆盖）
  - kivo    ：通用中文 / 国服译名 / 国际服繁体 / 日英韩 + 官方绰号（按 SchaleDB Id 挂）
  - 用户     ：aliases.json（键=群里的叫法，值=官方名或角色 ID）

关联主键：**SchaleDB Id**（kivo 的 character_datas[].character_id 就是它）。
GOALS 原本写「按 DevName 关联」，实测 kivo 的 dev_name 带 _DEFAULT/_SWIMSUIT 后缀、
与 SchaleDB 并不同源（星野泳装：kivo=Hoshino_Swimsuit，SchaleDB=CH0091），只覆盖 187/278；
Id 覆盖 278/278，且 ID 也不是名字，符合「不要用名字当主键」的原则。DevName 仍保留在
档案里做交叉校验。

显示策略（GOALS「名称显示策略」）：
  - 国服已上线（IsReleased[1] 为真）-> kivo 国服译名（缺则 SchaleDB 的 zh）
  - 国服未上线                     -> kivo 中文全名 + （日文）  例：椎名纺（ツムギ）
  - 形态（皮肤）用 SchaleDB 名的括号标签，缺了才用 kivo 的 skin_cn

判定链（顺序即语义优先级）：
  1. 精确命中：七语言官方名、派生形态（泳装星野/星野泳装）、kivo 三套中文与全名、
     官方绰号、用户别名、DevName、角色 ID
  2. 形态词 + 基名：允许跨语言混写（「水着星野」）
  3. 基名对但形态词不认识（「星野水」）-> 列该基名下所有形态让用户选
  4. 连基名都对不上 -> 提示检查拼写（附模糊候选）

刻意不做「任意子串当命中」：那样「水星野」会直接答成「星野」，等于默许拼错。
（「水星野」现在是 kivo 的官方绰号，会精确命中——这是 T4 引入绰号后的预期变化。）
"""

from __future__ import annotations

import difflib
import json
import os
import re
import time
import unicodedata

from astrbot.api import logger

from .sources import kivo as kivo_src
from .sources import schaledb

_KATA_TO_HIRA = {i: i - 0x60 for i in range(0x30A1, 0x30F7)}

ALIAS_FILE = "aliases.json"
LEGACY_ALIAS_FILE = "nicknames.json"      # T9 之前的老文件名，仍兼容读取


# ------------------------------------------------------------------ 归一化
def normalize(text: str) -> str:
    """统一大小写、全半角、空格标点，并把片假名折成平假名。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).lower()
    t = "".join(chr(_KATA_TO_HIRA.get(ord(c), ord(c))) for c in t)
    t = re.sub(r"[\s\-_·・.,、。()（）\[\]【】'\"!！?？~〜]", "", t)
    return t


def load_aliases(data_dir: str) -> dict:
    """用户别名表：{"大叔": "星野", "藻哥": "若藻", "石头": "10007"}。

    优先 aliases.json；老文件 nicknames.json 继续兼容（T9 收口，不再生成）。
    值可以是官方名（任意语言）或角色 ID。以 _ 开头的键当注释。
    """
    for fname in (ALIAS_FILE, LEGACY_ALIAS_FILE):
        p = os.path.join(data_dir, fname)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        return {normalize(k): str(v) for k, v in raw.items() if not str(k).startswith("_")}
    return {}


# ------------------------------------------------------------------ 形态
# 名字里的形态后缀，如「星野（泳装）」「Hoshino (Swimsuit)」「ホシノ（水着）」
_NAME_VARIANT_RE = re.compile(
    r"^\s*(?P<base>.+?)\s*[（(]\s*(?P<variant>[^）)]+?)\s*[）)]\s*$"
)


def _split_variant(name: str) -> tuple[str, str]:
    """「星野（泳装）」-> ("星野", "泳装")；没有括号 -> (原名, "")。"""
    m = _NAME_VARIANT_RE.match(name or "")
    if not m:
        return (name or "").strip(), ""
    return m.group("base").strip(), m.group("variant").strip()


def _name_variants(name: str) -> list[str]:
    """按「基名（形态）」命名规范自动派生别名，**不枚举形态词表**。

    例：星野（泳装） -> ["泳装星野", "星野泳装"]
        Hoshino (Swimsuit) -> ["Swimsuit Hoshino", "Hoshino Swimsuit"]
    """
    base, variant = _split_variant(name)
    if not base or not variant:
        return []
    out = [f"{variant}{base}", f"{base}{variant}"]
    # 英文习惯带空格，额外生成一份带空格的
    if re.search(r"[A-Za-z]", base) or re.search(r"[A-Za-z]", variant):
        out += [f"{variant} {base}", f"{base} {variant}"]
    return out


# ------------------------------------------------------------------ 档案
_KIVO_LANGS = ("zh", "cn", "tw", "jp", "kr", "en")
_NICK_SPLIT_RE = re.compile(r"[，,、/／；;]")


def _kivo_aliases(entry: dict) -> list[str]:
    """kivo 能参与匹配的写法：三套中文 + 日/韩/英的名单写与全名 + 官方绰号。"""
    out: list[str] = []
    for lang in _KIVO_LANGS:
        given = (entry.get(lang) or "").strip()
        family = (entry.get("family_" + lang) or "").strip()
        if given:
            out.append(given)
        if family and given:
            out.append(f"{family} {given}" if lang == "en" else f"{family}{given}")
    for nick in _NICK_SPLIT_RE.split(entry.get("nick") or ""):
        nick = nick.strip()
        if nick:
            out.append(nick)
    return out


def _display_name(rec: dict, by_lang: dict, entry: dict | None) -> str:
    """按 GOALS 的显示策略算一个学生的显示名。"""
    schale_zh = by_lang.get(schaledb.PRIMARY_LANG) or str(rec.get("Name") or "")
    base_zh, schale_tag = _split_variant(schale_zh)
    if not entry:
        return schale_zh or by_lang.get("en") or str(rec.get("Id") or "")

    released_cn = bool((rec.get("IsReleased") or [True, True, True])[1])
    cn_given = (entry.get("cn") or entry.get("zh") or "").strip()
    tag = (schale_tag or entry.get("skin_cn") or entry.get("skin") or "").strip()

    if released_cn:
        name = cn_given or base_zh
        return f"{name}（{tag}）" if tag else name

    family = (entry.get("family_cn") or entry.get("family_zh") or "").strip()
    core = f"{family}{cn_given or base_zh}"
    if tag:
        core = f"{core}（{tag}）"
    jp = (entry.get("jp") or by_lang.get("jp") or "").strip()
    if not jp:
        return core
    return f"{core}（{jp}{entry.get('skin_jp') or ''}）"


def build_profiles(students: dict, names: dict, kv: dict[str, dict]) -> dict[str, dict]:
    """每个学生一条档案：SchaleDB 名 + kivo 补充 + 显示名 + 可匹配别名。"""
    out: dict[str, dict] = {}
    for sid, rec in students.items():
        sid = str(sid)
        by_lang = names.get(sid) or {}
        entry = kv.get(sid)
        profile = {
            "id": sid,
            "dev": str(rec.get("DevName") or "").upper(),
            "released_cn": bool((rec.get("IsReleased") or [True, True, True])[1]),
            "names": by_lang,
            "kivo": entry,
            "display": _display_name(rec, by_lang, entry),
        }
        out[sid] = profile
    return out


# ------------------------------------------------------------------ 索引
def build_index(students: dict, names: dict, profiles: dict, aliases: dict) -> dict[str, list[tuple[str, str, str]]]:
    """归一化别名 -> [(角色ID, 来源, 原始写法)]"""
    index: dict[str, list[tuple[str, str, str]]] = {}

    def add(key: str, sid: str, source: str, alias: str) -> None:
        key = normalize(key)
        if key:
            index.setdefault(key, []).append((sid, source, alias))

    for sid in students:
        sid = str(sid)
        for lang, name in (names.get(sid) or {}).items():
            add(name, sid, lang, name)
            # 派生「形态前置」别名，如 泳装星野
            for alt in _name_variants(name):
                add(alt, sid, f"{lang}-variant", alt)
        dev = str(students[sid].get("DevName") or "")
        if dev:
            add(dev, sid, "dev", dev)
        profile = profiles.get(sid) or {}
        for alias in _kivo_aliases(profile.get("kivo") or {}):
            add(alias, sid, "kivo", alias)

    for key, target in aliases.items():
        if not key:
            continue
        resolved = _resolve_alias_target(target, names, profiles)
        if resolved:
            index.setdefault(key, []).append((resolved, "alias", target))
        else:
            logger.warning(f"[ba_wiki] 别名 {target!r} 找不到对应学生，已忽略（别名表：{ALIAS_FILE}）")
    return index


def _resolve_alias_target(target: str, names: dict, profiles: dict) -> str | None:
    """别名表的值 -> 角色 ID。支持官方名（任意语言）、DevName、显示名、角色 ID。"""
    want = normalize(target)
    for sid, by_lang in names.items():
        if target == str(sid) or want in {normalize(v) for v in by_lang.values()}:
            return str(sid)
    for sid, profile in profiles.items():
        if want and want in (normalize(profile.get("display") or ""), normalize(profile.get("dev") or "")):
            return str(sid)
    return None


_CACHE: dict[str, tuple] = {}
_CACHE_TTL = 300  # 秒，避免每次查询都重建索引


def invalidate(data_dir: str) -> None:
    """数据刷新后清掉内存索引，立即生效。"""
    _CACHE.pop(str(data_dir), None)


def load_all(data_dir: str) -> dict:
    """一次性拿到 students / names / profiles / index / 形态词，带 5 分钟内存缓存。"""
    key = str(data_dir)
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    students = schaledb.students(key)
    names = schaledb.names(key)
    # kivo 只读磁盘缓存：全量抓取很慢，刷新交给插件的后台任务
    kv = kivo_src.by_schale_id(key, refresh=False)
    profiles = build_profiles(students, names, kv)
    index = build_index(students, names, profiles, load_aliases(key))
    vwords = collect_variant_words(names)
    bundle = {
        "students": students,
        "names": names,
        "kivo": kv,
        "profiles": profiles,
        "index": index,
        "vwords": vwords,
    }
    _CACHE[key] = (now, bundle)
    return bundle


def collect_variant_words(names: dict) -> set[str]:
    """从所有语言的官方名里收集「形态」词（括号里的部分）。"""
    out: set[str] = set()
    for by_lang in names.values():
        for name in by_lang.values():
            _base, variant = _split_variant(name or "")
            v = normalize(variant)
            if v:
                out.add(v)
    return out


def base_names(names: dict) -> dict[str, list[str]]:
    """基名(归一化) -> 该基名下所有学生 ID（含本体与各形态）。"""
    out: dict[str, list[str]] = {}
    for sid, by_lang in names.items():
        seen: set[str] = set()
        for name in by_lang.values():
            base, _variant = _split_variant(name or "")
            base = normalize(base)
            if base and base not in seen:
                seen.add(base)
                out.setdefault(base, []).append(str(sid))
    return out


# ------------------------------------------------------------------ 解析
def resolve(data_dir: str, keyword: str, limit: int = 5) -> dict:
    """统一的「查学生」入口。判定链见模块文档。"""
    # 1) 只要精确命中（score==0）。子串/模糊命中一律不接受。
    strict = [h for h in search(data_dir, keyword, limit * 2) if h.get("score") == 0]
    if strict:
        return {"ok": True, "matches": strict[:limit]}

    bundle = load_all(data_dir)
    names = bundle["names"]
    profiles = bundle["profiles"]
    kw = normalize(keyword)
    bases = base_names(names)
    vwords = bundle["vwords"]

    # 2) 剥掉已知形态词，剩下的当基名；要求该学生的名字里确实含这个形态词
    for v in sorted(vwords, key=len, reverse=True):
        if len(kw) <= len(v):
            continue
        rest = ""
        if kw.startswith(v):
            rest = kw[len(v):]
        elif kw.endswith(v):
            rest = kw[: len(kw) - len(v)]
        if not rest:
            continue
        for sid in bases.get(rest) or []:
            by_lang = names.get(sid) or {}
            if any(v in normalize(n) for n in by_lang.values()):
                nm = (profiles.get(sid) or {}).get("display") or by_lang.get("en")
                if nm:
                    return {"ok": True, "matches": [{
                        "id": sid, "score": 0, "name": nm, "display": nm,
                        "matched_lang": "variant", "matched_alias": nm,
                    }]}

    # 3) 基名对得上但形态词不认识 -> 给候选（形态在前，本体在最后）
    hit_base = ""
    for base in bases:
        if len(base) >= 2 and base in kw and len(base) > len(hit_base):
            hit_base = base
    if hit_base:
        variants_first: list[tuple[int, str]] = []
        for sid in bases.get(hit_base) or []:
            profile = profiles.get(sid) or {}
            nm = profile.get("display") or (names.get(sid) or {}).get(schaledb.PRIMARY_LANG)
            if not nm:
                continue
            variants_first.append((0 if _NAME_VARIANT_RE.match(nm) else 1, nm))
        sugg: list[str] = []
        for _k, nm in sorted(variants_first, key=lambda x: x[0]):
            if nm not in sugg:
                sugg.append(nm)
        if sugg:
            return {"ok": False, "kind": "variant", "suggest": sugg[:limit]}

    # 4) 拼写问题
    return {"ok": False, "kind": "typo", "suggest": suggest(data_dir, keyword)}


# ------------------------------------------------------------------ 检索
def search(data_dir: str, keyword: str, limit: int = 5) -> list[dict]:
    """跨语言 + kivo 补充名 + 绰号 + 形态组合 + 模糊匹配。返回按质量排序的候选。"""
    bundle = load_all(data_dir)
    students = bundle["students"]
    index = bundle["index"]
    profiles = bundle["profiles"]
    kw = normalize(keyword)
    if not kw:
        return []

    hits: dict[str, dict] = {}

    def add(sid: str, score: int, lang: str, alias: str) -> None:
        cur = hits.get(sid)
        if cur is None or score < cur["_score"]:
            hits[sid] = {"_score": score, "id": sid, "lang": lang, "alias": alias}

    # 1) 精确（任意语言 / kivo 补充名 / 绰号 / 别名 / DevName / ID）
    for sid, lang, alias in index.get(kw, []):
        add(sid, 0, lang, alias)
    if kw in {normalize(k) for k in students.keys()}:
        add(kw, 0, "id", kw)

    # 2) 子串（双向），至少 2 字避免噪音
    if not hits and len(kw) >= 2:
        for alias_key, entries in index.items():
            if kw in alias_key or (len(alias_key) >= 2 and alias_key in kw):
                for sid, lang, alias in entries:
                    add(sid, 1 if kw == alias_key else 2, lang, alias)

    # 3) 模糊
    if not hits:
        cutoff = 0.75 if len(kw) <= 3 else 0.65
        for alias_key in difflib.get_close_matches(kw, list(index.keys()), n=limit, cutoff=cutoff):
            for sid, lang, alias in index[alias_key]:
                add(sid, 3, lang, alias)

    ordered = sorted(hits.values(), key=lambda h: (h["_score"], len(h["alias"])))[:limit]
    out = []
    for h in ordered:
        sid = h["id"]
        profile = profiles.get(sid) or {}
        out.append({
            "id": sid,
            "score": h["_score"],
            "matched_lang": h["lang"],
            "matched_alias": h["alias"],
            "name": profile.get("display") or (bundle["names"].get(sid) or {}).get(schaledb.PRIMARY_LANG) or sid,
            "display": profile.get("display") or "",
        })
    return out


def suggest(data_dir: str, keyword: str, limit: int = 3) -> list[str]:
    """没命中时给「你是不是想找」。

    短词（1~2 字）用更高的相似度门槛：kivo 带来了大量「姓+名」全名，门槛太低会把
    「若狹冬」这种无关长名混进来，反而挤掉真正该给的候选。
    """
    bundle = load_all(data_dir)
    index = bundle["index"]
    profiles = bundle["profiles"]
    kw = normalize(keyword)
    if not kw:
        return []
    cutoff = 0.5 if len(kw) <= 2 else 0.3
    cands = difflib.get_close_matches(kw, list(index.keys()), n=limit * 3, cutoff=cutoff)
    out, seen = [], set()
    for c in cands:
        for sid, _lang, _alias in index[c]:
            nm = (profiles.get(sid) or {}).get("display")
            if nm and nm not in seen:
                seen.add(nm)
                out.append(nm)
            break
        if len(out) >= limit:
            break
    # 同一基名的多个形态一起出现时，把本体排到最前面（「星也」-> 星野 优先）
    bases = {_split_variant(nm)[0] for nm in out if not _split_variant(nm)[1]}
    out.sort(key=lambda nm: 1 if (_split_variant(nm)[1] and _split_variant(nm)[0] in bases) else 0)
    return out[:limit]


# ------------------------------------------------------------------ 显示名
def display_name(data_dir: str, cid) -> str:
    """角色 ID -> 显示名（按 T4 的显示策略）。"""
    bundle = load_all(data_dir)
    profile = bundle["profiles"].get(str(cid))
    if profile:
        return profile["display"]
    by = bundle["names"].get(str(cid)) or {}
    return by.get(schaledb.PRIMARY_LANG) or by.get("en") or str(cid)
