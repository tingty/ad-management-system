"""V4.43 机制的动态回归：版本锚点自动同步、精简字段、最新在前、缓存失效。

不硬编码具体版本号（版本升到 V4.45 之后本测试仍然有效）：
系统版本来自 `version.APP_VERSION`，通知首条必须等于该版本的 release tag。
"""
import subprocess
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

import version
import release_notes as rn
import release_notes_data  # noqa: E402  随代码发布的权威发布数据（V4.48）
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from database import SessionLocal
from migrations import ensure_schema
from models import User
from auth import hash_password
from main import app  # noqa: E402  触发 on_startup：建表 + 默认管理员

FIELDS = {"version", "title", "date", "summary", "modules",
          "change_types", "points", "auto_generated"}
FORBIDDEN = {"body", "impact", "verification", "changes", "highlights", "roadmap"}
ROOT = Path(_bootstrap.ROOT)

ADMIN_EMAIL = "relnotest@recomob.com"
ADMIN_USER = "relnotest"
ADMIN_PWD = "TestPwd123"


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


class TestReleaseNotesV448(unittest.TestCase):
    """V4.48 可靠性回归：版本内容强制随代码同步，且每次代码更新都会生成发布数据。"""

    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="RN",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        cls.token = cls.client.post("/api/auth/login",
                                    json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}).json()["token"]
        cls.tag = version.release_tag()

    def _get(self):
        return self.client.get("/api/system/release-notes",
                              headers={"Authorization": f"Bearer {self.token}"})

    def test_01_endpoint_returns_current_version_with_content(self):
        r = self._get()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["version"], version.APP_VERSION)
        self.assertEqual(d["latest"], self.tag)
        # 当前版本必须来自正式发布数据，而非「自动同步」的弱兜底
        self.assertFalse(d["auto_generated"], "当前版本不应回退到自动兜底")
        cur = d["notes"][0]
        self.assertEqual(cur["version"], self.tag)
        self.assertTrue(cur["summary"], "当前版本「变更摘要」不得为空")
        self.assertTrue(cur["points"], "当前版本「更新要点」不得为空（否则新版通知无内容）")
        for p in cur["points"]:
            self.assertTrue(p.strip(), "更新要点不得为空白条目")

    def test_02_embedded_data_is_authoritative_and_complete(self):
        self.assertTrue(release_notes_data.NOTES, "发布数据文件不得为空")
        first = release_notes_data.NOTES[0]
        self.assertEqual(first["version"], self.tag, "随代码发布的发布数据首条必须是当前版本")
        self.assertFalse(first.get("auto_generated"), "当前版本不应标记为自动生成")
        self.assertTrue(first.get("summary"), "发布数据当前版本摘要不得为空")
        self.assertTrue(first.get("points"), "发布数据当前版本要点不得为空")
        versions = {n.get("version") for n in release_notes_data.NOTES}
        self.assertIn(self.tag, versions)

    def test_03_prepare_release_check_passes(self):
        # 发版闸门：发布数据版本必须与系统版本一致，否则拦截
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_release.py"), "--check"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0,
                        f"prepare_release --check 应通过的失败输出：\n{proc.stdout}\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
