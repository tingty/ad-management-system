# -*- coding: utf-8 -*-
"""按模板创作（模板只影响图片）+ V4.122 授权声明移除 专项测试。

历史：V4.120 曾引入投放授权强制闸门；V4.122 按产品决议整体移除——
导入 / 解构 / 归并 / 模板沉淀 / 按模板创作均不再要求投放授权声明。

覆盖：
1. 模板骨架只生成视觉路线，不注入产品事实 / 品牌 / 数字（模板只影响图片，Q9）；
2. 导入不再要求授权字段：无授权字段仍可登记素材；
3. 解构 / 归并 / 模板新建 edit / 工作坊模板列表不再有 rights_gate 拦截；
4. 前端不再渲染授权声明子模块 / 补录入口 / 授权状态字段。
"""
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _dims():
    return {
        "layout": {"composition": {"value": "左右分屏前后对比", "confidence": 0.9},
                   "focal_path": {"value": "由左向右", "confidence": 0.8}},
        "visual": {"palette": {"value": "米色暖光", "confidence": 0.9},
                   "lighting": {"value": "自然光", "confidence": 0.8}},
        "info": {"headline_role": {"value": "改造前后主利益点", "confidence": 0.9},
                 "benefits": {"value": ["空间显大"], "confidence": 0.9},
                 "cta": {"value": "低风险咨询", "confidence": 0.8},
                 "evidence_kind": {"value": "对比画面", "confidence": 0.9}},
        "effect": {"hook_type": {"value": "结果", "confidence": 0.8}},
    }


def _analysis(aid):
    return {"asset_id": aid, "framework_version": "asset-deconstruct/1.0",
            "status": "analyzed", "completeness": 0.92, "confidence": 0.88,
            "dims_json": _dims(),
            "category_json": {"primary": "前后对比", "purposes": ["转化"], "hooks": ["结果"]}}


class TestTemplateOnlyAffectsImage(unittest.TestCase):
    def test_template_style_only_visual_skeleton(self):
        import template_gate as tg
        tpl = SimpleNamespace(id=12, name="前后对比模板", primary_category="前后对比",
                              purpose=["转化"], status="active",
                              image_skeleton_json={
                                  "composition": "左右分屏", "palette": "米色暖光",
                                  "benefits": ["空间显大"], "cta": "低风险咨询",
                                  "golden_analysis_id": 99})
        so = tg.template_style_opts(tpl, "Meta")
        plan = so["creative_plan"]
        self.assertEqual(so["template_id"], 12)
        self.assertTrue(so["fit_overlay"])
        route = plan["routes"][0]
        self.assertIn("构图=左右分屏", route["description"])
        self.assertNotIn("空间显大", route["description"])
        self.assertNotIn("低风险咨询", plan["supplement"])
        self.assertIn("本次分析和文案", plan["supplement"])
        self.assertNotIn("golden_analysis_id", str(so))

    def test_no_rights_symbols_in_backend(self):
        import template_gate as tg
        import asset_merge as am
        # 闸门函数与授权归一常量已整体移除。
        self.assertFalse(hasattr(tg, "rights_check"))
        self.assertFalse(hasattr(tg, "normalize_status"))
        self.assertFalse(hasattr(tg, "REQUIRED_ACTION"))
        # eligibility 恢复为单一参数（只有解构结果，不接受授权状态）。
        import inspect
        self.assertEqual(list(inspect.signature(am.eligibility).parameters), ["analysis"])
        self.assertTrue(am.eligibility(_analysis(1))["eligible"])


class TestRightsRemovedApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User

        ensure_schema()
        email, user, pwd = "v4120@recomob.com", "v4120", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4120",
                            role="editor", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_01_import_without_rights_fields(self):
        # 不带任何授权字段仍可登记素材（闸门已移除）。
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "无授权字段", "media_kind": "image",
                                   "source_type": "upload", "file": "/files/v4120.png",
                                   "platform": "Meta"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotIn("rights_status", body)
        self.assertNotIn("rights_note", body)
        r2 = self.client.post("/api/template-library/import", headers=self.auth,
                              json={"title": "统一导入无授权", "source_type": "url",
                                    "media_kind": "image", "file": "/files/v4120.png"})
        self.assertEqual(r2.status_code, 200, r2.text)

    def test_02_analyze_and_merge_no_rights_gate(self):
        a = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "解构入口素材", "media_kind": "image",
                                   "source_type": "upload", "file": "/files/v4120.png"}).json()
        # 解构不再因授权被拦截：直接进入文件检查（文件不存在 → 说明闸门已过）。
        r = self.client.post(f"/api/template-library/analyze/{a['id']}", headers=self.auth)
        self.assertNotIn("rights_gate", r.text)
        # 归并候选不再排除授权素材。
        self.client.post("/api/template-library/analyses", headers=self.auth,
                         json=_analysis(a["id"]))
        cand = self.client.get("/api/template-library/merge-candidates", headers=self.auth).json()
        self.assertTrue(any(m["asset_id"] == a["id"]
                            for g in cand["groups"] for m in g["members"]),
                        "有合格解构的素材应进入归并候选（不再受授权影响）")

    def test_03_template_edit_and_workshop_no_rights_gate(self):
        a = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "模板来源素材", "media_kind": "image",
                                   "source_type": "upload", "file": "/files/v4120.png"}).json()
        t = self.client.post("/api/template-library/templates", headers=self.auth, json={
            "name": "无授权模板", "primary_category": "前后对比", "purpose": ["转化"],
            "image_skeleton_json": {"composition": "左右分屏"},
            "golden_asset_id": a["id"]})
        self.assertEqual(t.status_code, 200, t.text)
        t = t.json()
        # PATCH 绑定 golden 不再被授权闸门拦截。
        r = self.client.patch(f"/api/template-library/templates/{t['id']}", headers=self.auth,
                              json={"golden_asset_id": a["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        # 工作坊模板列表可用性不再含授权原因。
        lst = {x["id"]: x for x in self.client.get("/api/workshop/templates", headers=self.auth).json()}
        self.assertTrue(lst[t["id"]]["usable"])
        self.assertNotIn("授权", lst[t["id"]]["reason"])

    def test_04_rights_patch_endpoint_removed(self):
        # 授权补录端点已删除：PATCH /rights 应 404（路由不存在）。
        r = self.client.patch("/api/template-library/assets/1/rights", headers=self.auth,
                              json={"rights_status": "granted", "rights_note": "自有素材"})
        self.assertEqual(r.status_code, 404, r.text)


class TestFrontendV4120(unittest.TestCase):
    def test_workshop_home_tabs_and_default_flow(self):
        s = _read("frontend/src/pages/MaterialWorkshop.tsx")
        self.assertIn("ws-modebar", s)
        self.assertIn("默认创作", s)
        self.assertIn("按模板创作", s)
        self.assertIn("template_id: chosenTpl ? chosenTpl.id : null", s)
        self.assertIn("模板只影响图片", s)
        self.assertIn("开始创作", s, "默认流程按钮文案必须保留")

    def test_rights_ui_removed(self):
        s = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertNotIn("rights_status", s)
        self.assertNotIn("补录授权", s)
        self.assertNotIn("授权未声明", s)
        self.assertNotIn("tl-rights-box", s)
        self.assertNotIn("checkRightsGate", s)
        api = _read("frontend/src/api.ts")
        self.assertIn("workshopTemplates", api)
        self.assertNotIn("tlPatchRights", api)


if __name__ == "__main__":
    unittest.main()
