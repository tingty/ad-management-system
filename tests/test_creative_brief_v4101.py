"""V4.101 / P0：共享创意框架 brief 契约。

验证：九类高转化框架注册、用户原始输入补全为结构化 brief、预览文案可读、
未确认 brief 绝不进入任何生成提示词、证据/零文字警示不丢失。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from creative_brief import (  # noqa: E402
    FRAMEWORKS, FRAMEWORK_BY_KEY, DEFAULT_FRAMEWORK, LAYER_ORDER,
    framework_of, framework_options, normalize_brief, render_brief_for_review,
    build_copy_brief_block, build_image_brief_block, build_video_brief_block,
)


class TestCreativeFrameworkRegistry(unittest.TestCase):
    def test_01_nine_frameworks_registered(self):
        self.assertEqual(len(FRAMEWORKS), 9)
        keys = {f["key"] for f in FRAMEWORKS}
        self.assertEqual(keys, {"aida", "pas", "bab", "hso", "4p", "contrast_proof",
                                "scene", "social_proof", "scarcity"})
        for f in FRAMEWORKS:
            self.assertTrue(f["label"])
            self.assertTrue(f["beats"])
            self.assertTrue(f["visual_hook"])
            self.assertTrue(set(f["layers"]) <= set(LAYER_ORDER))

    def test_02_evidence_dependent_frameworks_marked(self):
        dependent = {f["key"] for f in FRAMEWORKS if f["requires_evidence"]}
        self.assertEqual(dependent, {"hso", "4p", "contrast_proof", "social_proof", "scarcity"})

    def test_03_unknown_framework_falls_back(self):
        self.assertEqual(framework_of("not-exist")["key"], DEFAULT_FRAMEWORK)
        opts = framework_options()
        self.assertEqual(len(opts), 9)
        self.assertTrue(all("beats" in o for o in opts))


class TestBriefNormalization(unittest.TestCase):
    def test_04_raw_string_is_completed(self):
        b = normalize_brief("突出续航，让用户放心出门", {"product": "Air Pro", "audience": "通勤人群"})
        self.assertEqual(b["framework"], DEFAULT_FRAMEWORK)
        self.assertEqual(b["product"], "Air Pro")
        self.assertEqual(b["audience"], "通勤人群")
        self.assertTrue(b["hook"])
        self.assertTrue(b["pain"])
        self.assertTrue(b["proof"])
        self.assertTrue(b["cta"])
        self.assertTrue(b["beat"])
        self.assertFalse(b["confirmed"])
        self.assertEqual(len(b["brief_hash"]), 12)

    def test_05_dict_override_and_layers(self):
        b = normalize_brief({
            "framework": "pas", "hook": "别再半路没电", "cta": "立即体验",
            "layers": ["pain", "cta"], "confirmed": True,
        }, {"product": "Air Pro"})
        self.assertEqual(b["framework"], "pas")
        self.assertEqual(b["hook"], "别再半路没电")
        self.assertEqual(b["cta"], "立即体验")
        self.assertEqual(b["layers"], ["pain", "cta"])
        self.assertTrue(b["confirmed"])

    def test_06_hash_stable_and_preview_readable(self):
        a = normalize_brief("强调真实续航", {"product": "Air Pro"})
        b = normalize_brief("强调真实续航", {"product": "Air Pro"})
        self.assertEqual(a["brief_hash"], b["brief_hash"])
        text = render_brief_for_review(a)
        self.assertIn("完善后的创意 brief", text)
        self.assertIn("可信证据", text)
        self.assertIn("未确认", text)

    def test_07_risk_warnings_are_kept(self):
        b = normalize_brief("限时 50% off，评分第一，\"立即购买\"", {"product": "Air Pro"},
                            framework="scarcity")
        self.assertTrue(any("数字" in w for w in b["warnings"]))
        self.assertTrue(any("引号" in w for w in b["warnings"]))
        self.assertTrue(any("证据" in w for w in b["warnings"]))
        self.assertNotIn("50% off", build_copy_brief_block(b) + build_image_brief_block(b) + build_video_brief_block(b))


class TestBriefGating(unittest.TestCase):
    def test_08_unconfirmed_brief_never_enters_prompt(self):
        raw = normalize_brief("突出续航", {"product": "Air Pro"})
        self.assertEqual(build_copy_brief_block(raw), "")
        self.assertEqual(build_image_brief_block(raw, "Meta"), "")
        self.assertEqual(build_video_brief_block(raw, "TikTok"), "")

    def test_09_confirmed_brief_enters_all_three_prompts(self):
        b = normalize_brief("突出续航，结尾引导了解", {"product": "Air Pro", "audience": "通勤人群"},
                            confirmed=True)
        copy_block = build_copy_brief_block(b, "Meta")
        image_block = build_image_brief_block(b, "Meta")
        video_block = build_video_brief_block(b, "TikTok")
        for block in (copy_block, image_block, video_block):
            self.assertIn(b["brief_hash"], block)
            self.assertIn("非事实依据", block)
        self.assertIn("CTA 措辞", copy_block)
        self.assertIn("画面仍保持零文字", image_block)
        self.assertIn("画面文字仍由三道防线管理", video_block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
