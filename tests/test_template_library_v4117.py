# -*- coding: utf-8 -*-
"""V4.117 素材创意模板库：三层数据模型 + CRUD + 菜单改造 专项测试。

覆盖：
1. 三表由 ensure_schema 自动建成（creative_asset_sources / analyses / templates）
2. 素材条目 CRUD（新增 / 列表 / 删除；删除被 golden 引用时拒绝）
3. 分析记录写入 + 状态边界（素材不存在 404 / status 非法 400 / 回写素材状态）
4. 模板 CRUD + 人工编辑版本自增 + reset_to_ai + 边界（空名/无主分类 400）
5. 前端静态断言：菜单改名 / 并入工作坊分组 / openKey 第三键 / 组件内无重复页头 / api 方法齐全
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend", "src")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestSchemaV4117(unittest.TestCase):
    def test_tables_registered(self):
        import models
        names = {c.__tablename__ for c in models.Base.__subclasses__()}
        for t in ("creative_asset_sources", "creative_asset_analyses", "creative_templates"):
            self.assertIn(t, names, f"缺少表定义 {t}")

    def test_ensure_schema_creates_tables(self):
        from migrations import ensure_schema
        from database import engine
        from sqlalchemy import inspect
        ensure_schema()
        db_tables = set(inspect(engine).get_table_names())
        for t in ("creative_asset_sources", "creative_asset_analyses", "creative_templates"):
            self.assertIn(t, db_tables, f"ensure_schema 未建表 {t}")


class TestCRUDV4117(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User

        ensure_schema()
        email, user, pwd = "v4117@recomob.com", "v4117", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4117",
                            role="editor", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def _add_asset(self, title="测试素材", kind="image"):
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": title, "media_kind": kind, "source_type": "upload",
                                   "file": "/files/tl_v4117.png", "platform": "Meta",
                                   "rights_status": "granted", "rights_note": "自有素材，已获投放授权"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_01_asset_add_and_list(self):
        a = self._add_asset("素材A")
        self.assertGreater(a["id"], 0)
        self.assertEqual(a["media_kind"], "image")
        self.assertEqual(a["status"], "imported")
        lst = self.client.get("/api/template-library/assets", headers=self.auth).json()
        self.assertTrue(any(x["id"] == a["id"] for x in lst), "新素材未出现在列表")
        self.__class__.asset_id = a["id"]

    def test_02_asset_bad_kind_400(self):
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "x", "media_kind": "gif"})
        self.assertEqual(r.status_code, 400)

    def test_03_analysis_write_and_status_refresh(self):
        aid = self.__class__.asset_id
        r = self.client.post("/api/template-library/analyses", headers=self.auth, json={
            "asset_id": aid,
            "dims_json": {"layout": {"composition": "前后对比分屏"}},
            "category_json": {"primary": "前后对比"},
            "template_guess": {"name": "前后对比实验", "confidence": 0.86},
            "completeness": 0.92, "confidence": 0.86, "status": "analyzed"})
        self.assertEqual(r.status_code, 200, r.text)
        an = r.json()
        self.assertEqual(an["framework_version"], "asset-deconstruct/1.0")
        self.assertAlmostEqual(an["completeness"], 0.92)
        # 素材状态应被回写 analyzed
        assets = self.client.get("/api/template-library/assets", headers=self.auth).json()
        row = next(x for x in assets if x["id"] == aid)
        self.assertEqual(row["status"], "analyzed")
        # 按 asset_id 过滤
        flt = self.client.get(f"/api/template-library/analyses?asset_id={aid}", headers=self.auth).json()
        self.assertTrue(any(x["id"] == an["id"] for x in flt))

    def test_04_analysis_bad_status_and_missing_asset(self):
        aid = self.__class__.asset_id
        bad = self.client.post("/api/template-library/analyses", headers=self.auth,
                               json={"asset_id": aid, "status": "passed"})
        self.assertEqual(bad.status_code, 400)
        miss = self.client.post("/api/template-library/analyses", headers=self.auth,
                                json={"asset_id": 999999, "status": "analyzed"})
        self.assertEqual(miss.status_code, 404)

    def test_05_template_crud_and_version(self):
        aid = self.__class__.asset_id
        r = self.client.post("/api/template-library/templates", headers=self.auth, json={
            "name": "前后对比实验", "primary_category": "前后对比",
            "purpose": ["转化"], "golden_asset_id": aid,
            "image_skeleton_json": {"composition": "split-screen"},
            "variables_json": {"PRODUCT": "产品名"}})
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()
        self.__class__.template_id = t["id"]
        self.assertEqual(t["version"], 1)
        # golden 引用的素材删除应被拒绝
        blocked = self.client.delete(f"/api/template-library/assets/{aid}", headers=self.auth)
        self.assertEqual(blocked.status_code, 400)
        # 编辑 → version 自增
        patch = self.client.patch(f"/api/template-library/templates/{t['id']}", headers=self.auth,
                                  json={"edit_note": "改为暖色调", "name": "前后对比实验V2"})
        self.assertEqual(patch.status_code, 200, patch.text)
        self.assertEqual(patch.json()["version"], 2)
        self.assertEqual(patch.json()["edit_note"], "改为暖色调")
        # reset_to_ai 清空 edit_note
        reset = self.client.patch(f"/api/template-library/templates/{t['id']}", headers=self.auth,
                                  json={"reset_to_ai": True})
        self.assertIsNone(reset.json()["edit_note"])
        self.assertEqual(reset.json()["version"], 3)
        # 分类过滤
        flt = self.client.get("/api/template-library/templates?category=前后对比", headers=self.auth).json()
        self.assertTrue(any(x["id"] == t["id"] for x in flt))

    def test_06_template_bad_input_400(self):
        r1 = self.client.post("/api/template-library/templates", headers=self.auth,
                              json={"name": "", "primary_category": "前后对比"})
        self.assertEqual(r1.status_code, 400)
        r2 = self.client.post("/api/template-library/templates", headers=self.auth,
                              json={"name": "x", "primary_category": ""})
        self.assertEqual(r2.status_code, 400)

    def test_07_delete_template_then_asset(self):
        tid, aid = self.__class__.template_id, self.__class__.asset_id
        self.assertEqual(self.client.delete(f"/api/template-library/templates/{tid}",
                                            headers=self.auth).status_code, 200)
        # 模板删除后素材可删
        self.assertEqual(self.client.delete(f"/api/template-library/assets/{aid}",
                                            headers=self.auth).status_code, 200)

    def test_08_requires_auth(self):
        r = self.client.get("/api/template-library/assets")
        self.assertIn(r.status_code, (401, 403))


class TestFrontendV4117(unittest.TestCase):
    def test_menu_moved_into_workshop(self):
        app = _read("frontend/src/App.tsx")
        # 素材工作坊分组含 creativeanalysis（2 项 → 二级菜单）
        self.assertIn("{ key: 'creativeanalysis', label: '素材创意模板库'", app)
        # 创意工作台分组不再含 creativeanalysis：creativeanalysis 只出现一次于菜单定义
        self.assertLessEqual(app.count("key: 'creativeanalysis'"), 1)
        # 第三折叠键
        self.assertIn("g.name === GROUP_WORKSHOP.name ? 'workshop'", app)
        self.assertIn("workshop: true, workbench: true, system: true", app)

    def test_no_duplicate_header(self):
        ca = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertNotIn("<h2>全球创意分析</h2>", ca)
        self.assertIn("素材创意模板库", ca)

    def test_api_methods(self):
        api = _read("frontend/src/api.ts")
        for m in ("tlAssets:", "tlAddAsset:", "tlDeleteAsset:", "tlAnalyses:", "tlAddAnalysis:",
                  "tlTemplates:", "tlAddTemplate:", "tlUpdateTemplate:", "tlDeleteTemplate:"):
            self.assertIn(m, api, f"缺少 api 方法 {m}")

    def test_hash_unchanged(self):
        app = _read("frontend/src/App.tsx")
        self.assertIn("'creativeanalysis'", app)  # Tab/TABS 保留原 hash


if __name__ == "__main__":
    unittest.main(verbosity=2)
