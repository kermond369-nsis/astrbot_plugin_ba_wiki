"""本地 T2I 字体：自动获取并校验字形覆盖。

背景：AstrBot 的本地文本转图片用 Pillow 渲染，字体候选表第一位是
`<AstrBot data>/font.ttf`，找不到才退到系统 Noto，最后退到只有拉丁字形的
`DejaVuSans.ttf` —— 那一刻中文全变方块（□□□）。

本模块负责三件事：

1. **判定**：`data/font.ttf` 是否存在，且**真的能画出字形**（位图自检，不只看文件大小）
2. **获取**：优先复制系统里已有的 CJK 字体；没有就从镜像下载 Noto Sans CJK
3. **兜底校验**：下载/复制后仍然要过覆盖检查，拦住「只有 CJK 没有拉丁」的 fallback 字体
   （例如 DroidSansFallbackFull.ttf：中文正常但数字/英文/★ 全变方块，实测 38 个字符缺字形）

公开接口：
    status(data_dir) -> dict      # 供插件页/诊断用，不发网络请求
    ensure(data_dir, force=False) -> dict   # 需要时下载，返回执行结果

都不抛异常（除 KeyboardInterrupt），失败以 {"ok": False, "error": ...} 返回。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import urllib.request

# 两套字体文件：AstrBot 分别用于常规文本与加粗文本
TARGETS = {
    "font.ttf": "NotoSansCJK-Regular",
    "font-bold.ttf": "NotoSansCJK-Bold",
}

# 位图自检用的字符集：拉丁 + 中文 + 日文假名 + 特殊符号 + 生僻字（䌷 是踩过的坑）
CHECK_CHARS = (
    "AazZ09/:.★·—（）「」"
    "中文蔚蓝档案若藻星野纺"
    "ツムギ䌷"
)

# 系统里可能已有的 CJK 字体（拉丁 + CJK 都覆盖的整字体，不要 fallback 字体）
SYSTEM_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
# 加粗目标优先用系统里的 Bold 面；没有就退到常规面（同一字体族，观感更好）
SYSTEM_FONTS_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
]

# 下载源，按顺序尝试（第一个是 GitHub 加速，国内实测 278 KB/s）
MIRRORS = [
    "https://ghfast.top/https://github.com/notofonts/noto-cjk/raw/main/Sans/OTC/{name}.ttc",
    "https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/OTC/{name}.ttc",
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTC/{name}.ttc",
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTC/{name}.ttc",
]

_FONT_MAGIC = (b"ttcf", b"OTTO", b"true", b"\x00\x01\x00\x00")
_MIN_SIZE = 1_000_000     # 小于 1MB 的几乎不可能是完整 CJK 字体

_DEFAULT_DIR = ""


def configure(data_dir: str | None) -> None:
    """记下插件数据目录，后续 status/ensure 可以省略参数。"""
    global _DEFAULT_DIR
    if data_dir:
        _DEFAULT_DIR = str(data_dir)


def _dir(data_dir: str | None) -> str:
    d = str(data_dir or _DEFAULT_DIR or "")
    if not d:
        raise ValueError("字体数据目录未配置")
    return d


def _bmp(font, ch: str, box: int = 40) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("L", (box, box), 255)
    ImageDraw.Draw(img).text((3, 3), ch, font=font, fill=0)
    return img.tobytes()


def missing_chars(path: str) -> list[str]:
    """返回该字体缺少字形的字符。无法加载时返回 None 表示"判断不了"。"""
    try:
        from PIL import ImageFont
    except Exception:  # noqa: BLE001
        return None  # 没有 Pillow 就没法判断，交给调用方保守处理

    try:
        font = ImageFont.truetype(str(path), 24, index=0)
    except Exception:  # noqa: BLE001
        return list(CHECK_CHARS)

    tofu = _bmp(font, "\uE000")      # 私用区：必然无字形，即豆腐块基准
    return [c for c in CHECK_CHARS if not c.isspace() and _bmp(font, c) == tofu]


def _describe(path: str) -> dict:
    missing = missing_chars(path)
    return {
        "path": str(path),
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 1) if os.path.exists(path) else 0,
        "missing": missing,
        "ok": bool(exists := os.path.exists(path)) and not missing,
    }


def _target_ok(path: str) -> bool:
    """真正的判定：文件存在 + 足够大 + 头部像字体 + 字形齐全。"""
    if not os.path.exists(path) or os.path.getsize(path) < _MIN_SIZE:
        return False
    try:
        with open(path, "rb") as f:
            if f.read(4) not in _FONT_MAGIC:
                return False
    except OSError:
        return False
    missing = missing_chars(path)
    return not missing       # None（无 Pillow）时会走这里 -> bool(None)=True? 见下


def status(data_dir: str | None = None) -> dict:
    """只读检查，不发网络请求。"""
    data_dir = _dir(data_dir)
    info = {}
    for fname, family in TARGETS.items():
        p = os.path.join(data_dir, fname)
        exists = os.path.exists(p)
        missing = missing_chars(p) if exists else None
        info[fname] = {
            "exists": exists,
            "size_mb": round(os.path.getsize(p) / 1024 / 1024, 1) if exists else 0.0,
            "missing_chars": "".join(missing) if missing else ("无" if exists else ""),
            "ok": bool(exists) and not missing,
            "family": family,
        }
    ok = all(v["ok"] for v in info.values())
    return {
        "ok": ok,
        "data_dir": data_dir,
        "files": info,
        "check_chars": CHECK_CHARS,
        "summary": (
            "字体已就绪，文字转图片不会出现方块"
            if ok
            else "字体缺失或不完整：中文会渲染成方块（□□□）"
        ),
    }


def _copy_system(target: str, bold: bool = False) -> str | None:
    for src in (SYSTEM_FONTS_BOLD if bold else []) + SYSTEM_FONTS:
        if not os.path.exists(src):
            continue
        missing = missing_chars(src)
        if missing:
            continue          # 缺字形，不用（比如 Droid 那种 fallback）
        shutil.copyfile(src, target)
        return src
    return None


def _download(name: str, target: str, timeout: int = 120) -> str | None:
    """下载指定字体。成功返回使用的 URL。"""
    for pattern in MIRRORS:
        url = pattern.format(name=name)
        tmp = target + ".part"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "astrbot-ba-wiki/0.6.2"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f, 1024 * 256)
            with open(tmp, "rb") as f:
                if f.read(4) not in _FONT_MAGIC:
                    os.remove(tmp)
                    continue
            if os.path.getsize(tmp) < _MIN_SIZE:
                os.remove(tmp)
                continue
            if missing_chars(tmp):
                os.remove(tmp)
                continue
            os.replace(tmp, target)
            return url
        except Exception:  # noqa: BLE001
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            continue
    return None


def ensure(data_dir: str | None = None, force: bool = False, log=None) -> dict:
    """确保 data 下的两套字体可用。需要时复制/下载，返回执行结果。

    force=True 时即使已就绪也会重新获取（插件页「重新下载」按钮用）。
    """
    data_dir = _dir(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    started = time.time()
    actions: list[str] = []
    errors: list[str] = []

    for fname, family in TARGETS.items():
        target = os.path.join(data_dir, fname)
        if not force and _target_ok(target):
            actions.append(f"{fname}: 已就绪，跳过")
            continue

        src = _copy_system(target, bold=fname.endswith("bold.ttf"))
        if src:
            actions.append(f"{fname}: 从系统字体复制 {src}")
        else:
            url = _download(family, target)
            if url:
                actions.append(f"{fname}: 下载 {family} <- {url}")
            else:
                errors.append(f"{fname}: 系统无可用字体，且所有镜像都下载失败")

        if not _target_ok(target):
            errors.append(f"{fname}: 获取后校验未通过（字形仍缺失）")

    result = status(data_dir)
    result.update({
        "ok": bool(result["ok"]) and not errors,
        "forced": bool(force),
        "actions": actions,
        "errors": errors,
        "elapsed": round(time.time() - started, 1),
    })
    if log:
        try:
            if result["ok"]:
                log(f"[ba_wiki] 字体检查完成：{'; '.join(actions) or '无操作'}")
            else:
                log(f"[ba_wiki] 字体检查失败：{'; '.join(errors)}")
        except Exception:  # noqa: BLE001
            pass
    return result
