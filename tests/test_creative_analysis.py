"""V4.50 创意工作台·全球创意分析：参考素材 → 大模型归类创意风格/类型 → 可复用提示词模板。

仅验证「接口契约 / 落库 / 鉴权 / 缺参拦截」，不依赖真实付费模型（无模型时走 Mock 兜底，
categories 可能为空，但记录必须创建成功、列表与详情可读）。"""
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

ADMIN_EMAIL = "cawtest@recomob.com"
ADMIN_USER = "cawtest"
ADMIN_PWD = "TestPwd123"


class TestCreativeAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="CA",
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
        r = self.client.post("/api/creative-analysis",
                             json={"text": "参考：某电商 App 的 Meta 信息流广告，主打极简产品特写 + 强 CTA",
                                   "title": "电商 App 信息流创意"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsNotNone(d.get("id"), "分析必须落库并返回记录 id")
        self.assertTrue(isinstance(d.get("categories"), list), "categories 必须为列表")
        self.assertIn("model_info", d)

    def test_02_list_returns_record(self):
        # 先创建一条
        self.client.post("/api/creative-analysis",
                         json={"text": "Unity 激励视频广告：关卡通关后弹出，主打奖励预告",
                               "title": "Unity 激励视频"},
                         headers=self.auth)
        r = self.client.get("/api/creative-analysis?limit=20", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("items", body)
        self.assertTrue(body["total"] >= 1)
        self.assertTrue(any(it.get("title") == "Unity 激励视频" for it in body["items"]))

    def test_03_get_by_id(self):
        created = self.client.post("/api/creative-analysis",
                                   json={"text": "Google Search RSA 广告：痛点 + 解决方案 + 扩展",
                                         "title": "GRS 搜索广告"},
                                   headers=self.auth).json()
        cid = created["id"]
        r = self.client.get(f"/api/creative-analysis/{cid}", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], cid)

    def test_04_missing_input_rejected(self):
        r = self.client.post("/api/creative-analysis", json={}, headers=self.auth)
        self.assertEqual(r.status_code, 400, r.text)

    def test_05_requires_auth(self):
        r = self.client.post("/api/creative-analysis",
                             json={"text": "无 token 调用应被拒绝"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    import unittest
    unittest.main()
