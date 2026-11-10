"""
V1.3 图片合成：用 Pillow 把文案渲染成"可直接投放"的 PNG。
- 支持任意平台尺寸（从 320x50 小banner 到 1080x1920 竖版）；
- 有 AI 底图时做文字叠加（含安全边距与压暗），无 AI 底图时用品牌渐变模板；
- 中文/英文混排自动选字体，长文本按像素宽度折行。
"""
import glob
import logging
import os
import subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger("imaging")

# 默认品牌色板（V4.41 / F05：调用方可显式传入品牌 token 覆盖，不再写死）
PALETTE = {
    "bg1": (16, 42, 67),
    "bg2": (31, 78, 121),
    "accent": (255, 196, 61),
    "fg": (255, 255, 255),
    "sub": (207, 226, 243),
    "card": (255, 255, 255),
    "on_accent": (25, 30, 38),
}

# V4.41 / F05：版式规格。text_x / text_w 是文字区相对画布的比例；
# `panel` 决定是否在文字区下方垫一层色块（保证可读性又不整幅压暗商品）。
LAYOUT_SPEC = {
    "hero":   {"x": 0.06, "w": 0.88, "top": 0.30, "panel": None,     "band": None,  "rule": "top"},
    "demo":   {"x": 0.06, "w": 0.88, "top": 0.60, "panel": "bottom", "band": None,  "rule": "left"},
    "detail": {"x": 0.55, "w": 0.39, "top": 0.20, "panel": "right",  "band": None,  "rule": "left"},
    "offer":  {"x": 0.12, "w": 0.76, "top": 0.34, "panel": "center", "band": "top", "rule": "center"},
    "review": {"x": 0.10, "w": 0.80, "top": 0.38, "panel": "card",   "band": None,  "rule": "left"},
}
DEFAULT_LAYOUT = "hero"


def hex_rgb(value, fallback=None):
    """把 #RRGGBB / rgb() / (r,g,b) 统一成 RGB 元组；无效值返回 fallback。"""
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            return tuple(max(0, min(255, int(v))) for v in value[:3])
        except (TypeError, ValueError):
            return fallback
    s = str(value or "").strip()
    if s.startswith("#") and len(s) in (4, 7):
        try:
            if len(s) == 4:
                return tuple(int(ch * 2, 16) for ch in s[1:])
            return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return fallback
    return fallback


def resolve_palette(palette: dict | None, accent=None) -> dict:
    """V4.41 / F05：把用户所选配色解析成完整渲染 token，缺省项回退默认值。

    传入的 `palette` 来自 `ResolvedCreativeConfig.visual.palette`（十六进制字符串），
    也会接收老的 `accent` 元组参数，保证旧调用与其它模块不受影响。
    """
    p = dict(palette or {})
    out = dict(PALETTE)
    for key in ("bg1", "bg2", "accent", "fg", "sub", "card", "on_accent"):
        v = hex_rgb(p.get(key))
        if v is not None:
            out[key] = v
    if accent is not None:
        v = hex_rgb(accent)
        if v is not None:
            out["accent"] = v
    out["light"] = bool(p.get("light"))
    return out


def layout_of(layout: str, width: int, height: int) -> str:
    """小横幅几何强制单行布局；未知值回退 hero（旧调用兼容）。"""
    if height <= 120 or width / max(1, height) > 4:
        return "banner"
    return layout if layout in LAYOUT_SPEC else DEFAULT_LAYOUT

# 候选字体路径：覆盖 macOS 与常见 Linux 发行版的 CJK / 拉丁字体。
# 不再依赖少数“写死”的路径——只要部署机装了任一 CJK 字体，就能正常渲染中文。
_FONT_PATHS = [
    # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/ArialHB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    # Linux - 思源 / Noto CJK（最常见的中文包）
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    # Linux - 文泉驿（轻量中文）
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # Linux - 其他常见 CJK
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/sourcehan/SourceHanSansSC-Regular.otf",
    "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
    # Linux - 拉丁回退（仅含拉丁/西里尔/希腊，不含中文）
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

# fontTools 提供精确的字形覆盖查询（字符 -> 是否存在），是判断“缺字”最可靠的方式。
try:
    from fontTools.ttLib import TTFont
    _HAS_FONTTOOLS = True
except Exception:
    _HAS_FONTTOOLS = False

_font_cache: dict = {}     # (path, size) -> ImageFont
_cmap_cache: dict = {}     # path -> set[int] | None


def _cmap(path: str):
    """返回字体的字符映射（codepoint 集合）；读取失败返回 None。"""
    if path in _cmap_cache:
        return _cmap_cache[path]
    chars = None
    try:
        # .ttc 可能含多个字体面，逐个尝试，取第一个非空 cmap
        for fn in range(0, 8):
            try:
                font = TTFont(path, fontNumber=fn, lazy=True)
            except Exception:
                break
            try:
                merged = set()
                for t in font["cmap"].tables:
                    merged |= set(t.cmap.keys())
                if merged:
                    chars = merged
                    break
            finally:
                font.close()
    except Exception:
        chars = None
    _cmap_cache[path] = chars
    return chars


def _discover_fonts() -> list[str]:
    """返回当前环境可用的字体路径列表（写死路径 + fontconfig 动态发现）。"""
    found = [p for p in _FONT_PATHS if os.path.exists(p)]
    # 若部署机装了 fontconfig，则把所有系统字体也纳入候选，最大化覆盖。
    try:
        out = subprocess.run(
            ["fc-list", "--file"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                line = line.strip()
                if line and line not in found:
                    found.append(line)
    except Exception:
        pass
    return found


_FONT_STACK = _discover_fonts()


def _load(path: str, size: int):
    key = (path, size)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = ImageFont.truetype(path, size)
            f._src = path
        except Exception:
            return None
        _font_cache[key] = f
    return f


def _default_font(size: int):
    try:
        f = ImageFont.load_default(size)
    except TypeError:
        f = ImageFont.load_default()
    f._is_default = True
    return f


def _has_glyph(font, ch: str) -> bool:
    """判断字体是否能真正渲染该字符（基于字形表，可靠；缺字则回退不绘制）。"""
    if ch in (" ", "\n", "\t", "\r"):
        return True
    if getattr(font, "_is_default", False):
        # 内置默认字体只含基础拉丁字符，其余一律视为缺字
        return ch.isascii() and ch.isprintable()
    if _HAS_FONTTOOLS:
        path = getattr(font, "_src", None)
        if path:
            cmap = _cmap(path)
            if cmap is not None:
                return ord(ch) in cmap
    # 无 fontTools 或读取失败时的兜底：乐观认为可渲染
    return True


def _font_for(ch: str, size: int):
    """为单个字符挑选能渲染它的字体（逐字符回退，杜绝豆腐块）。"""
    for path in _FONT_STACK:
        f = _load(path, size)
        if f and _has_glyph(f, ch):
            return f
    # 没有任何字体支持该字符：返回栈首字体（绘制时会被安全跳过并告警）
    if _FONT_STACK:
        return _load(_FONT_STACK[0], size) or _default_font(size)
    return _default_font(size)


def _primary_font(size: int):
    """用于折行测量等场景的“主字体”（栈中第一个可用字体）。"""
    for path in _FONT_STACK:
        f = _load(path, size)
        if f:
            return f
    return _default_font(size)


def _draw_text(d: ImageDraw.ImageDraw, xy, text: str, size: int, fill):
    """带逐字符字体回退的文字绘制：缺字字符不会变成豆腐块，而是被安全跳过并告警。"""
    x, y = xy
    missing: list[str] = []
    for ch in (text or ""):
        if ch == "\n":
            continue
        f = _font_for(ch, size)
        if f is None or not _has_glyph(f, ch):
            if ch.strip():  # 忽略空白，仅记录可见字符的缺字
                missing.append(ch)
            x += size * 0.5
            continue
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch)
    if missing:
        uniq = "".join(dict.fromkeys(missing))
        logger.warning(
            "imaging: 跳过 %d 个无法渲染的字符（环境缺少对应字体）: %r —— "
            "请安装覆盖这些字符的字体（中文需 CJK 字体，如 fonts-noto-cjk）",
            len(missing), uniq,
        )
    return x


def _has_cjk() -> bool:
    for path in _FONT_STACK:
        f = _load(path, 20)
        if f and _has_glyph(f, "中"):
            return True
    return False


if not _has_cjk():
    logger.warning(
        "imaging: 未检测到支持中文(CJK)的字体，中文文案将无法正常显示。"
        "请在部署环境安装 CJK 字体，例如: apt-get install fonts-noto-cjk 或 fonts-wqy-zenhei"
    )


class TextOverflowError(Exception):
    """V4.39 / F01：文字在给定版位内无法完整排版，不允许用省略号蒙混过关。"""


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int,
          allow_ellipsis: bool = True) -> list[str]:
    """折行：含空格按词折（避免英文断词），中文按字符折。

    默认超出行数加省略号（兼容历史调用）；`allow_ellipsis=False` 时改为抛
    TextOverflowError，由上层把该版位标记为 needs_revision 而不是输出残图。
    """
    text = (text or "").strip()
    if not text:
        return []
    words = text.split()
    by_word = len(words) > 1
    units = words if by_word else list(text)

    def join(cur: str, u: str) -> str:
        if not cur:
            return u
        return f"{cur} {u}" if by_word else cur + u

    lines, cur, i = [], "", 0
    while i < len(units):
        u = units[i]
        cand = join(cur, u)
        if draw.textlength(cand, font=font) <= max_width:
            cur = cand
            i += 1
            continue
        if cur:
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                break
            continue
        # 单个词/字就超宽：按字符硬切
        piece = ""
        for ch in u:
            if draw.textlength(piece + ch, font=font) <= max_width:
                piece += ch
            else:
                break
        cur = piece or u[:1]
        units[i] = u[len(piece):] or ""
        if not units[i]:
            i += 1

    if cur:
        lines.append(cur)
    complete = (i >= len(units)) and len([ln for ln in lines if ln]) <= max_lines
    if not complete:
        if not allow_ellipsis:
            raise TextOverflowError(f"文字超出可排版预算（最多 {max_lines} 行）")
        if len(lines) >= max_lines:
            last = lines[max_lines - 1]
            while last and draw.textlength(last + "…", font=font) > max_width:
                last = last[:-1]
            lines[max_lines - 1] = last + "…"
    return [ln for ln in lines[:max_lines] if ln]


def text_budget(width: int, height: int, layout: str = "",
                logo_path: str | None = None) -> dict:
    """V4.39 / F01 + V4.41 / F05：按版位几何、所选布局与 Logo 预留框估算图内文字预算。

    平台正文（primary_text / body / description）与图内文字是两套东西，这里只算图内文字。
    不传 layout / logo_path 时保持 V4.39 的旧数值，避免历史回归口径被改变；
    传了则按所选版式的真实文字区宽度计算，与 `render_ad_png` 使用同一份规格。
    """
    w, h = int(width or 1080), int(height or 1080)
    margin = max(10, int(min(w, h) * 0.06))
    eff = layout_of(layout, w, h)
    if eff == "banner":
        fs = max(11, int(h * 0.34))
        cta_w = int(w * 0.24)
        logo = logo_metrics(w, h, logo_path)
        logo_w = (logo[2] + 8) if logo else 0
        avail = max(8, w - margin * 2 - cta_w - logo_w - 8)
        cfs = max(9, int(h * 0.26))
        return {"layout": "banner", "headline_chars": max(6, int(avail / (fs * 0.55))),
                "sub_chars": 0, "cta_chars": max(4, int(cta_w / (cfs * 0.55))),
                "logo_reserved": bool(logo)}
    # 旧调用（未指定版式）保持原有预算公式；指定版式后按文字区实际宽度收紧
    spec = LAYOUT_SPEC[eff]
    if layout:
        max_width = max(12, int(w * spec["w"]))
    else:
        max_width = w - margin * 2
    fs = int(min(w, h) * 0.105)
    cpl = max(6, int(max_width / (fs * 0.55)))
    sfs = max(12, int(fs * 0.40))
    sub_cpl = max(8, int(max_width / (sfs * 0.55)))
    cfs = max(12, int(fs * 0.42))
    return {"layout": eff, "headline_chars": cpl * 3,
            "sub_chars": sub_cpl * 3,
            "cta_chars": max(6, int((w * 0.6) / (cfs * 0.55))),
            "text_width": max_width}


def logo_metrics(w: int, h: int, logo_path: str | None):
    """V4.41 / F05：先算 Logo 预留框，文字排版必须在它之外（T07 不重叠）。

    返回 (x, y, tw, th)；无可用 Logo 时返回 None。超宽 Logo 会等比缩小，
    避免吃掉整个小横幅。
    """
    if not logo_path or not os.path.exists(logo_path):
        return None
    try:
        with Image.open(logo_path) as im:
            lw, lh = im.size
    except Exception:
        return None
    if lw <= 0 or lh <= 0:
        return None
    is_small = h <= 120 or w / max(1, h) > 4
    th = int(h * 0.40) if is_small else int(min(w, h) * 0.13)
    th = max(18, min(th, 140))
    tw = max(1, int(lw * th / float(lh)))
    max_tw = int(w * 0.30)
    if tw > max_tw:
        ratio = max_tw / float(tw)
        tw, th = max(1, int(tw * ratio)), max(1, int(th * ratio))
    margin = max(8, int(min(w, h) * 0.04))
    x = max(0, w - tw - margin)
    y = margin if not is_small else max(0, (h - th) // 2)
    return (x, y, tw, th)


def _gradient(w: int, h: int, pal: dict | None = None) -> Image.Image:
    """V4.41 / F05：模板底图使用当前品牌 token，不再是写死的蓝黄渐变。"""
    p = pal or PALETTE
    img = Image.new("RGB", (w, h), p["bg1"])
    top, bottom = p["bg1"], p["bg2"]
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        ))
    return img


def _region_mask(w: int, h: int, layout: str) -> Image.Image:
    """文字区的渐变遮罩强度（0–255）。只压暗文字区，主体区强度为 0。"""
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if layout == "banner":
        for x in range(w):
            t = 1.0 - min(1.0, x / max(1, w * 0.90))
            d.line([(x, 0), (x, h)], fill=int(255 * max(0.0, t)))
    elif layout == "demo":
        start = int(h * 0.52)
        for y in range(start, h):
            t = (y - start) / max(1, h - start)
            d.line([(0, y), (w, y)], fill=int(255 * min(1.0, t * 1.5)))
    elif layout == "detail":
        start = int(w * 0.50)
        for x in range(start, w):
            t = (x - start) / max(1, w - start)
            d.line([(x, 0), (x, h)], fill=int(255 * min(1.0, t * 1.5)))
    elif layout == "offer":
        for y in range(h):
            t = 0.45 + 0.55 * (1.0 - abs(y - h / 2) / max(1, h / 2))
            d.line([(0, y), (w, y)], fill=int(255 * min(1.0, t)))
    elif layout == "review":
        for y in range(int(h * 0.30), int(h * 0.86)):
            d.line([(int(w * 0.06), y), (int(w * 0.94), y)], fill=190)
    else:  # hero
        for y in range(h):
            t = max(0.0, (y - h * 0.18) / max(1, h * 0.82))
            d.line([(0, y), (w, y)], fill=int(255 * min(1.0, t * 1.15)))
    return m


def _apply_local_veil(img: Image.Image, pal: dict, layout: str,
                      dim_ratio: float) -> Image.Image:
    """V4.41 / F05：局部遮罩替代「整幅混合 42% 暗色」，商品颜色不被改动。"""
    if dim_ratio <= 0:
        return img
    w, h = img.size
    strength = min(1.0, max(0.0, float(dim_ratio)) * 2.2)
    mask = _region_mask(w, h, layout).point(lambda v: int(v * strength))
    color = (248, 250, 252) if pal.get("light") else pal["bg1"]
    layer = Image.new("RGB", (w, h), color)
    return Image.composite(layer, img, mask)


# V4.42 / F06：每种内容版式的「主体保护区 / 文字区」（目标画布相对坐标）。
# 与 _SUBJECT_REGION（商品合成落位）分离：裁切要保护的是**主视觉**，不是贴图层。
COMPOSITION_REGIONS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "hero":   ((0.38, 0.06, 0.96, 0.58), (0.02, 0.60, 0.66, 0.98)),
    "demo":   ((0.08, 0.04, 0.92, 0.54), (0.02, 0.58, 0.98, 0.98)),
    "detail": ((0.04, 0.14, 0.50, 0.88), (0.52, 0.10, 0.98, 0.92)),
    "offer":  ((0.28, 0.04, 0.72, 0.52), (0.04, 0.56, 0.96, 0.96)),
    "review": ((0.58, 0.04, 0.96, 0.52), (0.04, 0.58, 0.94, 0.96)),
    "banner": ((0.34, 0.10, 0.72, 0.90), (0.00, 0.00, 0.36, 1.00)),
}


def composition_regions(layout: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    return COMPOSITION_REGIONS.get(layout, COMPOSITION_REGIONS["hero"])


def _prepare_bg(w: int, h: int, bg_path: str | None, pal: dict | None = None,
                layout: str = "hero", dim_ratio: float = 0.28,
                composition: dict | None = None,
                trace: dict | None = None) -> Image.Image:
    """V4.42 / F06：按主体保护框构图，而不是无条件 cover 居中裁切。

    - `composition` 由调用方（media_ad）按「实际返回底图尺寸」算好后传入；
      为空时本函数自行按源图尺寸规划，保证旧调用也能得到主体保护。
    - `trace` 为可写 dict，渲染后回填 `composition`（含 crop / anchor / mode /
      requested_size / returned_size），供逐图归档满足 T08 的记录要求。
    - 极端横幅或比例差过大时走扩图（contain + 边缘延展），源图内容一个像素都不裁。
    """
    p = pal or PALETTE
    if bg_path and os.path.exists(bg_path):
        try:
            from image_capabilities import plan_composition, apply_composition
            with Image.open(bg_path) as probe:
                sw, sh = probe.size
                src = probe.convert("RGB")
            sb, tb = composition_regions(layout)
            comp = composition or plan_composition(
                w, h, sw, sh, subject_box=sb, text_box=tb, layout=layout)
            fitted, applied = apply_composition(src, comp, fill=p["bg1"])
            if trace is not None:
                trace["composition"] = {**applied, "returned_size": [sw, sh],
                                        "requested_size": [w, h]}
            return _apply_local_veil(fitted, p, layout, dim_ratio)
        except Exception:
            pass
    if trace is not None:
        trace["composition"] = {
            "mode": "gradient", "crop": None, "protected": True,
            "returned_size": None, "requested_size": [w, h],
            "capability_note": "无 AI 底图，使用本地渐变模板，无裁切",
        }
    return _gradient(w, h, p)


def _composite_logo(img: Image.Image, logo_path: str | None, w: int, h: int,
                    box=None, remove_white_bg: bool = False) -> Image.Image:
    """V4.41 / F05：把 Logo 放进**预先算好**的安全区。

    默认完整保留透明源与白色品牌内容；只有调用方显式要求、且源文件没有真实
    透明通道时，才去除近白背景（避免把白色 Logo 细节一起删掉，说明书 T07）。
    """
    box = box if box is not None else logo_metrics(w, h, logo_path)
    if not box or not logo_path or not os.path.exists(logo_path):
        return img
    x, y, tw, th = box
    try:
        with Image.open(logo_path) as src_im:
            has_alpha = (src_im.mode in ("RGBA", "LA")
                         and src_im.getchannel("A").getextrema()[0] < 250)
            logo = src_im.convert("RGBA")
    except Exception:
        return img
    logo = logo.resize((max(1, tw), max(1, th)), Image.LANCZOS)
    if remove_white_bg and not has_alpha:
        pixels = list(logo.getdata())
        logo.putdata([(r, g, b, 0) if (a > 0 and r > 245 and g > 245 and b > 245)
                      else (r, g, b, a) for r, g, b, a in pixels])
    img.paste(logo, (x, y), logo)
    return img


_SUBJECT_REGION = {
    "hero":   (0.42, 0.08, 0.94, 0.46),
    "demo":   (0.10, 0.05, 0.90, 0.50),
    "detail": (0.05, 0.16, 0.48, 0.84),
    "offer":  (0.30, 0.06, 0.70, 0.28),
    "review": (0.66, 0.05, 0.94, 0.28),
}


def _composite_product(img: Image.Image, path: str | None, layout: str) -> Image.Image:
    """F03 能力回退：供应商不支持参考编辑时，把用户提供的真实商品图合进主体区。

    这是**本地合成**，不是 AI 参考编辑；调用方必须在归档里标注能力限制。
    """
    if not path or not os.path.exists(path) or layout not in _SUBJECT_REGION:
        return img
    w, h = img.size
    x0, y0, x1, y1 = _SUBJECT_REGION[layout]
    box = (int(w * x0), int(h * y0), int(w * x1), int(h * y1))
    rw, rh = box[2] - box[0], box[3] - box[1]
    if rw < 8 or rh < 8:
        return img
    try:
        src = Image.open(path).convert("RGB")
        scale = max(rw / src.width, rh / src.height)
        src = src.resize((max(1, int(src.width * scale)),
                          max(1, int(src.height * scale))), Image.LANCZOS)
        left, top = (src.width - rw) // 2, (src.height - rh) // 2
        src = src.crop((left, top, left + rw, top + rh))
        mask = Image.new("L", (rw, rh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, rw - 1, rh - 1],
                                               radius=max(2, int(min(rw, rh) * 0.08)),
                                               fill=255)
        img.paste(src, (box[0], box[1]), mask)
    except Exception:
        pass
    return img


def render_ad_png(out_path: str, width: int, height: int, headline: str, sub: str,
                  cta: str, brand: str = "", bg_path: str | None = None,
                  logo_path: str | None = None, accent: tuple = None,
                  strict_text: bool = False, palette: dict | None = None,
                  layout: str = "", product_image_path: str | None = None,
                  dim_ratio: float = 0.28,
                  remove_white_logo_bg: bool = False,
                  composition: dict | None = None,
                  trace: dict | None = None) -> str:
    """V4.41 / F05：按内容需求选布局、按品牌 token 上色、先预留 Logo 区。

    仍保留 V4.39 / F01 的硬约束：`strict_text=True` 时文字放不下就抛
    TextOverflowError，由上层标记 needs_revision，不输出省略号残图。
    旧调用（不传 palette / layout / logo）行为与 V4.40 一致。
    """
    w, h = int(width), int(height)
    pal = resolve_palette(palette, accent)
    eff = layout_of(layout, w, h)
    logo_box = logo_metrics(w, h, logo_path)
    margin = max(10, int(min(w, h) * 0.06))
    accent_c = pal["accent"]

    img = _prepare_bg(w, h, bg_path, pal, eff, dim_ratio,
                      composition=composition, trace=trace)
    img = _composite_product(img, product_image_path, eff)
    d = ImageDraw.Draw(img)

    if eff == "banner":
        # 小横幅：标题 | CTA | Logo 三段各自独立、按顺序预留，互不重叠（T07）
        fs = max(11, int(h * 0.34))
        pf = _primary_font(fs)
        line = (headline or brand or "Ad")
        cta_w = int(w * 0.24) if cta else 0
        logo_w = (logo_box[2] + 8) if logo_box else 0
        cta_x = w - margin - logo_w - cta_w
        avail = max(0, cta_x - margin - 8)
        if avail < 12:
            raise TextOverflowError("小横幅在预留 CTA 与 Logo 后已无标题空间")
        while d.textlength(line, font=pf) > avail and fs > 8:
            fs -= 1
            pf = _primary_font(fs)
        if strict_text and d.textlength(line, font=pf) > avail:
            raise TextOverflowError("小横幅标题超出可排版宽度")
        _draw_text(d, (margin, (h - fs * 1.2) / 2), line, fs, pal["fg"])
        if cta:
            cfs = max(9, int(h * 0.26))
            cf = _primary_font(cfs)
            while d.textlength(cta, font=cf) + cfs * 1.4 > cta_w and cfs > 8:
                cfs -= 1
                cf = _primary_font(cfs)
            if strict_text and d.textlength(cta, font=cf) + cfs * 1.4 > cta_w:
                raise TextOverflowError("小横幅 CTA 超出可排版宽度")
            bw = d.textlength(cta, font=cf) + cfs * 1.4
            bh = min(h - 8, cfs * 2.0)
            bx, by = cta_x, (h - bh) / 2
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh / 2),
                                fill=accent_c)
            _draw_text(d, (bx + cfs * 0.7, by + bh / 2 - cfs * 0.62),
                       cta, cfs, pal["on_accent"])
    else:
        spec = LAYOUT_SPEC[eff]
        pad = max(margin, int(w * spec["x"]))
        text_w = max(12, min(int(w * spec["w"]), w - pad - margin))
        light_card = spec["panel"] == "card"
        fg_c, sub_c = (pal["on_accent"], pal["on_accent"]) if light_card else (pal["fg"], pal["sub"])

        # 版面底色：只在文字区，主体区保留 AI 底图 / 商品原色
        if spec["panel"] == "bottom":
            d.rectangle([0, int(h * 0.55), w, h], fill=pal["bg1"])
        elif spec["panel"] == "right":
            d.rectangle([int(w * 0.52), 0, w, h], fill=pal["bg1"])
        elif spec["panel"] == "center":
            d.rounded_rectangle([int(w * 0.06), int(h * 0.27), int(w * 0.94), int(h * 0.83)],
                                radius=int(min(w, h) * 0.04), fill=pal["bg1"])
        elif light_card:
            d.rounded_rectangle([int(w * 0.07), int(h * 0.32), int(w * 0.93), int(h * 0.84)],
                                radius=int(min(w, h) * 0.035), fill=pal["card"])
        if spec["band"] == "top":
            d.rectangle([0, 0, w, max(2, int(h * 0.018))], fill=accent_c)

        fs = int(min(w, h) * 0.105)
        hf = _primary_font(fs)
        lines = _wrap(d, headline, hf, text_w, 4)
        while len(lines) > 3 and fs > 18:
            fs = int(fs * 0.88)
            hf = _primary_font(fs)
            lines = _wrap(d, headline, hf, text_w, 4)
        if strict_text:
            lines = _wrap(d, headline, hf, text_w, 4, allow_ellipsis=False)
        sfs = max(12, int(fs * 0.40))
        sf = _primary_font(sfs)
        sub_lines = (_wrap(d, sub, sf, text_w, 3,
                           allow_ellipsis=not strict_text) if sub else [])
        cfs = max(12, int(fs * 0.42))
        cf = _primary_font(cfs)
        bh = int(cfs * 2.1)
        bw = int(d.textlength(cta, font=cf) + cfs * 2.2) if cta else 0
        if strict_text and bw > text_w:
            raise TextOverflowError("CTA 超出该版式文字区宽度")

        line_h = int(fs * 1.24)
        block = len(lines) * line_h
        if sub_lines:
            block += int(fs * 0.22) + len(sub_lines) * int(sfs * 1.34)
        if cta:
            block += int(h * 0.055) + bh

        top = int(h * spec["top"])
        # Logo 在右上角时，文字块整体下移到 Logo 安全区之外
        if logo_box and pad + text_w > logo_box[0] - 4:
            if top < logo_box[1] + logo_box[3] + 6:
                top = logo_box[1] + logo_box[3] + 6
        if top + block > h - margin:
            top = max(int(h * 0.05), h - margin - block)

        if brand:
            bf = max(11, int(h * 0.026))
            _draw_text(d, (pad, max(int(h * 0.03), top - int(h * 0.075))),
                       brand, bf, sub_c)

        # 强调元素随版式变化，不再所有图共用一条短黄线
        if spec["rule"] == "left":
            d.rectangle([pad, top, pad + max(3, int(fs * 0.09)), top + block - 1],
                        fill=accent_c)
            text_x = pad + max(3, int(fs * 0.09)) + int(fs * 0.28)
        else:
            rx = pad if spec["rule"] == "top" else int((w - int(text_w * 0.14)) / 2)
            d.rectangle([rx, top - int(fs * 0.30), rx + int(text_w * 0.14),
                         top - int(fs * 0.23)], fill=accent_c)
            text_x = pad

        y = top
        for ln in lines:
            _draw_text(d, (text_x, y), ln, fs, fg_c)
            y += line_h
        if sub_lines:
            y += int(fs * 0.22)
            for ln in sub_lines:
                _draw_text(d, (text_x, y), ln, sfs, sub_c)
                y += int(sfs * 1.34)
        if cta:
            by = y + int(h * 0.055)
            bx = text_x if spec["rule"] != "center" else int(pad + (text_w - bw) / 2)
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh / 2),
                                fill=accent_c)
            _draw_text(d, (bx + cfs * 1.1, by + bh / 2 - cfs * 0.66),
                       cta, cfs, pal["on_accent"])

    img = _composite_logo(img, logo_path, w, h, logo_box, remove_white_logo_bg)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def image_size(path: str):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None
