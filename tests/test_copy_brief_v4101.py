"""V4.101 / P1：文案链路接入用户确认 brief 与创意框架。

验证：模板占位符 / 旧模板兜底注入、未确认 brief 后端 400 拦截、
预览接口返回可读补全结果、generate_media_copy 接收 brief 参数。
"""
import inspect
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from prompt_catalog import compose_copy_prompt, MEDIA_COPY_SYS  # noqa: E402
from media_ad import generate_media_copy  # noqa: E402
from creative_brief import normalize_brief  # noqa: E402
from models import User  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

ADMIN_EMAIL = "copybrief@recomob.com"
ADMIN_USER = "copybrief"
ADMIN_PWD = "TestPwd123"


class TestCopyPromptWiring(unittest.TestCase):
    def test_01_template_has_persuasion_and_brief_slot(self):
        self.assertIn("转化表达", MEDIA_COPY_SYS)
        self.assertIn("[[USER_BRIEF]]", MEDIA_COPY_SYS)

    def test_02_brief_injected_even_without_placeholder(self):
        out = compose_copy_prompt("老模板 [[SCHEMA]] [[LIMITS]] [[LANGUAGE]] [[PLATFORM]]",
                                  schema="headline: <=30", limits="<=30", language="English",
                                  platform="Meta", user_brief="【用户确认】钩子=真实续航")
        self.assertIn("【用户确认】钩子=真实续航", out)

    def test_03_generate_media_copy_accepts_brief(self):
        self.assertIn("brief", inspect.signature(generate_media_copy).parameters)


class TestCopyBriefApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="CopyBrief",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_04_frameworks_endpoint(self):
        r = self.client.get("/api/creative-frameworks", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["frameworks"]), 9)

    def test_05_preview_completes_raw_input(self):
        r = self.client.post("/api/creative-brief/preview", headers=self.auth, json={
            "raw_input": "突出真实续航，让用户放心通勤",
            "analysis": {"product": "Air Pro", "audience": "通勤人群"},
            "framework": "pas", "platform": "Meta",
        })
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["confirmed"])
        self.assertEqual(d["framework"], "pas")
        self.assertEqual(d["product"], "Air Pro")
        self.assertTrue(d["hook"])
        self.assertIn("完善后的创意 brief", d["prompt_text"])
        self.assertIn("Meta", d["prompt_text"])

    def test_06_unconfirmed_brief_blocked_before_generation(self):
        raw = normalize_brief("续航", {"product": "Air Pro"})
        r = self.client.post("/api/media-campaign/copy", headers=self.auth, json={
            "analysis": {"product": "Air Pro", "industry": "consumer electronics",
                         "audience": "commuters", "competitors": [], "advantages": ["long battery"],
                         "channels": [{"platform": "Meta", "reason": "测试用"}]},
            "platform": "Meta", "lang": "en", "brief": raw,
        })
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("尚未确认", r.json()["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
