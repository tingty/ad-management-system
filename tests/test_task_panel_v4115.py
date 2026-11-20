"""V4.115 两项修复的回归锁：

A. 「确认并批量生成」422 `Input should be a valid dictionary`：
   根因是未确认 brief 时前端 confirmedBrief() 返回 null，作为 `brief` 传给后端，
   而 `MediaCopyRequest.brief: dict` 在 Pydantic v2 下对显式 null 报 dict_type 422。
   同类隐患：analysis.creative_intent / evidence_ref_audit、style_opts、copy_fields、
   CWRoutesRequest.user_brief 为 null 时同样 422。
   修复：后端对请求体里的 dict 字段做 null→{} 收敛；前端调用点用 `|| {}`。

B. 任务栏：显示创建时间（YYYY-MM-DD HH:MM，UTC→本地）；进行中任务可直接手动停止，
   落 MANUAL_STOP 标记，前端显示「手动停止」便于在「需处理」查询。

本测试只验证契约与静态代码，不调用付费模型。
"""
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from pydantic import ValidationError  # noqa: E402
from schemas import MediaCopyRequest, MediaImageRequest, CWRoutesRequest  # noqa: E402
from analysis_contract import normalize_analysis  # noqa: E402

BASE = {
    "url": "https://example.com", "industry": "Beauty", "type": "ecommerce",
    "audience": "US women", "competitors": [], "advantages": ["Vegan"],
    "channels": [], "evidence_gate": "ok",
}


class TestCopyNullDict422(unittest.TestCase):
    def test_01_brief_none_no_longer_422(self):
        """用户报错场景：brief=null 必须归一化成 {}，不再 dict_type 422。"""
        r = MediaCopyRequest(analysis=BASE, platform="Meta", brief=None)
        self.assertEqual(r.brief, {})
        # 关键：空 brief 不能被误判成「已确认」
        self.assertFalse(r.brief.get("confirmed"))

    def test_02_confirmed_brief_preserved(self):
        """显式已确认 brief 不被归一化破坏。"""
        r = MediaCopyRequest(analysis=BASE, platform="Meta",
                             brief={"confirmed": True, "prompt_text": "突出天然成分"})
        self.assertTrue(r.brief["confirmed"])
        self.assertEqual(r.brief["prompt_text"], "突出天然成分")

    def test_03_other_null_dict_fields(self):
        """同链路其它 dict 字段为 null 也不能 422。"""
        r = MediaCopyRequest(analysis=BASE, platform="Meta", style_opts=None, brief=None)
        self.assertEqual(r.style_opts, {})
        im = MediaImageRequest(analysis=BASE, platform="Meta",
                               copy_fields=None, style_opts=None)
        self.assertEqual(im.copy_fields, {})
        self.assertEqual(im.style_opts, {})
        cr = CWRoutesRequest(analysis=BASE, user_brief=None, creative_intent=None, brief=None)
        self.assertEqual(cr.user_brief, {})
        self.assertEqual(cr.creative_intent, {})

    def test_04_analysis_null_dict_fields(self):
        """analysis 内 creative_intent / evidence_ref_audit 为 null 时归一化。"""
        a = dict(BASE)
        a["creative_intent"] = None
        a["evidence_ref_audit"] = None
        out = normalize_analysis(a)
        self.assertEqual(out["creative_intent"], {})
        self.assertEqual(out["evidence_ref_audit"], {})
        r = MediaCopyRequest(analysis=a, platform="Meta")
        self.assertEqual(r.analysis.creative_intent, {})

    def test_05_non_dict_still_rejected(self):
        """归一化只针对 null，不掩盖真正的类型错误（如 brief 给成 list）。"""
        with self.assertRaises(ValidationError):
            MediaCopyRequest(analysis=BASE, platform="Meta", brief=["not", "dict"])

    def test_06_frontend_passes_empty_object(self):
        """前端三处 API 调用点不再把 null 直接传给后端。"""
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("brief: confirmedBrief() || {}", page)
        self.assertIn("user_brief: confirmedBrief() || {}", page)
        # 不应再有裸露的 `brief: confirmedBrief()`（后面紧跟逗号或换行的旧写法）
        self.assertNotIn("brief: confirmedBrief(),", page)


class TestTaskPanelV4115(unittest.TestCase):
    def test_07_drawer_shows_created_time(self):
        drawer = (FRONTEND / "CreativeTasksDrawer.tsx").read_text(encoding="utf-8")
        self.assertIn("formatCreatedAt", drawer)
        self.assertIn("YYYY-MM-DD", drawer)
        self.assertIn("parseUtcMs", drawer)
        self.assertIn("创建 {formatCreatedAt(b.created_at)}", drawer)

    def test_08_drawer_manual_stop_button(self):
        drawer = (FRONTEND / "CreativeTasksDrawer.tsx").read_text(encoding="utf-8")
        self.assertIn("stopNow", drawer)
        self.assertIn("MANUAL_STOP", drawer)
        self.assertIn("手动停止", drawer)
        self.assertIn("onCancel(b.batch_id, '', 'user')", drawer)

    def test_09_backend_manual_stop_mark(self):
        src = (BACKEND / "creative_tasks.py").read_text(encoding="utf-8")
        self.assertIn('def cancel(db: Session, user, batch_id: str, job_id: str = "", reason: str = "user")', src)
        self.assertIn('code = "MANUAL_STOP" if manual else "CANCELED"', src)
        self.assertIn('"手动停止" if job.error_code == "MANUAL_STOP"', src)

    def test_10_cancel_reason_endpoint_and_api(self):
        routers = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn('reason = str((body or {}).get("reason") or "user").strip()', routers)
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("cancelCreativeTask: (batchId: string, jobId = '', reason = 'user')", api)
        use = (FRONTEND / "useCreativeTasks.ts").read_text(encoding="utf-8")
        self.assertIn("cancelCreativeTask(batchId, jobId, reason)", use)


class TestCopyEndpointNullBriefE2E(unittest.TestCase):
    """端到端：未确认 brief（null）不得再在 Pydantic 校验阶段 422。

    只验证「不再 422」——用假模型返回合规文案，避免真实付费调用。
    """

    @classmethod
    def setUpClass(cls):
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User

        ensure_schema()
        email, user, pwd = "v4115@recomob.com", "v4115", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4115",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_11_copy_endpoint_accepts_null_brief(self):
        import media_ad
        from providers import MockLLM

        orig = media_ad.get_llm_with_info
        fake_info = {"provider": "fake", "model": "fake", "role": "copy",
                     "source": "llm", "fallback": False, "config_id": None,
                     "request_id": "v4115", "retries": 0, "error_type": ""}
        analysis = {
            "url": "https://soundora.example/air-pro", "industry": "Consumer Electronics",
            "type": "ecommerce", "audience": "commuters", "advantages": ["40H playtime"],
            "competitors": [], "channels": [{"platform": "Meta", "reason": "visual"}],
            "language": "en", "brand": "Soundora", "evidence_gate": "ok",
            "evidence_index": [{"evidence_id": "E001", "quote": "Up to 40 hours of playtime.",
                                "char_start": 0, "char_end": 26}],
            "evidence_ids": ["E001"], "facts": ["Up to 40 hours of playtime"],
        }
        try:
            media_ad.get_llm_with_info = lambda db, usage="copy", allow_reuse=False: (MockLLM(), dict(fake_info))
            r = self.client.post("/api/media-campaign/copy",
                                 json={"analysis": analysis, "platform": "Meta", "brief": None},
                                 headers=self.auth)
        finally:
            media_ad.get_llm_with_info = orig
        self.assertNotEqual(r.status_code, 422, r.text)
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
