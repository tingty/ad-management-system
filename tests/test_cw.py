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
from models import User, GenerationJob, CwLibrary
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

    def test_08_copy_generated_per_platform(self):
        # B3 / P0#4：文案生成必须返回非空 fields（修复「文案为空」）
        a = self.client.post("/api/cw/analyze",
                             json={"url": "https://x.com/p", "platforms": ["Meta"], "demo_mode": True},
                             headers=self.auth).json()
        analysis = a.get("analysis") or {}
        # 前端 normalizeAnalysis 会把 channels 由平台名字符串转成 [{platform, reason}]
        analysis = {**analysis, "channels": [{"platform": p, "reason": ""}
                                            for p in (analysis.get("recommendedPlatforms") or ["Facebook", "Google"])]}
        r = self.client.post("/api/media-campaign/copy",
                             json={"analysis": analysis, "platform": "Facebook", "lang": "en"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsInstance(d.get("fields"), dict, "文案必须为字典")
        non_empty = [v for v in (d.get("fields") or {}).values() if v]
        self.assertTrue(len(non_empty) > 0, "文案 fields 不应全空（P0#4：文案为空）")
        self.assertIsInstance(d.get("model_info"), dict)

    def test_09_generation_job_carries_copy_and_reference(self):
        # B3：生成任务的 images_request 必须携带 copy_variants 与 style_opts.reference_image
        a = self.client.post("/api/cw/analyze",
                             json={"url": "https://x.com/p", "platforms": ["Meta"], "demo_mode": True},
                             headers=self.auth).json()
        analysis = a.get("analysis") or {}
        # 前端 normalizeAnalysis：channels 平台名字符串 → [{platform, reason}]
        analysis = {**analysis, "channels": [{"platform": p, "reason": ""}
                                            for p in (analysis.get("recommendedPlatforms") or ["Meta", "Google"])]}
        copy = self.client.post("/api/media-campaign/copy",
                                json={"analysis": analysis, "platform": "Meta", "lang": "en"},
                                headers=self.auth).json()
        fields = copy.get("fields") or {}
        first = lambda v: (v[0] if isinstance(v, list) else v) or ""
        variant = {"headline": str(first(fields.get("headline") or fields.get("title"))),
                   "sub": str(first(fields.get("description") or fields.get("body") or fields.get("primary_text"))),
                   "cta": str(first(fields.get("cta"))),
                   "brand": str(first(copy.get("brand"))), "label": "Meta"}
        payload = {
            "images_request": {
                "analysis": analysis, "platform": "Meta", "lang": "en",
                "copy_fields": {}, "copy_variants": [variant],
                "style_opts": {"creative_direction": "D01", "reference_image": "/files/ref_test.png"},
                "slots": [{"size": "1080x1080", "placement": "Meta"}],
                "spec_version": "", "total_pixels": 1080 * 1080,
            },
            "idempotency_key": "cw_b3_test_1",
        }
        r = self.client.post("/api/generation-jobs", json=payload, headers=self.auth)
        self.assertEqual(r.status_code, 202, r.text)
        job_id = r.json().get("job_id")
        self.assertIsNotNone(job_id)
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter_by(job_id=job_id).first()
            self.assertIsNotNone(job, "生成任务必须落库")
            req = job.request_json or {}
            ir = req.get("images_request") or {}
            self.assertEqual(len(ir.get("copy_variants") or []), 1, "images_request 必须携带 copy_variants")
            self.assertEqual((ir.get("style_opts") or {}).get("reference_image"), "/files/ref_test.png",
                             "参考图必须透传到 style_opts.reference_image")
        finally:
            db.close()

    def test_10_fetch_url_validates(self):
        # B3：非 http(s) 的参考图 URL 必须 400 拒绝（不静默通过）
        r = self.client.post("/api/assets/fetch-url", json={"url": "ftp://example.com/x.png"}, headers=self.auth)
        self.assertEqual(r.status_code, 400, r.text)
        r2 = self.client.post("/api/assets/fetch-url", json={"url": "just-text"}, headers=self.auth)
        self.assertEqual(r2.status_code, 400, r2.text)

    def test_11_pasted_analyze_sinks_product(self):
        # V4.61 / B4：粘贴文本分析（source=pasted）后，产品快照自动沉淀进素材库
        text = "一款面向跑步爱好者的智能运动手环，主打心率监测与长续航。"
        r = self.client.post("/api/cw/analyze",
                             json={"text": text, "platforms": ["Meta"]}, headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d.get("source"), "pasted")
        plan_id = d.get("id")
        self.assertIsNotNone(plan_id)
        # 产品应自动沉淀（去重键 source_plan_id）
        r2 = self.client.get("/api/cw/library?kind=product", headers=self.auth)
        self.assertEqual(r2.status_code, 200, r2.text)
        items = r2.json()
        self.assertIsInstance(items, list)
        self.assertTrue(any(it.get("kind") == "product" and it.get("title") for it in items),
                        "粘贴文本分析后应在素材库沉淀至少一条产品")
        # 同一方案只应沉淀一条产品（去重，避免重复分析刷屏）
        db = SessionLocal()
        try:
            cnt = db.query(CwLibrary).filter_by(kind="product", source_plan_id=plan_id).count()
            self.assertEqual(cnt, 1, "同一方案只应沉淀一条产品")
        finally:
            db.close()

    def test_12_reference_library_add_and_reuse(self):
        # V4.61 / B4：参考图可沉淀进素材库，且新会话（GET）可读到并复用
        add = self.client.post("/api/cw/library",
                               json={"kind": "reference", "title": "品牌Logo", "file": "/files/ref_reuse_test.png"},
                               headers=self.auth)
        self.assertEqual(add.status_code, 200, add.text)
        rid = add.json().get("id")
        self.assertIsNotNone(rid)
        # 去重：同一 file 再次提交应命中同一条（upsert）
        add2 = self.client.post("/api/cw/library",
                                json={"kind": "reference", "title": "品牌Logo2", "file": "/files/ref_reuse_test.png"},
                                headers=self.auth)
        self.assertEqual(add2.status_code, 200, add2.text)
        self.assertEqual(add2.json().get("id"), rid, "同一文件应去重 upsert 到同一条")
        # 新会话可读取并复用
        lst = self.client.get("/api/cw/library?kind=reference", headers=self.auth)
        self.assertEqual(lst.status_code, 200)
        ids = [it["id"] for it in lst.json()]
        self.assertIn(rid, ids)
        # 校验：kind 非法应 400；reference 缺 file 应 400
        bad = self.client.post("/api/cw/library", json={"kind": "video", "title": "x"}, headers=self.auth)
        self.assertEqual(bad.status_code, 400, bad.text)
        nofile = self.client.post("/api/cw/library", json={"kind": "reference", "title": "x"}, headers=self.auth)
        self.assertEqual(nofile.status_code, 400, nofile.text)

    def test_13_library_delete_owner_scoped(self):
        # V4.61 / B4：删除自己的素材；未登录 401，删除后再次删除 404
        add = self.client.post("/api/cw/library",
                               json={"kind": "brand", "title": "AcmeBrand"}, headers=self.auth)
        self.assertEqual(add.status_code, 200, add.text)
        bid = add.json().get("id")
        self.assertIsNotNone(bid)
        noauth = self.client.delete(f"/api/cw/library/{bid}")
        self.assertEqual(noauth.status_code, 401)
        delr = self.client.delete(f"/api/cw/library/{bid}", headers=self.auth)
        self.assertEqual(delr.status_code, 200, delr.text)
        again = self.client.delete(f"/api/cw/library/{bid}", headers=self.auth)
        self.assertEqual(again.status_code, 404, again.text)

    def test_14_export_zip_has_copy_csv_and_delivery_notes(self):
        # V4.62 / B5：历史导出包应含结构化交付物 ad_copy.csv 与 delivery_notes.md，且文案字段正确提取。
        import io as _io
        import zipfile as _zf
        import datetime as _dt
        import types as _types
        from creation_history import build_history_zip
        row = _types.SimpleNamespace(
            id=1, title="测试品牌 Acme", url="https://acme.example.com/p", image_count=1,
            platform="Meta", lang="en",
            images_json=[{"file": "x.png", "placement": "feed", "size": "1080x1080"}],
            copy_json={
                "platform_copies": {"Meta": {"fields": {"headline": "H1", "sub": "S1", "cta": "Buy"}, "brand": "Acme"}},
                "copy_variants": [{"label": "组合A", "headline": "H2", "sub": "S2", "cta": "Shop", "brand": "Acme"}],
            },
            analysis_json={
                "snapshot": {"source": "real_fetch", "title": "测试品牌 Acme",
                             "fetched_at": "2026-01-01 10:00", "fetch_quality": "high"},
                "model_info": {"provider": "openai", "model": "gpt-4o"},
            },
            style_opts_json={}, image_model_json={}, note="", owner_name="tester",
            created_at=_dt.datetime(2026, 1, 1), updated_at=_dt.datetime(2026, 1, 1),
        )
        buf = build_history_zip([row], multi=False)
        self.assertIsInstance(buf, _io.BytesIO)
        with _zf.ZipFile(buf) as z:
            names = z.namelist()
            self.assertIn("ad_copy.csv", names, names)
            self.assertIn("delivery_notes.md", names, names)
            csv_text = z.read("ad_copy.csv").decode("utf-8-sig")
            self.assertIn("平台", csv_text)
            self.assertIn("Meta", csv_text)
            self.assertIn("Acme", csv_text)
            self.assertIn("H1", csv_text)
            md_text = z.read("delivery_notes.md").decode("utf-8")
            self.assertIn("交付说明", md_text)
            self.assertIn("测试品牌 Acme", md_text)
            self.assertIn("gpt-4o", md_text)


if __name__ == "__main__":
    import unittest
    unittest.main()
