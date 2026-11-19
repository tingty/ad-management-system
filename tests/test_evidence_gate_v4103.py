"""V4.103 / 方案A：证据链入统一分析 + 生成前证据硬门回归。

C02：真实抓取的证据包必须写入 analysis（evidence_index / snapshot_id / gate），
     使 D0 证据门、prompt_contract、claim_contract 拿到可定位原文。
A 决策：真实抓取分析无可用证据时，文案 / 图片 / 视频 / 通用任务入口在调用模型、
     入队前硬阻断（needs_input），不产生费用。
无模型 / 无网络：纯函数 + 静态源码断言 + 临时分析对象。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
sys.path.insert(0, str(BACKEND))

from claims import generation_evidence_gate, EvidenceSnapshot  # noqa: E402


class TestEvidenceGateV4103(unittest.TestCase):

    def test_01_real_fetch_with_evidence_index_allowed(self):
        """真实抓取带可定位证据 → 放行。"""
        a = {
            "snapshot": {"source": "real_fetch"},
            "evidence_index": [{"evidence_id": "E001", "quote": "续航 20 小时",
                                "char_start": 0, "char_end": 6}],
            "evidence_snapshot_id": "evs_abc",
            "evidence_gate": "ok",
        }
        gate = generation_evidence_gate(a)
        self.assertTrue(gate["allowed"], gate)
        self.assertEqual(gate["status"], "ok")
        self.assertEqual(gate["count"], 1)
        self.assertTrue(EvidenceSnapshot.from_analysis(a).available)

    def test_02_real_fetch_without_evidence_blocked(self):
        """真实抓取但无证据 → needs_input 硬阻断。"""
        a = {
            "snapshot": {"source": "real_fetch"},
            "evidence_gate": "needs_input",
            "evidence_snapshot_id": "",
            "evidence_index": [],
        }
        gate = generation_evidence_gate(a)
        self.assertFalse(gate["allowed"], gate)
        self.assertEqual(gate["status"], "needs_input")
        self.assertIn("[E###]", gate["reason"])

    def test_03_empty_snapshot_id_but_blocked_gate(self):
        """门显式判 needs_input（即便无 snapshot_id）也硬拦。"""
        gate = generation_evidence_gate({"evidence_gate": "needs_input",
                                         "evidence_index": []})
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["status"], "needs_input")

    def test_04_demo_analysis_passthrough(self):
        """演示样例放行（source=demo，Pydantic 解析后 snapshot 可能丢失）。"""
        self.assertTrue(generation_evidence_gate({"snapshot": {"source": "demo"}})["allowed"])
        self.assertTrue(generation_evidence_gate({"source": "demo"})["allowed"])

    def test_05_pasted_analysis_passthrough(self):
        """手工粘贴文本放行（无真实抓取证据来源）。"""
        self.assertTrue(generation_evidence_gate({"snapshot": {"source": "pasted"}})["allowed"])

    def test_06_plain_simplified_analysis_passthrough(self):
        """测试 / 历史缓存里的简化 analysis（无来源标记）放行，维持向后兼容。

        关键：LandingAnalysis.evidence_gate 默认 'ok'，单凭它不得判定真实抓取。
        """
        gate = generation_evidence_gate({"product": "Air Pro", "evidence_gate": "ok",
                                         "evidence_index": []})
        self.assertTrue(gate["allowed"], gate)
        self.assertEqual(gate["status"], "passthrough")

    def test_07_enforce_helper_wired_into_four_entries(self):
        """四个生成入口都在调用模型 / 入队前接入统一证据门。"""
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn("from claims import generation_evidence_gate", src)
        # 助手定义
        self.assertIn("def _enforce_evidence_gate", src)
        # 文案入口
        copy_seg = src.split("@router.post(\"/media-campaign/copy\")", 1)[1].split("@router.get(\"/creative-frameworks\")", 1)[0]
        self.assertIn("_enforce_evidence_gate", copy_seg)
        # 图片同步入口
        img_seg = src.split("@router.post(\"/media-campaign/images\")", 1)[1].split("# ===========================================================================", 1)[0]
        self.assertIn("_enforce_evidence_gate", img_seg)
        # 通用任务入口（实际出图）
        job_seg = src.split("@router.post(\"/generation-jobs\", status_code=202)", 1)[1].split("@router.get(\"/generation-jobs\")", 1)[0]
        self.assertIn("_enforce_evidence_gate", job_seg)
        # 视频入队入口
        vid_seg = src.split("@router.post(\"/cw-video/generate-jobs\"", 1)[1].split("@router.get(\"/cw-video/generate-jobs/{job_id}\"", 1)[0]
        self.assertIn("_enforce_evidence_gate", vid_seg)

    def test_08_build_cw_result_writes_evidence_fields(self):
        """_build_cw_result 在有证据包时写入全部证据字段。"""
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn("evidence_pack=None", src)
        seg = src.split("if evidence_pack:", 1)[1].split("result = {", 1)[0]
        for field in ("evidence_index", "evidence_snapshot_id", "evidence_gate",
                      "evidence_chain", "evidence_review_status"):
            self.assertIn('"%s"' % field, seg, "analysis 须写入 %s" % field)
        # 真实抓取分支须把 pack 传入
        self.assertIn("user=user, platforms=platforms, evidence_pack=pack", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
