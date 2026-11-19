"""V4.101 / P3：视频分镜框架化 + 出片提示词断点修复。

验证：规划系统提示词含五段节奏与框架字段；出片 prompt 必须注入 hook/cta/camera/motion；
用户确认 brief 与换一批入参可用；证据门 / 三道防线措辞仍在。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
import routers  # noqa: E402
from schemas import CWVideoPlanRequest  # noqa: E402
from creative_brief import normalize_brief  # noqa: E402
from models import User  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

ADMIN_EMAIL = "vidplan4101@recomob.com"
ADMIN_USER = "vidplan4101"
ADMIN_PWD = "TestPwd123"


class TestVideoPlanPromptWiring(unittest.TestCase):
    def test_01_plan_prompt_has_framework_and_five_beats(self):
        sys_prompt = routers._CW_VIDEO_PLAN_SYS
        for token in ("framework", "frames", "sound_design", "0-3s 钩子", "3-6s 痛点放大",
                      "6-10s 方案演示", "10-13s 证据证明", "13-15s CTA 收口", "regenerate=true"):
            self.assertIn(token, sys_prompt)

    def test_02_plan_request_supports_regeneration(self):
        fields = CWVideoPlanRequest.model_fields
        for key in ("framework", "user_brief", "regenerate", "seed"):
            self.assertIn(key, fields)

    def test_03_provider_prompt_receives_director_fields(self):
        src = Path(routers.__file__).read_text(encoding="utf-8")
        self.assertIn("（运镜：{s['camera']}）", src)
        self.assertIn("（动作/转场：{s['motion']}）", src)
        self.assertIn("开场钩子意图（用动作/反差表达，不作为上屏文字）", src)
        self.assertIn("收口动作意图（仅作为动作/叠加位，不绘制文字）", src)
        self.assertIn("创意框架：%s", src)

    def test_04_guardrails_still_present(self):
        sys_prompt = routers._CW_VIDEO_PLAN_SYS
        self.assertIn("V4.82 硬约束", sys_prompt)
        self.assertIn("V4.88 无字策略", sys_prompt)
        self.assertIn("render_video_text_guard_block", Path(routers.__file__).read_text(encoding="utf-8"))


class TestVideoPlanApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="VidPlan",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_05_plan_with_confirmed_brief_and_regenerate(self):
        brief = normalize_brief("用前后对比突出真实续航", {"product": "Air Pro"},
                                framework="contrast_proof", confirmed=True)
        r = self.client.post("/api/cw-video/plan", headers=self.auth, json={
            "analysis": {"product": "Air Pro", "audience": "通勤人群",
                         "advantages": ["long battery"]},
            "platform": "Meta", "framework": "contrast_proof", "user_brief": brief,
            "regenerate": True, "seed": "v2",
            "options": {"duration": 15, "aspect": "9:16", "lang": "zh"},
        })
        self.assertEqual(r.status_code, 200, r.text)
        plan = r.json()["plan"]
        self.assertTrue(plan.get("shots"))
        self.assertEqual(plan.get("framework", "contrast_proof"), "contrast_proof")
        self.assertTrue(plan.get("hook"))
        self.assertTrue(plan.get("cta"))
        self.assertEqual((plan.get("creative_brief") or {}).get("brief_hash"), brief["brief_hash"])

    def test_06_unconfirmed_brief_not_stored(self):
        brief = normalize_brief("突出续航", {"product": "Air Pro"})
        r = self.client.post("/api/cw-video/plan", headers=self.auth, json={
            "analysis": {"product": "Air Pro"}, "platform": "Meta",
            "user_brief": brief, "options": {"lang": "zh"},
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("creative_brief", r.json()["plan"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
