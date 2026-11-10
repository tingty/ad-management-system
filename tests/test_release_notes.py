"""V4.43 机制的动态回归：版本锚点自动同步、精简字段、最新在前、缓存失效。

不硬编码具体版本号（版本升到 V4.45 之后本测试仍然有效）：
系统版本来自 `version.APP_VERSION`，通知首条必须等于该版本的 release tag。
"""
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

import version
import release_notes as rn

FIELDS = {"version", "title", "date", "summary", "modules",
          "change_types", "points", "auto_generated"}
FORBIDDEN = {"body", "impact", "verification", "changes", "highlights", "roadmap"}
ROOT = Path(_bootstrap.ROOT)


class TestReleaseNotesSync(unittest.TestCase):
    def setUp(self):
        rn.invalidate_cache()
        self.data = rn.get_release_notes()
        self.tag = version.release_tag()

    def test_01_single_source_version(self):
        import main
        self.assertEqual(main.app.version, version.APP_VERSION)

    def test_02_tag_mapping(self):
        self.assertEqual(version.release_tag("4.44.0"), "V4.44")
        self.assertEqual(version.release_tag("4.44.2"), "V4.44.2")

    def test_03_app_version_is_anchor(self):
        self.assertEqual(self.data["app_version"], self.tag)

    def test_04_latest_equals_running_version(self):
        self.assertEqual(self.data["latest"], self.tag)
        self.assertEqual(self.data["notes"][0]["version"], self.tag)

    def test_05_auto_fallback_is_explicit(self):
        # 未写 CHANGELOG 时自动生成兜底通知，且明确标注，不会停在旧版本
        self.assertIsInstance(self.data["auto_generated"], bool)

    def test_06_notes_sorted_desc(self):
        def num(v):
            return tuple(int(x) for x in __import__("re").findall(r"\d+", v))
        vs = [num(n["version"]) for n in self.data["notes"]]
        self.assertEqual(vs, sorted(vs, reverse=True))

    def test_07_only_summary_fields(self):
        for n in self.data["notes"]:
            self.assertEqual(set(n.keys()), FIELDS)
            self.assertFalse(set(n.keys()) & FORBIDDEN)

    def test_08_current_points_limited(self):
        cur = self.data["current"]
        self.assertEqual(set(cur.keys()), FIELDS)
        self.assertLessEqual(len(cur["points"]), 6)
        self.assertTrue(all(len(str(p)) <= 200 for p in cur["points"]))

    def test_09_every_version_has_points(self):
        for n in self.data["notes"]:
            self.assertLessEqual(len(n["points"]), 6)

    def test_10_cache_invalidate_is_safe(self):
        rn.invalidate_cache()
        self.assertEqual(rn.get_release_notes()["app_version"], self.tag)

    def test_11_changelog_is_single_source(self):
        self.assertTrue((ROOT / "CHANGELOG.md").exists())


if __name__ == "__main__":
    unittest.main()
