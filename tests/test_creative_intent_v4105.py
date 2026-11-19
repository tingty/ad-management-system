"""V4.105 / 方案C：结构化创作意图（分析前确认创作要求 + 路线卡就地编辑）回归。

- parse_text：一句话按规则拆成 audience / core_value / avoid 等字段（不调用模型）；
- merge / conflicts / classify_change：变更摘要、冲突提示、视觉项与概念项的区分；
- prompt_block：意图与禁止项进入 analyze / routes / 文案 / 图片 / 视频提示词；
- 接口与前端接线：/cw/intent/parse、路线 PATCH、补充框与分析请求都带意图。
无模型 / 无网络。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

import creative_intent as ci  # noqa: E402


class TestCreativeIntentV4105(unittest.TestCase):

    def test_01_parse_acceptance_example(self):
        """文档验收原句：受众 / 禁止项 / 核心价值 三个字段都要落到。"""
        r = ci.parse_text("面向首次装修业主，不做全息，重点看清家具布局")
        self.assertEqual(r["patch"]["audience"], ["首次装修业主"])
        self.assertEqual(r["patch"]["avoid"], ["全息"])
        self.assertEqual(r["patch"]["core_value"], "看清家具布局")
        self.assertEqual(r["notes"], [])

    def test_02_avoid_strips_leading_verb(self):
        self.assertEqual(ci.parse_text("不要做成全息风格")["patch"]["avoid"], ["全息风格"])
        self.assertEqual(ci.parse_text("不要出现虚构的界面截图")["patch"]["avoid"], ["虚构的界面截图"])

    def test_03_goal_not_misread_as_audience(self):
        p = ci.parse_text("目标是提高预约量")["patch"]
        self.assertEqual(p.get("goal"), "提高预约量")
        self.assertNotIn("audience", p)
        p2 = ci.parse_text("目标人群是25-35岁租房白领")["patch"]
        self.assertEqual(p2.get("audience"), ["25-35岁租房白领"])

    def test_04_unmatched_text_is_kept_not_dropped(self):
        r = ci.parse_text("做一个温馨的家居广告")
        self.assertEqual(r["patch"].get("core_value"), "做一个温馨的家居广告")
        self.assertTrue(any("未识别出明确字段" in n for n in r["notes"]))
        r2 = ci.parse_text("风格温暖真实，另外要有电视购物那种热闹感")
        self.assertTrue(r2["notes"], "未归类片段必须写进 notes，不能静默丢弃")

    def test_05_merge_reports_changes(self):
        base = {"audience": ["首次装修业主"], "style": "温暖"}
        m = ci.merge(base, {"avoid": ["全息"], "style": "冷峻"})
        self.assertEqual(m["intent"]["avoid"], ["全息"])
        self.assertEqual(m["intent"]["style"], "冷峻")
        self.assertEqual(len(m["changes"]), 2)
        # 重复项不重复追加
        m2 = ci.merge(m["intent"], {"avoid": ["全息"]})
        self.assertEqual(m2["changes"], [])
        self.assertEqual(m2["intent"]["avoid"], ["全息"])

    def test_06_conflicts_avoid_wins(self):
        cs = ci.conflicts({"avoid": ["全息"], "core_value": "全息投影体验"})
        self.assertEqual(len(cs), 1)
        self.assertIn("禁止项为准", cs[0])
        self.assertEqual(ci.conflicts({"avoid": ["全息"], "style": "温暖"}), [])

    def test_07_classify_change_visual_vs_concept(self):
        self.assertEqual(ci.classify_change({"style": "a"}, {"style": "b"}), "visual")
        self.assertEqual(ci.classify_change({"style": "a", "scenario": "x"},
                                            {"style": "b", "scenario": "y"}), "visual")
        self.assertEqual(ci.classify_change({"style": "a"}, {"audience": ["x"]}), "concept")
        self.assertEqual(ci.classify_change({"avoid": []}, {"avoid": ["全息"]}), "concept")
        self.assertEqual(ci.classify_change({"style": "a"}, {"style": "a"}), "none")

    def test_08_prompt_block_empty_and_content(self):
        self.assertEqual(ci.prompt_block({}), "")
        self.assertEqual(ci.prompt_block({"raw_text": "随便说说"}), "")
        block = ci.prompt_block({"audience": ["首次装修业主"], "avoid": ["全息"],
                                 "core_value": "看清家具布局"})
        self.assertIn("目标受众：首次装修业主", block)
        self.assertIn("禁止项（硬约束）", block)
        self.assertIn("以禁止项为准", block)

    def test_09_from_analysis_reads_nested(self):
        a = {"analysis": {"creative_intent": {"style": "温暖"}}}
        self.assertEqual(ci.from_analysis(a)["style"], "温暖")
        self.assertEqual(ci.from_analysis({"creative_intent": {"avoid": ["全息"]}})["avoid"], ["全息"])
        self.assertTrue(ci.is_empty(ci.from_analysis({})))

    def test_10_schema_and_routes_wired(self):
        import schemas
        self.assertIn("creative_intent", schemas.CWAnalyzeRequest.model_fields)
        self.assertIn("intent_text", schemas.CWAnalyzeRequest.model_fields)
        self.assertIn("intent", schemas.CWAnalysisResult.model_fields)
        self.assertEqual(schemas.CWAnalysisResult.model_fields["intent_change"].default, "none")
        self.assertIn("creative_intent", schemas.CWRoutesRequest.model_fields)
        self.assertIn("intent", schemas.CWRoutesResult.model_fields)
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        for token in ('"/cw/intent/parse"', '"/cw/routes/{plan_id}/{key}"',
                      "cw_intent.prompt_block", "creative_intent_block"):
            self.assertIn(token, src, f"routers.py 缺少 {token}")
        # 分析结果必须把意图写进统一分析，供三类生成链路读取
        self.assertIn('result["analysis"]["creative_intent"] = intent', src)

    def test_11_generation_prompts_carry_intent(self):
        import media_ad
        analysis = {"industry": "home", "audience": "owners",
                    "creative_intent": {"audience": ["首次装修业主"], "avoid": ["全息"]}}
        ctx = media_ad._analysis_context(analysis, "Meta", "zh", None)
        self.assertIn("创作意图", ctx)
        self.assertIn("全息", ctx)
        prompt = media_ad._media_image_prompt(analysis, "Meta", {}, None, None, overlay_mode="pure")
        self.assertIn("创作意图", prompt)
        self.assertIn("全息", prompt)

    def test_12_frontend_wiring(self):
        api_src = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        for token in ("cwIntentParse", "patchCwRoute", "CreativeIntent", "/api/cw/intent/parse",
                      "/api/cw/routes/${planId}/${key}"):
            self.assertIn(token, api_src, f"api.ts 缺少 {token}")
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        for token in ("intent_text: intentText.trim()", "creative_intent:", "改一句",
                      "确认创作要求", "api.patchCwRoute"):
            self.assertIn(token, page, f"CreativeWorkbench.tsx 缺少 {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
