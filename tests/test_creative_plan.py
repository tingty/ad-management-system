"""V4.52 创意工作台·创意策略 / 路线规划 + 历史库：产品分析 + 媒体平台 → 大模型规划每平台创意路线 → 落库。

仅验证「接口契约 / 落库 / 列表 / 详情 / 更新 / 鉴权 / 缺参拦截」，不依赖真实付费模型
（无模型时走 Mock 兜底，routes 可能为空，但记录必须创建成功、列表与详情可读、PATCH 可回填）。
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

ADMIN_EMAIL = "cwptest@recomob.com"
ADMIN_USER = "cwptest"
ADMIN_PWD = "TestPwd123"

SAMPLE_ANALYSIS = {
    "url": "https://example.com",
    "industry": "工具", "type": "效率 App", "audience": "职场人群",
    "advantages": ["一键整理", "跨端同步"], "language": "zh", "competitors": ["X"],
    "channels": [{"platform": "Facebook", "reason": "覆盖广"}],
}


class TestCreativePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="CP",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login",
                            json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.token = r.json()["token"]
        cls.auth = {"Authorization": f"Bearer {cls.token}"}

    def test_01_create_plan(self):
        r = self.client.post("/api/creative-plan",
                             json={"title": "电商 App 创意策略", "analysis": SAMPLE_ANALYSIS,
                                   "platforms": ["Facebook", "Unity"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsNotNone(d.get("id"), "创意策略必须落库并返回记录 id")
        self.assertTrue(isinstance(d.get("routes"), list), "routes 必须为列表")
        # routes 须与平台一一对应
        self.assertEqual([rt.get("platform") for rt in d["routes"]], ["Facebook", "Unity"])
        self.assertIn("model_info", d)

    def test_02_list_plans(self):
        self.client.post("/api/creative-plan",
                         json={"title": "Unity 激励视频策略", "analysis": SAMPLE_ANALYSIS,
                               "platforms": ["Unity"]},
                         headers=self.auth)
        r = self.client.get("/api/creative-plan?limit=20", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("items", body)
        self.assertTrue(body["total"] >= 1)
        self.assertTrue(any(it.get("title") == "Unity 激励视频策略" for it in body["items"]))

    def test_03_get_and_patch(self):
        created = self.client.post("/api/creative-plan",
                                   json={"title": "GRS 搜索广告策略", "analysis": SAMPLE_ANALYSIS,
                                         "platforms": ["Google Search"]},
                                   headers=self.auth).json()
        pid = created["id"]
        r = self.client.get(f"/api/creative-plan/{pid}", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], pid)

        p = self.client.patch(f"/api/creative-plan/{pid}",
                              json={"status": "done", "asset_count": 4, "history_id": 9},
                              headers=self.auth)
        self.assertEqual(p.status_code, 200, p.text)
        self.assertEqual(p.json()["status"], "done")
        self.assertEqual(p.json()["asset_count"], 4)
        self.assertEqual(p.json()["history_id"], 9)

    def test_04_missing_platforms_rejected(self):
        r = self.client.post("/api/creative-plan",
                             json={"analysis": SAMPLE_ANALYSIS, "platforms": []},
                             headers=self.auth)
        self.assertEqual(r.status_code, 400, r.text)

    def test_05_missing_analysis_rejected(self):
        r = self.client.post("/api/creative-plan",
                             json={"platforms": ["Facebook"]}, headers=self.auth)
        self.assertEqual(r.status_code, 400, r.text)

    def test_06_requires_auth(self):
        r = self.client.post("/api/creative-plan",
                             json={"analysis": SAMPLE_ANALYSIS, "platforms": ["Facebook"]})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    import unittest
    unittest.main()
