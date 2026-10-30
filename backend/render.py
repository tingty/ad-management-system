"""
广告图渲染引擎 V2（Pillow）。

旧版问题：只有一套「深蓝渐变 + 大字」版式，同平台 8 个尺寸 = 同一张图换比例，
画面里没有视觉主体，成品更像海报占位图而不是可投放素材。

本版：
- 6 套视觉模板，每套有自己的构图与视觉主体（产品界面 / 评分卡 / 折扣角标 / 前后对比 / UGC 手机框 / 大字）；
- 同一创意在不同版位是「重新排版」：横幅改为左右分栏、竖版改为上下分区，而不是拉伸；
- 品牌色驱动整套配色，支持上传产品图与 Logo；
- 标题按像素自适应，绝不切断单词；文字区与主体区互不侵占。
"""
import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_LATIN_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_LATIN_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
FONT_LATIN = "/System/Library/Fonts/Supplemental/Arial.ttf"
# 注意：新版 macOS 已移除 PingFang.ttc，写死它会让中文渲染成方框（旧版就有这个隐患）。
# 这里按可用性依次尝试，并保留 Linux 的 Noto 兜底。
FONT_CJK_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
FONT_FALLBACK = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]

DEFAULT_ACCENT = (255, 176, 32)


# ----------------------------- 颜色 -----------------------------
def hex2rgb(s: str, default=DEFAULT_ACCENT):
    try:
        s = (s or "").strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shade(c, t):
    """t<0 变暗，t>0 变亮。"""
    target = (0, 0, 0) if t < 0 else (255, 255, 255)
    return mix(c, target, abs(t))


def make_palette(brand_hex: str | None, light: bool = False) -> dict:
    """深底用「近黑中性色 + 少量品牌色」，而不是把品牌色直接压暗。

    直接把橙色压暗会得到土褐色，画面发闷；中性深底才能让强调色跳出来。
    """
    accent = hex2rgb(brand_hex) if brand_hex else DEFAULT_ACCENT
    on_accent = (16, 20, 28) if sum(accent) > 420 else (255, 255, 255)
    if light:
        return {
            "accent": accent,
            "bg1": (250, 250, 252),
            "bg2": mix(accent, (255, 255, 255), 0.88),
            "fg": (18, 22, 30),
            "sub": (96, 106, 122),
            "card": (255, 255, 255),
            "on_accent": on_accent,
        }
    return {
        "accent": accent,
        "bg1": mix((12, 14, 19), accent, 0.05),
        "bg2": mix((24, 27, 33), accent, 0.045),
        "fg": (255, 255, 255),
        "sub": mix(accent, (214, 222, 234), 0.72),
        "card": (255, 255, 255),
        "on_accent": on_accent,
    }


def phone_box(box, aspect: float = 0.52):
    """在给定区域内取一个符合手机比例（宽/高≈0.52）的居中矩形。"""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    w = min(bw, bh * aspect)
    h = w / aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


# ----------------------------- 字体 / 排版 -----------------------------
def has_cjk(text: str) -> bool:
    return bool(text) and any("\u4e00" <= ch <= "\u9fa5" for ch in text)


def _font(size: int, text: str = "", bold: bool = True) -> ImageFont.FreeTypeFont:
    size = max(6, int(size))
    cjk = has_cjk(text)
    if bold:
        cands = FONT_CJK_CANDIDATES if cjk else [FONT_LATIN_BLACK, FONT_LATIN_BOLD]
    else:
        cands = FONT_CJK_CANDIDATES if cjk else [FONT_LATIN, FONT_LATIN_BOLD]
    for p in cands + FONT_FALLBACK:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def text_w(draw, text, font) -> float:
    return draw.textlength(text or "", font=font)


def wrap_text(draw, text: str, font, max_w: int, max_lines: int = 99) -> list[str]:
    """按词折行（中文按字），不切断单词。"""
    text = (text or "").strip()
    if not text:
        return []
    if has_cjk(text):
        units = list(text)
        sep = ""
    else:
        units = text.split()
        sep = " "
    lines, cur, i = [], "", 0
    while i < len(units):
        u = units[i]
        cand = u if not cur else cur + sep + u
        if text_w(draw, cand, font) <= max_w:
            cur = cand
            i += 1
            continue
        if cur:
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                return lines[:max_lines]
            continue
        # 单个词就超宽：逐个字符塞
        piece = ""
        for ch in u:
            if text_w(draw, piece + ch, font) <= max_w:
                piece += ch
            else:
                break
        lines.append(piece or u[:1])
        rest = u[len(piece):]
        units[i] = rest
        if not rest:
            i += 1
        if len(lines) >= max_lines:
            return lines[:max_lines]
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def fit_headline(draw, text, max_w, max_h, size_max, size_min, max_lines=3, bold=True):
    """在给定框内找可用字号：优先少行，其次大字号。

    只按「能塞进几行」放字号，会把 “Ends soon” 排成两行超大字，行距大得像两句话。
    这里先算出每个行数下的最大字号，再优先选行数少、字号损失不超过 18% 的方案。
    """
    def best_for(line_cap):
        size = int(size_max)
        while size >= size_min:
            f = _font(size, text, bold)
            # 必须用 99 行做测量：wrap_text 带 max_lines 时会把多余的行丢掉，
            # 拿它判断"能不能放下"永远为真，标题就会被悄悄截成一行。
            lines = wrap_text(draw, text, f, max_w, 99)
            line_h = int(size * 1.18)
            if lines and len(lines) <= line_cap and len(lines) * line_h <= max_h:
                return size, lines, line_h
            size = int(size * 0.92)
        f = _font(size_min, text, bold)
        return size_min, wrap_text(draw, text, f, max_w, line_cap), int(size_min * 1.18)

    sizes = {}
    for cap in range(1, max_lines + 1):
        s, lines, lh = best_for(cap)
        sizes[cap] = (s, lines, lh)
    top = max(v[0] for v in sizes.values())
    for cap in range(1, max_lines + 1):
        s, lines, lh = sizes[cap]
        if s >= top * 0.82 and len(lines) <= cap:
            return _font(s, text, bold), s, lines, lh
    return _font(size_min, text, bold), size_min, sizes[max_lines][1], int(size_min * 1.18)


# ----------------------------- 画布 -----------------------------
class Canvas:
    def __init__(self, w, h, pal):
        self.w, self.h = w, h
        self.pal = pal
        self.img = Image.new("RGB", (w, h), pal["bg1"])
        self.d = ImageDraw.Draw(self.img)
        self.s = min(w, h)
        self.m = max(10, int(self.s * 0.055))     # 安全边距

    def gradient(self, c1, c2, diagonal=True):
        w, h = self.w, self.h
        base = Image.new("RGB", (w, h), c1)
        d = ImageDraw.Draw(base)
        steps = h if not diagonal else max(w, h)
        for i in range(steps):
            t = i / max(1, steps - 1)
            col = mix(c1, c2, t)
            if diagonal:
                d.line([(0, i), (w, i)], fill=col)
            else:
                d.line([(i, 0), (i, h)], fill=col)
        self.img = base
        self.d = ImageDraw.Draw(self.img)

    def blobs(self, color, n=3, alpha=26):
        """柔光色块，避免纯渐变显得死板。"""
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        rnd = [(0.15, 0.22, 0.42), (0.86, 0.12, 0.30), (0.72, 0.86, 0.46)]
        for i in range(min(n, len(rnd))):
            fx, fy, fr = rnd[i]
            r = int(self.s * fr)
            dl.ellipse([fx * self.w - r, fy * self.h - r, fx * self.w + r, fy * self.h + r],
                       fill=color + (alpha,))
        layer = layer.filter(ImageFilter.GaussianBlur(int(self.s * 0.09)))
        self.img = Image.alpha_composite(self.img.convert("RGBA"), layer).convert("RGB")
        self.d = ImageDraw.Draw(self.img)

    def rrect(self, box, r, fill=None, outline=None, width=2):
        self.d.rounded_rectangle(box, radius=max(0, int(r)), fill=fill, outline=outline, width=width)

    def shadow(self, box, r, spread=None, alpha=90):
        spread = spread or int(self.s * 0.02)
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        x0, y0, x1, y1 = box
        dl.rounded_rectangle([x0 - spread, y0 - spread, x1 + spread, y1 + spread],
                             radius=r + spread, fill=(0, 0, 0, alpha))
        layer = layer.filter(ImageFilter.GaussianBlur(int(self.s * 0.022)))
        self.img = Image.alpha_composite(self.img.convert("RGBA"), layer).convert("RGB")
        self.d = ImageDraw.Draw(self.img)

    def pill(self, x, y, text, size, pad_x=None, pad_y=None, fill=None, fg=None, r=None):
        f = _font(size, text, True)
        pad_x = pad_x if pad_x is not None else int(size * 1.1)
        pad_y = pad_y if pad_y is not None else int(size * 0.55)
        tw = text_w(self.d, text, f)
        bw, bh = tw + pad_x * 2, size + pad_y * 2
        r = bh / 2 if r is None else r
        self.rrect([x, y, x + bw, y + bh], r, fill or self.pal["accent"])
        ty = y + (bh - size * 1.2) / 2
        self.d.text((x + pad_x, ty), text, font=f, fill=fg or self.pal["on_accent"])
        return bw, bh

    def brand_mark(self, x, y, size, name="", fg=None):
        """品牌标识：首字母方块 + 名称。"""
        fg = fg or self.pal["fg"]
        r = int(size * 0.28)
        self.rrect([x, y, x + size, y + size], r, fill=self.pal["accent"])
        initial = (name or "A")[:1].upper()
        f = _font(int(size * 0.58), initial, True)
        tw = text_w(self.d, initial, f)
        self.d.text((x + (size - tw) / 2, y + size * 0.17), initial, font=f,
                    fill=self.pal["on_accent"])
        if name:
            nf = _font(int(size * 0.46), name, True)
            self.d.text((x + size * 1.35, y + size * 0.22), name, font=nf, fill=fg)


# ----------------------------- 视觉主体 -----------------------------
def paste_product(c: Canvas, path: str, box, radius=None) -> bool:
    """把上传的产品图按 contain 放进框内（不裁切主体），圆角遮罩。"""
    if not path or not os.path.exists(path):
        return False
    try:
        src = Image.open(path).convert("RGBA")
    except Exception:
        return False
    x0, y0, x1, y1 = [int(v) for v in box]
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    scale = min(bw / src.width, bh / src.height)
    nw, nh = max(1, int(src.width * scale)), max(1, int(src.height * scale))
    src = src.resize((nw, nh), Image.LANCZOS)
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    layer.paste(src, ((bw - nw) // 2, (bh - nh) // 2), src)
    r = radius if radius is not None else int(min(bw, bh) * 0.08)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=r, fill=255)
    c.img.paste(layer, (x0, y0), Image.composite(mask, Image.new("L", (bw, bh), 0), layer.split()[3]))
    c.d = ImageDraw.Draw(c.img)
    return True


def draw_phone(c: Canvas, box, accent, ui="list", caption=None):
    """画一个手机界面（合成 UI），作为「产品使用中」的视觉主体。

    没有真实产品截图时，这比纯文字海报更接近可投放素材：
    有设备轮廓、有界面层级、有 CTA 按钮，缩到 300x250 仍能辨认。
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    bw, bh = x1 - x0, y1 - y0
    r = int(min(bw, bh) * 0.10)
    c.shadow([x0, y0, x1, y1], r, alpha=110)
    c.rrect([x0, y0, x1, y1], r, fill=(12, 16, 24))
    pad = max(3, int(min(bw, bh) * 0.035))
    sx0, sy0, sx1, sy1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    sr = max(2, r - pad // 2)
    # 屏幕底色
    c.rrect([sx0, sy0, sx1, sy1], sr, fill=(24, 30, 42))
    sw, sh = sx1 - sx0, sy1 - sy0
    inner = int(min(sw, sh) * 0.06)

    # 状态栏
    bar_h = max(4, int(sh * 0.045))
    c.d.rectangle([sx0 + inner, sy0 + bar_h // 2, sx0 + inner + int(sw * 0.18), sy0 + bar_h // 2 + 2],
                  fill=(120, 132, 150))
    c.d.ellipse([sx1 - inner - 8, sy0 + bar_h // 2 - 3, sx1 - inner - 2, sy0 + bar_h // 2 + 3],
                fill=(120, 132, 150))

    top = sy0 + bar_h + int(sh * 0.02)
    # 顶部标题条
    c.rrect([sx0 + inner, top, sx0 + inner + int(sw * 0.46), top + int(sh * 0.035)],
            int(sh * 0.018), fill=(210, 220, 235))
    top += int(sh * 0.075)

    if ui == "grid":
        cols, rows = 3, 3
        cell = (sw - inner * 2 - inner * (cols - 1)) / cols
        for r_i in range(rows):
            for c_i in range(cols):
                bx = sx0 + inner + c_i * (cell + inner)
                by = top + r_i * (cell + inner)
                if by + cell > sy1 - int(sh * 0.12):
                    break
                col = accent if (r_i + c_i) % 3 == 0 else (58, 70, 90)
                c.rrect([bx, by, bx + cell, by + cell], cell * 0.22, fill=col)
    else:
        # 内容卡片列表
        card_h = int(sh * 0.16)
        for i in range(3):
            cy = top + i * (card_h + int(sh * 0.03))
            if cy + card_h > sy1 - int(sh * 0.12):
                break
            c.rrect([sx0 + inner, cy, sx1 - inner, cy + card_h], card_h * 0.18, fill=(38, 46, 62))
            thumb = int(card_h * 0.62)
            c.rrect([sx0 + inner + card_h * 0.2, cy + (card_h - thumb) / 2,
                     sx0 + inner + card_h * 0.2 + thumb, cy + (card_h + thumb) / 2],
                    thumb * 0.24, fill=accent if i == 0 else (72, 86, 108))
            lx = sx0 + inner + card_h * 0.2 + thumb + card_h * 0.22
            c.rrect([lx, cy + card_h * 0.28, lx + int(sw * 0.32), cy + card_h * 0.28 + card_h * 0.14],
                    card_h * 0.07, fill=(196, 208, 224))
            c.rrect([lx, cy + card_h * 0.54, lx + int(sw * 0.24), cy + card_h * 0.54 + card_h * 0.11],
                    card_h * 0.06, fill=(120, 134, 156))

    # 底部主按钮
    bw2 = int(sw * 0.62)
    bh2 = max(10, int(sh * 0.075))
    bxx = sx0 + (sw - bw2) / 2
    byy = sy1 - inner - bh2 - int(sh * 0.03)
    c.rrect([bxx, byy, bxx + bw2, byy + bh2], bh2 / 2, fill=accent)

    if caption:
        cf = _font(max(7, int(sh * 0.05)), caption, True)
        c.d.text((x0 + (bw - text_w(c.d, caption, cf)) / 2, y1 + int(bh * 0.04)),
                 caption, font=cf, fill=c.pal["sub"])


def draw_stars(c: Canvas, cx, cy, r, n=5, fill=None, gap=0.55):
    fill = fill or c.pal["accent"]
    total = n * r * 2 + (n - 1) * r * gap
    x = cx - total / 2
    for _ in range(n):
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rad = r if k % 2 == 0 else r * 0.42
            pts.append((x + r + rad * math.cos(ang), cy + rad * math.sin(ang)))
        c.d.polygon(pts, fill=fill)
        x += r * 2 + r * gap


def draw_check(c: Canvas, cx, cy, r, ok=True, fill=None):
    fill = fill or ((64, 196, 120) if ok else (232, 92, 92))
    c.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    if ok:
        c.d.line([(cx - r * 0.42, cy + r * 0.02), (cx - r * 0.08, cy + r * 0.38),
                  (cx + r * 0.46, cy - r * 0.34)], fill=(255, 255, 255), width=max(2, int(r * 0.22)),
                 joint="curve")
    else:
        c.d.line([(cx - r * 0.36, cy - r * 0.36), (cx + r * 0.36, cy + r * 0.36)],
                 fill=(255, 255, 255), width=max(2, int(r * 0.22)))
        c.d.line([(cx + r * 0.36, cy - r * 0.36), (cx - r * 0.36, cy + r * 0.36)],
                 fill=(255, 255, 255), width=max(2, int(r * 0.22)))


def draw_badge(c: Canvas, cx, cy, r, top, bottom, accent, on_accent, rotate=-8):
    """圆形折扣角标（可轻微倾斜），促销模板的核心视觉。文字按圆内宽度收字号。"""
    c.shadow([cx - r, cy - r, cx + r, cy + r], r, alpha=120)
    c.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    c.d.ellipse([cx - r * 0.88, cy - r * 0.88, cx + r * 0.88, cy + r * 0.88],
                outline=on_accent, width=max(2, int(r * 0.045)))

    max_w = r * 1.42
    size = int(r * 0.66)
    f1 = _font(size, top, True)
    while text_w(c.d, top, f1) > max_w and size > 6:
        size = int(size * 0.9)
        f1 = _font(size, top, True)
    c.d.text((cx - text_w(c.d, top, f1) / 2, cy - size * 0.62), top, font=f1, fill=on_accent)

    if bottom:
        bsize = int(r * 0.26)
        f2 = _font(bsize, bottom, True)
        while text_w(c.d, bottom, f2) > max_w and bsize > 5:
            bsize = int(bsize * 0.88)
            f2 = _font(bsize, bottom, True)
        c.d.text((cx - text_w(c.d, bottom, f2) / 2, cy + r * 0.18), bottom,
                 font=f2, fill=on_accent)


# ----------------------------- 版位判定 -----------------------------
def layout_kind(w, h):
    ratio = w / max(1, h)
    if h <= 150 or ratio >= 3.0:
        return "banner"
    if ratio >= 1.35:
        return "landscape"
    if ratio >= 0.85:
        return "square"
    if ratio <= 0.5:
        return "tall"
    return "portrait"


# ----------------------------- 文本块 -----------------------------
def draw_text_block(c: Canvas, box, headline, sub, cta, sizes=(1.0, 1.0)):
    """在指定框内排版标题/副标/CTA，自动缩放，不溢出。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    bw, bh = x1 - x0, y1 - y0
    if bw <= 8 or bh <= 8:
        return
    cta_h = 0
    cta_size = 0
    if cta:
        cta_size = max(9, int(min(bh * 0.17, bw * 0.062)))
        cta_h = int(cta_size * 2.0)
    sub_size = max(9, int(min(bh * 0.085, bw * 0.048)))
    head_max_h = bh - cta_h - (bh * 0.05 if cta else 0) - (sub_size * 1.25 if sub else 0)
    f, size, lines, line_h = fit_headline(
        c.d, headline, bw, max(10, head_max_h),
        size_max=min(bh * 0.30, bw * 0.19), size_min=max(8, int(min(bw, bh) * 0.05)),
        max_lines=3 if bh > bw * 0.4 else 2)

    sub_lines = []
    if sub:
        sf = _font(sub_size, sub, False)
        sub_lines = wrap_text(c.d, sub, sf, bw, 99)
        # 两行时若末行只剩一两个词（"...need it." 的 it.），把词数均分重排，
        # 避免孤字行——信息流里这种细节一眼就能看出是模板自动生成的。
        if len(sub_lines) == 2 and len(sub_lines[-1]) < len(sub_lines[0]) * 0.45:
            words = sub.split()
            if len(words) >= 4:
                for cut in range(len(words) // 2, len(words) - 1):
                    a, b = " ".join(words[:cut]), " ".join(words[cut:])
                    if (text_w(c.d, a, sf) <= bw and text_w(c.d, b, sf) <= bw
                            and min(len(a), len(b)) > len(sub_lines[-1])):
                        sub_lines = [a, b]
                        break
        while len(sub_lines) > 2 and sub_size > 8:
            sub_size -= 1
            sf = _font(sub_size, sub, False)
            sub_lines = wrap_text(c.d, sub, sf, bw, 99)
        if len(sub_lines) > 2:      # 字号已到下限：只保留前两行，避免压到 CTA
            sub_lines = sub_lines[:2]

    total = len(lines) * line_h
    if sub_lines:
        total += int(size * 0.26) + len(sub_lines) * int(sub_size * 1.32)
    if cta:
        total += int(bh * 0.06) + cta_h

    y = y0 + max(0, (bh - total) / 2)
    for ln in lines:
        c.d.text((x0, y), ln, font=f, fill=c.pal["fg"])
        y += line_h
    if sub_lines:
        y += int(size * 0.26)
        sf = _font(sub_size, sub, False)
        for ln in sub_lines:
            c.d.text((x0, y), ln, font=sf, fill=c.pal["sub"])
            y += int(sub_size * 1.32)
    if cta:
        y += int(bh * 0.06)
        c.pill(x0, y, cta, cta_size)


def draw_banner(c: Canvas, headline, cta, brand):
    """横幅/小尺寸：单行标题 + 右侧按钮，保证 320x50 也能读清。"""
    m = max(6, int(c.h * 0.10))
    mark = int(c.h * 0.62)
    c.brand_mark(m, (c.h - mark) / 2, mark, "")
    tx = m + mark * 1.5
    cta_w = 0
    if cta:
        cs = max(8, int(c.h * 0.30))
        cf = _font(cs, cta, True)
        cta_w = text_w(c.d, cta, cf) + cs * 2.0
        bw = cta_w
        bh = min(c.h - m, cs * 2.1)
        bx = c.w - m - bw
        c.rrect([bx, (c.h - bh) / 2, bx + bw, (c.h + bh) / 2], bh / 2, fill=c.pal["accent"])
        c.d.text((bx + cs * 1.0, (c.h - cs * 1.2) / 2), cta, font=cf, fill=c.pal["on_accent"])
    avail = c.w - tx - m - (cta_w + m if cta else 0)
    size = int(c.h * 0.42)
    while size > 7:
        f = _font(size, headline, True)
        if text_w(c.d, headline, f) <= avail:
            break
        size -= 1
    f = _font(size, headline, True)
    c.d.text((tx, (c.h - size * 1.2) / 2), headline, font=f, fill=c.pal["fg"])


# ----------------------------- 模板 -----------------------------
def _zones(c: Canvas):
    """按版位返回 (主体框, 文本框)；横幅由调用方单独处理。"""
    kind = layout_kind(c.w, c.h)
    m = c.m
    if kind == "landscape":
        subject = (m, int(c.h * 0.12), int(c.w * 0.44), int(c.h * 0.88))
        text = (int(c.w * 0.50), int(c.h * 0.16), c.w - m, int(c.h * 0.84))
    elif kind == "square":
        subject = (int(c.w * 0.16), int(c.h * 0.09), int(c.w * 0.84), int(c.h * 0.52))
        text = (m, int(c.h * 0.57), c.w - m, c.h - m)
    elif kind == "tall":
        subject = (int(c.w * 0.10), int(c.h * 0.06), int(c.w * 0.90), int(c.h * 0.36))
        text = (m, int(c.h * 0.40), c.w - m, int(c.h * 0.94))
    else:  # portrait
        subject = (int(c.w * 0.14), int(c.h * 0.08), int(c.w * 0.86), int(c.h * 0.47))
        text = (m, int(c.h * 0.52), c.w - m, int(c.h * 0.93))
    return kind, subject, text


def _base(c: Canvas, brand, light=False):
    c.gradient(c.pal["bg1"], c.pal["bg2"])
    c.blobs(c.pal["accent"], 3, 24)
    if brand:
        c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)


def render_creative(out_path, w, h, data: dict) -> str:
    """渲染一张广告图。data: template/headline/sub/cta/brand/brand_color/product_img/metric"""
    kind = layout_kind(w, h)
    template = data.get("template") or "bigtype"
    brand = data.get("brand") or ""
    metric = (data.get("metric") or "").strip()
    headline = (data.get("headline") or brand or "Ad").strip()
    sub = (data.get("sub") or "").strip()
    cta = (data.get("cta") or "").strip()
    if template == "stat" and not metric:
        # "数字主体"模板没有数字就没有主体，硬画会变成空壳手机框，退回纯字体
        template = "bigtype"
    light = template in ("rating",)
    pal = make_palette(data.get("brand_color"), light=False)
    c = Canvas(w, h, pal)

    if kind == "banner":
        c.gradient(pal["bg1"], pal["bg2"])
        draw_banner(c, headline, cta, brand)
        c.img.save(out_path, "PNG", optimize=True)
        return out_path

    kind, subject, text = _zones(c)

    if template == "rating":
        # 浅色底 + 白色评分卡
        c.gradient((246, 247, 251), mix(pal["accent"], (255, 255, 255), 0.80))
        c.blobs(pal["accent"], 2, 30)
        _base_light_brand(c, brand)
        sx0, sy0, sx1, sy1 = subject
        card_h = min(sy1 - sy0, (sx1 - sx0) * 0.66)
        cy = (sy0 + sy1) / 2
        card = (sx0, cy - card_h / 2, sx1, cy + card_h / 2)
        sy0, sy1 = card[1], card[3]
        c.shadow(card, int(min(sx1 - sx0, sy1 - sy0) * 0.10), alpha=60)
        c.rrect(card, int(min(sx1 - sx0, sy1 - sy0) * 0.10), fill=(255, 255, 255))
        cw, ch = sx1 - sx0, sy1 - sy0
        # 分数只能来自原文里的真实评分。写死 4.8 属于虚构评分，
        # 拿这种素材去投放会被平台判虚假宣传，账户是要受罚的。
        value = (data.get("rating_value") or "").strip()
        label = (data.get("rating_label") or "user rating").strip()
        draw_stars(c, (sx0 + sx1) / 2, sy0 + ch * (0.28 if value else 0.34),
                   max(4, int(cw * 0.045)))
        if value:
            f = _font(int(ch * 0.26), value, True)
            c.d.text(((sx0 + sx1) / 2 - text_w(c.d, value, f) / 2, sy0 + ch * 0.40),
                     value, font=f, fill=(18, 22, 30))
        lf = _font(int(ch * 0.075), label, False)
        lab_y = sy0 + ch * (0.70 if value else 0.52)
        c.d.text(((sx0 + sx1) / 2 - text_w(c.d, label, lf) / 2, lab_y), label,
                 font=lf, fill=(110, 118, 132))
        if data.get("product_img"):
            paste_product(c, data["product_img"], (sx0 + cw * 0.06, sy1 - ch * 0.24,
                                                    sx0 + cw * 0.26, sy1 - ch * 0.06), int(cw * 0.03))
        c.pal = make_palette(data.get("brand_color"), light=True)
        draw_text_block(c, text, headline, sub, cta)

    elif template == "promo":
        c.gradient(pal["bg1"], pal["bg2"])
        c.blobs(pal["accent"], 3, 30)
        if brand:
            c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)
        sx0, sy0, sx1, sy1 = subject
        # 产品/界面作为底
        if not paste_product(c, data.get("product_img"), subject, int(c.s * 0.05)):
            draw_phone(c, phone_box(subject), pal["accent"], "list")
        # 角标
        r = int(min(c.w, c.h) * 0.13)
        draw_badge(c, sx1 - r * 0.6, sy0 + r * 0.9, r, data.get("badge") or "OFFER",
                   data.get("badge_sub") or "", pal["accent"], pal["on_accent"])
        # 这里原来写死一条 "Ends in 02:14:33" 的倒计时——假倒计时同样属于误导，
        # 只在调用方真的传了截止时间时才显示
        note = (data.get("promo_note") or "").strip()
        if note:
            c.pill(c.m, text[1] - int(c.h * 0.045), note, max(9, int(c.h * 0.024)),
                   fill=shade(pal["accent"], -0.15), fg=pal["on_accent"])
        draw_text_block(c, text, headline, sub, cta)

    elif template == "ugc":
        c.gradient((14, 16, 22), mix(pal["accent"], (10, 12, 18), 0.78))
        c.blobs(pal["accent"], 2, 26)
        if brand:
            c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)
        sx0, sy0, sx1, sy1 = subject
        if not paste_product(c, data.get("product_img"), subject, int(c.s * 0.04)):
            draw_phone(c, phone_box(subject), pal["accent"], "list")
        # 右侧竖排互动图标（点赞/评论/分享），UGC 语境的视觉提示
        ix, iy = sx1 - int(c.w * 0.03), sy1 - int((sy1 - sy0) * 0.34)
        rr = max(3, int(c.s * 0.010))
        for i in range(3):
            cy_i = iy + i * rr * 6
            c.d.ellipse([ix - rr * 2, cy_i - rr, ix, cy_i + rr], outline=(240, 244, 250), width=max(1, int(rr * 0.5)))
        draw_text_block(c, text, headline, sub, cta)

    elif template == "compare":
        c.gradient(pal["bg1"], pal["bg2"])
        c.blobs(pal["accent"], 2, 22)
        if brand:
            c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)
        sx0, sy0, sx1, sy1 = subject
        mid = (sx0 + sx1) / 2
        gap = int(c.w * 0.015)
        left = (sx0, sy0, mid - gap, sy1)
        right = (mid + gap, sy0, sx1, sy1)
        c.rrect(left, int(c.s * 0.03), fill=shade(pal["bg1"], -0.18))
        c.rrect(right, int(c.s * 0.03), fill=shade(pal["bg2"], 0.10))
        pw = (right[2] - right[0]) * 0.52
        for box, ok in ((left, False), (right, True)):
            bx0, by0, bx1, by1 = box
            draw_check(c, (bx0 + bx1) / 2, by0 + (by1 - by0) * 0.26,
                       max(6, int(min(bx1 - bx0, by1 - by0) * 0.13)), ok)
            # 下方放一台小手机：左侧灰暗（旧做法），右侧用品牌色（用了产品）
            if bw_px := (bx1 - bx0) >= 80:
                pb = phone_box((bx0 + (bx1 - bx0) * 0.18, by0 + (by1 - by0) * 0.50,
                                bx1 - (bx1 - bx0) * 0.18, by1 - (by1 - by0) * 0.05))
                draw_phone(c, pb, pal["accent"] if ok else (120, 128, 140),
                           "list" if ok else "grid")
            lf = _font(max(8, int((by1 - by0) * 0.062)), "before", True)
            lab = data.get("after_label") if ok else data.get("before_label")
            lab = lab or ("AFTER" if ok else "BEFORE")
            ty = by0 + (by1 - by0) * (0.415 if bw_px else 0.58)
            c.d.text(((bx0 + bx1) / 2 - text_w(c.d, lab, lf) / 2, ty), lab, font=lf,
                     fill=(255, 255, 255) if ok else (188, 198, 214))
        draw_text_block(c, text, headline, sub, cta)

    elif template == "stat":
        c.gradient(pal["bg1"], pal["bg2"])
        c.blobs(pal["accent"], 3, 28)
        if brand:
            c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)
        sx0, sy0, sx1, sy1 = subject
        if data.get("product_img") and paste_product(c, data["product_img"], subject, int(c.s * 0.05)):
            pass
        elif metric:
            fnum = _font(int(min(sx1 - sx0, sy1 - sy0) * 0.62), metric, True)
            tn = metric
            while text_w(c.d, tn, fnum) > (sx1 - sx0) and int(fnum.size) > 12:
                fnum = _font(int(fnum.size * 0.9), tn, True)
            c.d.text(((sx0 + sx1) / 2 - text_w(c.d, tn, fnum) / 2,
                      (sy0 + sy1) / 2 - fnum.size * 0.62), tn, font=fnum, fill=pal["accent"])
        else:
            draw_phone(c, phone_box(subject), pal["accent"], "list")
        if metric and data.get("metric_label"):
            lf = _font(max(9, int(c.s * 0.028)), data["metric_label"], False)
            lb = data["metric_label"]
            c.d.text(((sx0 + sx1) / 2 - text_w(c.d, lb, lf) / 2, sy1 - int(c.h * 0.03)),
                     lb, font=lf, fill=pal["sub"])
        draw_text_block(c, text, headline, sub, cta)

    else:  # bigtype
        c.gradient(pal["bg1"], pal["bg2"], diagonal=False)
        c.blobs(pal["accent"], 2, 18)
        # 强调斜带
        c.d.polygon([(c.w * 0.62, c.h), (c.w, c.h * 0.72), (c.w, c.h)], fill=shade(pal["accent"], -0.55))
        if brand:
            c.brand_mark(c.m, c.m, max(14, int(c.s * 0.052)), brand)
        full = (c.m, int(c.h * 0.18), c.w - c.m, int(c.h * 0.86))
        # 强调短线
        c.d.rectangle([full[0], full[1] - int(c.h * 0.045), full[0] + int((full[2] - full[0]) * 0.16),
                       full[1] - int(c.h * 0.038)], fill=pal["accent"])
        draw_text_block(c, full, headline, sub, cta)

    c.img.save(out_path, "PNG", optimize=True)
    return out_path


def _base_light_brand(c: Canvas, brand: str):
    if brand:
        f = _font(max(12, int(c.s * 0.030)), brand, True)
        c.d.text((c.m, c.m), brand, font=f, fill=(24, 28, 36))


# ----------------------------- 视频关键帧 -----------------------------
def render_keyframe(out_path, w, h, data: dict, idx: int, total: int,
                    timecode: str, scene: str) -> str:
    """视频关键帧：上方是画面，下方预留信息条（镜头号 / 时间码 / 本镜说明 / 进度）。

    信息条单独占位，不压在画面上——叠在底部会把 CTA 挡住，那种帧交给剪辑没法用。
    """
    band = max(60, int(h * 0.125))
    ch = h - band
    tmp = out_path + ".base.png"
    render_creative(tmp, w, ch, data)
    canvas = Image.new("RGB", (w, h), (9, 11, 16))
    canvas.paste(Image.open(tmp).convert("RGB"), (0, 0))
    try:
        os.remove(tmp)
    except Exception:
        pass
    d = ImageDraw.Draw(canvas)

    pad = int(w * 0.04)
    f1 = _font(max(10, int(band * 0.26)), scene, True)
    d.text((pad, ch + band * 0.14), f"{idx:02d}/{total:02d}  {scene}", font=f1, fill=(255, 255, 255))
    ft = _font(max(10, int(band * 0.24)), timecode, True)
    d.text((w - pad - d.textlength(timecode, font=ft), ch + band * 0.15), timecode,
           font=ft, fill=(255, 176, 32))

    cap = data.get("caption") or ""
    if cap:
        cf = _font(max(9, int(band * 0.21)), cap, False)
        lines = wrap_text(d, cap, cf, w - pad * 2, 2)
        y = ch + band * 0.50
        for ln in lines:
            d.text((pad, y), ln, font=cf, fill=(176, 189, 205))
            y += int(cf.size * 1.34)

    bar_y = h - max(4, int(h * 0.005))
    d.rectangle([0, bar_y - 4, w, bar_y], fill=(255, 255, 255, 40))
    d.rectangle([0, bar_y - 4, int(w * idx / max(1, total)), bar_y], fill=(255, 176, 32))

    canvas.save(out_path, "PNG", optimize=True)
    return out_path
