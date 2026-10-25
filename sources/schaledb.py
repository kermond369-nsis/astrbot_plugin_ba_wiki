"""SchaleDB 数据源：students.json 的下载、ETag 条件刷新与七语言名称表。

上层只用两个读接口，不要再自己拼路径、自己 json.load：
    students(data_dir=None) -> {id: record}           缺失/过期时会自动同步
    names(data_dir=None)    -> {id: {lang: name}}

数据目录由上层 schaledb.configure(data_dir) 指定（测试里也可以显式传参）。

七套名称共用同一批角色 ID：
  zh 国服简体（输出用）/ tw 繁中 / en 英文 / jp 日文 / kr 韩文 / th 泰文 / vi 越南文

追新策略（三级）：
  1. 缓存缺失                     -> 全量下载 + 重建名称表
  2. 距上次检查 >= CHECK_INTERVAL -> 带 If-None-Match 条件请求
                                    304 表示上游没变，零下载；200 则替换并重建名称表
  3. 距文件修改 > MAX_AGE_SECONDS  -> 无条件全量下载（防止上游不返回 ETag）
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://schaledb.com/data/{lang}/students.json"
# 顺序有意义：第一个是输出用语言（国服简体）
LANGS = ["zh", "tw", "en", "jp", "kr", "th", "vi"]
PRIMARY_LANG = "zh"
LANG_CN = {"zh": "国服", "tw": "繁中", "en": "英文", "jp": "日服", "kr": "韩文", "th": "泰文", "vi": "越南文"}

MAX_AGE_SECONDS = 7 * 24 * 3600

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}

CHECK_INTERVAL = int(os.environ.get("BA_WIKI_CHECK_INTERVAL", "3600"))  # 秒：多久探一次上游

STUDENTS_FILE = "students_zh.json"
NAMES_FILE = "names.json"
META_FILE = "meta.json"
EQUIP_FILE = "equipment_zh.json"
EQUIP_URL = "https://schaledb.com/data/zh/equipment.min.json"

_DEFAULT_DIR: list[str | None] = [None]


# ------------------------------------------------------------------ 目录
def configure(data_dir: str | None) -> None:
    """指定默认数据目录（插件启动时调一次）。"""
    _DEFAULT_DIR[0] = str(data_dir) if data_dir else None


def _resolve(dir_path: str | None = None) -> str:
    d = dir_path if dir_path is not None else _DEFAULT_DIR[0]
    if not d:
        raise RuntimeError("SchaleDB 数据目录未配置：先调用 schaledb.configure(data_dir)")
    return str(d)


# ------------------------------------------------------------------ 装备表
def equipment(data_dir: str | None = None, force: bool = False) -> dict[int, dict]:
    """装备表 {Id: 记录}，用于面板计算。缓存 7 天，缺失/过期时下载。"""
    d = _resolve(data_dir)
    path = os.path.join(d, EQUIP_FILE)

    def _load() -> dict[int, dict]:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.values() if isinstance(raw, dict) else raw
        return {int(item["Id"]): item for item in items}

    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE_SECONDS
    if fresh and not force:
        try:
            return _load()
        except Exception:  # noqa: BLE001
            pass
    try:
        status, body, _etag = _download(EQUIP_URL)
        if status == 200 and body:
            os.makedirs(d, exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
            return _load()
    except Exception:  # noqa: BLE001
        pass
    if os.path.exists(path):
        return _load()
    raise FileNotFoundError("装备表缺失且下载失败：schaledb.com/equipment")


# ------------------------------------------------------------------ 下载与缓存
def _download(url: str, etag: str | None = None) -> tuple[int, bytes | None, str | None]:
    """返回 (http 状态, 内容, 新 etag)。304 时内容为 None。"""
    headers = dict(HEADERS)
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)  # 不带 UA 会被 CDN 拒（403）
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read(), resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, None
        raise


def _load_meta(dir_path: str) -> dict:
    p = os.path.join(dir_path, META_FILE)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_meta(dir_path: str, meta: dict) -> None:
    try:
        with open(os.path.join(dir_path, META_FILE), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def _write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _fetch_names(lang: str) -> dict:
    _status, raw, _etag = _download(BASE.format(lang=lang))
    obj = json.loads(raw or b"{}")
    items = obj.values() if isinstance(obj, dict) else obj
    return {str(s.get("Id")): str(s.get("Name") or "") for s in items if s.get("Id")}


def _rebuild_names(dir_path: str) -> None:
    merged: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        try:
            for sid, name in _fetch_names(lang).items():
                if name:
                    merged.setdefault(sid, {})[lang] = name
        except Exception:  # noqa: BLE001
            continue  # 少一种语言不致命
    if merged:
        with open(os.path.join(dir_path, NAMES_FILE), "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)


def refresh(data_dir: str | None = None) -> bool:
    """按策略检查上游；返回「这次是否真的改了数据」。304/未到期时为 False。"""
    dir_path = _resolve(data_dir)
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, STUDENTS_FILE)
    meta = _load_meta(dir_path)
    now = time.time()
    names_dirty = not os.path.exists(os.path.join(dir_path, NAMES_FILE))
    changed = False

    if not os.path.exists(path):
        _status, body, etag = _download(BASE.format(lang=PRIMARY_LANG))
        if body:
            _write_atomic(path, body)
            meta.update({"etag": etag, "checked_at": now})
            changed = names_dirty = True
    elif now - os.path.getmtime(path) > MAX_AGE_SECONDS:
        _status, body, etag = _download(BASE.format(lang=PRIMARY_LANG))
        if body:
            _write_atomic(path, body)
            meta.update({"etag": etag, "checked_at": now})
            changed = names_dirty = True
    elif now - float(meta.get("checked_at") or 0) >= CHECK_INTERVAL:
        try:
            status, body, etag = _download(BASE.format(lang=PRIMARY_LANG), meta.get("etag"))
            if status == 304:
                meta["checked_at"] = now          # 上游未变，零下载
            elif body:
                _write_atomic(path, body)
                meta.update({"etag": etag, "checked_at": now})
                changed = names_dirty = True
        except Exception:  # noqa: BLE001
            meta["checked_at"] = now              # 探测失败也别高频重试
    _save_meta(dir_path, meta)

    if names_dirty:
        _rebuild_names(dir_path)
    return changed


# ------------------------------------------------------------------ 读接口
def students(data_dir: str | None = None) -> dict:
    """{id: record}。调用时按追新策略自检一次（未到期/304 都是零下载）。"""
    dir_path = _resolve(data_dir)
    refresh(dir_path)
    with open(os.path.join(dir_path, STUDENTS_FILE), encoding="utf-8") as f:
        return json.load(f)


def names(data_dir: str | None = None) -> dict:
    """{id: {lang: name}}。名称表缺失时返回空字典（不抛错）。"""
    p = os.path.join(_resolve(data_dir), NAMES_FILE)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)
