"""V4.53 创意工作台（Figma 设计对齐）：产品分析（4 盒 + 项目简报）+ 3 条创意路线。

仅验证「接口契约 / 落库 / 列表 / 详情 / 鉴权 / 缺参拦截」，不依赖真实付费模型
（无模型时走 Mock 兜底，端点必须 200 落库、返回 id、字段结构正确）。
"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402  环境变量隔离（DATABASE_URL -> 临时 SQLite）

from fastapi.testclient import TestClient

from database import SessionLocal
from migrations import ensure_schema
from models import User
from auth import hash_password
from main import app  # 触发 on_startup：建表 + 默认管理员

ADMIN_EMAIL = "cwtest@recomob.com"
ADMIN_USER = "cwtest"
ADMIN_PWD = "TestPwd123"


class TestCW(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="CW",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login",
                            json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.token = r.json()["token"]
        cls.auth = {"Authorization": f"Bearer {cls.token}"}

    def test_01_analyze_creates_record(self):
        r = self.client.post("/api/cw/analyze",
                             json={"url": "https://soundora.com/products/air-pro",
                                   "platforms": ["Meta", "Google"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsNotNone(d.get("id"), "产品分析必须落库并返回记录 id")
        self.assertIsInstance(d.get("boxes"), dict, "boxes 必须为字典")
        self.assertIsInstance(d.get("brief"), dict, "brief 必须为字典")
        self.assertIn("industry", d["boxes"])
        # V4.58 / B2：分析接口须返回统一分析来源，供路线规划与素材生成复用（避免二次模型理解）
        self.assertIsInstance(d.get("analysis"), dict, "analysis 必须为字典（统一分析来源）")
        self.assertTrue(d["analysis"].get("industry") or d["analysis"].get("summary"),
                        "analysis 应携带 industry / summary 等生成所需字段")
        self.assertIn("promotionGoal", d["brief"])
        self.assertIn("sellingPoints", d["brief"])

    def test_02_routes_needs_plan(self):
        # 先分析拿到 plan_id
        a = self.client.post("/api/cw/analyze",
                             json={"url": "https://x.com/p", "platforms": ["Meta"]},
                             headers=self.auth).json()
        r = self.client.post("/api/cw/routes",
                             json={"plan_id": a["id"], "platforms": ["Meta"],
                                   "analysis": a.get("analysis", {}), "brief": a.get("brief", {})},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsInstance(d.get("routes"), list, "routes 必须为列表")
        # Mock 兜底也会返回 3 条默认路线；真实模型返回 LLM 规划的路线
        self.assertTrue(len(d["routes"]) >= 1, "至少要返回 1 条创意路线")
        for rt in d["routes"]:
            self.assertIn(rt.get("key"), ("A", "B", "C"))

    def test_03_missing_input_rejected(self):
        r = self.client.post("/api/cw/analyze", json={"platforms": ["Meta"]}, headers=self.auth)
        self.assertEqual(r.status_code, 400, r.text)

    def test_04_history_via_creative_plan(self):
        self.client.post("/api/cw/analyze",
                         json={"url": "https://y.com/p", "platforms": ["Google"]}, headers=self.auth)
        r = self.client.get("/api/creative-plan?limit=20", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["total"] >= 1)

    def test_05_requires_auth(self):
        r = self.client.post("/api/cw/analyze",
                             json={"url": "https://z.com", "platforms": ["Meta"]})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    import unittest
    unittest.main()
