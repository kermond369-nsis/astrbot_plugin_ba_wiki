# -*- coding: utf-8 -*-
"""测试用的 AstrBot 桩 + 插件加载器。

不用真的 AstrBot，只复刻它影响本插件的两处行为：

  1. 插件布局是 data/plugins/<目录名>/main.py，导入方式是
     __import__("data.plugins.<目录名>.main", fromlist=["main"])

  2. LLM 工具只绑定 __module__ 等于插件主模块的 handler
     （astrbot/core/star/star_manager.py: ft.handler.__module__ == metadata.module_path）
     这就是 main.py 里给 5 个工具对齐 __module__ 的原因。AstrBot 改了这条规则时，
     bind_tools() 要同步改，selfcheck 才会继续有意义。

数据目录放在 tests/.data/，首次运行会下载一次 SchaleDB，之后走缓存。
"""

import functools
import importlib
import os
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
PLUGIN_NAME = "astrbot_plugin_ba_wiki"
# 仓库根目录本身就是插件包（AstrBot 要求 metadata.yaml / main.py 在包根），
# 复制时把只服务于开发的东西剔除，还原成 AstrBot 实际安装后的目录内容。
PLUGIN_SRC = WS
PLUGIN_IGNORE_DIRS = {
    "tests", "deploy", "docs", "tools", "data",
    ".git", ".github", ".t1_backup", "__pycache__",
}
PLUGIN_IGNORE_PATTERNS = (*PLUGIN_IGNORE_DIRS, "*.zip", "*.pyc")
RUN_ROOT = os.path.join(HERE, ".run")
DATA_ROOT = os.path.join(HERE, ".data")
BASELINE_ZIP = os.path.join(WS, "backup-pre-t1.zip")
BASELINE_DIR = os.path.join(HERE, ".baseline", PLUGIN_NAME)

LOG = []            # [(level, message)]
LLM_TOOLS = []      # 假 llm_tools.func_list
COMMANDS = []       # 注册过的指令名


class FakeTool:
    """只保留 star_manager 用到的那几个字段。"""

    def __init__(self, name, handler):
        self.name = name
        self.handler = handler
        self.handler_module_path = handler.__module__
        self.active = True


def _install_stubs():
    if "astrbot" in sys.modules:
        return

    def _mk(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    def _log(level):
        def f(msg, *a, **k):
            LOG.append((level, str(msg)))
        return f

    api = _mk("astrbot.api")
    api.logger = types.SimpleNamespace(
        info=_log("info"), warning=_log("warning"), error=_log("error"), debug=_log("debug"))

    def llm_tool(name=None, **kwargs):
        def deco(fn):
            LLM_TOOLS.append(FakeTool(name or fn.__name__, fn))
            return fn
        return deco

    api.llm_tool = llm_tool

    star = _mk("astrbot.api.star")

    class Star:
        def __init__(self, context=None):
            self.context = context

    class Context:
        pass

    class StarTools:
        @staticmethod
        def get_data_dir(name):
            return os.path.join(DATA_ROOT, name)

    def register(*args, **kwargs):
        def deco(cls):
            cls.__star_meta__ = args
            return cls
        return deco

    star.Star = Star
    star.Context = Context
    star.StarTools = StarTools
    star.register = register

    event = _mk("astrbot.api.event")

    class AstrMessageEvent:
        pass

    class _Filter:
        def command(self, name=None, **kwargs):
            def deco(fn):
                fn.__command_name__ = name
                COMMANDS.append(name)
                return fn
            return deco

        def __getattr__(self, item):
            def any_filter(*a, **k):
                def deco(fn):
                    return fn
                return deco
            return any_filter

    event.AstrMessageEvent = AstrMessageEvent
    event.filter = _Filter()

    # ---- 消息链 / 组件：测评卡要走图片，工具里用 event.send(MessageChain([Image...])) ----
    class BaseMessageComponent:
        type = "base"

    class Plain(BaseMessageComponent):
        type = "plain"

        def __init__(self, text=""):
            self.text = text

    class Image(BaseMessageComponent):
        type = "image"

        def __init__(self, url=None, file=None):
            self.url = url
            self.file = file

        @staticmethod
        def fromURL(url, **_):
            return Image(url=url)

        @staticmethod
        def fromFileSystem(path, **_):
            return Image(file=path)

    class MessageChain:
        def __init__(self, chain=None, **kwargs):
            self.chain = list(chain or [])

    comp_mod = _mk("astrbot.api.message_components")
    comp_mod.BaseMessageComponent = BaseMessageComponent
    comp_mod.Plain = Plain
    comp_mod.Image = Image

    event.MessageChain = MessageChain
    event.MessageEventResult = MessageChain

    _mk("astrbot.core")


def plugin_import_path():
    return "data.plugins.%s.main" % PLUGIN_NAME


def load_plugin():
    """把插件复制成 AstrBot 的目录布局再导入，返回主模块。"""
    _install_stubs()
    target = os.path.join(RUN_ROOT, "data", "plugins", PLUGIN_NAME)
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copytree(PLUGIN_SRC, target, ignore=shutil.ignore_patterns(*PLUGIN_IGNORE_PATTERNS))
    for d in (os.path.join(RUN_ROOT, "data"), os.path.join(RUN_ROOT, "data", "plugins")):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "__init__.py"), "w").close()
    if RUN_ROOT not in sys.path:
        sys.path.insert(0, RUN_ROOT)
    return importlib.import_module(plugin_import_path())


def plugin_module(suffix):
    """取插件内的子模块，例如 plugin_module("directory")。"""
    return importlib.import_module("data.plugins.%s.%s" % (PLUGIN_NAME, suffix))


def load_baseline(dir_path):
    """把重构前的插件目录当成独立包导入，用于新旧对比。"""
    _install_stubs()
    if "baseline_plugin" in sys.modules:
        return sys.modules["baseline_plugin.main"]
    pkg = types.ModuleType("baseline_plugin")
    pkg.__path__ = [dir_path]
    sys.modules["baseline_plugin"] = pkg
    return importlib.import_module("baseline_plugin.main")


def bind_tools(plugin, module_path=None):
    """复刻 star_manager 的工具绑定规则，返回属于该插件且已绑定的工具。"""
    module_path = module_path or plugin_import_path()
    for tool in LLM_TOOLS:
        handler = tool.handler
        matched = getattr(handler, "__module__", None) == module_path or (
            isinstance(handler, functools.partial) and tool.handler_module_path == module_path)
        if matched:
            raw = handler.func if isinstance(handler, functools.partial) else handler
            tool.handler_module_path = module_path
            tool.handler = functools.partial(raw, plugin)
    bound = []
    for tool in LLM_TOOLS:
        owned = (tool.handler_module_path == module_path
                 or tool.handler_module_path.startswith(module_path + "."))
        tool.active = tool.active and owned
        if tool.active:
            bound.append(tool)
    return bound


def data_paths(name):
    d = os.path.join(DATA_ROOT, name)
    os.makedirs(d, exist_ok=True)
    return d, os.path.join(d, "students_zh.json")


def baseline_dir():
    """重构前的插件目录：先看 .t1_backup，没有再从不联网的硬存档里解一份缓存。"""
    direct = os.path.join(WS, ".t1_backup", PLUGIN_NAME)
    if os.path.isdir(direct):
        return direct
    if os.path.isdir(BASELINE_DIR):
        return BASELINE_DIR
    if not os.path.exists(BASELINE_ZIP):
        return None
    import zipfile
    prefix = "pre-t1/%s/" % PLUGIN_NAME
    with zipfile.ZipFile(BASELINE_ZIP) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            target = os.path.join(BASELINE_DIR, info.filename[len(prefix):])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return BASELINE_DIR if os.path.isdir(BASELINE_DIR) else None


def new_instance(main_module, data_dir, students_path=None):
    """建一个插件实例。students_path 只有旧实现（按文件路径工作）才需要传。"""
    plugin = main_module.BAWikiPlugin(None)
    plugin.data_dir = str(data_dir)
    if students_path is not None:
        plugin.data_path = str(students_path)
    return plugin


def ensure_ready(instance):
    """同步一次 SchaleDB 数据（首次下载；之后由 schaledb 自己判断是否探测）。"""
    importlib.import_module("data.plugins.%s.sources.schaledb" % PLUGIN_NAME).students(
        instance.data_dir)


class FakeEvent:
    def __init__(self, message, umo="umo-test"):
        self.message_str = message
        self.unified_msg_origin = umo
        self.results = []
        self.images = []       # image_result() 产出的图片（URL 或本地路径）
        self.sent = []         # event.send(MessageChain) 直接发出的组件

    def plain_result(self, text):
        self.results.append(text)
        return text

    def image_result(self, url_or_path):
        self.images.append(url_or_path)
        return url_or_path

    def make_result(self):
        return _FakeResult()

    async def send(self, chain):
        items = getattr(chain, "chain", None) or list(chain or [])
        self.sent.extend(items)


class _FakeResult:
    """够用的 MessageEventResult：收集组件，最后交给 FakeEvent.send。"""

    def __init__(self):
        self.chain = []

    def message(self, text):
        self.chain.append(("plain", text))
        return self

    def url_image(self, url):
        self.chain.append(("image_url", url))
        return self

    def file_image(self, path):
        self.chain.append(("image_file", path))
        return self


async def run_ba(plugin, message, umo="umo-test"):
    ev = FakeEvent(message, umo)
    async for _ in plugin.ba_cmd(ev):
        pass
    return ev.results


async def call_tool(tool, message, **kwargs):
    return await tool.handler(event=FakeEvent(message), **kwargs)
