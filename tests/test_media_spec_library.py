"""V4.84：素材标准库 API 端点 + 二级菜单数据契约（无真实模型 / 无网络）。

验证：
- GET /api/media-spec-library 需鉴权；
- 返回库版本、核验日期、8 平台规则、A/B/C 分级与来源字段；
- 与生成链路共享的 video_target / validate_video_delivery 判定一致。
"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from models import User  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

import media_spec_library as lib  # noqa: E402

ADMIN_EMAIL = "speclib@recomob.com"
ADMIN_USER = "speclib"
ADMIN_PWD = "TestPwd123"


class TestMediaSpecLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="规格库",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_01_endpoint_requires_auth(self):
        r = self.client.get("/api/media-spec-library")
        self.assertIn(r.status_code, (401, 403), r.text)

    def test_02_endpoint_returns_library(self):
        r = self.client.get("/api/media-spec-library", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d.get("library_version"))
        self.assertTrue(d.get("reviewed_on"))
        self.assertIn("A", d.get("verification_label", {}))
        entries = d.get("entries") or []
        self.assertGreaterEqual(len(entries), 30)
        self.assertTrue({"Meta", "Google", "Unity", "AppLovin", "Mintegral",
                         "TikTok", "Moloco", "Adsterra"}.issubset({e["platform"] for e in entries}))
        # 每条都带核验分级与库版本，展示与生成同源
        for e in entries:
            self.assertIn(e["verification"], ("A", "B", "C"))
            self.assertEqual(e["library_version"], d["library_version"])

    def test_03_a_entries_have_official_source(self):
        r = self.client.get("/api/media-spec-library", headers=self.auth)
        entries = r.json()["entries"]
        a = [e for e in entries if e["verification"] == "A"]
        self.assertTrue(a)
        for e in a:
            self.assertTrue(e.get("source_url") and e.get("verified_on"),
                            f"A 级条目缺来源/日期：{e['platform']}/{e['ad_product']}")

    def test_04_generation_shares_same_rules(self):
        # 生成前解析 + 交付复核与标准库共用一份规则
        t = lib.video_target("Moloco", "9:16", 5)
        self.assertEqual(t["verification"], "A")
        self.assertFalse(t["duration_ok"])          # 官方 6s 下限
        self.assertIn("end_card", t["companions"])
        chk = lib.validate_video_delivery(lib.video_target("Moloco", "9:16", 15), 5)
        self.assertEqual(chk["status"], "hard_fail")
        # Meta 受限 → B 级 advisory，不冒充官方硬规则
        chk_meta = lib.validate_video_delivery(lib.video_target("Meta", "9:16", 15), 5)
        self.assertEqual(chk_meta["status"], "advisory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
