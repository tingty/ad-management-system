"""V4.97：参考图仅用于「学习」风格/配色，不再直接合成进素材图片。

无模型 / 无网络：验证风格学习模块能提取配色与主色、fail-open、不改入参文件；
图片链路彻底移除 local_composite 贴图与供应商 reference_image 传参；
前端文案明确「仅学习、生成新画面」。视频侧图生视频参考图不受影响。
"""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from reference_image import analyze_reference_style, render_reference_style_block  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

ROOT = BACKEND.parent
MEDIA_AD = BACKEND / "media_ad.py"
TSX = ROOT / "frontend" / "src" / "pages" / "CreativeWorkbench.tsx"
VIDEO_CLAIMS = BACKEND / "video_claims.py"


def _make_ref_image(path: str, light: bool = True):
    """浅图：大面积浅黄 + 深色块；暗图：整体深蓝 + 略亮的暗蓝（无大面积亮色）。"""
    from PIL import Image
    if light:
        im = Image.new("RGB", (140, 140), (240, 220, 40))
        for x in range(140):
            for y in range(70, 140):
                im.putpixel((x, y), (20, 30, 55))
    else:
        im = Image.new("RGB", (140, 140), (12, 16, 32))
        for x in range(140):
            for y in range(70, 140):
                im.putpixel((x, y), (28, 58, 118))
    im.save(path)


class TestReferenceStyleV497(unittest.TestCase):

    def test_01_missing_path_fail_open(self):
        r = analyze_reference_style(None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["palette_override"], {})
        self.assertEqual(r["style_prompt"], "")
        self.assertEqual(render_reference_style_block(r), "")

    def test_02_nonexistent_file_fail_open(self):
        r = analyze_reference_style("/no/such/ref/image.png")
        self.assertFalse(r["ok"])
        self.assertEqual(r["palette_override"], {})

    def test_03_extracts_palette_and_traits(self):
        fd, p = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _make_ref_image(p)
            with open(p, "rb") as fh:
                before = hashlib.md5(fh.read()).hexdigest()
            r = analyze_reference_style(p)
            self.assertTrue(r["ok"], r["reason"])
            ov = r["palette_override"]
            for k in ("accent", "bg1", "bg2", "fg", "sub"):
                self.assertRegex(ov[k], r"^#[0-9A-F]{6}$")
            self.assertIn(ov["light"], (True, False))
            self.assertIn(r["traits"]["tone"], ("warm", "cool"))
            self.assertTrue(r["traits"]["colors"])
            # 不修改入参文件
            with open(p, "rb") as fh:
                self.assertEqual(hashlib.md5(fh.read()).hexdigest(), before)
        finally:
            os.remove(p)

    def test_04_style_prompt_is_learn_only(self):
        fd, p = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _make_ref_image(p, light=False)
            r = analyze_reference_style(p)
            block = render_reference_style_block(r)
            self.assertTrue(block.startswith("[ReferenceStyle / learn-only]"))
            low = block.lower()
            self.assertIn("do not copy", low)
            self.assertIn("new", low)  # 生成全新画面
            self.assertIn("do not reproduce", low)
        finally:
            os.remove(p)

    def test_05_dark_ref_flips_foreground(self):
        fd, p = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _make_ref_image(p, light=False)
            r = analyze_reference_style(p)
            self.assertFalse(r["palette_override"]["light"])
            self.assertEqual(r["palette_override"]["fg"], "#F5F5F5")
        finally:
            os.remove(p)

    def test_06_no_local_composite_in_image_pipeline(self):
        src = MEDIA_AD.read_text(encoding="utf-8")
        self.assertNotIn('reference_mode = "local_composite"', src)
        self.assertNotIn("provider_reference", src)
        self.assertNotIn("reference_image=product_path", src)
        # 渲染时不再把参考图作为 product_image_path 传入
        self.assertIn("None,  # V4.97：永不把参考图贴进成品", src)

    def test_07_style_block_injected_before_contract(self):
        src = MEDIA_AD.read_text(encoding="utf-8")
        self.assertIn("style_block: str = \"\"", src)
        self.assertIn("blocks.append(style_block.strip())", src)
        # 规则块 → 风格块 → 契约块，契约仍是最后兜底
        self.assertLess(src.index("blocks.append(rule_text)"),
                        src.index("blocks.append(style_block.strip())"))
        self.assertLess(src.index("blocks.append(style_block.strip())"),
                        src.index("blocks.append(render_image_contract_block(contract))"))

    def test_08_meta_records_no_original_composited(self):
        src = MEDIA_AD.read_text(encoding="utf-8")
        self.assertIn('"original_composited": False', src)
        self.assertIn('"reference_style"', src)

    def test_09_frontend_copy_says_learn_only(self):
        src = TSX.read_text(encoding="utf-8")
        self.assertIn("仅学习配色与画面质感", src)
        self.assertIn("不会出现在素材中", src)
        self.assertNotIn("注入出图链路参考真实外观", src)

    def test_10_video_image_to_video_untouched(self):
        # 视频侧图生视频参考图是合理用途，未因本次图片改动被禁用
        src = VIDEO_CLAIMS.read_text(encoding="utf-8")
        self.assertIn("image_to_video", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
