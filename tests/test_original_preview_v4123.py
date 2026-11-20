# -*- coding: utf-8 -*-
"""V4.123 原图预览专项测试。

覆盖：
1. 素材库卡片与已沉淀模板 golden 卡片均有「查看原图」入口，且共用同一预览弹层；
2. 归并 Tab 主动加载素材列表，直接进入时也能拿到 golden 原图；
3. 原图 URL 优先使用 file（不是缩略图），/files/<name> 可真实访问到图片字节。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestOriginalPreviewFrontend(unittest.TestCase):
    def test_asset_card_and_template_card_have_preview_entry(self):
        s = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertIn("V4.123", s)
        self.assertIn("查看原图", s)
        self.assertIn("setPreviewAsset(a)", s, "素材库卡片应能打开原图预览")
        self.assertIn("setPreviewAsset(goldenAsset)", s, "已沉淀模板 golden 应能打开原图预览")
        self.assertIn("tl-preview-backdrop", s)
        self.assertIn("tl-preview-modal", s)
        self.assertIn("在新窗口打开原图", s)
        self.assertIn("api.fileUrl(a.file || a.thumb || '')", s, "原图应优先使用 file 而非 thumb")

    def test_merge_tab_loads_assets_for_golden_preview(self):
        s = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertIn("if (tab === 'merge') { loadAssets(); loadCandidates(); loadLibraryMeta() }", s,
                      "直接进入归并 Tab 也要加载素材列表，否则模板卡片拿不到 golden 原图")

    def test_preview_styles_exist(self):
        s = _read("frontend/src/styles.css")
        for cls in (".tl-preview-thumb", ".tl-preview-hint", ".tl-preview-backdrop",
                    ".tl-preview-modal", ".tl-preview-body", ".tl-preview-foot", ".tl-template-thumb"):
            self.assertIn(cls, s)


class TestOriginalFileServing(unittest.TestCase):
    NAME = "v4123_preview.png"
    PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 40)

    @classmethod
    def setUpClass(cls):
        cls.uploads = os.path.join(ROOT, "backend", "uploads")
        os.makedirs(cls.uploads, exist_ok=True)
        cls.path = os.path.join(cls.uploads, cls.NAME)
        with open(cls.path, "wb") as f:
            f.write(cls.PNG)

    @classmethod
    def tearDownClass(cls):
        if os.path.isfile(cls.path):
            os.remove(cls.path)

    def test_files_route_serves_original_bytes(self):
        from fastapi.testclient import TestClient
        from main import app

        r = TestClient(app).get(f"/files/{self.NAME}")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertTrue(r.content.startswith(b"\x89PNG"), "原图静态路由应返回真实图片字节")


if __name__ == "__main__":
    unittest.main()
