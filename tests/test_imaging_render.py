"""V4.65 成像渲染回归：验证「实景照片满铺 + 单一纯色对比字（无描边/无蒙版）+ 按钮不压字」。

仅用 Pillow 本地合成（不依赖文生图供应商 / 网络），用一张合成「照片感」底图渲染各版式，
断言（对齐样例素材风格：文字直接浮于照片、按钮为独立 pill 且不压字）：
1. 文字区无任何背景板（场景像素方差显著 > 阈值，证明背景完全透出、无遮罩）；
2. CTA 落在画布内，且与文字块包围盒不相交（按钮绝不压字 / 与文字交叉）；
3. 标题字号受控（<= 0.09 * min(w,h)，不再过大突兀）；
4. trace.render 字段完整（scrim=False / legibility={shadow:False,outline:False} / text_container / cta_box / composition.mode=full_bleed），供线上排障。
"""
import os
import random
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: F401  将 backend/ 加入 sys.path，隔离环境变量

from PIL import Image, ImageDraw

import imaging


def _make_photo_bg(path, w=1080, h=1080, seed=7):
    """生成一张有梯度与色块的「照片感」底图，确保文字区像素有可观方差。"""
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(0, w, 4):
            r = int(120 + 90 * (x / max(1, w)))
            g = int(180 * (y / max(1, h)))
            b = int(90 + 130 * (1 - y / max(1, h)))
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = (r, g, b)
    d = ImageDraw.Draw(img)
    for _ in range(24):
        x0, x1 = sorted([rng.randint(0, w), rng.randint(0, w)])
        y0, y1 = sorted([rng.randint(0, h), rng.randint(0, h)])
        d.ellipse([x0, y0, x1, y1], fill=(rng.randint(0, 255),
                                         rng.randint(0, 255), rng.randint(0, 255)))
    img.save(path)
    return path


def _region_variance(path, box):
    im = Image.open(path).convert("RGB")
    r = im.load()
    x0, y0, x1, y1 = box
    vals = [r[x, y][0] for y in range(y0 + 8, y1 - 8, 18)
            for x in range(x0 + 8, x1 - 8, 18)
            if x < im.width and y < im.height]
    return statistics.pvariance(vals) if len(vals) > 4 else 0.0


class ImagingRenderTest(unittest.TestCase):
    LAYOUTS = ["offer", "review", "hero", "demo", "detail"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bg = os.path.join(self.tmp, "bg.png")
        _make_photo_bg(self.bg)

    def _render(self, layout, w=1080, h=1080, headline="Tool-Free Dog Fence, No Digging",
                sub="Multiple sizes, adjustable fit", cta="Shop Dog Fences",
                brand="petorldog"):
        out = os.path.join(self.tmp, f"out_{layout}.png")
        trace = {}
        imaging.render_ad_png(out, w, h, headline, sub, cta, brand=brand,
                              bg_path=self.bg, layout=layout, trace=trace)
        self.assertTrue(os.path.isfile(out), f"{layout}: 未生成输出文件")
        return out, trace

    def test_no_opaque_panel_scene_shows_through(self):
        """核心修复①：文字区不再是实心面板，背景场景透出（方差显著 > 0）。"""
        for layout in self.LAYOUTS:
            out, trace = self._render(layout)
            box = trace["render"]["text_container"]
            var = _region_variance(out, box)
            self.assertGreater(var, 100.0,
                               f"{layout}: 文字区像素方差仅 {var:.1f}，疑似仍为实心面板（背景被遮挡）")

    def test_cta_inside_canvas_and_not_overlapping_text(self):
        """核心修复②：CTA 落在画布内，且与文字块包围盒不相交（按钮绝不压字 / 交叉）。"""
        for layout in self.LAYOUTS:
            out, trace = self._render(layout)
            cb = trace["render"]["cta_box"]
            self.assertIsNotNone(cb, f"{layout}: 缺少 cta_box")
            self.assertLessEqual(cb[2], 1080, f"{layout}: CTA 右越界")
            self.assertLessEqual(cb[3], 1080, f"{layout}: CTA 下越界")
            self.assertGreaterEqual(cb[0], 0, f"{layout}: CTA 左越界")
            self.assertGreaterEqual(cb[1], 0, f"{layout}: CTA 上越界")
            cont = trace["render"]["text_container"]
            overlap = not (cb[2] <= cont[0] + 8 or cont[2] <= cb[0] + 8
                           or cb[3] <= cont[1] + 8 or cont[3] <= cb[1] + 8)
            self.assertFalse(overlap, f"{layout}: CTA 与文字块相交（按钮压字）")

    def test_headline_font_capped(self):
        """核心修复③：标题字号受控，不再过大突兀。"""
        for layout in self.LAYOUTS:
            out, trace = self._render(layout)
            fs = trace["render"]["headline_font"]
            self.assertLessEqual(fs, int(1080 * 0.09),
                                 f"{layout}: 标题字号 {fs} 超过 0.09*min 阈值")
            self.assertGreater(fs, 10, f"{layout}: 标题字号过小 {fs}")

    def test_trace_render_fields_present(self):
        for layout in self.LAYOUTS:
            _, trace = self._render(layout)
            r = trace.get("render", {})
            for k in ("layout", "headline_font", "text_container", "scrim",
                      "legibility", "cta_box"):
                self.assertIn(k, r, f"{layout}: trace.render 缺字段 {k}")
            self.assertFalse(r["scrim"], f"{layout}: 仍存在背景板（scrim 应为 False）")
            self.assertEqual(r["legibility"], {"shadow": False, "outline": False},
                             f"{layout}: V4.65 起文字应为单一纯色对比字（无描边 / 无投影）")

    def test_long_headline_shrinks_without_overflow(self):
        """长标题触发自适应收缩，不抛 TextOverflowError（strict_text=False 默认）。"""
        long = "The Most Advanced Tool-Free Modular Adjustable Dog Fence System For Backyard"
        out, trace = self._render("offer", headline=long)
        self.assertTrue(os.path.isfile(out))
        self.assertLessEqual(trace["render"]["headline_font"], int(1080 * 0.09))

    def test_banner_still_renders(self):
        out = os.path.join(self.tmp, "out_banner.png")
        imaging.render_ad_png(out, 1200, 300, "Tool-Free Dog Fence",
                              "", "Shop", brand="petorldog", bg_path=self.bg,
                              layout="banner")
        self.assertTrue(os.path.isfile(out))

    def test_full_bleed_no_solid_margins(self):
        """V4.65：实景照片满铺整图，四角保持底图原色（无纯色填充边 / 无蒙版）。"""
        bg = Image.new("RGB", (1080, 1080))
        d = ImageDraw.Draw(bg)
        d.rectangle([0, 0, 540, 540], fill=(20, 120, 200))
        d.rectangle([540, 0, 1080, 540], fill=(220, 180, 30))
        d.rectangle([0, 540, 540, 1080], fill=(40, 160, 90))
        d.rectangle([540, 540, 1080, 1080], fill=(200, 60, 60))
        bgp = os.path.join(self.tmp, "corner_bg.png")
        bg.save(bgp)
        corners = [((0, 0, 12, 12), (20, 120, 200), "左上"),
                   ((1068, 0, 1080, 12), (220, 180, 30), "右上"),
                   ((0, 1068, 12, 1080), (40, 160, 90), "左下"),
                   ((1068, 1068, 1080, 1080), (200, 60, 60), "右下")]
        for mode in ("pure", "text", "text_button"):
            out = os.path.join(self.tmp, f"fb_{mode}.png")
            trace = {}
            imaging.render_ad_png(out, 1080, 1080, "Headline Here", "Sub text",
                                  "Shop", brand="brand", bg_path=bgp,
                                  layout="hero", trace=trace, overlay_mode=mode)
            self.assertEqual(trace["composition"]["mode"], "full_bleed",
                             f"{mode}: 未走 full_bleed 满铺")
            im = Image.open(out).convert("RGB")
            for box, target, name in corners:
                px = list(im.crop(box).getdata())
                avg = tuple(sum(ch) / len(px) for ch in zip(*px))
                self.assertTrue(all(abs(avg[i] - target[i]) < 40 for i in range(3)),
                                f"{mode}: {name}角非满铺原色（疑似纯色边/蒙版） avg={avg}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
