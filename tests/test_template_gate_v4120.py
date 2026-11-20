# -*- coding: utf-8 -*-
"""V4.120 素材工作坊：授权强制闸门 + 按模板创作（模板只影响图片）专项测试。

覆盖：
1. 授权状态归一与闸门判定：granted 且说明完整才放行；unknown / denied / 说明过短拦截
2. 导入闸门：无 rights_status / 授权说明过短 422；denied 仅归档，解构被拦截
3. 补录授权：PATCH 后可进入解构链路；PATCH 模板 golden 也不能塞未授权素材
4. 归并闸门：未授权素材被排除候选；工作坊模板列表逐条标记 usable / reason
5. 按模板创作：不可用模板在付费入队前 422；模板骨架只生成视觉路线，不注入产品事实
6. 前端静态断言：首页 Tab、默认流程保留、授权必填与补录入口
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


class TestRightsGateRulesV4120(unittest.TestCase):
    def test_status_normalize(self):
        import template_gate as tg
        self.assertEqual(tg.normalize_status("GRANTED"), tg.GRANTED)
        self.assertEqual(tg.normalize_status("denied"), tg.DENIED)
        self.assertEqual(tg.normalize_status(None), tg.UNKNOWN)
        self.assertEqual(tg.normalize_status("hacked"), tg.UNKNOWN)

    def test_rights_check_all_paths(self):
        import template_gate as tg
        ok = tg.rights_check(SimpleNamespace(
            rights_status="granted", rights_note="自有素材，已获全球投放授权"))
        self.assertTrue(ok["ok"])
        for st, note in [("granted", "自有"), ("denied", "竞品截图不可投放"),
                         ("unknown", "历史素材"), (None, "")]:
            chk = tg.rights_check(SimpleNamespace(rights_status=st, rights_note=note))
            self.assertFalse(chk["ok"], (st, note))
            self.assertTrue(chk["reason"])
            self.assertTrue(chk["required_action"])

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

    def test_merge_eligibility_rights_gate(self):
        import asset_merge as am
        a = _analysis(1)
        self.assertFalse(am.eligibility(a, "unknown")["eligible"])
        self.assertIn("授权", am.eligibility(a, "denied")["reason"])
        self.assertTrue(am.eligibility(a, "granted")["eligible"])
        items = [{"asset": {"id": 1, "rights_status": "denied", "title": "无授权"},
                  "analysis": a}]
        self.assertEqual(len(am.build_candidates(items)["groups"]), 0)
        self.assertEqual(len(am.build_candidates(items)["excluded"]), 1)


class TestRightsGateApiV4120(unittest.TestCase):
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

    def _add(self, title, status="granted", note="自有素材，已获投放授权"):
        payload = {"title": title, "media_kind": "image", "source_type": "upload",
                   "file": "/files/v4120.png", "platform": "Meta"}
        if status is not None:
            payload.update(rights_status=status, rights_note=note)
        r = self.client.post("/api/template-library/assets", headers=self.auth, json=payload)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_01_import_requires_rights(self):
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "无授权", "media_kind": "image"})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["blocked"], "rights_gate")
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": "说明过短", "media_kind": "image",
                                   "rights_status": "granted", "rights_note": "自有"})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post("/api/template-library/import", headers=self.auth,
                             json={"title": "统一导入无授权", "source_type": "url", "media_kind": "image",
                                   "file": "/files/v4120.png"})
        self.assertEqual(r.status_code, 422, r.text)

    def test_02_denied_archived_but_analyze_blocked(self):
        a = self._add("竞品截图仅归档", "denied", "竞品公开截图，未取得投放授权")
        self.assertEqual(a["rights_status"], "denied")
        r = self.client.post(f"/api/template-library/analyze/{a['id']}", headers=self.auth)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["blocked"], "rights_gate")
        self.__class__.denied_id = a["id"]

    def test_03_patch_rights_unlocks_deconstruct_path(self):
        r = self.client.patch(f"/api/template-library/assets/{self.denied_id}/rights",
                              headers=self.auth,
                              json={"rights_status": "granted", "rights_note": "已取得该竞品素材的全球投放授权"})
        self.assertEqual(r.status_code, 200, r.text)
        # 闸门通过后流程继续到文件检查，而不是继续返回 rights_gate。
        r2 = self.client.post(f"/api/template-library/analyze/{self.denied_id}", headers=self.auth)
        self.assertNotIn("rights_gate", r2.text)
        self.assertIn("文件", r2.text)

    def test_04_candidate_excludes_unauthorized(self):
        a = self._add("未授权素材候选", "denied", "第三方素材，禁止投放")
        r = self.client.post("/api/template-library/analyses", headers=self.auth, json=_analysis(a["id"]))
        self.assertEqual(r.status_code, 200, r.text)
        cand = self.client.get("/api/template-library/merge-candidates", headers=self.auth).json()
        self.assertTrue(any(x["asset_id"] == a["id"] for x in cand["excluded"]),
                        "未授权素材必须被候选排除")
        r = self.client.post("/api/template-library/merge/confirm", headers=self.auth,
                             json={"asset_ids": [a["id"]]})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["blocked"], "rights_gate")

    def test_05_workshop_template_gate(self):
        a = self._add("模板来源素材", "denied", "未获授权，仅归档")
        r = self.client.post("/api/template-library/templates", headers=self.auth, json={
            "name": "闸门测试模板", "primary_category": "前后对比", "purpose": ["转化"],
            "image_skeleton_json": {"composition": "左右分屏"},
            "golden_asset_id": a["id"]})
        self.assertEqual(r.status_code, 422, r.text)
        t = self.client.post("/api/template-library/templates", headers=self.auth, json={
            "name": "闸门测试模板", "primary_category": "前后对比", "purpose": ["转化"],
            "image_skeleton_json": {"composition": "左右分屏"}}).json()
        r = self.client.patch(f"/api/template-library/templates/{t['id']}", headers=self.auth,
                              json={"golden_asset_id": a["id"]})
        self.assertEqual(r.status_code, 422, r.text)
        lst = {x["id"]: x for x in self.client.get("/api/workshop/templates", headers=self.auth).json()}
        self.assertFalse(lst[t["id"]]["usable"])
        self.assertTrue(lst[t["id"]]["reason"])

        # 补录授权后重新绑定 golden，模板恢复可用（同一条模板，不改骨架）。
        self.client.patch(f"/api/template-library/assets/{a['id']}/rights", headers=self.auth,
                          json={"rights_status": "granted",
                                "rights_note": "已取得该素材的全球投放授权"})
        ok = self.client.patch(f"/api/template-library/templates/{t['id']}", headers=self.auth,
                               json={"golden_asset_id": a["id"]})
        self.assertEqual(ok.status_code, 200, ok.text)
        lst = {x["id"]: x for x in self.client.get("/api/workshop/templates", headers=self.auth).json()}
        self.assertTrue(lst[t["id"]]["usable"])

        # 不可用模板在生成接口入队 / 付费调用前直接 422。
        blocked_asset = self._add("按模板创作拦截素材", "denied", "未获授权，仅归档")
        bad = self.client.post("/api/template-library/templates", headers=self.auth, json={
            "name": "不可用模板", "primary_category": "前后对比",
            "image_skeleton_json": {"composition": "上下分层"},
            "merged_asset_ids": [blocked_asset["id"]]}).json()
        lst = {x["id"]: x for x in self.client.get("/api/workshop/templates", headers=self.auth).json()}
        self.assertFalse(lst[bad["id"]]["usable"])
        r = self.client.post("/api/workshop/generate", headers=self.auth,
                             json={"analysis": {"industry": "家居"}, "template_id": bad["id"]})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["blocked"], "template_gate")


class TestFrontendV4120(unittest.TestCase):
    def test_workshop_home_tabs_and_default_flow(self):
        s = _read("frontend/src/pages/MaterialWorkshop.tsx")
        self.assertIn("ws-modebar", s)
        self.assertIn("默认创作", s)
        self.assertIn("按模板创作", s)
        self.assertIn("template_id: chosenTpl ? chosenTpl.id : null", s)
        self.assertIn("模板只影响图片", s)
        self.assertIn("开始创作", s, "默认流程按钮文案必须保留")

    def test_rights_gate_ui(self):
        s = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertIn("rights_status", s)
        self.assertIn("强制闸门", s)
        self.assertIn("补录授权", s)
        self.assertIn("授权未声明", s)
        api = _read("frontend/src/api.ts")
        self.assertIn("workshopTemplates", api)
        self.assertIn("tlPatchRights", api)


if __name__ == "__main__":
    unittest.main()
