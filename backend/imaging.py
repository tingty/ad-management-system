"""
V1.3 图片合成：用 Pillow 把文案渲染成"可直接投放"的 PNG。
- 支持任意平台尺寸（从 320x50 小banner 到 1080x1920 竖版）；
- 有 AI 底图时做文字叠加（含安全边距与压暗），无 AI 底图时用品牌渐变模板；
- 中文/英文混排自动选字体，长文本按像素宽度折行。
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    # 新版 macOS 无 PingFang.ttc，按可用性回退，避免中文渲染成方框
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]

# 品牌色板（可按客户替换）
PALETTE = {
    "bg1": (16, 42, 67),
    "bg2": (31, 78, 121),
    "accent": (255, 196, 61),
    "fg": (255, 255, 255),
    "sub": (207, 226, 243),
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)   # Pillow >= 10.1
    except Exception:
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """折行：含空格按词折（避免英文断词），中文按字符折；超出行数加省略号。"""
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
    if len(lines) >= max_lines and i < len(units):
        last = lines[max_lines - 1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[max_lines - 1] = last + "…"
    return [ln for ln in lines[:max_lines] if ln]


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


def render_ad_png(out_path: str, width: int, height: int, headline: str, sub: str,
                  cta: str, brand: str = "", bg_path: str | None = None,
                  accent: tuple = None) -> str:
    accent = accent or PALETTE["accent"]
    img = _prepare_bg(width, height, bg_path)
    d = ImageDraw.Draw(img)
    w, h = width, height
    margin = max(10, int(min(w, h) * 0.06))

    if h <= 120 or w / h > 4:
        # 小banner / 横条：单行布局（文案与 CTA 各占一侧，互不挤压）
        fs = max(11, int(h * 0.34))
        f = _font(fs)
        line = (headline or brand or "Ad")
        cta_w = int(w * 0.24) if cta else 0
        avail = w - margin * 2 - cta_w - 8
        while d.textlength(line, font=f) > avail and fs > 8:
            fs -= 1
            f = _font(fs)
        d.text((margin, (h - fs * 1.2) / 2), line, font=f, fill=PALETTE["fg"])
        if cta:
            cfs = max(9, int(h * 0.26))
            cf = _font(cfs)
            while d.textlength(cta, font=cf) + cfs * 1.4 > cta_w and cfs > 8:
                cfs -= 1
                cf = _font(cfs)
            tw = d.textlength(cta, font=cf)
            bw = tw + cfs * 1.4
            bh = min(h - 8, cfs * 2.0)
            bx, by = w - margin - bw, (h - bh) / 2
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh / 2), fill=accent)
            d.text((bx + cfs * 0.7, by + bh / 2 - cfs * 0.62), cta, font=cf, fill=(25, 30, 38))
    else:
        # 竖版 / 方版 / 横版：垂直居中分块布局
        pad = margin
        fs = int(min(w, h) * 0.105)
        hf = _font(fs)
        lines = _wrap(d, headline, hf, w - pad * 2, 4)
        while len(lines) > 3 and fs > 18:
            fs = int(fs * 0.88)
            hf = _font(fs)
            lines = _wrap(d, headline, hf, w - pad * 2, 4)

        sfs = max(12, int(fs * 0.40))
        sf = _font(sfs)
        sub_lines = _wrap(d, sub, sf, w - pad * 2, 3) if sub else []

        cfs = max(12, int(fs * 0.42))
        cf = _font(cfs)
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
            bf = _font(max(11, int(h * 0.026)))
            d.text((pad, max(int(h * 0.03), top - int(h * 0.075))), brand, font=bf, fill=PALETTE["sub"])

        # 强调短线
        d.rectangle([pad, top - int(fs * 0.30), pad + int((w - pad * 2) * 0.14), top - int(fs * 0.23)], fill=accent)

        y = top
        for ln in lines:
            d.text((pad, y), ln, font=hf, fill=PALETTE["fg"])
            y += line_h
        if sub_lines:
            y += int(fs * 0.22)
            for ln in sub_lines:
                d.text((pad, y), ln, font=sf, fill=PALETTE["sub"])
                y += int(sfs * 1.34)
        if cta:
            by = y + int(h * 0.055)
            d.rounded_rectangle([pad, by, pad + bw, by + bh], radius=int(bh / 2), fill=accent)
            d.text((pad + cfs * 1.1, by + bh / 2 - cfs * 0.66), cta, font=cf, fill=(25, 30, 38))

    img.save(out_path, "PNG", optimize=True)
    return out_path


def image_size(path: str):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None
