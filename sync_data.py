#!/usr/bin/env python3
"""手动全量同步：SchaleDB 学生数据 + kivo 名字缓存。

一般不需要手动跑（插件加载后会自动预热），遇到这两种情况用它：
  - 新环境部署，不想等后台那 2 分钟
  - 上游刚更新，想立刻拿到新角色/新名字

    docker exec astrbot python /AstrBot/data/plugins/astrbot_plugin_ba_wiki/sync_data.py

环境变量 BA_DATA_DIR 可指定数据目录（默认容器内的路径）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import kivo, schaledb  # noqa: E402

DATA_DIR = os.environ.get("BA_DATA_DIR", "/AstrBot/data/plugin_data/astrbot_plugin_ba_wiki")
students_file = os.path.join(DATA_DIR, schaledb.STUDENTS_FILE)

# SchaleDB：删掉旧数据强制重新下载（名称表会跟着重建）
if os.path.exists(students_file):
    os.remove(students_file)
    print(f"已删除旧缓存: {students_file}")

raw = schaledb.students(DATA_DIR)
print(f"SchaleDB 就绪，角色数: {len(raw)}")
print(f"七语言名称表: {os.path.join(DATA_DIR, schaledb.NAMES_FILE)}")

# kivo：无视 24h 缓存，强制重抓（约 2 分钟 / 510 条）
print("开始抓取 kivo 名字缓存（约 2 分钟）...", flush=True)
records = kivo.records(DATA_DIR, force=True)
print(f"kivo 就绪，记录数: {len(records)}")
print(f"kivo 缓存: {kivo.cache_path(DATA_DIR)}")
