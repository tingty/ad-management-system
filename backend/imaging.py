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

# 品牌色板（可按客户替换）
PALETTE = {
    "bg1": (16, 42, 67),
    "bg2": (31, 78, 121),
    "accent": (255, 196, 61),
    "fg": (255, 255, 255),
    "sub": (207, 226, 243),
}

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


def text_budget(width: int, height: int) -> dict:
    """V4.39 / F01：按版位像素预算估算图内文字可容纳的字符数。

    平台正文（primary_text / body / description）与图内文字（headline + 短副标 + CTA）
    是两套东西：这里只算**图内文字**预算，供 media_ad 在调用模型 / 渲染之前拦截。
    系数 0.55 为字体平均字宽的经验值，最终以 `_wrap` 的真实字体度量为准。
    """
    w, h = int(width or 1080), int(height or 1080)
    margin = max(10, int(min(w, h) * 0.06))
    if h <= 120 or w / h > 4:
        fs = max(11, int(h * 0.34))
        avail = w - margin * 2 - int(w * 0.24) - 8
        cfs = max(9, int(h * 0.26))
        return {"layout": "banner", "headline_chars": max(6, int(avail / (fs * 0.55))),
                "sub_chars": 0, "cta_chars": max(4, int((w * 0.24) / (cfs * 0.55)))}
    fs = int(min(w, h) * 0.105)
    max_width = w - margin * 2
    cpl = max(6, int(max_width / (fs * 0.55)))
    sfs = max(12, int(fs * 0.40))
    sub_cpl = max(8, int(max_width / (sfs * 0.55)))
    cfs = max(12, int(fs * 0.42))
    return {"layout": "block", "headline_chars": cpl * 3,
            "sub_chars": sub_cpl * 3,
            "cta_chars": max(6, int((w * 0.6) / (cfs * 0.55)))}


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), PALETTE["bg1"])
    top, bottom = PALETTE["bg1"], PALETTE["bg2"]
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        ))
    return img


def _prepare_bg(w: int, h: int, bg_path: str | None) -> Image.Image:
    """AI 底图按 cover 裁剪到目标尺寸并压暗，保证文字可读。"""
    if bg_path and os.path.exists(bg_path):
        try:
            src = Image.open(bg_path).convert("RGB")
            scale = max(w / src.width, h / src.height)
            src = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.LANCZOS)
            left = (src.width - w) // 2
            top = (src.height - h) // 2
            src = src.crop((left, top, left + w, top + h))
            veil = Image.new("RGB", (w, h), (8, 18, 30))
            return Image.blend(src, veil, 0.42)   # 压暗 42%，文字更清晰
        except Exception:
            pass
    return _gradient(w, h)


def _composite_logo(img: Image.Image, logo_path: str | None, w: int, h: int) -> Image.Image:
    """把品牌 logo 合成到广告图右上角安全区（小 banner 则贴右侧居中）。

    自动处理透明通道；针对无透明通道的 JPG 做近白背景去除，避免白块。
    """
    if not logo_path or not os.path.exists(logo_path):
        return img
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return img
    if logo.height <= 0 or logo.width <= 0:
        return img
    is_small = h <= 120 or w / h > 4
    target_h = int(h * 0.40) if is_small else int(min(w, h) * 0.13)
    target_h = max(18, min(target_h, 140))
    ratio = target_h / float(logo.height)
    tw, th = max(1, int(logo.width * ratio)), target_h
    logo = logo.resize((tw, th), Image.LANCZOS)
    if logo.mode != "RGBA":
        logo = logo.convert("RGBA")
    # 近白背景去除（仅作用于原本不透明的像素）
    datas = logo.getdata()
    new_data = []
    for r, g, b, a in datas:
        if a > 0 and r > 245 and g > 245 and b > 245:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    logo.putdata(new_data)
    margin = max(8, int(min(w, h) * 0.04))
    x = w - tw - margin
    y = margin if not is_small else (h - th) // 2
    img.paste(logo, (x, y), logo)
    return img


def render_ad_png(out_path: str, width: int, height: int, headline: str, sub: str,
                  cta: str, brand: str = "", bg_path: str | None = None,
                  logo_path: str | None = None, accent: tuple = None,
                  strict_text: bool = False) -> str:
    """V4.39 / F01：strict_text=True 时文字放不下就抛 TextOverflowError，
    不再用省略号代替必要说明；由上层把该版位标为 needs_revision 并阻止导出。
    """
    accent = accent or PALETTE["accent"]
    img = _prepare_bg(width, height, bg_path)
    d = ImageDraw.Draw(img)
    w, h = width, height
    margin = max(10, int(min(w, h) * 0.06))

    if h <= 120 or w / h > 4:
        # 小banner / 横条：单行布局（文案与 CTA 各占一侧，互不挤压）
        fs = max(11, int(h * 0.34))
        pf = _primary_font(fs)
        line = (headline or brand or "Ad")
        cta_w = int(w * 0.24) if cta else 0
        avail = w - margin * 2 - cta_w - 8
        while d.textlength(line, font=pf) > avail and fs > 8:
            fs -= 1
            pf = _primary_font(fs)
        if strict_text and d.textlength(line, font=pf) > avail:
            raise TextOverflowError("小横幅标题超出可排版宽度")
        _draw_text(d, (margin, (h - fs * 1.2) / 2), line, fs, PALETTE["fg"])
        if cta:
            cfs = max(9, int(h * 0.26))
            cf = _primary_font(cfs)
            while d.textlength(cta, font=cf) + cfs * 1.4 > cta_w and cfs > 8:
                cfs -= 1
                cf = _primary_font(cfs)
            if strict_text and d.textlength(cta, font=cf) + cfs * 1.4 > cta_w:
                raise TextOverflowError("小横幅 CTA 超出可排版宽度")
            tw = d.textlength(cta, font=cf)
            bw = tw + cfs * 1.4
            bh = min(h - 8, cfs * 2.0)
            bx, by = w - margin - bw, (h - bh) / 2
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh / 2), fill=accent)
            _draw_text(d, (bx + cfs * 0.7, by + bh / 2 - cfs * 0.62), cta, cfs, (25, 30, 38))
    else:
        # 竖版 / 方版 / 横版：垂直居中分块布局
        pad = margin
        fs = int(min(w, h) * 0.105)
        hf = _primary_font(fs)
        lines = _wrap(d, headline, hf, w - pad * 2, 4)
        while len(lines) > 3 and fs > 18:
            fs = int(fs * 0.88)
            hf = _primary_font(fs)
            lines = _wrap(d, headline, hf, w - pad * 2, 4)

        if strict_text:
            # 自适应阶段用探测模式，定稿后再以严格模式校验，放不下就阻断出图
            lines = _wrap(d, headline, hf, w - pad * 2, 4, allow_ellipsis=False)
        sfs = max(12, int(fs * 0.40))
        sf = _primary_font(sfs)
        sub_lines = (_wrap(d, sub, sf, w - pad * 2, 3,
                           allow_ellipsis=not strict_text) if sub else [])

        cfs = max(12, int(fs * 0.42))
        cf = _primary_font(cfs)
        bh = int(cfs * 2.1)
        bw = int(d.textlength(cta, font=cf) + cfs * 2.2) if cta else 0

        line_h = int(fs * 1.24)
        block = len(lines) * line_h
        if sub_lines:
            block += int(fs * 0.22) + len(sub_lines) * int(sfs * 1.34)
        if cta:
            block += int(h * 0.055) + bh

        # 内容块起点：默认在 30% 高度，若会压到底部安全区则整体上移
        top = int(h * 0.30)
        if top + block > h - pad:
            top = max(int(h * 0.08), h - pad - block)
        # 顶部品牌条
        if brand:
            bf = _primary_font(max(11, int(h * 0.026)))
            _draw_text(d, (pad, max(int(h * 0.03), top - int(h * 0.075))), brand, max(11, int(h * 0.026)), PALETTE["sub"])

        # 强调短线
        d.rectangle([pad, top - int(fs * 0.30), pad + int((w - pad * 2) * 0.14), top - int(fs * 0.23)], fill=accent)

        y = top
        for ln in lines:
            _draw_text(d, (pad, y), ln, fs, PALETTE["fg"])
            y += line_h
        if sub_lines:
            y += int(fs * 0.22)
            for ln in sub_lines:
                _draw_text(d, (pad, y), ln, sfs, PALETTE["sub"])
                y += int(sfs * 1.34)
        if cta:
            by = y + int(h * 0.055)
            d.rounded_rectangle([pad, by, pad + bw, by + bh], radius=int(bh / 2), fill=accent)
            _draw_text(d, (pad + cfs * 1.1, by + bh / 2 - cfs * 0.66), cta, cfs, (25, 30, 38))

    img = _composite_logo(img, logo_path, w, h)

    img.save(out_path, "PNG", optimize=True)
    return out_path


def image_size(path: str):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None
