"""V4.100：「素材提示管理」改名「提示词管理」并修复菜单点击被重定向。

验证：菜单/页面标题改名、allowedTabs 白名单补入 materialprompts（点击不再弹回工作台）、
后端模块名与注册表同步改名、旧模块名查询保持兼容、页面按 meta.module 动态取数。
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
from material_prompt_manage import MODULE, LEGACY_MODULE, material_prompt_entries  # noqa: E402
from services import PROMPT_REGISTRY  # noqa: E402
from models import User  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
ADMIN_EMAIL = "renamepm@recomob.com"
ADMIN_USER = "renamepm"
ADMIN_PWD = "TestPwd123"
EXPECTED_KEYS = {"material_prompt_copy", "material_prompt_image", "material_prompt_video"}


class TestPromptManageRenameStatic(unittest.TestCase):
    def test_01_menu_label_and_allowed_tab(self):
        src = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("{ key: 'materialprompts', label: '提示词管理'", src)
        self.assertNotIn("label: '素材提示管理'", src)
        allowed = src[src.index("function allowedTabs"):src.index("function readCollapsed")]
        self.assertIn("'materialprompts'", allowed)
        self.assertIn("['workbench', 'creativeanalysis', 'speclibrary', 'materialprompts', 'history']", allowed)

    def test_02_page_title_and_dynamic_module(self):
        src = (FRONTEND / "pages" / "MaterialPromptManage.tsx").read_text(encoding="utf-8")
        self.assertIn("<h2>提示词管理</h2>", src)
        self.assertNotIn("<h2>素材提示管理</h2>", src)
        self.assertIn("const list = await api.prompts(m.module)", src)
        self.assertNotIn("api.prompts('素材提示管理')", src)


class TestPromptManageRenameBackend(unittest.TestCase):
    def test_03_module_constant_and_registry(self):
        self.assertEqual(MODULE, "提示词管理")
        self.assertEqual(LEGACY_MODULE, "素材提示管理")
        self.assertEqual({x["module"] for x in material_prompt_entries()}, {MODULE})
        keys = {p["key"] for p in PROMPT_REGISTRY if p.get("module") == MODULE}
        self.assertEqual(keys, EXPECTED_KEYS)
        self.assertFalse({p["key"] for p in PROMPT_REGISTRY if p.get("module") == LEGACY_MODULE})


class TestPromptManageRenameApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="RenamePM",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_04_meta_exposes_new_and_legacy_module(self):
        r = self.client.get("/api/settings/material-prompts/meta", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["module"], "提示词管理")
        self.assertEqual(d.get("legacy_module"), "素材提示管理")

    def test_05_new_module_query(self):
        r = self.client.get("/api/settings/prompts?module=提示词管理", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({x["key"] for x in r.json()}, EXPECTED_KEYS)

    def test_06_legacy_module_query_still_works(self):
        r = self.client.get("/api/settings/prompts?module=素材提示管理", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({x["key"] for x in r.json()}, EXPECTED_KEYS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
