"""kivo.wiki 数据源：三套并列中文名 + 官方绰号，按 DevName 与 SchaleDB 关联。

要解决的问题（见 GOALS.md）：
  - SchaleDB 的 zh 是「通用中文」（阿露），不是国服译名（爱露），也没有官方绰号
  - kivo 同时给 given_name / given_name_cn / given_name_zh_tw / nick_name 四套
  - 未上线角色的 SchaleDB 中文名不可靠（椎名纺在 SchaleDB 里是「䌷」）

关联主键是游戏角色代号（DevName），**不是名字**（两次踩坑都是名字）。
  kivo 详情里的 character_datas[].dev_name 就是 "CH0252"，avatar 路径里也有
  Student_Portrait_CH0252_... → 与 SchaleDB 的 DevName 同源。

缓存：全量 510 条详情一次拉完写 kivo_students.json（24h 内不再请求）。

对外接口：
    records(data_dir=None)    -> list[detail]（已裁剪，只留名字/立绘/角色代号相关字段）
    by_devname(data_dir=None) -> {"CH0252": {zh, cn, tw, jp, kr, en, nick, ...}}
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

BASE = "https://api.kivo.wiki/api/v1/data/students"
CACHE_FILE = "kivo_students.json"
CACHE_TTL = int(os.environ.get("BA_WIKI_KIVO_TTL", str(24 * 3600)))  # 秒
PAGE_SLEEP = 0.12        # 分页/详情之间的礼貌间隔
TIMEOUT = 40

UA = {"User-Agent": "Mozilla/5.0 (compatible; astrbot-ba-wiki/0.7)"}
DEVNAME_RE = re.compile(r"Student_Portrait_([A-Za-z0-9]+)", re.I)

_DEFAULT_DIR: list[str | None] = [None]


# ------------------------------------------------------------------ 目录
def configure(data_dir: str | None) -> None:
    _DEFAULT_DIR[0] = str(data_dir) if data_dir else None


def _resolve(dir_path: str | None = None) -> str:
    d = dir_path if dir_path is not None else _DEFAULT_DIR[0]
    if not d:
        raise RuntimeError("kivo 数据目录未配置：先调用 kivo.configure(data_dir)")
    return str(d)


# ------------------------------------------------------------------ 抓取
def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def dev_of(rec: dict) -> str:
    """从 kivo 记录里取 DevName：优先 character_datas，其次 avatar 路径。"""
    for ch in rec.get("character_datas") or []:
        dev = str(ch.get("dev_name") or "").strip()
        if dev:
            return dev.upper()
    for url in [rec.get("avatar")] + [s.get("avatar") for s in rec.get("skin_list") or []]:
        m = DEVNAME_RE.search(str(url or ""))
        if m:
            return m.group(1).upper()
    return ""


def _trim(rec: dict) -> dict:
    """只留需要的字段：缓存文件更小，也不怕上游加字段。"""
    chars = [{"character_id": ch.get("character_id"), "dev_name": ch.get("dev_name")}
             for ch in rec.get("character_datas") or []]
    skins = [{"id": s.get("id"), "skin": s.get("skin"), "skin_cn": s.get("skin_cn")}
             for s in rec.get("skin_list") or []]
    return {
        "id": rec.get("id"),
        "family_name": rec.get("family_name"),
        "family_name_cn": rec.get("family_name_cn"),
        "family_name_zh_tw": rec.get("family_name_zh_tw"),
        "family_name_jp": rec.get("family_name_jp"),
        "family_name_kr": rec.get("family_name_kr"),
        "family_name_en": rec.get("family_name_en"),
        "given_name": rec.get("given_name"),
        "given_name_cn": rec.get("given_name_cn"),
        "given_name_zh_tw": rec.get("given_name_zh_tw"),
        "given_name_jp": rec.get("given_name_jp"),
        "given_name_kr": rec.get("given_name_kr"),
        "given_name_en": rec.get("given_name_en"),
        "nick_name": rec.get("nick_name") or "",
        "skin": rec.get("skin") or "",
        "skin_cn": rec.get("skin_cn") or "",
        "skin_jp": rec.get("skin_jp") or "",
        "skin_zh_tw": rec.get("skin_zh_tw") or "",
        "avatar": rec.get("avatar"),
        "character_datas": chars,
        "skin_list": skins,
    }


def _fetch_all() -> list[dict]:
    """分页拿全量 id，再逐条取详情。单条失败不致命。"""
    first = _get(BASE + "/").get("data") or {}
    max_page = int(first.get("max_page") or 1)
    ids = [s["id"] for s in (first.get("students") or []) if s.get("id")]
    for page in range(2, max_page + 1):
        try:
            data = _get("%s/?page=%d" % (BASE, page)).get("data") or {}
        except Exception:  # noqa: BLE001
            continue
        ids += [s["id"] for s in (data.get("students") or []) if s.get("id")]
        time.sleep(PAGE_SLEEP)

    out: list[dict] = []
    for i, sid in enumerate(ids, 1):
        try:
            detail = _get("%s/%s" % (BASE, sid)).get("data") or {}
        except Exception:  # noqa: BLE001
            continue
        if detail:
            out.append(_trim(detail))
        if i % 25 == 0:
            time.sleep(PAGE_SLEEP)
    return out


# ------------------------------------------------------------------ 缓存与读接口
def cache_path(data_dir: str | None = None) -> str:
    return os.path.join(_resolve(data_dir), CACHE_FILE)


def _load_cache(dir_path: str) -> dict:
    p = os.path.join(dir_path, CACHE_FILE)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def records(data_dir: str | None = None, refresh: bool = True, force: bool = False) -> list[dict]:
    """全量 kivo 记录（带 24h 磁盘缓存）。抓取失败时退回旧缓存。

    force=True 无视缓存直接重抓（sync_data.py 手动同步用）。
    """
    dir_path = _resolve(data_dir)
    os.makedirs(dir_path, exist_ok=True)
    cache = _load_cache(dir_path)
    fresh = bool(cache) and (time.time() - float(cache.get("fetched_at") or 0) < CACHE_TTL)
    if not force and (fresh or not refresh):
        return cache.get("records") or []

    try:
        fetched = _fetch_all()
    except Exception:  # noqa: BLE001
        return cache.get("records") or []
    if not fetched:
        return cache.get("records") or []

    with open(os.path.join(dir_path, CACHE_FILE), "w", encoding="utf-8") as f:
        json.dump({"fetched_at": time.time(), "records": fetched}, f, ensure_ascii=False)
    return fetched


def _entries(recs: list[dict]) -> list[dict]:
    """把裁剪后的 kivo 记录整理成「名称补充」条目（含它覆盖的所有 SchaleDB Id）。"""
    out: list[dict] = []
    for rec in recs:
        dev = dev_of(rec)
        ids = [str(c.get("character_id")) for c in rec.get("character_datas") or []
               if c.get("character_id")]
        entry = {
            "kivo_id": rec.get("id"),
            "dev": dev,
            "schale_id": int(ids[0]) if ids else None,
            "_schale_ids": ids,
            "zh": rec.get("given_name") or "",
            "cn": rec.get("given_name_cn") or "",
            "tw": rec.get("given_name_zh_tw") or "",
            "jp": rec.get("given_name_jp") or "",
            "kr": rec.get("given_name_kr") or "",
            "en": rec.get("given_name_en") or "",
            "nick": rec.get("nick_name") or "",
            "family_zh": rec.get("family_name") or "",
            "family_cn": rec.get("family_name_cn") or "",
            "family_tw": rec.get("family_name_zh_tw") or "",
            "family_jp": rec.get("family_name_jp") or "",
            "family_kr": rec.get("family_name_kr") or "",
            "family_en": rec.get("family_name_en") or "",
            "skin": rec.get("skin") or "",
            "skin_cn": rec.get("skin_cn") or "",
            "skin_jp": rec.get("skin_jp") or "",
        }
        out.append(entry)
    return out


def by_schale_id(data_dir: str | None = None, refresh: bool = False) -> dict[str, dict]:
    """{SchaleDB Id: 名称补充}，合并时按这个键挂。

    kivo 记录里的 character_datas[].character_id 就是 SchaleDB 的 Id，实测 278/278 全覆盖；
    而 DevName 有 _DEFAULT / _SWIMSUIT 之类后缀、与 SchaleDB 并不同源（只覆盖 187/278），
    所以合并主键用 Id，DevName 只用于人工核对。

    refresh=False（默认）只读磁盘缓存：查询路径上不能因为 kivo 全量抓取（约 2 分钟）卡住，
    刷新交给插件启动时的后台任务或 workers。
    """
    out: dict[str, dict] = {}
    for entry in _entries(records(data_dir, refresh=refresh)):
        ids = entry.pop("_schale_ids")
        for cid in ids:
            old = out.get(cid)
            if old is None or (old.get("skin") and not entry.get("skin")):
                out[cid] = dict(entry)
    return out


def by_devname(data_dir: str | None = None, refresh: bool = False) -> dict[str, dict]:
    """{DevName: 名称补充}，键统一大写（CH0252）。

    只覆盖 187/278（见 by_schale_id 的说明），保留给 DevName 查询和交叉校验用。
    """
    out: dict[str, dict] = {}
    for entry in _entries(records(data_dir, refresh=refresh)):
        dev = entry.get("dev")
        if dev:
            out.setdefault(dev, dict(entry))
    return out
