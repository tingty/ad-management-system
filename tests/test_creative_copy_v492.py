"""V4.92 回归：创意文案作为一等素材类型 + 按平台规格生成。

覆盖：
1. 后端 generate_media_copy 按平台返回差异化 schema（Meta / Google RSA / Unity 等），
   且每个 schema 字段带字数上限 max，输出经 _validate / audit_copy_fields 证据门；
2. 前端源码契约：素材类型多选下拉、独立文案工作区、一键复制、平台规格徽标与逐字段字数展示；
3. 任务模块识别 copy 类型；cwTask 组合类型包含 copy / mixed；
4. 不发起任何真实模型调用。
"""
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"

from media_ad import copy_schema_for, generate_media_copy  # noqa: E402


class TestBackendCopyByPlatform(unittest.TestCase):
    def test_01_schema_differs_by_platform(self):
        """不同媒体平台返回不同的文案字段结构（符合各平台规格）。"""
        meta = [(s["key"], s.get("max")) for s in copy_schema_for("Meta", "")]
        google = [(s["key"], s.get("max")) for s in copy_schema_for("Google", "RSA")]
        unity = [(s["key"], s.get("max")) for s in copy_schema_for("Unity", "")]
        meta_keys = {k for k, _ in meta}
        google_keys = {k for k, _ in google}
        unity_keys = {k for k, _ in unity}
        self.assertIn("primary_text", meta_keys)
        self.assertIn("headline", meta_keys)
        self.assertIn("headline", google_keys)
        self.assertIn("description", google_keys)
        self.assertNotIn("primary_text", google_keys)  # Google RSA 无 Meta 的 primary_text
        self.assertIn("body", unity_keys)
        # 每个字段都必须有字数上限，供平台规格校验
        for _, mx in meta + google + unity:
            self.assertIsInstance(mx, int)
            self.assertGreater(mx, 0)

    def test_02_generate_media_copy_is_async_and_uses_copy_schema(self):
        """文案生成入口为 async，且源码中接入 schema / 字数校验 / 证据门。"""
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(generate_media_copy))
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        self.assertIn("copy_schema_for", src)
        self.assertIn("audit_copy_fields", src)
        self.assertIn("char_table", src)
        self.assertIn("_validate(", src)


class TestFrontendContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cw = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        cls.css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        cls.drawer = (FRONTEND / "CreativeTasksDrawer.tsx").read_text(encoding="utf-8")
        cls.cwtask = (FRONTEND / "cwTask.ts").read_text(encoding="utf-8")

    def test_03_material_type_is_multiselect(self):
        """素材类型改为多选下拉，选项含文案/图片/视频。"""
        self.assertIn("materialTypes", self.cw)
        self.assertIn("toggleMaterial", self.cw)
        self.assertIn("cwb-mt-trigger", self.cw)
        self.assertIn("cwb-mt-menu", self.cw)
        self.assertIn("aria-multiselectable=\"true\"", self.cw)
        self.assertIn("copy: '文案'", self.cw)
        self.assertIn("image: '图片'", self.cw)
        self.assertIn("video: '视频'", self.cw)

    def test_04_copy_workspace_and_clipboard(self):
        """独立文案工作区 + 一键复制（含剪贴板与回退）。"""
        self.assertIn("创意文案工作区", self.cw)
        self.assertIn("cwb-copy-workspace", self.cw)
        self.assertIn("navigator.clipboard.writeText", self.cw)
        self.assertIn("document.execCommand('copy')", self.cw)
        self.assertIn("function copyAllCopy", self.cw)
        self.assertIn("function copyCopyPlatform", self.cw)
        self.assertIn("function generateCopy", self.cw)

    def test_05_platform_spec_visible(self):
        """文案工作区展示平台规格合规徽标、ad_product 细分与逐字段字数。"""
        self.assertIn("cwb-copy-spec-badge", self.cw)
        self.assertIn("cwb-copy-spec-tag", self.cw)
        self.assertIn("char_table", self.cw)
        self.assertIn("符合平台文案规则", self.cw)
        self.assertIn(".cwb-copy-v.over", self.css)

    def test_06_copy_generation_decoupled_and_reused(self):
        """文案生成解耦为 buildCopies，且纯图片模式不再跳过文案；图片复用预生成结果。"""
        self.assertIn("async function buildCopies", self.cw)
        self.assertIn("prebuilt", self.cw)
        # 旧逻辑 "overlayMode === 'pure' 时 continue 跳过文案" 应已移除
        self.assertNotIn("if (overlayMode === 'pure') { variantsByPlat[p] = []; continue }", self.cw)

    def test_07_task_module_recognizes_copy(self):
        """任务抽屉与常驻任务类型识别文案。"""
        self.assertIn("copy: '文案'", self.drawer)
        self.assertIn("'copy' | 'both' | 'mixed'", self.cwtask)

    def test_08_media_copy_api_exists(self):
        """前端具备按平台调用文案生成大模型的能力（api.mediaCopy）。"""
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("mediaCopy:", api)
        self.assertIn("/api/media-campaign/copy", api)


if __name__ == "__main__":
    unittest.main(verbosity=2)
