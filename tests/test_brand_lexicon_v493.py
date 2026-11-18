"""V4.93：品牌 / 文案黄金词典与视频上屏文字收紧测试（无模型 / 无网络 / 无 db）。

验证：
- 词典只取已确认来源（brand / product / CTA），facts / 卖点整句不进词典；
- 被校验对象（plan.approved_texts）不能自我认证，错拼品牌名不会进词典；
- 品牌名大小写 / 近似错拼（Novax vs NovaX）被识别且自动修正；
- 词典外上屏文字在 approved_only 下阻断，不产生厂商费用；
- 截断补全仍可用 facts 语料（不破坏 V4.90 能力）；
- 黄金词典块编译进出片提示词，router 在规划与出片两处均接入。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from brand_lexicon import (build_lexicon, enforce_onscreen,  # noqa: E402
                           render_lexicon_block, LEXICON_VERSION)
from video_text_guard import repair_video_text  # noqa: E402

from _bootstrap import BACKEND  # noqa: E402


ANALYSIS = {
    "product": "NovaX 创作应用",
    "brand": "NovaX",
    "facts": ["在真实任务中完成创作", "无需设计基础"],
    "evidence_chain": [{"evidence_ids": ["E001"], "claim": "真实任务"}],
    "brief": {"promotionGoal": "转化", "cta": "立即下载",
              "sellingPoints": ["在真实任务中完成创作"]},
}


class TestBrandLexiconV493(unittest.TestCase):
    def test_01_lexicon_only_confirmed_sources(self):
        lex = build_lexicon(ANALYSIS)
        self.assertEqual(lex["brand"], "NovaX")
        self.assertEqual(lex["cta"], "立即下载")
        self.assertIn("NovaX", lex["entries"])
        self.assertIn("立即下载", lex["entries"])
        # 卖点 / facts 整句不得进词典
        self.assertNotIn("在真实任务中完成创作", lex["entries"])
        self.assertEqual(lex["version"], LEXICON_VERSION)

    def test_02_plan_cannot_self_certify_brand(self):
        plan = {"approved_texts": ["Novax", "FakeBrand"]}
        lex = build_lexicon(ANALYSIS, plan)
        self.assertNotIn("Novax", lex["entries"])
        self.assertNotIn("FakeBrand", lex["entries"])

    def test_03_case_miss_detected_as_typo(self):
        lex = build_lexicon(ANALYSIS)
        report = enforce_onscreen(["Novax"], lex)
        self.assertEqual(report["status"], "needs_revision")
        bad = report["violations"][0]
        self.assertEqual(bad["risk"], "case_miss")
        self.assertEqual(bad["near_lexicon"], "NovaX")

    def test_04_brand_typo_auto_repaired(self):
        plan = {"text_policy": "approved_only",
                "shots": [{"visual": "场景", "brand_text": "Novax"}]}
        lex = build_lexicon(ANALYSIS, plan)
        repaired, report, done = repair_video_text(plan, ANALYSIS, {}, lex)
        self.assertGreaterEqual(done, 1)
        self.assertEqual(repaired["shots"][0]["brand_text"], "NovaX")
        self.assertEqual(report["status"], "ok")
        self.assertFalse(repaired.get("generation_blocked"))

    def test_05_unapproved_onscreen_blocks(self):
        plan = {"text_policy": "approved_only",
                "shots": [{"visual": "场景", "brand_text": "完全未批准的文字"}]}
        lex = build_lexicon(ANALYSIS, plan)
        repaired, report, done = repair_video_text(plan, ANALYSIS, {}, lex)
        self.assertEqual(report["status"], "needs_revision")
        self.assertTrue(repaired.get("generation_blocked"))
        self.assertTrue(report["lexicon_enforced"])

    def test_06_truncation_still_repairs_from_corpus(self):
        plan = {"shots": [{"visual": "场景", "text": "在真实任务..."}]}
        lex = build_lexicon(ANALYSIS, plan)
        repaired, report, done = repair_video_text(plan, ANALYSIS, {}, lex)
        self.assertGreaterEqual(done, 1)
        self.assertIn("在真实任务", repaired["shots"][0]["text"])

    def test_07_lexicon_block_compiled_with_ban(self):
        lex = build_lexicon(ANALYSIS)
        block = render_lexicon_block(lex)
        self.assertIn("品牌黄金词典", block)
        self.assertIn("NovaX", block)
        self.assertIn("严禁", block)
        self.assertIn("不得猜测近似拼写", block)

    def test_08_routers_wired_in_plan_and_build(self):
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn("from brand_lexicon import build_lexicon", src)
        # 规划端点与出片构建都应创建词典并传入文字审查
        self.assertGreaterEqual(src.count("build_lexicon("), 2)  # 规划端点 + 出片构建各一处
        self.assertGreaterEqual(src.count("repair_video_text("), 2)
        self.assertIn("render_lexicon_block(lexicon)", src)
        self.assertIn('"brand_lexicon": lexicon', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
