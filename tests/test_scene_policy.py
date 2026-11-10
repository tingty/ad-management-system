"""N02 / A03 / A09：删除哈希动作池，场景由产品事实与声明式画像决定。"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from industry_profiles import (INDUSTRY_PROFILES, resolve_profile, list_profiles,
                               scene_policy, SCENE_POLICIES)
from creative_config import build_concept, build_visual_brief, brief_prompt_block

BACKEND = Path(_bootstrap.ROOT) / "backend"


class TestScenePolicy(unittest.TestCase):
    def test_01_all_profiles_have_policy(self):
        for key, p in INDUSTRY_PROFILES.items():
            self.assertIn("scene_policy", p, key)
            self.assertIn(p["scene_policy"]["entity_type"],
                          ("physical_good", "software", "service", "travel", "general"), key)

    def test_02_list_profiles_exposes_policy(self):
        self.assertTrue(all("scene_policy" in x for x in list_profiles()))

    def test_03_fallback_is_conservative(self):
        pol = scene_policy({})
        self.assertEqual(pol["entity_type"], "general")
        self.assertFalse(pol["requires_asset"])
        self.assertTrue(any("随机" in x for x in pol["forbidden_inferences"]))

    def test_04_declared_policies_differ_by_entity(self):
        kinds = {v["entity_type"] for v in SCENE_POLICIES.values()}
        self.assertGreaterEqual(len(kinds), 4)

    def test_05_source_has_no_action_pool(self):
        src = (BACKEND / "creative_config.py").read_text(encoding="utf-8")
        self.assertNotIn("_ACTION_POOL", src)
        self.assertNotIn("_SETTING_POOL", src)
        self.assertNotIn("def _pick(", src)


class TestVisualBrief(unittest.TestCase):
    def _brief(self, key, variant=None, analysis=None, w=1080, h=1080):
        p = resolve_profile(key=key)
        c = build_concept(variant or {"headline": "A", "sub": "B", "cta": "C"}, 0,
                          analysis or {}, p)
        return build_visual_brief(c, analysis or {}, p, {}, w, h)

    def test_06_never_randomized(self):
        for key in INDUSTRY_PROFILES:
            b = self._brief(key)
            self.assertFalse(b["scene_randomized"], key)
            self.assertEqual(b["scene_source"], "declared_profile_policy", key)

    def test_07_software_uses_real_ui(self):
        b = self._brief("subscription")
        self.assertEqual(b["subject_asset"], "real_ui")
        self.assertIn("界面", b["action"])
        self.assertIn("no-UI", b["facts_boundary"])
        self.assertIn("不受 no-UI 背景约束", b["facts_boundary"])

    def test_08_physical_good_uses_official_sku(self):
        b = self._brief("ecommerce")
        self.assertEqual(b["subject_asset"], "official_sku_image")
        self.assertIn("第二个同类商品", b["facts_boundary"])

    def test_09_b2b_forbids_fabricated_metrics(self):
        b = self._brief("b2b_service")
        self.assertTrue(any("上涨曲线" in x or "收益" in x
                            for x in b["forbidden_inferences"]))

    def test_10_travel_forbids_fake_price(self):
        b = self._brief("travel_local")
        self.assertTrue(any("低价" in x for x in b["forbidden_inferences"]))

    def test_11_same_profile_same_scene_not_random(self):
        a = self._brief("general", {"headline": "X", "sub": "Y", "cta": "Z"})
        b = self._brief("general", {"headline": "完全不同的承诺", "sub": "另一个副标", "cta": "Go"})
        self.assertEqual(a["action"], b["action"])
        self.assertEqual(a["setting"], b["setting"])

    def test_12_prompts_still_differ_by_concept(self):
        a = self._brief("ecommerce", {"headline": "X", "sub": "Y", "cta": "Z"})
        b = self._brief("ecommerce", {"headline": "完全不同的承诺", "sub": "另一个副标", "cta": "Go"})
        self.assertNotEqual(brief_prompt_block(a), brief_prompt_block(b))

    def test_13_claim_refs_bind_to_snapshot(self):
        analysis = {"evidence_index": [{"evidence_id": "E001", "quote": "14 天免费试用"}],
                    "evidence_chain": [{"claim": "14 天免费试用", "evidence_ids": ["E001"]}]}
        c = build_concept({"headline": "14 天免费试用", "sub": "", "cta": ""}, 0, analysis,
                          resolve_profile(key="subscription"))
        self.assertTrue(c["claim_verified"])
        self.assertEqual(c["evidence_ids"], ["E001"])
        self.assertEqual(c["evidence_kind"], "copy_subhead_not_verified")

    def test_14_invalid_evidence_not_bound(self):
        analysis = {"evidence_index": [{"evidence_id": "E001", "quote": "14 天免费试用"}],
                    "evidence_chain": [{"claim": "14 天免费试用", "evidence_ids": ["E999"]}]}
        c = build_concept({"headline": "14 天免费试用", "sub": "", "cta": ""}, 0, analysis,
                          resolve_profile(key="subscription"))
        self.assertFalse(c["claim_verified"])
        self.assertEqual(c["evidence_ids"], [])


if __name__ == "__main__":
    unittest.main()
