"""V4.101 / P2：图片创意路线框架化、换一批与统一规则细化。

验证：兜底路线含框架/钩子/证据/视觉钩子；seed 轮换真实改变路线集合；
规则文本渲染主干框架细项；已确认 brief 注入；框架反推创意方向预设。
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
from creative_brief import normalize_brief  # noqa: E402
from image_prompt_rule import build_image_prompt_rule  # noqa: E402
from creative_config import resolve_creative_config, FRAMEWORK_DIRECTION  # noqa: E402
from routers import _CW_FALLBACK_ROUTES, _rotated_fallback_routes  # noqa: E402
from models import User  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

ADMIN_EMAIL = "imgplan4101@recomob.com"
ADMIN_USER = "imgplan4101"
ADMIN_PWD = "TestPwd123"


class TestImageFrameworkRules(unittest.TestCase):
    def test_01_fallback_routes_are_framework_driven(self):
        self.assertEqual(len(_CW_FALLBACK_ROUTES), 10)
        for r in _CW_FALLBACK_ROUTES:
            self.assertTrue(r["framework"])
            for key in ("hook", "proof", "visual_hook", "cta_role"):
                self.assertTrue(r[key], "%s 缺 %s" % (r["name"], key))

    def test_02_seed_rotation_changes_route_set(self):
        plain = [r["name"] for r in _rotated_fallback_routes("", [], 10)]
        rotated = [r["name"] for r in _rotated_fallback_routes("v2", [], 10)]
        self.assertNotEqual(plain, rotated)
        self.assertEqual(set(plain), set(rotated))
        excluded = [r["name"] for r in _rotated_fallback_routes("", [plain[0]], 9)]
        self.assertNotIn(plain[0], excluded)

    def test_03_rule_renders_framework_details(self):
        route = {"key": "A", "name": "前后对比实验", "angle": "前后对比",
                 "description": "真实前后对照", "tags": ["转化导向"],
                 "framework": "contrast_proof", "framework_label": "对比证明",
                 "hook": "同机位两种状态并置", "proof": "真实功能演示，不写数字",
                 "visual_hook": "左右分屏", "cta_role": "叠加位收口"}
        rule = build_image_prompt_rule(routes=[route], platform="Meta")
        self.assertIn("主干转化框架：对比证明", rule["rule_text"])
        self.assertIn("同机位两种状态并置", rule["rule_text"])
        self.assertIn("画面内不绘制任何文字", rule["rule_text"])
        self.assertEqual(rule["route_keys"], ["A"])

    def test_04_confirmed_brief_enters_rule(self):
        b = normalize_brief("用真实续航做前后对比", {"product": "Air Pro"},
                            framework="bab", confirmed=True)
        rule = build_image_prompt_rule(routes=[], brief=b, platform="Meta")
        self.assertEqual(rule["brief_hash"], b["brief_hash"])
        self.assertIn("用户确认的视觉表达策略", rule["rule_text"])

    def test_05_framework_infers_creative_direction(self):
        for key, direction in FRAMEWORK_DIRECTION.items():
            cfg = resolve_creative_config({"creative_plan": {"routes": [
                {"key": "A", "name": "路线", "framework": key}]}})
            self.assertEqual(cfg["preset_ids"]["direction"], direction)
            self.assertTrue(cfg["prompt_rule"]["rule_text"])


class TestImageRoutesApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="ImgPlan",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def _routes(self, **extra):
        return self.client.post("/api/cw/routes", headers=self.auth, json={
            "plan_id": None, "analysis": {"product": "Air Pro"}, "brief": {},
            "platforms": ["Meta"], "count": 10, **extra,
        })

    def test_06_route_response_has_framework_fields(self):
        r = self._routes()
        self.assertEqual(r.status_code, 200, r.text)
        routes = r.json()["routes"]
        self.assertEqual(len(routes), 10)
        for item in routes:
            for key in ("framework", "framework_label", "hook", "proof", "visual_hook", "cta_role"):
                self.assertIn(key, item)

    def test_07_seed_changes_fallback_routes(self):
        a = [x["name"] for x in self._routes().json()["routes"]]
        b = [x["name"] for x in self._routes(seed="v2").json()["routes"]]
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
