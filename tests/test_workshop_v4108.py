"""V4.108 素材工作坊：模型闸门 + 标准库尺寸 + 结果整形回归。

覆盖：
- 输入拆分（整行链接 vs 产品描述）；
- 尺寸只来自素材标准库（含比例标签、spec_id，且不含 logo / banner 等次要规则）；
- 未登记的「平台 + 尺寸」在调用前被拒绝；
- 只用「测试通过」的模型：未配置 / 未测试 / 测试失败一律不 ready；
- 文案回退 Mock、图片回退模板时如实标注，不当成交付物；
- 统一分析进 `LandingAnalysis` 时 channels 字符串被转成结构，且 extra 键被裁掉；
- 新一级菜单、页面、API 方法确实接线。

无模型 / 无网络。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

import workshop  # noqa: E402


class TestWorkshopV4108(unittest.TestCase):

    # ---------- 输入 ----------
    def test_01_split_input(self):
        self.assertEqual(workshop.split_input("https://shop.example.com/p/1"),
                         ("https://shop.example.com/p/1", ""))
        self.assertEqual(workshop.split_input("  https://a.com/x  "), ("https://a.com/x", ""))
        url, text = workshop.split_input("https://a.com/x 这款杯子主打轻便")
        self.assertEqual(url, "")
        self.assertIn("杯子", text)
        self.assertEqual(workshop.split_input("   "), ("", ""))

    # ---------- 尺寸标准库 ----------
    def test_02_options_come_from_spec_library(self):
        opts = {o["platform"]: o for o in workshop.platform_options()}
        self.assertIn("Meta", opts)
        meta = {s["size"]: s for s in opts["Meta"]["sizes"]}
        self.assertIn("1080x1080", meta)
        self.assertEqual(meta["1080x1080"]["aspect"], "1:1")
        self.assertEqual(meta["1080x1080"]["label"], "1:1 · 1080×1080")
        self.assertTrue(meta["1080x1080"]["spec_id"], "尺寸必须带标准库 spec_id")
        # 4:5 与 9:16 的比例标签按最大公约数算，不做近似
        self.assertIn("1080x1350", meta)
        self.assertEqual(meta["1080x1350"]["aspect"], "4:5")
        # 只保留主素材类规则：Google 的 logo 位（1200x300）与展示横幅不进工作坊
        google = {s["size"] for s in opts["Google"]["sizes"]}
        self.assertNotIn("1200x300", google)
        self.assertNotIn("300x250", google)

    def test_03_resolve_targets_rejects_unknown(self):
        rows = [{"platform": "Meta", "sizes": ["1080x1080", "1080x1080", "999x999"]},
                {"platform": "NoSuchMedia", "sizes": ["1080x1080"]}]
        targets, errors = workshop.resolve_targets(rows)
        self.assertEqual(len(targets), 1, "重复尺寸去重后只留一条")
        self.assertEqual(targets[0]["size"], "1080x1080")
        self.assertTrue(any("999x999" in e for e in errors))
        self.assertTrue(any("NoSuchMedia" in e for e in errors))

    def test_04_group_targets_keeps_order(self):
        targets, _ = workshop.resolve_targets([
            {"platform": "TikTok", "sizes": ["720x1280"]},
            {"platform": "Meta", "sizes": ["1080x1080", "1080x1350"]},
        ])
        grouped = workshop.group_targets(targets)
        self.assertEqual(list(grouped.keys()), ["TikTok", "Meta"])
        self.assertEqual([t["size"] for t in grouped["Meta"]], ["1080x1080", "1080x1350"])

    # ---------- 模型闸门 ----------
    def test_05_model_status_requires_passed_test(self):
        from database import SessionLocal
        from migrations import ensure_schema
        from models import ModelConfig

        ensure_schema()
        db = SessionLocal()
        saved = [(r.id, r.is_active, r.last_test_ok) for r in db.query(ModelConfig).all()]
        made = None
        try:
            for r in db.query(ModelConfig).all():
                r.is_active = False
            db.commit()
            st = workshop.model_status(db)
            self.assertFalse(st["ready"], "没有任何启用配置时不能 ready")
            self.assertEqual(set(st["missing"]), {"分析模型", "文案模型", "图片模型"})

            cfg = ModelConfig(name="ws-analysis", usage="analysis", usages=["analysis"],
                              provider="openai", api_key="sk-test",
                              base_url="http://127.0.0.1:1/v1", model="test-model",
                              is_active=True, last_test_ok=None)
            db.add(cfg); db.commit(); db.refresh(cfg); made = cfg.id
            item = [i for i in workshop.model_status(db)["items"] if i["usage"] == "analysis"][0]
            self.assertFalse(item["ready"])
            self.assertEqual(item["reason"], "尚未测试通过")

            cfg.last_test_ok = False; db.commit()
            self.assertFalse([i for i in workshop.model_status(db)["items"]
                              if i["usage"] == "analysis"][0]["ready"])

            cfg.last_test_ok = True; db.commit()
            item = [i for i in workshop.model_status(db)["items"] if i["usage"] == "analysis"][0]
            self.assertTrue(item["ready"])
            self.assertEqual(item["model"], "test-model")
            self.assertEqual(workshop.missing_models(db, ["analysis"]), [])
            self.assertTrue(workshop.missing_models(db, ["copy", "image"]))
        finally:
            if made:
                row = db.query(ModelConfig).filter_by(id=made).first()
                if row:
                    db.delete(row)
            for mid, active, ok in saved:
                row = db.query(ModelConfig).filter_by(id=mid).first()
                if row:
                    row.is_active = active; row.last_test_ok = ok
            db.commit(); db.close()

    # ---------- 结果整形 ----------
    def test_06_copy_view_marks_mock_as_failed(self):
        schema = [{"key": "primary_text", "label": "正文", "max": 125, "count": 1},
                  {"key": "headline", "label": "广告标题", "max": 40, "count": 3}]
        ok = workshop.copy_view("Meta", {
            "schema": schema,
            "fields": {"primary_text": ["买一只好用的杯子"], "headline": ["轻 350g", "通勤不洒"]},
            "model_info": {"source": "llm", "fallback": False, "model": "m1"},
            "validation": {"problem_count": 0},
        })
        self.assertEqual(ok["status"], "ok")
        self.assertEqual([r["key"] for r in ok["rows"]], ["primary_text", "headline"])
        self.assertEqual(ok["rows"][1]["values"], ["轻 350g", "通勤不洒"])
        self.assertIn("广告标题：", ok["text"])

        bad = workshop.copy_view("Meta", {
            "schema": schema, "fields": {"headline": ["MOCK 标题"]},
            "model_info": {"source": "mock", "fallback": True},
        })
        self.assertEqual(bad["status"], "failed")
        self.assertIn("模拟", bad["reason"])

    def test_07_overlay_variant_uses_first_values(self):
        v = workshop.overlay_variant({
            "platform": "Meta", "brand": "Acme",
            "fields": {"headline": ["A", "B"], "primary_text": ["正文一", "正文二"],
                       "cta": ["Shop Now"]},
        }, {})
        self.assertEqual(v["headline"], "A")
        self.assertEqual(v["sub"], "正文一")
        self.assertEqual(v["cta"], "Shop Now")
        self.assertEqual(v["brand"], "Acme")

    def test_08_landing_payload_fixes_channels(self):
        payload = workshop.landing_payload({
            "title": "通勤杯", "channels": ["Meta", "Google"],
            "advantages": ["350mL", "7cm 直径"],
            "boxes": {"should": "drop"}, "snapshot": {"source": "real_fetch"},
        })
        self.assertEqual(payload["channels"],
                         [{"platform": "Meta", "reason": ""},
                          {"platform": "Google", "reason": ""}])
        self.assertNotIn("boxes", payload, "未声明字段不应进入出图任务")
        self.assertNotIn("snapshot", payload)
        from schemas import LandingAnalysis
        LandingAnalysis(**payload)   # 构造不抛错 = 可用于 MediaImageRequest

    def test_09_image_view_labels_and_fallback(self):
        ok = workshop.image_view({"url": "/files/a.png", "file": "a.png", "size": "1080x1350",
                                  "status": "ok", "ai_background": True, "w": 1080, "h": 1350})
        self.assertEqual(ok["label"], "4:5 · 1080×1350")
        self.assertFalse(ok["fallback"])
        fb = workshop.image_view({"url": "/files/b.png", "file": "b.png", "size": "1080x1080",
                                  "status": "fallback", "ai_background": False,
                                  "fallback_reason": "供应商超时"})
        self.assertTrue(fb["fallback"])
        self.assertEqual(fb["fallback_reason"], "供应商超时")

    # ---------- 接线 ----------
    def test_10_routes_and_frontend_wired(self):
        import routers
        paths = {r.path for r in routers.router.routes}
        for p in ("/api/workshop/options", "/api/workshop/analyze", "/api/workshop/generate"):
            self.assertIn(p, paths)

        app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("MaterialWorkshop", app)
        self.assertIn("GROUP_WORKSHOP", app)
        self.assertIn("'workshop'", app)

        page = (FRONTEND / "pages" / "MaterialWorkshop.tsx").read_text(encoding="utf-8")
        self.assertIn("api.workshopOptions", page)
        self.assertIn("api.workshopAnalyze", page)
        self.assertIn("api.workshopGenerate", page)
        self.assertIn("图片素材", page)
        self.assertIn("文案素材", page)
        self.assertIn("预览", page)
        self.assertIn("下载", page)

        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("/api/workshop/options", api)
        self.assertIn("/api/workshop/analyze", api)
        self.assertIn("/api/workshop/generate", api)



    # ---------- 接口串联 ----------
    def test_11_endpoint_creates_job_with_spec_id(self):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import GenerationJob, ModelConfig, User
        import job_service
        import routers

        ensure_schema()
        db = SessionLocal()
        saved = [(r.id, r.is_active, r.last_test_ok) for r in db.query(ModelConfig).all()]
        made_cfg: list[int] = []
        orig_copy = routers.generate_media_copy
        orig_spawn = job_service.spawn_job
        try:
            for r in db.query(ModelConfig).all():
                r.is_active = False
            db.commit()
            for usage in ("analysis", "copy", "image"):
                cfg = ModelConfig(name=f"ws-{usage}", usage=usage, usages=[usage],
                                  provider="openai", api_key="sk-test",
                                  base_url="http://127.0.0.1:1/v1", model="test-model",
                                  is_active=True, last_test_ok=True)
                db.add(cfg); db.commit(); db.refresh(cfg); made_cfg.append(cfg.id)

            user = db.query(User).filter_by(username="wstest").first()
            if not user:
                h, salt = hash_password("TestPwd123")
                db.add(User(username="wstest", email="wstest@example.com", display_name="WS",
                            role="admin", password_hash=h, salt=salt, active=True))
                db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login",
                                json={"email": "wstest@example.com", "password": "TestPwd123"})
            auth = {"Authorization": f"Bearer {login.json()['token']}"}

            opts = client.get("/api/workshop/options", headers=auth)
            self.assertEqual(opts.status_code, 200, opts.text)
            self.assertTrue(opts.json()["models"]["ready"])

            demo = client.post("/api/workshop/analyze", headers=auth, json={
                "input": "https://soundora.com/products/air-pro", "platforms": ["Meta"],
                "demo_mode": True,
                # 创作意图必须一路带到出图任务：落地页分析 → 图片提示词
                "intent_text": "面向通勤上班族，不要出现价格数字"})
            self.assertEqual(demo.status_code, 200, demo.text)
            analysis = demo.json()["analysis"]
            self.assertEqual(demo.json()["source"], "demo")

            async def fake_copy(db_, analysis_, platform, lang="en", **kw):
                return {"platform": platform, "brand": "Demo",
                        "schema": [{"key": "headline", "label": "广告标题", "max": 40, "count": 1},
                                   {"key": "primary_text", "label": "正文", "max": 125, "count": 1},
                                   {"key": "cta", "label": "CTA", "max": 24, "count": 1}],
                        "fields": {"headline": ["H1"], "primary_text": ["Body"], "cta": ["Shop Now"]},
                        "model_info": {"source": "llm", "fallback": False, "model": "test-model"},
                        "validation": {"problem_count": 0}}

            routers.generate_media_copy = fake_copy
            job_service.spawn_job = lambda jid: None

            gen = client.post("/api/workshop/generate", headers=auth, json={
                "analysis": analysis,
                "targets": [{"platform": "Meta", "sizes": ["1080x1080", "1080x1350"]}]})
            self.assertEqual(gen.status_code, 200, gen.text)
            body = gen.json()
            self.assertEqual(body["copies"][0]["status"], "ok")
            self.assertEqual(len(body["image_jobs"]), 1)
            self.assertEqual(body["image_jobs"][0]["sizes"][0]["label"], "1:1 · 1080×1080")

            row = db.query(GenerationJob).filter_by(job_id=body["image_jobs"][0]["job_id"]).first()
            self.assertIsNotNone(row)
            req = (row.request_json or {}).get("images_request") or {}
            self.assertEqual([s["size"] for s in req["slots"]], ["1080x1080", "1080x1350"])
            self.assertTrue(req["slots"][0]["spec_id"], "出图任务必须携带标准库 spec_id")
            intent = req["analysis"].get("creative_intent") or {}
            self.assertTrue(intent.get("audience"), "创作意图必须随任务落库（V4.108 修复 Pydantic 裁剪）")
            self.assertIn("通勤上班族", "".join(intent.get("audience") or []))
            self.assertTrue(intent.get("avoid"), "禁止项必须保留，供图片提示词逐条排除")
            self.assertEqual(row.status, "queued", "未就绪前的替身不应真正开跑")

            # 未选尺寸直接 400，不进付费链路
            bad = client.post("/api/workshop/generate", headers=auth,
                              json={"analysis": analysis, "targets": []})
            self.assertEqual(bad.status_code, 400)
        finally:
            routers.generate_media_copy = orig_copy
            job_service.spawn_job = orig_spawn
            for mid in made_cfg:
                row = db.query(ModelConfig).filter_by(id=mid).first()
                if row:
                    db.delete(row)
            for mid, active, ok in saved:
                row = db.query(ModelConfig).filter_by(id=mid).first()
                if row:
                    row.is_active = active; row.last_test_ok = ok
            db.commit(); db.close()

    def test_12_copy_only_when_image_model_missing(self):
        """图片模型未就绪：只出文案并明确标注，不阻断、不假装出图。"""
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import GenerationJob, ModelConfig, User
        import job_service
        import routers

        ensure_schema()
        db = SessionLocal()
        saved = [(r.id, r.is_active, r.last_test_ok) for r in db.query(ModelConfig).all()]
        made: list[int] = []
        orig_copy = routers.generate_media_copy
        orig_spawn = job_service.spawn_job
        try:
            for r in db.query(ModelConfig).all():
                r.is_active = False
            db.commit()
            for usage in ("analysis", "copy"):
                cfg = ModelConfig(name=f"ws2-{usage}", usage=usage, usages=[usage],
                                  provider="openai", api_key="sk-test",
                                  base_url="http://127.0.0.1:1/v1", model="test-model",
                                  is_active=True, last_test_ok=True)
                db.add(cfg); db.commit(); db.refresh(cfg); made.append(cfg.id)
            if not db.query(User).filter_by(username="wstest").first():
                h, salt = hash_password("TestPwd123")
                db.add(User(username="wstest", email="wstest@example.com", display_name="WS",
                            role="admin", password_hash=h, salt=salt, active=True))
                db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login",
                                json={"email": "wstest@example.com", "password": "TestPwd123"})
            auth = {"Authorization": f"Bearer {login.json()['token']}"}
            demo = client.post("/api/workshop/analyze", headers=auth, json={
                "input": "一款通勤保温杯", "platforms": ["Meta"], "demo_mode": True})
            self.assertEqual(demo.status_code, 200, demo.text)

            async def fake_copy(db_, analysis_, platform, lang="en", **kw):
                return {"platform": platform, "brand": "Demo",
                        "schema": [{"key": "headline", "label": "广告标题", "max": 40, "count": 1}],
                        "fields": {"headline": ["H1"]},
                        "model_info": {"source": "llm", "fallback": False},
                        "validation": {"problem_count": 0}}

            routers.generate_media_copy = fake_copy
            job_service.spawn_job = lambda jid: None
            before = db.query(GenerationJob).count()

            gen = client.post("/api/workshop/generate", headers=auth, json={
                "analysis": demo.json()["analysis"],
                "targets": [{"platform": "Meta", "sizes": []}]})
            self.assertEqual(gen.status_code, 200, gen.text)
            body = gen.json()
            self.assertTrue(body["images_skipped"])
            self.assertEqual(body["image_jobs"], [], "图片模型缺失时不得创建出图任务")
            self.assertEqual(len(body["copies"]), 1)
            self.assertTrue(any("图片模型未就绪" in w for w in body["warnings"]))
            self.assertEqual(db.query(GenerationJob).count(), before, "不得产生任何出图任务")
        finally:
            routers.generate_media_copy = orig_copy
            job_service.spawn_job = orig_spawn
            for mid in made:
                row = db.query(ModelConfig).filter_by(id=mid).first()
                if row:
                    db.delete(row)
            for mid, active, ok in saved:
                row = db.query(ModelConfig).filter_by(id=mid).first()
                if row:
                    row.is_active = active; row.last_test_ok = ok
            db.commit(); db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
