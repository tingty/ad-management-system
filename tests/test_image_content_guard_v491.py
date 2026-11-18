"""V4.91 回归：纯色 / 无画面图片体检门。

覆盖：
1. 检测模块对纯色 / 渐变兜底 / 近纯色微噪判为 blank，对真实场景 / 白底产品 /
   纯色+大字判为 has_content（不误杀）；
2. 异常与空路径 fail-open（不因体检模块自身问题阻断出图）；
3. 端到端：无文生图模型时整批走本地渐变兜底，全部被拦截，images=0、
   status=failed、blank_rejected_count>0、reason 明确；
4. 端到端：文生图返回有内容底图时正常放行，ai_background=True，不被误杀。

只用 Pillow 本地合成，不发起任何真实付费模型调用。
"""
import asyncio
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: F401

from PIL import Image, ImageDraw

from image_content_guard import inspect_image_content
from imaging import _gradient


def _save(d: str, name: str, img: Image.Image) -> str:
    p = os.path.join(d, name + ".png")
    img.save(p)
    return p


def _scene(w=400, h=400) -> Image.Image:
    im = Image.new("RGB", (w, h), (200, 210, 220))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 180, 180], fill=(220, 60, 60))
    d.ellipse([200, 40, 380, 220], fill=(40, 120, 200))
    for i in range(0, h, 20):
        d.line([(0, i), (w, i + 10)], fill=((i * 3) % 255, 80, 120), width=2)
    return im


class TestImageContentGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._d = tempfile.mkdtemp(prefix="icg_test_")
        cls.solid = _save(cls._d, "solid", Image.new("RGB", (400, 400), (30, 60, 90)))
        cls.grad = _save(cls._d, "grad", _gradient(400, 400))
        cls.scene = _save(cls._d, "scene", _scene())
        prod = Image.new("RGB", (400, 400), (255, 255, 255))
        ImageDraw.Draw(prod).rounded_rectangle([100, 80, 300, 320], radius=20,
                                               fill=(30, 90, 180))
        cls.prod = _save(cls._d, "prod", prod)
        txt = Image.new("RGB", (400, 400), (20, 40, 80))
        dt = ImageDraw.Draw(txt)
        for i in range(6):
            dt.rectangle([40, 60 + i * 45, 360, 95 + i * 45], fill=(240, 240, 240))
        cls.txt = _save(cls._d, "txt", txt)

    def test_01_blank_images_rejected(self):
        """纯色 / 品牌渐变兜底必须判为 blank。"""
        for p in (self.solid, self.grad):
            with self.subTest(path=os.path.basename(p)):
                r = inspect_image_content(p)
                self.assertFalse(r["ok"])
                self.assertEqual(r["verdict"], "blank")
                self.assertTrue(r["reason"])
                self.assertIn("metrics", r)

    def test_02_near_solid_rejected(self):
        """近纯色微噪（±3）也应判为 blank——这类图同样没有画面。"""
        random.seed(0)
        im = Image.new("RGB", (400, 400))
        px = im.load()
        for y in range(400):
            for x in range(400):
                n = random.randint(-3, 3)
                px[x, y] = (30 + n, 60 + n, 90 + n)
        p = _save(self._d, "near", im)
        r = inspect_image_content(p)
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "blank")

    def test_03_real_content_not_rejected(self):
        """真实场景 / 白底产品 / 纯色+大字都应放行，不误杀。"""
        for p in (self.scene, self.prod, self.txt):
            with self.subTest(path=os.path.basename(p)):
                r = inspect_image_content(p)
                self.assertTrue(r["ok"])
                self.assertEqual(r["verdict"], "has_content")

    def test_04_fail_open_on_bad_input(self):
        """文件不存在 / 损坏时 fail-open，不因体检模块故障阻断出图。"""
        self.assertTrue(inspect_image_content(None)["ok"])
        self.assertTrue(inspect_image_content("/no/such/image.png")["ok"])
        bad = os.path.join(self._d, "bad.png")
        with open(bad, "wb") as f:
            f.write(b"not a png")
        self.assertTrue(inspect_image_content(bad)["ok"])


class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _FakeDB:
    def query(self, *a, **k):
        return _FakeQuery()


class _FakeCfg:
    id = None
    provider = "fake"
    model = "content-model"
    params = {}


class TestEndToEndGuard(unittest.TestCase):
    """端到端：验证体检门确实挂在 generate_media_images 的交付路径上。"""

    def setUp(self):
        import media_ad
        from providers import UPLOAD_DIR
        self.media_ad = media_ad
        self.UPLOAD_DIR = UPLOAD_DIR
        self._orig_get_image = media_ad.get_image
        self._orig_cfg = media_ad._active_config
        self.slots = [{"size": "1080x1080", "w": 1080, "h": 1080,
                       "placement": "feed", "ad_product": "app"}]
        self.analysis = {"product": "X", "advantages": ["真实卖点一"], "audience": "大众"}
        self.copy = {"brand": "B", "headline": "标题", "sub": "副", "cta": "了解"}

    def tearDown(self):
        self.media_ad.get_image = self._orig_get_image
        self.media_ad._active_config = self._orig_cfg

    def _run(self):
        return asyncio.run(self.media_ad.generate_media_images(
            _FakeDB(), self.analysis, "Meta", "zh", self.copy, {}, self.slots,
            overlay_mode="pure"))

    def test_05_no_model_gradient_fallback_is_rejected(self):
        """无文生图模型 → 本地渐变兜底 → 全部拦截，不作为合格素材交付。"""
        self.media_ad.get_image = lambda db: None
        self.media_ad._active_config = lambda db, usage: None
        r = self._run()
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["status"], "failed")
        self.assertGreater(r["image_model"].get("blank_rejected_count", 0), 0)
        self.assertTrue(r["skipped"])
        self.assertEqual(r["skipped"][0]["status"], "needs_attention")
        self.assertIn("纯色", r["skipped"][0]["reason"])

    def test_06_content_background_passes(self):
        """有内容底图（模拟真实文生图返回）正常放行，不被误杀。"""
        from PIL import Image as PILImage

        class _ContentImage:
            capability_key = "generic_image"

            async def generate(self, prompt, w, h, out, *a, **k):
                full = out if os.path.isabs(out) else os.path.join(self.UPLOAD_DIR, out)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                im = PILImage.new("RGB", (w, h), (210, 215, 220))
                d = ImageDraw.Draw(im)
                d.rectangle([int(w * .1), int(h * .1), int(w * .5), int(h * .6)],
                            fill=(220, 60, 60))
                d.ellipse([int(w * .5), int(h * .2), int(w * .9), int(h * .7)],
                          fill=(40, 120, 200))
                for y in range(0, h, max(1, h // 40)):
                    d.line([(0, y), (w, y + 3)], fill=((y * 2) % 255, 80, 120), width=2)
                im.save(full)
                return full

        provider = _ContentImage()
        provider.UPLOAD_DIR = self.UPLOAD_DIR
        self.media_ad.get_image = lambda db: provider
        self.media_ad._active_config = lambda db, usage: _FakeCfg() if usage == "image" else None
        r = self._run()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["image_model"].get("blank_rejected_count", 0), 0)
        self.assertTrue(r["images"][0]["ai_background"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
