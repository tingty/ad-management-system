"""V4.101 / P4：三类素材共用的提示词补全确认交互与换一批入口（静态回归）。"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
sys.path.insert(0, str(BACKEND))

from creative_brief import normalize_brief, build_copy_brief_block  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"


class TestCreativeUiV4101(unittest.TestCase):
    def test_01_workbench_has_preview_confirm_gate(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        for token in ("previewCreativeBrief", "creativeBriefConfirmed", "确认使用",
                      "未确认 · 不会进入生成", "确认补全后的提示词", "FRAMEWORK_FALLBACK"):
            self.assertIn(token, src)
        self.assertIn("creativeBriefDraft && !creativeBriefConfirmed", src)

    def test_02_workbench_has_regenerate_entries(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("换一批路线", src)
        self.assertIn("function rerouteRoutes", src)
        self.assertIn("换一批文案", src)
        self.assertIn("function regenerateCopy", src)

    def test_03_three_kinds_receive_confirmed_brief(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("brief: confirmedBrief() || {}", src)  # 文案（V4.115：null 归一成 {}）
        self.assertIn("brief: confirmedBrief() || {},", src)  # 图片 creative_plan
        self.assertIn("creativeBrief={confirmedBrief()}", src)  # 视频

    def test_04_video_studio_has_hint_and_reroll(self):
        src = (FRONTEND / "pages" / "VideoStudio.tsx").read_text(encoding="utf-8")
        self.assertIn("补充出片提示词", src)
        self.assertIn("setOpt('prompt_hint', e.target.value)", src)
        self.assertIn("换一批分镜", src)
        self.assertIn("regenerate = false", src)
        self.assertIn("user_brief: creativeBrief?.confirmed ? creativeBrief : undefined", src)

    def test_05_api_contracts_extended(self):
        src = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("previewCreativeBrief", src)
        self.assertIn("creativeFrameworks", src)
        self.assertIn("framework?: string; user_brief?: CreativeBrief | null", src)

    def test_06_styles_exist(self):
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        for cls in (".cwb-brief-form", ".cwb-brief-preview", ".cwb-brief-ok",
                    ".cwb-route-framework", ".vs-opt-wide"):
            self.assertIn(cls, css)

    def test_07_copy_variation_is_rendered_in_prompt(self):
        b = normalize_brief("强调真实续航", {"product": "Air Pro"}, confirmed=True)
        b["variation"] = 2
        self.assertIn("换一批变体：第 2 版", build_copy_brief_block(b, "Meta"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
