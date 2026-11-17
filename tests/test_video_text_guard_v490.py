"""V4.90：视频文字 / 文案预检测试（无模型 / 无网络）。

验证：
- 截断、乱码、过长、重复标点等文本形态问题会被发现；
- 可确定的截断 / 重复 / 批准清单近似错误能被保守修正；
- text_effect 只放宽可读性，不绕过完整性与批准清单；
- 默认无字契约与 approved_only 例外都能编译进出片提示词；
- 修复使用深拷贝，不污染调用方的原始分镜。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from prompt_contract import build_prompt_contract, render_video_contract_block  # noqa: E402
from video_text_guard import (  # noqa: E402
    audit_video_text, render_video_text_guard_block, repair_video_text,
)


ANALYSIS = {
    "product": "创作类应用",
    "facts": ["在真实任务中完成创作"],
    "evidence_chain": [{"evidence_ids": ["E001"], "claim": "真实任务"}],
    "brief": {"promotionGoal": "转化", "sellingPoints": ["在真实任务中完成创作"]},
}


def _plan(**shot):
    base = {
        "hook": "认识创作类应用",
        "cta": "了解更多",
        "shots": [{"idx": 1, "t": "0-3s", "shot": "text_to_video",
                   "visual": "真实使用场景", "vo": "看看实际效果", **shot}],
    }
    return base


class TestVideoTextGuardV490(unittest.TestCase):
    def test_01_truncated_text_completed_from_approved_corpus(self):
        plan = _plan(text="真实任务...")
        repaired, report, done = repair_video_text(plan, ANALYSIS)
        self.assertGreaterEqual(done, 1)
        self.assertEqual(repaired["shots"][0]["text"], "在真实任务中完成创作")
        self.assertEqual(report["status"], "ok")

    def test_02_garbled_text_blocks_and_cannot_be_repaired(self):
        plan = _plan(text="ÃÂ\ufffd")
        repaired, report, done = repair_video_text(plan, ANALYSIS)
        self.assertEqual(done, 0)
        self.assertEqual(report["status"], "needs_revision")
        self.assertTrue(repaired["generation_blocked"])
        self.assertTrue(any(v["type"] == "garbled_text" for v in report["violations"]))

    def test_03_long_text_blocked_unless_effect_marked(self):
        long_text = "这是一段非常长的上屏文字用来测试超出安全区后无法清晰阅读的情况" * 2
        plain = audit_video_text(_plan(text=long_text), ANALYSIS)
        self.assertEqual(plain["status"], "needs_revision")
        self.assertTrue(any(v["type"] == "too_long" for v in plain["violations"]))

        effected = audit_video_text(_plan(text=long_text, text_effect="kinetic"), ANALYSIS)
        self.assertEqual(effected["status"], "ok")
        self.assertTrue(any(v["type"] == "long_text_effect" for v in effected["violations"]))

    def test_04_approved_only_rejects_unapproved_text(self):
        plan = _plan(text="马上下载")
        plan["text_policy"] = "approved_only"
        plan["approved_texts"] = ["立即体验"]
        report = audit_video_text(plan, ANALYSIS)
        self.assertEqual(report["status"], "needs_revision")
        self.assertTrue(any(v["type"] == "unapproved_text" for v in report["violations"]))

        plan["shots"][0]["text"] = "立即体验"
        self.assertEqual(audit_video_text(plan, ANALYSIS)["status"], "ok")

    def test_05_effect_does_not_bypass_completeness_or_allowlist(self):
        plan = _plan(text="立即体验...", text_effect="motion_graphics")
        plan["text_policy"] = "approved_only"
        plan["approved_texts"] = ["立即体验"]
        report = audit_video_text(plan, ANALYSIS)
        self.assertEqual(report["status"], "needs_revision")
        self.assertTrue(any(v["type"] == "truncated_text" for v in report["violations"]))

    def test_06_repeated_punctuation_is_repaired(self):
        plan = _plan(text="立即体验！！！")
        repaired, report, done = repair_video_text(plan, ANALYSIS)
        self.assertGreaterEqual(done, 1)
        self.assertEqual(repaired["shots"][0]["text"], "立即体验！")
        self.assertEqual(report["status"], "ok")

    def test_07_repair_uses_deep_copy_and_writes_report(self):
        original = _plan(text="真实任务...")
        repaired, report, _done = repair_video_text(original, ANALYSIS)
        self.assertEqual(original["shots"][0]["text"], "真实任务...")
        self.assertNotEqual(repaired["shots"][0]["text"], original["shots"][0]["text"])
        self.assertEqual(repaired["text_guard"]["status"], report["status"])

    def test_08_quoted_text_in_visual_is_checked(self):
        plan = _plan(visual='产品旁出现 "马上下载" 字样')
        plan["text_policy"] = "approved_only"
        plan["approved_texts"] = ["立即体验"]
        report = audit_video_text(plan, ANALYSIS)
        self.assertEqual(report["status"], "needs_revision")
        bad = [v for v in report["violations"] if v["type"] == "unapproved_text"]
        self.assertTrue(bad)
        self.assertEqual(bad[0]["kind"], "quoted")

    def test_09_render_block_default_and_approved_only(self):
        default_report = audit_video_text(_plan(), ANALYSIS)
        default_block = render_video_text_guard_block(default_report)
        self.assertIn("文字审查 · 无字", default_block)
        self.assertNotIn("批准清单", default_block)

        plan = _plan()
        plan["text_policy"] = "approved_only"
        plan["approved_texts"] = ["立即体验"]
        approved_block = render_video_text_guard_block(audit_video_text(plan, ANALYSIS))
        self.assertIn("文字审查 · 批准清单", approved_block)
        self.assertIn("立即体验", approved_block)
        self.assertIn("不得改写", approved_block)

    def test_10_prompt_contract_supports_controlled_text_exception(self):
        contract = build_prompt_contract(
            media_type="video", analysis=ANALYSIS, plan=_plan(),
            text_policy="approved_only", approved_texts=["立即体验"])
        self.assertEqual(contract["video_text_policy"], "approved_only")
        self.assertIn("立即体验", contract["approved_texts"])
        rendered = render_video_contract_block(contract)
        self.assertIn("文字例外", rendered)
        self.assertIn("批准文字", rendered)

        default_contract = build_prompt_contract(media_type="video", analysis=ANALYSIS, plan=_plan())
        self.assertEqual(default_contract["video_text_policy"], "none")
        self.assertIn("GLOBAL-VISUAL-1", render_video_contract_block(default_contract))


if __name__ == "__main__":
    unittest.main()
