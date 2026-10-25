"""B 站视频搜索（攻略/作业用）。

只用标准库。B 站搜索接口不带 Cookie 会返回 HTML 风控页，带任意 buvid3 即可。
结果缓存 10 分钟，避免被限流。
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://search.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    # 不带这个 Cookie 会返回风控 HTML 页
    "Cookie": "buvid3=8A1B2C3D-1234-5678-9ABC-DEF012345678infoc",
}

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 600


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def _fmt_date(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except Exception:  # noqa: BLE001
        return ""


def _fmt_play(n: int | None) -> str:
    try:
        n = int(n or 0)
    except Exception:  # noqa: BLE001
        return ""
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def search(keyword: str, limit: int = 5) -> dict:
    """搜索 B 站视频，返回标题/链接/播放量/日期。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "reason": "关键词为空", "videos": []}

    hit = _CACHE.get(kw)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return {"ok": True, "cached": True, "keyword": kw, "videos": hit[1][:limit]}

    params = urllib.parse.urlencode({
        "search_type": "video",
        "keyword": kw,
        "page": 1,
        "order": "totalrank",
    })
    req = urllib.request.Request(f"{SEARCH_URL}?{params}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "B 站返回了非 JSON（可能被风控）", "videos": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"请求失败：{exc}", "videos": []}

    if data.get("code") != 0:
        return {"ok": False, "reason": f"B 站返回 code={data.get('code')}", "videos": []}

    results = ((data.get("data") or {}).get("result") or [])
    videos = []
    for v in results:
        bvid = v.get("bvid")
        if not bvid:
            continue
        videos.append({
            "title": _strip_html(v.get("title")),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "author": v.get("author"),
            "play": _fmt_play(v.get("play")),
            "date": _fmt_date(v.get("pubdate")),
        })
        if len(videos) >= limit:
            break

    _CACHE[kw] = (time.time(), videos)
    return {"ok": True, "keyword": kw, "videos": videos}
