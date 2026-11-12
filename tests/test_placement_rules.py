"""N04 / A10 / A11：版位级规则主键、未知版位拒绝、目录补齐与未核验标记。"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from media_platforms import (validate_task_matrix, resolve_placement, MediaRuleError,
                             list_media_platforms, allowed_sizes, SPEC_VERSION,
                             SPEC_VERIFIED_ON, PLACEMENT_RULES, MEDIA_RULES)

BACKEND = Path(_bootstrap.ROOT) / "backend"


class TestPlacementRules(unittest.TestCase):
    def _blocked(self, slots, platform="Meta"):
        with self.assertRaises(MediaRuleError) as ctx:
            validate_task_matrix(platform, slots)
        return "；".join(ctx.exception.errors)

    def test_01_feed_square_ok(self):
        r = validate_task_matrix("Meta", [{"size": "1080x1080", "placement_id": "feed"}])
        self.assertEqual(r["meta"]["effective_tasks"], 1)
        self.assertEqual(r["meta"]["placement_validation"], "strict_primary_key")

    def test_02_feed_vertical_blocked(self):
        msg = self._blocked([{"size": "1080x1920", "placement_id": "feed"}])
        self.assertIn("不匹配", msg)
        self.assertIn("feed", msg)

    def test_03_unknown_placement_blocked(self):
        msg = self._blocked([{"size": "1080x1080", "placement_id": "does_not_exist"}])
        self.assertIn("未知广告版位", msg)
        self.assertNotIn("unspecified", msg)

    def test_04_unknown_placement_name_blocked(self):
        self.assertIn("未知广告版位", self._blocked(
            [{"size": "1080x1080", "placement": "不存在的版位"}]))

    def test_05_stories_vertical_ok(self):
        r = validate_task_matrix("Meta", [{"size": "1080x1920", "placement_id": "stories"}])
        self.assertEqual(r["slots"][0]["asset_role"], "story_vertical")

    def test_06_legacy_call_kept_but_flagged(self):
        r = validate_task_matrix("Meta", [{"size": "1080x1080"}])
        self.assertTrue(r["meta"]["placement_warnings"])
        self.assertEqual(r["meta"]["placement_validation"], "mixed_legacy")

    def test_07_resolve_returns_full_primary_key(self):
        pl = resolve_placement("Google", placement_id="uac")
        self.assertIn("ad_product", pl)
        self.assertIn("asset_role", pl)
        self.assertIn("sizes", pl)

    def test_08_unregistered_role_blocked(self):
        with self.assertRaises(MediaRuleError):
            resolve_placement("NotAPlatform", placement_id="x")

    def test_09_moloco_in_catalog(self):
        names = [p["platform"] for p in list_media_platforms()]
        self.assertIn("Moloco", names)
        self.assertIn("Moloco", PLACEMENT_RULES)
        self.assertIn("1200x628", allowed_sizes("Moloco"))

    def test_10_google_no_rsa_image_misnomer(self):
        text = (BACKEND / "media_platforms.py").read_text(encoding="utf-8")
        self.assertNotIn("RSA 配图", text)
        self.assertIn("上传式展示图", text)

    def test_11_verified_on_still_empty(self):
        self.assertEqual(SPEC_VERIFIED_ON, "")
        self.assertTrue(any("未核验" in x or "复核" in x for x in MEDIA_RULES["policy"]))

    def test_12_hard_rules_document_primary_key(self):
        self.assertTrue(any("placement" in x for x in MEDIA_RULES["hard"]))

    def test_13_spec_version_bumped(self):
        self.assertEqual(SPEC_VERSION, "2026-11-12.1")

    def test_14_task_matrix_multi_platform_scope(self):
        r = validate_task_matrix("Google", [
            {"size": "300x250", "placement_id": "display_mrec"},
            {"size": "1080x1920", "placement_id": "uac"}])
        self.assertEqual(r["meta"]["effective_tasks"], 2)
        self.assertTrue(r["meta"]["mixed_ad_products"])


if __name__ == "__main__":
    unittest.main()
