"""V4.88：文档提示词契约接入测试（无模型 / 无网络）。

验证：
- I/A/T 分类映射与现有 internal profile 对齐，不新增界面字段；
- 纯图片 / 视频提示词带 GLOBAL-VISUAL-1 无字满版契约，字幕字段不进视频出片提示词；
- 图片标准库 image_targets / image_target_for_size 与生成提示词共用一份规则；
- 叠加模式仍保留旧文案策略，只追加底线约束。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from image_capabilities import composition_goal  # noqa: E402
import media_spec_library as lib  # noqa: E402
from media_ad import _media_image_prompt  # noqa: E402
from prompt_contract import (  # noqa: E402
    build_prompt_contract, classify_audience, classify_creative_type,
    classify_industry, render_image_contract_block, render_video_contract_block,
)


ANALYSIS = {
    "industry_profile": "app_game",
    "industry": "移动应用",
    "audience": "成长与效率导向者",
    "facts": ["在真实任务中完成创作"],
    "evidence_chain": [{"evidence_ids": ["E001"], "claim": "真实任务"}],
    "brief": {"targetAudience": ["成长与效率导向者"], "promotionGoal": "转化"},
}


class TestPromptContractV488(unittest.TestCase):
    def test_01_taxonomy_mapping(self):
        self.assertEqual(classify_industry(ANALYSIS)["id"], "I07")
        self.assertEqual(classify_industry({"industry": "宠物围栏"})["id"], "I05")
        self.assertEqual(classify_audience(ANALYSIS)["id"], "A08")
        self.assertEqual(classify_creative_type(None, {"composition": "真实玩法演示"})["id"], "T02")

    def test_02_contract_snapshot(self):
        c = build_prompt_contract(
            media_type="image", analysis=ANALYSIS,
            brief={"subject": "创作类应用", "core_promise": "完成真实创作任务"},
            placement={"platform": "Meta", "target_size": "1080x1080",
                       "spec_version": "2026-11-17.1", "verification": "B"})
        self.assertTrue(c["prompt_id"].startswith("IMG-I07-A08-"))
        self.assertTrue(c["no_text_policy"])
        self.assertEqual(c["evidence_status"], "verified")
        self.assertEqual(c["constraints_ref"], "GLOBAL-VISUAL-1")
        self.assertEqual(c["product_facts"][0]["source_id"], "E001")

    def test_03_pure_image_prompt_has_no_negative_space(self):
        prompt = _media_image_prompt(
            ANALYSIS, "Meta", {}, {"subject": "创作类应用", "core_promise": "完成真实创作任务"},
            None, overlay_mode="pure",
            placement={"platform": "Meta", "target_size": "1080x1080", "spec_version": "v"})
        self.assertIn("PromptContract", prompt)
        self.assertIn("GLOBAL-VISUAL-1", prompt)
        self.assertNotIn("negative space", prompt.lower())
        self.assertNotIn("keep generous clean", prompt.lower())
        self.assertIn("覆盖规则", prompt)

    def test_04_overlay_image_prompt_keeps_legacy_text_behavior(self):
        prompt = _media_image_prompt(
            ANALYSIS, "Meta", {}, {"subject": "创作类应用"}, None,
            overlay_mode="text_button", placement={"platform": "Meta"})
        self.assertIn("叠加模式底线约束", prompt)
        self.assertIn("保留现有图内文案", prompt)

    def test_05_composition_goal_branches(self):
        pure = composition_goal(1080, 1920, "hero", overlay_mode="pure")
        legacy = composition_goal(1080, 1920, "hero", overlay_mode="text_button")
        self.assertIn("Full-bleed", pure)
        self.assertNotIn("negative space", pure.lower())
        self.assertIn("negative space", legacy.lower())

    def test_06_video_contract_excludes_subtitles_from_prompt(self):
        plan = {"duration_sec": 15, "voiceover": "narration", "shots": [
            {"t": "0-3s", "visual": "真实创作动作", "text": "上屏字幕", "vo": "看看实际流程"}]}
        c = build_prompt_contract(
            media_type="video", analysis=ANALYSIS, brief={"subject": "创作类应用"},
            plan=plan, placement={"platform": "TikTok", "target_aspect": "9:16",
                                  "duration": 15, "verification": "A"})
        block = render_video_contract_block(c)
        self.assertTrue(c["no_text_policy"])
        self.assertEqual(c["video"]["shots"][0]["audio"], "看看实际流程")
        self.assertIn("字幕 / CTA / 品牌 Logo 字段只用于内部节奏", block)
        self.assertIn("不绘制到画面", block)
        self.assertNotIn("上屏字幕", render_image_contract_block(
            build_prompt_contract(media_type="image", analysis=ANALYSIS, overlay_mode="pure")))

    def test_07_image_spec_library_shared_with_generation(self):
        targets = lib.image_targets("Meta")
        self.assertTrue(targets)
        hit = lib.image_target_for_size("Meta", "1080x1080")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["verification"], "B")
        self.assertIsNone(lib.image_target_for_size("Meta", "999x999"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
