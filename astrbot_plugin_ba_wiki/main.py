"""蔚蓝档案（BA）插件入口 —— 只做 AstrBot 胶水。

这一层只剩三件事：
  1. 插件生命周期：数据目录、按节奏探测上游、翻页会话状态、绰号表模板
  2. 工具接线：把工具函数的来源模块对齐到本模块（见下面的循环）
  3. 指令接线：把 /ba 转给 commands.handle_ba

实现都在别处：
  工具定义 -> tools.py          /ba 分发 -> commands.py
  名字解析 -> directory.py      技能数值 -> skills.py
  文本输出 -> render.py         外部接口 -> clients/
  数据下载 -> sources/schaledb.py（kivo 待 T3）
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from . import commands, directory, render, tools as tools_layer
from .clients import arona
from .sources import font as font_src
from .sources import kivo as kivo_src
from .sources import schaledb

try:                                    # 插件页 / 字体接口用；老版本没有这个模块就降级
    from astrbot.api.web import json_response
except Exception:                       # noqa: BLE001
    json_response = None

PLUGIN_NAME = "astrbot_plugin_ba_wiki"
ASSIST_STATE_TTL = 600     # 翻页会话状态保留 10 分钟

ALIAS_TEMPLATE = {
    "_说明": "别名表：键是群里的叫法，值是官方名（任意语言）/ 角色 ID / 显示名，例如 \"藻哥\": \"若藻\"。改完重载插件生效。",
}

# AstrBot 只把 __module__ 等于插件主模块的 handler 绑定到插件实例
# （astrbot/core/star/star_manager.py: ft.handler.__module__ == metadata.module_path，
#  插件主模块即 data.plugins.<目录名>.main）。工具定义在 tools.py，这里把 5 个工具
# 的来源模块对齐到本模块，它们才会被识别、绑定 self 并出现在工具列表里。
# 升级 AstrBot 或改加载方式后，务必重跑 tests/selfcheck.py 的绑定检查。
for _tool_name in ("query_ba_skill", "query_ba_stats", "search_ba_guide", "query_ba_raid_team",
                   "query_ba_player", "query_ba_assist"):
    getattr(tools_layer.BAToolsMixin, _tool_name).__module__ = __name__


@register(
    PLUGIN_NAME,
    "dsh",
    "蔚蓝档案角色技能数值查询（SchaleDB 本地缓存，多语言名称 + 绰号，输出国服译名）",
    "0.6.2",
)
class BAWikiPlugin(tools_layer.BAToolsMixin, Star):
    # ------------------------------------------------------------ 初始化
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.context = context
        self.config = dict(config or {})
        try:
            data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        except Exception:  # noqa: BLE001
            data_dir = None
        if data_dir is None:
            data_dir = os.path.join(os.getcwd(), "data", PLUGIN_NAME)
        self.data_dir = str(data_dir)
        # ⚠️ 字体必须放在 **AstrBot 的 data 目录**（T2I 只认 <astrbot_data>/font.ttf），
        # 不是插件的 plugin_data 目录。get_astrbot_data_path() 拿不到时退到 plugin_data 的父目录。
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            self.font_dir = str(get_astrbot_data_path())
        except Exception:  # noqa: BLE001
            self.font_dir = os.path.dirname(self.data_dir)
        schaledb.configure(self.data_dir)
        kivo_src.configure(self.data_dir)
        font_src.configure(self.font_dir)
        self._lock = asyncio.Lock()
        self._kivo_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._font_task: asyncio.Task | None = None
        self._kivo_checked_at = 0.0
        self._assist_state: dict[str, dict] = {}   # 会话 UMO -> 翻页状态
        self._ensure_alias_template()
        self._register_font_api()

    # ------------------------------------------------------------ 字体接口
    def _font_cfg(self) -> dict:
        cfg = self.config.get("font")
        return cfg if isinstance(cfg, dict) else {}

    def _register_font_api(self) -> None:
        """给插件页「字体」标签注册两个接口；老版本 AstrBot 没有 register_web_api 就跳过。"""
        if json_response is None:
            return
        reg = getattr(self.context, "register_web_api", None)
        if not callable(reg):
            logger.info("[ba_wiki] 当前 AstrBot 不支持 register_web_api，跳过字体页接口")
            return
        try:
            reg(f"/{PLUGIN_NAME}/font/status", self.page_font_status, ["GET"], "字体状态")
            reg(f"/{PLUGIN_NAME}/font/download", self.page_font_download, ["POST"], "下载/修复字体")
            logger.info("[ba_wiki] 已注册字体页接口：font/status, font/download")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ba_wiki] 注册字体页接口失败: {exc}")

    async def page_font_status(self):
        return json_response(font_src.status(self.font_dir))

    async def page_font_download(self):
        res = await asyncio.to_thread(font_src.ensure, self.font_dir, True, logger.info)
        return json_response(res)

    # ------------------------------------------------------------ 翻页状态
    def _state_set(self, key: str, st: dict) -> None:
        self._assist_state[key] = {**st, "ts": time.time()}
        # 顺手清理过期项，避免字典无限增长
        now = time.time()
        for k in [k for k, v in self._assist_state.items() if now - v.get("ts", 0) > ASSIST_STATE_TTL]:
            self._assist_state.pop(k, None)

    def _state_get(self, key: str) -> dict | None:
        st = self._assist_state.get(key)
        if not st:
            return None
        if time.time() - st.get("ts", 0) > ASSIST_STATE_TTL:
            self._assist_state.pop(key, None)
            return None
        return st

    # ------------------------------------------------------------ 别名表
    def _ensure_alias_template(self) -> None:
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            p = os.path.join(self.data_dir, directory.ALIAS_FILE)
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(ALIAS_TEMPLATE, f, ensure_ascii=False, indent=2)
                logger.info(f"[ba_wiki] 已生成别名表模板: {p}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ba_wiki] 创建别名表失败: {exc}")

    # ------------------------------------------------------------ 启动预热
    async def initialize(self) -> None:
        """插件加载完（AstrBot 在 load 后 await 本方法）就排一个后台预热任务。

        不能在这里等网络：SchaleDB 下载慢或 kivo 抓取要两分钟，会把 AstrBot
        启动一起拖住。所以只排任务，立刻返回。
        """
        try:
            self._warm_task = asyncio.ensure_future(self._warm_up())
            logger.info("[ba_wiki] 已排入启动预热任务：SchaleDB 检查 + kivo 名字缓存同步")
        except RuntimeError:      # 没有事件循环（单元测试场景）
            logger.warning("[ba_wiki] 当前没有事件循环，跳过启动预热；需要时跑 sync_data.py")

        # 字体：单独一个任务，不和 SchaleDB/kivo 抢，也不阻塞启动
        if self._font_cfg().get("auto_download", True):
            try:
                self._font_task = asyncio.ensure_future(self._font_warm_up())
                logger.info("[ba_wiki] 已排入字体检查任务（缺失才下载）")
            except RuntimeError:
                pass

    async def _font_warm_up(self) -> None:
        try:
            res = await asyncio.to_thread(font_src.ensure, self.font_dir, False, logger.info)
            if not res.get("ok"):
                logger.warning(
                    "[ba_wiki] 字体未就绪，文字转图片会出现方块；"
                    "可在插件页「字体」里点按钮修复，或发 /ba 字体。详情：" + "; ".join(res.get("errors") or [])
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ba_wiki] 字体检查异常: {exc}")

    async def _warm_up(self) -> None:
        """启动预热：先确认 SchaleDB（304 就是零下载），再把 kivo 名字缓存丢后台。"""
        try:
            changed = await asyncio.to_thread(schaledb.refresh, self.data_dir)
            if changed:
                directory.invalidate(self.data_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ba_wiki] 启动时同步 SchaleDB 失败（继续用本地缓存）: {exc}")
        self._kick_kivo_refresh()

    def _kick_kivo_refresh(self):
        """kivo 全量要一两分钟：后台刷新，刷完再把名字索引失效。

        最多每小时踢一次；kivo 自己按 24h 缓存判断要不要真的发请求。
        返回排入的任务（没排成就返回 None），测试里可以 await 它。
        """
        now = time.time()
        if now - self._kivo_checked_at < 3600:
            return self._kivo_task
        if self._kivo_task is not None and not self._kivo_task.done():
            return self._kivo_task

        async def _run() -> None:
            try:
                recs = await asyncio.to_thread(kivo_src.records, self.data_dir, True)
                directory.invalidate(self.data_dir)
                logger.info(f"[ba_wiki] kivo 名字缓存就绪：{len(recs)} 条 -> "
                            f"{kivo_src.cache_path(self.data_dir)}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[ba_wiki] kivo 同步失败（继续用旧缓存）: {exc}")

        try:
            self._kivo_task = asyncio.ensure_future(_run())
            self._kivo_checked_at = now
            logger.info("[ba_wiki] 已排入后台任务：同步 kivo 名字缓存（首次约 2 分钟，不阻塞查询）")
        except RuntimeError:      # 没有事件循环（单元测试场景）
            self._kivo_task = None
            logger.warning("[ba_wiki] 当前没有事件循环，跳过 kivo 后台同步；需要时跑 sync_data.py")
        return self._kivo_task

    # ------------------------------------------------------------ 数据
    async def _ensure_ready(self) -> None:
        """首次使用时把 SchaleDB 拉下来；kivo 补充名按 24h 缓存后台刷新。"""
        students_file = os.path.join(self.data_dir, schaledb.STUDENTS_FILE)
        if not os.path.exists(students_file):
            async with self._lock:
                if not os.path.exists(students_file):   # 等锁期间可能已经同步好
                    logger.info(f"[ba_wiki] 首次同步 SchaleDB 数据（含多语言名称）-> {self.data_dir}")
                    try:
                        await asyncio.to_thread(schaledb.students, self.data_dir)
                        directory.invalidate(self.data_dir)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[ba_wiki] 数据同步失败（继续用本地缓存）: {exc}")
        self._kick_kivo_refresh()

    async def _query(self, keyword: str, skill: str = "", level: int | None = None) -> dict:
        await self._ensure_ready()
        try:
            return await asyncio.to_thread(
                tools_layer.build_skill_payload, self.data_dir, keyword, skill, level)
        except FileNotFoundError:
            return {"ok": False, "reason": "本地数据缺失且下载失败，请检查服务器能否访问 schaledb.com"}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ba_wiki] 查询失败: {exc}")
            return {"ok": False, "reason": f"查询出错：{exc}"}

    async def _stats(self, keyword: str, *, level: int = 90, star: int = 5,
                     equip_tier: int = 0, equip_tiers: str = "", favorite_item: bool = True,
                     weapon_level: int | None = None, ue_tier: int = 0, potential: str = "",
                     bond_level: int = 50, skill_level: int = 10) -> dict:
        """面板查询：等级/星级/装备/专武/能力解放都走这里。"""
        await self._ensure_ready()
        try:
            return await asyncio.to_thread(
                tools_layer.build_stats_payload, self.data_dir, keyword,
                level=level, star=star, equip_tier=equip_tier, equip_tiers=equip_tiers,
                favorite_item=favorite_item, weapon_level=weapon_level, ue_tier=ue_tier,
                potential=potential, bond_level=bond_level, skill_level=skill_level,
            )
        except FileNotFoundError:
            return {"ok": False, "reason": "本地数据缺失且下载失败，请检查服务器能否访问 schaledb.com"}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ba_wiki] 面板查询失败: {exc}")
            return {"ok": False, "reason": f"查询出错：{exc}"}

    async def _resolve_student(self, keyword: str) -> tuple[dict | None, str | None]:
        """解析学生名。命中返回 (学生, None)，未命中返回 (None, 给用户的话)。"""
        res = await asyncio.to_thread(directory.resolve, self.data_dir, keyword)
        if res.get("ok"):
            return res["matches"][0], None
        return None, render.resolve_failed(res.get("kind"), res.get("suggest"))

    def _name_of(self, cid) -> str:
        return directory.display_name(self.data_dir, cid)

    # ------------------------------------------------------------ 大决战
    async def _raid_team(self, server: int, season: int | None, top: int, tier: int) -> dict:
        await self._ensure_ready()
        try:
            return await asyncio.to_thread(
                arona.rank_players, server, season, tier, top, self.data_dir
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": str(exc)}

    # ------------------------------------------------------------ 助战分页
    async def _assist_page(self, st: dict, page: int) -> tuple[dict, dict]:
        """按已有状态取指定页，返回 (结果, 新状态)。"""
        f = st.get("filters") or {}
        res = await asyncio.to_thread(
            arona.assist_players,
            st.get("server", 1), st.get("sid"), page, arona.ASSIST_PAGE_SIZE,
            f.get("min_star"), f.get("min_level"),
            f.get("min_weapon_star"), f.get("min_ex_level"),
            self.data_dir,
        )
        res["student_name"] = st.get("name")
        new_st = {**st, "page": page,
                  "total_pages": int(res.get("total_pages") or 1)}
        return res, new_st

    # ------------------------------------------------------------ 手动指令
    @filter.command("ba")
    async def ba_cmd(self, event: AstrMessageEvent):
        """查询 BA 角色技能数值，用法：/ba 若藻 ns"""
        async for result in commands.handle_ba(self, event):
            yield result
