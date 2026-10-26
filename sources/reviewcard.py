"""角色测评卡：gamekee 碧蓝档案 wiki 的「角色评分」表，由校委会攻略组制作。

为什么用它：群里问「XX 值不值得抽 / 强不强 / 就业行不行」，需要的不是几个数值，
而是一张把强度评级、就业场合、抽取建议放在一起的卡。这类卡由校委会攻略组维护在
gamekee（ba.gamekee.com），按学园分篇发布，每篇里一个角色配一张图。

数据链路（全部是公开接口，不需要登录）：

    1. POST 无、GET https://www.gamekee.com/v1/content/searchArticle?keyword=角色评分
       -> 各学园的文章 id（标题形如「角色评分8.0版 - 瓦尔基里警察学校」）
    2. GET https://www.gamekee.com/v1/content/detail/{id}
       -> data.content_cdn（正文 JSON 在 CDN 上，正文本身是「块」的 JSON 数组）
    3. GET content_cdn -> [{type, children:[...]}, ...]
       每个角色一个 paragraph（粗体角色名 + 活动说明），紧跟一个含 image 的 paragraph
    4. 图片 http://cdnimg-v2.gamekee.com/... -> 下载到本地缓存再发给消息平台

索引按 **SchaleDB Id** 存，和 directory.resolve 的结果对齐；名字解析失败的字串
（「看前必读」「3星限定」这类卡片标题）在同步时就被丢掉，所以索引里都是真角色。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from . import schaledb

# ---------------------------------------------------------------- 常量
API_ROOT = "https://www.gamekee.com/v1"
GAME_ALIAS = "ba"
INDEX_FILE = "review_cards.json"
IMAGE_DIR = "review_cards"
CACHE_TTL = 7 * 24 * 3600          # 一周同步一次就够：评分表更新很慢
MAX_ARTICLES = 30
MIN_VERSION = 8.0                  # 7.x 那批是旧版式（表格块），8.0 起才是这套卡片
ARTICLE_KEYWORD = "角色评分"
# 卡片上的写法与图鉴/名称表对不上的，逐个补（gamekee 角评页自身的笔误/旧译名）。
# 只做「写法 -> 我们的名字」的映射，解析不出来依旧丢弃，不会硬塞给某个角色。
NAME_FIXUPS = {
    "美祢": "美弥",
    "美弥(偶像)": "美祢（偶像）",
    "初音": "未来",
    "食蜂": "操祈",
    "妮娅": "尼娅",
    "蕾娜": "莱娜",
    "莱伊": "莱依",
    "绮良良": "绮罗罗",
    "晴(野营)": "晴（露营）",
    "小玉(野营)": "小玉（露营）",
    "芹娜(圣诞)": "芹娜（圣诞节）",
    "花江(圣诞)": "花江（圣诞节）",
    "御坂": "美琴",          # 超电磁炮联动：卡片只印姓氏
    "佐天": "泪子",
    "玛丽娜(旗袍)": "真里奈（旗袍）",
}
# 栏目标题 / 分隔说明，不该拿去做名字解析
_SKIP_NAME_RE = re.compile(
    r"^(超级长文|看前必读|食用说明|.{0,4}星(限定|常驻)|1&2星|全部角色|目录|前言|后记)|^[\s\u200b\uFEFF]*$"
)
_VERSION_RE = re.compile(r"角色评分\s*(?P<v>\d+(?:\.\d+)?)\s*版")
ATTRIBUTION = "测评卡：gamekee 碧蓝档案 wiki · 校委会攻略组（ba.gamekee.com）"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "X-Requested-With": "XMLHttpRequest",
    "game-alias": GAME_ALIAS,
    "Lang": "zh-cn",
    "Referer": "https://www.gamekee.com/ba/",
    "Accept": "application/json, text/plain, */*",
}
# CDN 的 WAF 反过来挑头：带 game-alias / X-Requested-With 会直接 567，
# 只认 User-Agent + Referer。图片也一样。
_CDN_HEADERS = {"User-Agent": _UA, "Referer": "https://www.gamekee.com/"}

_configured_dir: str | None = None


def configure(data_dir: str | None) -> None:
    """由插件初始化时注入数据目录（和 schaledb / kivo 一样的用法）。"""
    global _configured_dir
    _configured_dir = str(data_dir) if data_dir else None


def _dir(data_dir: str | None = None) -> str:
    return str(data_dir or _configured_dir or os.path.join(os.getcwd(), "data", "ba_wiki"))


# ---------------------------------------------------------------- IO
def _http_json(url: str, timeout: int = 25, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=dict(headers or _HEADERS))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _download(url: str, dest: str, timeout: int = 40) -> bool:
    """下载到本地；先写 .part 再原子改名，避免半截文件被当成缓存。"""
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=_CDN_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 1024:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return True
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def index_path(data_dir: str | None = None) -> str:
    return os.path.join(_dir(data_dir), INDEX_FILE)


def image_path(data_dir: str | None, url: str) -> str:
    name = hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:16] + ".png"
    return os.path.join(_dir(data_dir), IMAGE_DIR, name)


def _load_index(data_dir: str | None = None) -> dict:
    p = index_path(data_dir)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_index(data_dir: str | None, index: dict) -> None:
    p = index_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------- 解析
def _texts(node) -> str:
    """把一个块里所有 text 片段拼起来（角色名和活动说明在同一个 paragraph 里分几段）。"""
    out: list[str] = []

    def rec(n):
        if isinstance(n, list):
            for x in n:
                rec(x)
            return
        if not isinstance(n, dict):
            return
        if isinstance(n.get("text"), str):
            out.append(n["text"])
        for c in n.get("children") or []:
            rec(c)

    rec(node)
    return "".join(out).strip()


def _first_image(node) -> str:
    def rec(n):
        if isinstance(n, list):
            for x in n:
                yield from rec(x)
            return
        if not isinstance(n, dict):
            return
        src = n.get("src")
        if n.get("type") == "image" and isinstance(src, str) and src:
            yield src
            return
        for c in n.get("children") or []:
            yield from rec(c)

    for s in rec(node):
        return s
    return ""


def _normalize_image(src: str) -> str:
    src = (src or "").strip()
    if src.startswith("//"):
        return "https:" + src
    return src


def _has_image(node) -> bool:
    if isinstance(node, list):
        return any(_has_image(x) for x in node)
    if not isinstance(node, dict):
        return False
    if node.get("type") == "image" and node.get("src"):
        return True
    return any(_has_image(c) for c in node.get("children") or [])


def _ordered_events(node, out: list) -> None:
    """按文档顺序吐出 ("text", 文本) / ("img", 地址)。"""
    if isinstance(node, list):
        for x in node:
            _ordered_events(x, out)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "image":
        src = node.get("src")
        if isinstance(src, str) and src:
            out.append(("img", src))
        return
    text = node.get("text")
    if isinstance(text, str) and text.strip():
        out.append(("text", text))
    for c in node.get("children") or []:
        _ordered_events(c, out)


def _line(texts: list[str]) -> str:
    # gamekee 编辑器会在名字前后塞零宽字符（\u200b / \ufeff），不剔掉会解析不到
    raw = " ".join(" ".join(texts).split())
    return raw.strip(_ZERO_WIDTH)


_ZERO_WIDTH = "\u200b\u200c\u200d\ufeff\u2060"


def pairs_from_blocks(blocks) -> list[dict]:
    """块数组 -> [{"name": 角色名, "note": 活动说明, "image": 卡片图}]。

    卡片是「一行角色名（+活动说明）→ 图片」交替，但版式有两种：
      · 名字、说明、图片挤在同一个 paragraph 里（三一 / 阿拜多斯页）
      · 名字一个 paragraph、图片一个 paragraph，中间还夹着「3星限定」这类栏目标题
        （千年 / 红冬页）
    所以按块顺序扫：块内文本拼成一行，遇到图片就用**最近那一行**当角色名。
    名字取行首那个词（「康娜(泳装) 泳七「Say-Bing!」…」-> 「康娜(泳装)」）。
    """
    if not isinstance(blocks, list):
        return []

    flat: list = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "flod":
            flat.extend(b.get("children") or [])
        else:
            flat.append(b)

    out: list[dict] = []
    prev_line = ""
    for block in flat:
        if not isinstance(block, dict):
            continue
        if not _has_image(block):
            text = _line([_texts(block)]) if _texts(block) else ""
            if text:
                prev_line = text
            continue
        buf: list[str] = []
        events: list[tuple[str, str]] = []
        _ordered_events(block, events)
        for kind, value in events:
            if kind == "text":
                buf.append(value)
                continue
            line = _line(buf) or prev_line
            buf = []
            if not line:
                continue
            prev_line = line
            name = re.split(r"[\s\u3000]+", line)[0]
            if name:
                out.append({"name": name, "note": line[len(name):].strip(),
                            "image": _normalize_image(value)})
        tail = _line(buf)
        if tail:
            prev_line = tail
    return out


def _article_version(title: str) -> float:
    m = _VERSION_RE.search(title or "")
    try:
        return float(m.group("v")) if m else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 同步
def search_articles() -> list[dict]:
    """搜「角色评分」相关文章，只留标题是「角色评分 x.y 版 - 学园」的正文。"""
    q = urllib.parse.urlencode({"keyword": ARTICLE_KEYWORD, "page": 1, "limit": 50})
    data = _http_json(f"{API_ROOT}/content/searchArticle?{q}")
    items = data.get("data") or []
    arts = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        aid = it.get("id") or it.get("content_id")
        title = str(it.get("title") or "")
        if not aid or aid in seen or not _VERSION_RE.search(title):
            continue
        version = _article_version(title)
        if version < MIN_VERSION:
            continue                      # 7.x 是旧版式（表格块），解析不出卡片
        seen.add(aid)
        arts.append({"id": int(aid), "title": title, "version": version})
    arts.sort(key=lambda a: (-a["version"], a["id"]))
    return arts[:MAX_ARTICLES]


def article_blocks(content_id: int) -> list:
    """取一篇文章的正文块数组。正文在 CDN 上，先拿 content_cdn 再取 JSON。"""
    detail = _http_json(f"{API_ROOT}/content/detail/{int(content_id)}")
    if detail.get("code") != 0:
        raise RuntimeError(f"文章 {content_id} 打不开：{detail.get('msg')}")
    cdn = str(((detail.get("data") or {}).get("content_cdn")) or "")
    if not cdn:
        raise RuntimeError(f"文章 {content_id} 没有 content_cdn")
    payload = _http_json(_normalize_image(cdn), headers=_CDN_HEADERS)
    raw = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(raw, str):
        raise RuntimeError(f"文章 {content_id} 正文格式不认识")
    blocks = json.loads(raw)
    if not isinstance(blocks, list):
        raise RuntimeError(f"文章 {content_id} 正文不是块数组")
    return blocks


def _resolve_cid(data_dir: str, name: str) -> tuple[str, str] | None:
    """gamekee 的角色名 -> (SchaleDB Id, 显示名)。解析不了就丢掉（多是栏目标题）。"""
    try:
        from .. import directory          # 延迟导入：避免 sources <-> 顶层循环依赖
    except ImportError:                   # pragma: no cover  (直接当脚本跑时)
        import directory                  # type: ignore
    raw = (name or "").strip()
    if not raw:
        return None
    for cand in dict.fromkeys((NAME_FIXUPS.get(raw, raw), raw)):
        try:
            res = directory.resolve(data_dir, cand)
        except Exception:  # noqa: BLE001
            continue
        if not res.get("ok"):
            continue
        hit = (res.get("matches") or [{}])[0]
        cid = hit.get("id")
        if cid is not None:
            return str(cid), str(hit.get("name") or cand)
    return None


def build_index(data_dir: str | None = None, log=None) -> dict:
    """抓全部评分文章，重建成 {SchaleDB Id -> 卡片}。失败就抛，调用方保留旧索引。"""
    d = _dir(data_dir)
    say = log or (lambda *_a, **_k: None)
    articles = search_articles()
    if not articles:
        raise RuntimeError("没有搜到「角色评分」文章，上游可能改版了")

    entries: dict[str, dict] = {}
    done: list[dict] = []
    for art in articles:
        try:
            blocks = article_blocks(art["id"])
        except Exception as exc:  # noqa: BLE001
            say(f"[ba_wiki] 测评卡：跳过文章 {art['id']}（{exc}）")
            continue
        pairs = pairs_from_blocks(blocks)
        added = 0
        for p in pairs:
            if _SKIP_NAME_RE.search(p["name"]):
                continue
            got = _resolve_cid(d, p["name"])
            if not got:
                continue                      # 「看前必读」「3星限定」这类标题
            cid, display = got
            prev = entries.get(cid)
            if prev and prev.get("version", 0) >= art["version"]:
                continue                      # 已经拿到更新版本的卡
            entries[cid] = {
                "name": display,
                "raw_name": p["name"],
                "note": p.get("note") or "",
                "image": p["image"],
                "article": art["id"],
                "article_title": art["title"],
                "version": art["version"],
            }
            added += 1
        done.append({**art, "cards": added, "total": len(pairs)})
        say(f"[ba_wiki] 测评卡：{art['title']} -> {added}/{len(pairs)} 张")

    if not entries:
        raise RuntimeError("评分文章解析出 0 张卡，上游结构可能变了")
    index = {
        "updated": int(time.time()),
        "source": "gamekee 碧蓝档案 wiki · 校委会攻略组",
        "attribution": ATTRIBUTION,
        "articles": done,
        "entries": entries,
    }
    _save_index(d, index)
    return index


# ---------------------------------------------------------------- 对外
def cards(data_dir: str | None = None, refresh: bool = False, *, force: bool = False,
          ttl: int = CACHE_TTL, log=None) -> dict:
    """取索引；过期或缺失时同步一次。同步失败时退回旧索引（有就先用着）。"""
    d = _dir(data_dir)
    index = _load_index(d)
    fresh = bool(index.get("entries")) and not force and (
        ttl <= 0 or time.time() - int(index.get("updated") or 0) < ttl)
    if fresh and not refresh:
        return index
    try:
        return build_index(d, log=log)
    except Exception as exc:  # noqa: BLE001
        if index.get("entries"):
            (log or (lambda *_a, **_k: None))(f"[ba_wiki] 测评卡同步失败，继续用缓存：{exc}")
            return index
        raise


def find(data_dir: str | None, keyword: str) -> dict:
    """按用户说法查卡片：先解析学生，再查索引。"""
    d = _dir(data_dir)
    try:
        index = cards(d)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"测评卡索引暂时拿不到：{exc}"}

    entries = index.get("entries") or {}
    if not entries:
        return {"ok": False, "reason": "测评卡索引是空的"}

    try:
        from .. import directory
    except ImportError:                   # pragma: no cover
        import directory                  # type: ignore
    res = directory.resolve(d, keyword)
    if not res.get("ok"):
        return {"ok": False, "kind": res.get("kind"), "reason": "没有查询到此学生",
                "suggest": res.get("suggest") or []}

    hit = (res.get("matches") or [{}])[0]
    cid = hit.get("id")
    card = entries.get(str(cid))
    if not card:
        return {
            "ok": False,
            "reason": "这个角色还没有测评分（评分表按学园分篇，可能还没覆盖到）",
            "name": hit.get("name"),
            "have_total": len(entries),
        }
    return {
        "ok": True,
        "id": cid,
        "name": hit.get("name") or card.get("name"),
        "raw_name": card.get("raw_name"),
        "note": card.get("note"),
        "image": card.get("image"),
        "article": card.get("article"),
        "article_title": card.get("article_title"),
        "version": card.get("version"),
        "attribution": index.get("attribution") or ATTRIBUTION,
        "total": len(entries),
        "updated": index.get("updated"),
    }


def local_image(data_dir: str | None, url: str, force: bool = False) -> str | None:
    """把卡片图落到本地（消息平台发文件比发外链稳），返回本地路径或 None。"""
    if not url:
        return None
    dest = image_path(data_dir, url)
    if not force and os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return dest
    return dest if _download(url, dest) else None


def available(data_dir: str | None = None) -> int:
    """索引里有多少张卡（给 /ba 测评 的空状态提示用）。"""
    return len((_load_index(_dir(data_dir)).get("entries") or {}))
