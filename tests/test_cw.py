"""V4.53 创意工作台（Figma 设计对齐）：产品分析（4 盒 + 项目简报）+ 3 条创意路线。

仅验证「接口契约 / 落库 / 列表 / 详情 / 鉴权 / 缺参拦截 / 来源快照」，不依赖真实付费模型
（无模型时走 Mock 兜底，端点必须 200 落库、返回 id、字段结构正确）。

V4.59 / B1：新增对「真实抓取 / 演示模式隔离 / 抓取失败阻断 / 来源快照」的断言。
为避免触发真实网络抓取，URL 类用例统一用 `demo_mode=True`（不联网、不调用模型、source=demo）；
抓取失败阻断用例用一个不可达地址验证 422；粘贴文本用例验证 source=pasted。
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

    def test_01_analyze_demo_creates_record(self):
        # B1：演示模式不联网、不调用真实模型，确定性返回样例并标注 source=demo
        r = self.client.post("/api/cw/analyze",
                             json={"url": "https://soundora.com/products/air-pro",
                                   "platforms": ["Meta", "Google"],
                                   "demo_mode": True},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsNotNone(d.get("id"), "产品分析必须落库并返回记录 id")
        self.assertIsInstance(d.get("boxes"), dict, "boxes 必须为字典")
        self.assertIsInstance(d.get("brief"), dict, "brief 必须为字典")
        self.assertIn("industry", d["boxes"])
        # V4.58 / B2：分析接口须返回统一分析来源，供路线规划与素材生成复用
        self.assertIsInstance(d.get("analysis"), dict, "analysis 必须为字典（统一分析来源）")
        self.assertTrue(d["analysis"].get("industry") or d["analysis"].get("summary"),
                        "analysis 应携带 industry / summary 等生成所需字段")
        self.assertIn("promotionGoal", d["brief"])
        self.assertIn("sellingPoints", d["brief"])
        # V4.59 / B1：演示模式必须返回来源快照且明确标注 source=demo
        self.assertIsInstance(d.get("snapshot"), dict, "snapshot 必须为字典")
        self.assertEqual(d["snapshot"].get("source"), "demo", "演示模式 source 必须为 demo")
        self.assertEqual(d.get("source"), "demo", "顶层 source 必须与快照一致(demo)")
        self.assertIn("演示", d.get("title") or "", "演示样例标题应标明为演示")

    def test_02_routes_needs_plan(self):
        # 先以演示模式分析拿到 plan_id
        a = self.client.post("/api/cw/analyze",
                             json={"url": "https://x.com/p", "platforms": ["Meta"],
                                   "demo_mode": True},
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
                         json={"url": "https://y.com/p", "platforms": ["Google"],
                               "demo_mode": True}, headers=self.auth)
        r = self.client.get("/api/creative-plan?limit=20", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["total"] >= 1)

    def test_05_requires_auth(self):
        r = self.client.post("/api/cw/analyze",
                             json={"url": "https://z.com", "platforms": ["Meta"]})
        self.assertEqual(r.status_code, 401)

    def test_06_fetch_failed_blocked(self):
        # B1：链接不可达且未开启演示模式、未提供文本 → 必须在调用模型前 422 阻断，不得静默套用演示数据
        r = self.client.post("/api/cw/analyze",
                             json={"url": "http://127.0.0.1:9/unreachable", "platforms": ["Meta"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 422, r.text)
        body = r.json()
        # FastAPI HTTPException 的 detail 可能是 dict（含 message/errors）或字符串
        detail = body.get("detail", "")
        if isinstance(detail, dict):
            self.assertIn("needs_input", detail.get("message", "") + detail.get("hint", "")
                          + str(detail.get("errors", "")), "阻断信息应说明链接不可达，提示开启演示模式或补充正文")
        else:
            self.assertIn("抓取", str(detail), "阻断信息应说明抓取失败")

    def test_07_pasted_text_source(self):
        # B1：仅粘贴文本 → source=pasted，不联网、不伪装成真实抓取
        r = self.client.post("/api/cw/analyze",
                             json={"text": "一款面向跑步爱好者的智能运动手环，主打心率监测与长续航。",
                                   "platforms": ["Meta"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d.get("source"), "pasted", "仅文本模式 source 必须为 pasted")
        self.assertIsInstance(d.get("snapshot"), dict)
        self.assertEqual(d["snapshot"].get("source"), "pasted")


if __name__ == "__main__":
    import unittest
    unittest.main()
