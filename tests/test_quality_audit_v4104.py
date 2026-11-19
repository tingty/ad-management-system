"""V4.104 / 方案E：图片质检扩展 + 系统设置开关回归。

- image_content_guard 保留旧字段（ok/verdict），新增 quality_status + checks；
  缺扩展结论标 unverified，不冒充通过；blank 仍硬拦截。
- audit_image_quality 无视觉配置 → unavailable，不走 Mock/Fallback。
- app_settings 布尔配置默认打开、缺行 default=True。
- 系统设置 GET/PUT /settings/image-quality-audit 接线（admin 可改）。
- 前端开关卡片、质量标签、样式接线。
无模型 / 无网络 / 临时数据库。
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

from image_content_guard import inspect_image_content  # noqa: E402
import image_content_guard as icg  # noqa: E402


class TestQualityAuditV4104(unittest.TestCase):

    def test_01_missing_extended_is_unverified(self):
        """未传扩展结论 → quality_status=unverified，4 个维度均 unverified。"""
        r = inspect_image_content(None)
        self.assertTrue(r["ok"])  # 旧字段不变（fail-open）
        self.assertEqual(r["verdict"], "has_content")
        self.assertEqual(r["quality_status"], "unverified")
        self.assertEqual(set(r["checks"].keys()),
                         {"product_presence", "value_visibility", "visual_conflict", "ocr"})
        for v in r["checks"].values():
            self.assertEqual(v["status"], "unverified")

    def test_02_extended_ok_upgrades_status(self):
        checks = {d: {"status": "ok", "detail": ""} for d in
                  ("product_presence", "value_visibility", "visual_conflict", "ocr")}
        r = inspect_image_content(None, {"status": "ok", "checks": checks})
        self.assertEqual(r["quality_status"], "ok")

    def test_03_extended_fail_marks_fail(self):
        checks = {d: {"status": "ok", "detail": ""} for d in
                  ("product_presence", "value_visibility", "visual_conflict", "ocr")}
        checks["product_presence"] = {"status": "fail", "detail": "no product"}
        r = inspect_image_content(None, {"status": "fail", "checks": checks})
        self.assertEqual(r["quality_status"], "fail")

    def test_04_legacy_blank_fields_intact(self):
        """纯色拦截仍设置旧 verdict=blank，且 quality_status=fail。"""
        from PIL import Image
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            Image.new("RGB", (1080, 1080), (30, 60, 90)).save(path)
            r = inspect_image_content(path)
            self.assertFalse(r["ok"])
            self.assertEqual(r["verdict"], "blank")
            self.assertEqual(r["quality_status"], "fail")
        finally:
            os.unlink(path)

    def test_05_image_vision_audit_unavailable_without_cfg(self):
        import asyncio
        from video_vision_audit import audit_image_quality
        r = asyncio.run(audit_image_quality(b"fake-jpeg", None))
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("未配置", r["reason"])
        self.assertEqual(r["checks"], {})

    def test_06_app_settings_default_true_and_toggle(self):
        import app_settings
        from models import SystemState
        from database import SessionLocal
        from migrations import ensure_schema
        ensure_schema()
        db = SessionLocal()
        try:
            key = app_settings.IMAGE_QUALITY_AUDIT_ENABLED
            db.query(SystemState).filter_by(key=key).delete()
            db.commit()
            self.assertTrue(app_settings.get_bool(db, key, True), "缺行默认打开")
            app_settings.set_bool(db, key, False); db.commit()
            self.assertFalse(app_settings.get_bool(db, key, True))
            app_settings.set_bool(db, key, True); db.commit()
            self.assertTrue(app_settings.get_bool(db, key, True))
            db.query(SystemState).filter_by(key=key).delete(); db.commit()
        finally:
            db.close()

    def test_07_backend_endpoints_wired(self):
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/settings/image-quality-audit")', src)
        self.assertIn('@router.put("/settings/image-quality-audit")', src)
        self.assertIn("ImageQualityAuditIn", src)
        self.assertIn("settings.image_quality_audit", src)

    def test_08_generation_reads_switch_and_reports_quality(self):
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        self.assertIn("app_settings.IMAGE_QUALITY_AUDIT_ENABLED", src)
        self.assertIn("audit_image_quality", src)
        self.assertIn('"quality_status": content_check.get("quality_status")', src)
        self.assertIn("inspect_image_content, t[\"out\"], extended_check", src)

    def test_09_frontend_switch_and_label(self):
        llm = (FRONTEND / "pages" / "LLMSettings.tsx").read_text(encoding="utf-8")
        cw = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn("ImageQualitySetting", llm)
        self.assertIn("imageQualityAudit()", llm)
        self.assertIn("imageQualityAudit:", api)
        self.assertIn("质量未核验", cw)
        self.assertIn("cw-quality-unverified", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
