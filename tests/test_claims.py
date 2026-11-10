"""N01 / A06 / A07：证据统一命名空间、无效引用拒绝、限定保护、生成后审计。"""
import unittest

import _bootstrap  # noqa: F401  必须在 backend 导入前执行
import re

from evidence import build_evidence_pack, evidence_contract
from claims import (EvidenceSnapshot, validate_evidence_refs, validate_evidence_chain,
                    check_claim_qualifiers, audit_copy_fields, claim_contract)
from services import _normalize_landing

SOURCE = (
    "Anker MagStand Nightstand Charger. " +
    "Battery degradation reduced by up to 20% in Battery Care mode under laboratory "
    "conditions. Results may vary by device. " +
    "Offer valid until 2025-01-01 is not used. " * 3 +
    "Free trial for 14 days, then billed annually. Cancel anytime. " +
    "Compatible with MagSafe cases; charger sold separately. " +
    "Dimensions 10 x 10 cm, 15W output. "
) * 6


def make_pack():
    return build_evidence_pack({"final_url": "https://shop.example.com/p",
                                "fetch_quality": "ok", "html": ""}, SOURCE)


class TestEvidenceNamespace(unittest.TestCase):
    def test_01_single_namespace(self):
        pack = make_pack()
        ids = pack["evidence_ids"]
        self.assertTrue(ids)
        self.assertTrue(all(re.fullmatch(r"E\d{3}", x) for x in ids))
        self.assertFalse(any(x.startswith("EV_") for x in ids))
        self.assertEqual(len(ids), len(pack["evidence"]))

    def test_02_every_entry_locatable(self):
        for row in make_pack()["evidence"]:
            self.assertTrue(row["quote"])
            self.assertTrue(row["referenceable"])
            self.assertEqual(row["review_status"], "locatable_not_reviewed")
            self.assertIsInstance(row["section_ids"], list)

    def test_03_section_index_not_referenceable(self):
        for row in make_pack()["sections_index"]:
            self.assertFalse(row["referenceable"])
            self.assertIn("sample_ids", row)

    def test_04_snapshot_id_stable(self):
        a, b = make_pack(), make_pack()
        self.assertEqual(a["evidence_snapshot_id"], b["evidence_snapshot_id"])
        self.assertTrue(a["evidence_snapshot_id"].startswith("evs_"))

    def test_05_contract_names_single_namespace(self):
        self.assertIn("唯一可引用", evidence_contract(make_pack()))


class TestClaimRefs(unittest.TestCase):
    def setUp(self):
        self.pack = make_pack()
        self.snap = EvidenceSnapshot(self.pack["evidence"],
                                     snapshot_id=self.pack["evidence_snapshot_id"])

    def test_06_valid_refs(self):
        eid = self.pack["evidence_ids"][0]
        self.assertTrue(validate_evidence_refs([eid], self.snap)["ok"])

    def test_07_invalid_id_rejected(self):
        r = validate_evidence_refs(["E999"], self.snap)
        self.assertFalse(r["ok"])
        self.assertEqual(r["invalid_ids"], ["E999"])

    def test_08_legacy_section_id_rejected(self):
        self.assertFalse(validate_evidence_refs(["EV_S001"], self.snap)["ok"])

    def test_09_empty_snapshot_is_legacy(self):
        empty = EvidenceSnapshot([])
        self.assertFalse(empty.available)
        self.assertEqual(audit_copy_fields({"headline": "x"}, {})["status"],
                         "legacy_unverified")

    def test_10_chain_marks_rejected(self):
        chain = [{"claim": "电池老化降低 20%", "evidence_ids": ["E999"], "rejected": True}]
        r = validate_evidence_chain(chain, self.snap)
        self.assertEqual(r["invalid"], 1)
        self.assertEqual(r["status"], "needs_revision")

    def test_11_contract_lists_only_valid_ids(self):
        text = claim_contract(self.snap)
        self.assertIn(self.snap.snapshot_id, text)
        self.assertIn("EV_S###", text)     # 明确禁止引用旧分区编号

    def test_12_normalize_drops_invalid_ids(self):
        eid = self.pack["evidence_ids"][0]
        raw = {"industry": "retail", "evidence_ids": [eid, "E999"],
               "evidence_chain": [{"claim": "c1", "evidence_ids": [eid, "E999"]},
                                  {"claim": "c2", "evidence_ids": [eid]}]}
        out = _normalize_landing(raw, "https://shop.example.com/p", self.pack)
        self.assertIn("E999", out["evidence_invalid_ids"])
        self.assertEqual(out["evidence_chain"][0]["evidence_ids"], [eid])
        self.assertFalse(out["evidence_chain"][1]["rejected"])
        self.assertEqual(out["evidence_ref_audit"]["status"], "ok")


class TestQualifierProtection(unittest.TestCase):
    SRC = ("Battery degradation reduced by up to 20% in Battery Care mode under "
           "laboratory conditions. Results may vary.")

    def test_13_short_claim_losing_qualifier_blocked(self):
        r = check_claim_qualifiers(self.SRC, "电池老化降低20%")
        self.assertTrue(r["checked"])
        self.assertFalse(r["ok"])
        self.assertIn("upper_bound", r["missing"])

    def test_14_qualified_claim_passes(self):
        r = check_claim_qualifiers(self.SRC, "在护理模式下电池老化最多降低20%，实验室条件，结果可能不同")
        self.assertTrue(r["ok"], r)

    def test_15_english_claim_passes(self):
        r = check_claim_qualifiers(self.SRC,
                                   "Battery degradation reduced by up to 20% in care mode, results may vary")
        self.assertTrue(r["ok"], r)

    def test_16_no_number_no_check(self):
        self.assertFalse(check_claim_qualifiers(self.SRC, "简洁设计，安心使用")["checked"])

    def test_17_audit_reports_violation(self):
        pack = make_pack()
        analysis = {"evidence_index": pack["evidence"],
                    "evidence_snapshot_id": pack["evidence_snapshot_id"],
                    "evidence_chain": []}
        audit = audit_copy_fields({"headline": "电池老化降低20%"}, analysis)
        self.assertEqual(audit["status"], "needs_revision")
        self.assertEqual(audit["violations"][0]["type"], "missing_qualifier")

    def test_18_audit_passes_with_qualifiers(self):
        pack = make_pack()
        analysis = {"evidence_index": pack["evidence"],
                    "evidence_snapshot_id": pack["evidence_snapshot_id"],
                    "evidence_chain": []}
        audit = audit_copy_fields({"headline": "在护理模式下最多降低20%，实验室条件，结果可能不同"},
                                  analysis)
        self.assertEqual(audit["status"], "ok", audit)


if __name__ == "__main__":
    unittest.main()
