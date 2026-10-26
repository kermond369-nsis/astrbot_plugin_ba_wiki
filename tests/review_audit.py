# -*- coding: utf-8 -*-
"""测评卡索引体检：上游 gamekee 又加了角色时，用它看哪些卡没映射上。

    python tests/review_audit.py            # 用本地缓存（过期才联网）
    python tests/review_audit.py --refresh  # 强制重抓一遍

输出：
  · 每个学园页解析出多少张卡、映射上多少张
  · 没映射上的卡片名（多半是上游写法差异，往 sources/reviewcard.NAME_FIXUPS 里加一行）
  · 索引里总共有多少张卡

这是维护脚本，不参与 tests/selfcheck.py（那个不联网）。
"""

import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _harness as H  # noqa: E402


def main() -> int:
    refresh = "--refresh" in sys.argv[1:]
    main_mod = H.load_plugin()
    data_dir, _ = H.data_paths("new")
    inst = H.new_instance(main_mod, data_dir)
    H.ensure_ready(inst)                       # 名字解析需要 SchaleDB

    rc = H.plugin_module("sources.reviewcard")
    rc.configure(data_dir)

    if refresh or not os.path.exists(rc.index_path(data_dir)):
        index = rc.build_index(data_dir, log=print)
    else:
        index = rc.cards(data_dir)
    entries = index.get("entries") or {}

    print(f"\n索引卡片数：{len(entries)}")
    print("按学园页：")
    for art in index.get("articles") or []:
        print(f"  {art['title'][:34]:36} {art.get('cards', 0):3}/{art.get('total', 0):3}")

    lost = Counter()
    for art in rc.search_articles():
        try:
            pairs = rc.pairs_from_blocks(rc.article_blocks(art["id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  跳过 {art['id']}：{exc}")
            continue
        for p in pairs:
            if rc._SKIP_NAME_RE.search(p["name"]):
                continue
            if not rc._resolve_cid(data_dir, p["name"]):
                lost[p["name"]] += 1

    if not lost:
        print("\n没有解析失败的卡片名 ✓")
        return 0
    print(f"\n没映射上的卡片名 {len(lost)} 个：")
    for name, n in lost.most_common():
        print(f"  {name[:26]:28} x{n}")
    print("\n修法：在 sources/reviewcard.NAME_FIXUPS 里加一行「上游写法: 我们的名字」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
