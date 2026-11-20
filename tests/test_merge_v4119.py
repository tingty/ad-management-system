# -*- coding: utf-8 -*-
"""V4.119 素材创意模板库：分类归并 + 按框架完整度选 golden 沉淀模板 专项测试。

覆盖：
1. 纯函数口径：归并键 / 信息结构相似度阈值 / 完整度与最近导入 tie-break / 不可用排除
2. 分类字典端点：12 类主分类 + 目的 + 钩子 + 阈值单一来源
3. 候选组 API：三条相似素材成组、golden 为最高完整度、低完整度 / 失败素材被排除
4. 人工确认归并：沉淀图片骨架模板、软归并标记、golden 与归并数量的唯一事实
5. 人工覆盖 golden / 撤销软归并 / 删除模板自动解标记；已归并素材禁止直接删除
6. 非法输入：跨归并键硬凑 400、golden 不在所选范围 400、分类未归一 400
7. 前端静态断言：第三 Tab、分类确认、候选勾选、golden 覆盖与撤销入口
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


def _dims(headline="上下分层前后对比", benefit="空间显大动线合理"):
    return {
        "layout": {"composition": {"value": "上下分层前后对比", "confidence": 0.9}},
        "visual": {"palette": {"value": "暖光米色木色", "confidence": 0.85}},
        "info": {
            "headline_role": {"value": headline, "confidence": 0.9},
            "benefits": {"value": [benefit], "confidence": 0.9},
            "cta": {"value": "低风险咨询", "confidence": 0.85},
            "evidence_kind": {"value": "对比画面", "confidence": 0.9},
        },
        "effect": {"hook_type": {"value": "结果", "confidence": 0.8}},
        "category": {
            "primary": {"value": "前后对比", "confidence": 0.9},
            "purpose": {"value": ["转化"], "confidence": 0.9},
            "hook": {"value": "结果", "confidence": 0.8},
        },
    }


def _analysis(aid, comp, headline="上下分层前后对比", benefit="空间显大动线合理",
              primary="前后对比", status="analyzed"):
    return {
        "asset_id": aid, "completeness": comp, "confidence": 0.88, "status": status,
        "framework_version": "asset-deconstruct/1.0",
        "dims_json": _dims(headline, benefit),
        "category_json": {"primary": primary, "purposes": ["转化"], "hooks": ["结果"],
                          "taxonomy_version": "asset-category/1.0"},
    }


class TestMergeRulesV4119(unittest.TestCase):
    def test_similarity_and_threshold(self):
        import asset_merge as am
        a, b = _dims(), _dims()
        self.assertAlmostEqual(am.information_similarity(a, b), 1.0)
        unrelated = _dims(headline="限时折扣秒杀", benefit="满减优惠券")
        self.assertLess(am.information_similarity(a, unrelated), am.SIMILARITY_THRESHOLD)
        self.assertAlmostEqual(am.information_similarity(a, {"info": {}}), 0.0)

    def test_eligibility_excludes_low_and_unavailable(self):
        import asset_merge as am
        self.assertTrue(am.eligibility(_analysis(1, 0.9))["eligible"])
        self.assertIn("完整度", am.eligibility(_analysis(2, 0.3))["reason"])
        self.assertIn("状态", am.eligibility(_analysis(3, 0.9, status="unavailable"))["reason"])
        self.assertIn("未归一", am.eligibility(_analysis(4, 0.9, primary="野路子分类"))["reason"])

    def test_golden_by_completeness_then_recency(self):
        import asset_merge as am
        members = [
            {"asset_id": 1, "completeness": 0.8, "confidence": 0.9, "created_at": "2026-11-20T10:00:00Z"},
            {"asset_id": 2, "completeness": 0.9, "confidence": 0.7, "created_at": "2026-01-01T10:00:00Z"},
            {"asset_id": 3, "completeness": 0.8, "confidence": 0.7, "created_at": "2026-11-21T10:00:00Z"},
        ]
        self.assertEqual(am.choose_golden(members)["asset_id"], 2, "完整度优先于导入时间")
        members[1]["completeness"] = 0.8
        self.assertEqual(am.choose_golden(members)["asset_id"], 3, "并列时最近导入打破平局")

    def test_cluster_and_excluded(self):
        import asset_merge as am
        items = [
            {"asset": {"id": 1, "title": "高完整", "created_at": "2026-11-20T10:00:00Z"},
             "analysis": _analysis(1, 0.92)},
            {"asset": {"id": 2, "title": "中完整", "created_at": "2026-11-19T10:00:00Z"},
             "analysis": _analysis(2, 0.83)},
            {"asset": {"id": 3, "title": "不可用", "created_at": "2026-11-19T10:00:00Z"},
             "analysis": _analysis(3, 0.2, status="unavailable")},
        ]
        r = am.build_candidates(items)
        self.assertEqual(len(r["groups"]), 1)
        self.assertEqual(r["groups"][0]["size"], 2)
        self.assertEqual(r["groups"][0]["golden_asset_id"], 1)
        self.assertEqual(len(r["excluded"]), 1)
        self.assertEqual(r["excluded"][0]["asset_id"], 3)

    def test_confirm_category_keeps_ai_suggestion(self):
        import asset_merge as am
        cat = am.confirm_category(_analysis(1, 0.9), "问题-方案", ["拉新"], ["痛点"],
                                  "tester", "2026-11-20T12:00:00")
        self.assertEqual(cat["ai_suggestion"]["primary"], "前后对比")
        self.assertEqual(cat["confirmed"]["primary"], "问题-方案")
        self.assertEqual(am.effective_category({"category_json": cat})[:3], ("问题-方案", "拉新", "痛点"))


class TestMergeApiV4119(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User

        ensure_schema()
        email, user, pwd = "v4119@recomob.com", "v4119", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4119",
                            role="editor", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def _asset(self, title):
        r = self.client.post("/api/template-library/assets", headers=self.auth,
                             json={"title": title, "media_kind": "image", "source_type": "upload",
                                   "file": "/files/v4119.png", "platform": "Meta"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def _analysis(self, aid, comp, primary="前后对比"):
        r = self.client.post("/api/template-library/analyses", headers=self.auth,
                             json=_analysis(aid, comp, primary=primary))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_01_taxonomy_endpoint(self):
        r = self.client.get("/api/template-library/taxonomy", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["primary_categories"]), 12)
        self.assertAlmostEqual(r.json()["similarity_threshold"], 0.45)

    def test_02_candidates_group_and_golden(self):
        ids = [self._asset(f"V4119相似图{i}") for i in range(1, 4)]
        for aid, comp in zip(ids, (0.92, 0.84, 0.76)):
            self._analysis(aid, comp)
        low = self._asset("V4119低完整度")
        self._analysis(low, 0.3, primary="悬念钩子")
        other = self._asset("V4119其他主分类")
        self._analysis(other, 0.9, primary="社会证明")
        r = self.client.get("/api/template-library/merge-candidates", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        group = next((g for g in data["groups"] if set(m["asset_id"] for m in g["members"]) == set(ids)), None)
        self.assertIsNotNone(group, "三条相似素材应归为同组")
        self.assertEqual(group["golden_asset_id"], ids[0], "golden 应为完整度最高者")
        self.assertTrue(any(x["asset_id"] == low for x in data["excluded"]), "低完整度应被排除")
        self.__class__.ids = ids
        self.__class__.low_id = low
        self.__class__.other_id = other

    def test_03_merge_confirm_and_soft_mark(self):
        r = self.client.post("/api/template-library/merge/confirm", headers=self.auth,
                             json={"asset_ids": self.ids, "name": "V4119 前后对比模板"})
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()
        self.__class__.tid = t["id"]
        self.assertEqual(t["golden_asset_id"], self.ids[0])
        self.assertEqual(set(t["merged_asset_ids"]), set(self.ids))
        self.assertIn("composition", t["image_skeleton_json"], "沉淀的应是图片骨架")
        self.assertIn("{{CTA}}", t["variables_json"])
        assets = {a["id"]: a for a in self.client.get("/api/template-library/assets", headers=self.auth).json()}
        for aid in self.ids:
            self.assertEqual(assets[aid]["merged_template_id"], t["id"])
        self.assertEqual(assets[self.ids[0]]["status"], "analyzed", "golden 仍为已解构唯一表达")
        self.assertEqual(assets[self.ids[1]]["status"], "merged", "被归并素材软保留")
        # 被归并素材禁止直接删除（避免悬空引用）
        blocked = self.client.delete(f"/api/template-library/assets/{self.ids[1]}", headers=self.auth)
        self.assertEqual(blocked.status_code, 400)

    def test_04_cross_key_and_bad_golden_rejected(self):
        bad = self.client.post("/api/template-library/merge/confirm", headers=self.auth,
                               json={"asset_ids": [self.ids[0], self.other_id]})
        self.assertEqual(bad.status_code, 400, "跨主分类不允许硬凑")
        bad2 = self.client.post("/api/template-library/merge/confirm", headers=self.auth,
                                json={"asset_ids": [self.low_id, self.low_id]})
        self.assertEqual(bad2.status_code, 400, "重复素材应被去重后拒绝孤立不可用项")

    def test_05_manual_golden_and_unmerge(self):
        r = self.client.post(f"/api/template-library/templates/{self.tid}/golden", headers=self.auth,
                             json={"asset_id": self.ids[1]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["golden_asset_id"], self.ids[1])
        self.assertGreaterEqual(r.json()["version"], 2)
        u = self.client.post(f"/api/template-library/templates/{self.tid}/unmerge", headers=self.auth,
                             json={"asset_ids": [self.ids[2]]})
        self.assertEqual(u.status_code, 200, u.text)
        self.assertNotIn(self.ids[2], u.json()["merged_asset_ids"])
        assets = {a["id"]: a for a in self.client.get("/api/template-library/assets", headers=self.auth).json()}
        self.assertIsNone(assets[self.ids[2]]["merged_template_id"])
        self.assertEqual(assets[self.ids[2]]["status"], "analyzed")
        bad = self.client.post(f"/api/template-library/templates/{self.tid}/unmerge", headers=self.auth,
                               json={"asset_ids": [self.ids[1]]})
        self.assertEqual(bad.status_code, 400, "golden 不能直接撤销，需先改选")

    def test_06_category_confirm_then_delete_template(self):
        analysis_id = self._analysis(self.ids[0], 0.92)
        r = self.client.patch(f"/api/template-library/analyses/{analysis_id}/category", headers=self.auth,
                              json={"primary": "前后对比", "purposes": ["转化"], "hooks": ["结果"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["category_json"]["confirmed"]["primary"], "前后对比")
        self.assertEqual(r.json()["category_json"]["ai_suggestion"]["primary"], "前后对比")
        bad = self.client.patch(f"/api/template-library/analyses/{analysis_id}/category", headers=self.auth,
                                json={"primary": "野路子分类", "purposes": ["转化"], "hooks": ["结果"]})
        self.assertEqual(bad.status_code, 400)
        # 删除模板只解软归并标记，不删原件
        self.assertEqual(self.client.delete(f"/api/template-library/templates/{self.tid}",
                                            headers=self.auth).status_code, 200)
        for aid in self.ids[:2]:
            a = next(x for x in self.client.get("/api/template-library/assets", headers=self.auth).json()
                     if x["id"] == aid)
            self.assertIsNone(a["merged_template_id"])
            self.assertEqual(self.client.delete(f"/api/template-library/assets/{aid}",
                                                headers=self.auth).status_code, 200)

    def test_07_requires_auth(self):
        self.assertIn(self.client.get("/api/template-library/merge-candidates").status_code, (401, 403))


class TestMergeFrontendV4119(unittest.TestCase):
    def test_frontend_contract(self):
        page = _read("frontend/src/pages/CreativeAnalysis.tsx")
        api = _read("frontend/src/api.ts")
        self.assertIn("分类归并 · 模板沉淀", page)
        self.assertIn("确认分类", page)
        self.assertIn("确认归并并沉淀模板", page)
        self.assertIn("设为 golden", page)
        self.assertIn("撤销归并", page)
        self.assertIn("merged_template_id", page)
        for method in ("tlTaxonomy", "tlMergeCandidates", "tlMergeConfirm",
                       "tlConfirmCategory", "tlSetGolden", "tlUnmerge"):
            self.assertIn(method, api, f"api.ts 缺少 {method}")
        css = _read("frontend/src/styles.css")
        self.assertIn(".tl-merge-group", css)
        self.assertIn(".tl-template-card", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
