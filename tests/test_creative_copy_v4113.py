"""V4.113 创意工作台文案「失败不可见」修复。

真实故障链（截图为证）：
- 文案模型调用 401 / 超时 / 限流时，`generate_media_copy` 把异常静默吞掉并回退 Mock；
- Mock 返回的键是 titles / descriptions，与平台 schema（primary_text / headline /
  description / cta）不匹配 → 字段全空 → validation.invalid；
- 前端只能显示「文案未生成成功，请检查模型配置」，用户看不出是 Key 过期还是没配置；
- 文案失败后每个图片任务又被记成 failed，页面再补一句「请调整媒体或重试」，
  把用户引向改尺寸 / 换平台。

本测试锁住五件事：
1. 模型失败 / 缺失 / 非 JSON 时必须 `validation.status="blocked"` 并写明真实原因；
2. 文案模型缺失但分析模型可用时，复用分析模型并在 model_info 里如实标注；
3. 工作坊 copy_view 与会话自检都透出同一份原因；
4. 前端展示模型自检条与逐平台失败原因，图片「未提交」不再记成 failed；
5. 自检端点可用，且自检口径与 `providers._pick_config` 的实际调用行为一致。
"""
import asyncio
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

import media_ad  # noqa: E402
import workshop  # noqa: E402
import providers  # noqa: E402
from providers import MockLLM, FallbackLLM  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from models import ModelConfig  # noqa: E402

ANALYSIS = {
    "url": "https://example.com", "brand": "GlowSkin", "language": "en",
    "industry": "Beauty", "type": "ecommerce",
    "audience": "US women 25-40", "competitors": ["A"], "advantages": ["Vegan formula"],
    "channels": [{"platform": "Meta", "reason": "visual"}],
    "source": "pasted", "snapshot": {"source": "pasted"}, "industry_profile": "general",
}


class _Boom:
    """模拟真实供应商：chat 直接抛 401 类异常。"""

    used_fallback = False
    error_type = ""
    exception_type = ""
    retries = 0

    async def chat(self, system, user, **kw):
        raise RuntimeError("Client error '401 Unauthorized'")


class _Stub:
    """返回指定 JSON 的假模型（不联网、不计费）。"""

    used_fallback = False
    error_type = ""
    retries = 0

    def __init__(self, payload):
        self.payload = payload

    async def chat(self, system, user, **kw):
        return self.payload


def _info(provider="千问大模型", model="qwen-plus", config_id=7, source="llm",
          fallback=False, error_type=""):
    return {"provider": provider, "model": model, "role": "copy", "config_id": config_id,
            "request_id": "t", "source": source, "fallback": fallback,
            "error_type": error_type, "retries": 0, "resolved_from": ""}


class TestCreativeCopyHonestV4113(unittest.TestCase):
    def setUp(self):
        self._orig = media_ad.get_llm_with_info

    def tearDown(self):
        media_ad.get_llm_with_info = self._orig

    def _run(self, llm, info):
        media_ad.get_llm_with_info = lambda db, usage="copy", allow_reuse=False: (llm, dict(info))
        db = SessionLocal()
        try:
            return asyncio.run(media_ad.generate_media_copy(db, ANALYSIS, "Meta", "en"))
        finally:
            db.close()

    def test_01_auth_failure_is_explicit_not_generic(self):
        """401 必须变成「鉴权失败 + 去改 Key」，而不是「文案未生成成功」。"""
        llm = FallbackLLM(_Boom(), MockLLM())
        res = self._run(llm, _info())
        val = res["validation"]
        self.assertEqual(val["status"], "blocked", val)
        self.assertFalse(val["valid"])
        self.assertIn("鉴权", val["message"])
        self.assertIn("qwen-plus", val["message"])
        self.assertEqual(res["blocked"]["code"], "model_failed")

    def test_02_missing_copy_model_says_not_configured(self):
        """完全没有可用配置时，原因必须是「没有可用的文案模型」，并说明会复用分析模型。"""
        res = self._run(MockLLM(), _info(provider="", model="", config_id=None,
                                         source="mock", fallback=True))
        val = res["validation"]
        self.assertEqual(val["status"], "blocked")
        self.assertIn("没有可用的文案模型", val["message"])
        self.assertIn("复用", val["message"])

    def test_03_plain_text_response_is_named(self):
        """模型返回一段普通文本（不是 JSON）时，指出「无法解析为 JSON」而不是笼统失败。"""
        res = self._run(_Stub("Sure! Here is your ad copy."), _info(source="invalid_response"))
        val = res["validation"]
        self.assertEqual(val["status"], "blocked")
        self.assertIn("JSON", val["message"])

    def test_04_valid_model_output_passes_and_is_not_blocked(self):
        """真模型返回合法平台字段时不得被误判成 blocked。"""
        payload = ('{"primary_text": "Meet GlowSkin", "headline": ["Skincare made simple"], '
                   '"description": "Shop the range", "cta": "Shop Now"}')
        res = self._run(_Stub(payload), _info())
        self.assertIsNone(res.get("blocked"), res.get("blocked"))
        self.assertTrue(res["validation"]["valid"], res["validation"])
        self.assertEqual(res["fields"]["primary_text"], "Meet GlowSkin")

    def test_05_workshop_view_surfaces_the_same_reason(self):
        """素材工作坊的文案卡也读同一份 blocked 原因，不另写一套话术。"""
        res = self._run(FallbackLLM(_Boom(), MockLLM()), _info())
        view = workshop.copy_view("Meta", res)
        self.assertEqual(view["status"], "failed")
        self.assertIn("鉴权", view["reason"])

    def test_06_copy_reuses_analysis_model_when_not_configured(self):
        """只配了分析模型时，文案复用分析模型并如实标注 resolved_from。"""
        ensure_schema()
        db = SessionLocal()
        try:
            db.query(ModelConfig).delete()
            db.add(ModelConfig(name="only-analysis", usage="analysis", usages=["analysis"],
                               provider="openai", api_key="sk-test", base_url="http://127.0.0.1:9/v1",
                               model="gpt-4o-mini", is_active=True, last_test_ok=True))
            db.commit()
            st = workshop.workbench_model_status(db)
            copy = [i for i in st["items"] if i["usage"] == "copy"][0]
            self.assertTrue(copy["ready"], copy)
            self.assertEqual(copy.get("reused_from"), "analysis")
            self.assertIn("复用分析模型", copy.get("note") or "")
            # 解析器层同样复用，且 role 仍是 copy
            llm, info = providers.get_llm_with_info(db, "copy", allow_reuse=True)
            self.assertEqual(info.get("resolved_from"), "analysis")
            self.assertEqual(info.get("role"), "copy")
            self.assertTrue(info.get("provider"))
        finally:
            db.close()

    def test_07_frontend_surfaces_reasons_and_does_not_call_blocked_failed(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text()
        api = (FRONTEND / "api.ts").read_text()
        css = (FRONTEND / "styles.css").read_text()
        # 模型自检
        self.assertIn("cwModelStatus", api)
        self.assertIn("/api/cw/model-status", api)
        self.assertIn("cwb-model-alert", page)
        # 逐平台失败原因直接进文案工作区
        self.assertIn("copyErrors", page)
        self.assertIn("cwb-copy-blocked", page)
        self.assertIn("去「大模型配置」检查", page)
        # 语义：文案缺失导致图片未提交 → blocked，不再记 failed
        self.assertIn("status: 'blocked'", page)
        self.assertIn("图片未提交", page)
        self.assertIn(".cwb-model-alert", css)
        self.assertIn(".cwb-copy-blocked", css)

    def test_08_status_agrees_with_actual_config_when_never_tested(self):
        """配置存在但从未测试通过：自检不能误报「未就绪」，必须与 _pick_config 一致。

        工作坊硬门仍按「必须测试通过」判未就绪（那是它的正确行为）；创意工作台
        是既有链路，_pick_config 在全部未测试时仍会选中并真实调用该配置，
        若自检说未就绪、点生成却成功了，就是新的状态矛盾。
        """
        ensure_schema()
        db = SessionLocal()
        try:
            db.query(ModelConfig).delete()
            db.add(ModelConfig(name="untested", usage="analysis", usages=["analysis", "copy"],
                               provider="openai", api_key="sk-test",
                               base_url="http://127.0.0.1:9/v1", model="gpt-4o-mini",
                               is_active=True, last_test_ok=None))
            db.commit()
            strict = workshop.model_status(db)
            ana_strict = [i for i in strict["items"] if i["usage"] == "analysis"][0]
            self.assertFalse(ana_strict["ready"], "工作坊硬门应仍判未就绪")
            self.assertIsNotNone(providers._active_config(db, "analysis"))

            st = workshop.workbench_model_status(db)
            by = {i["usage"]: i for i in st["items"]}
            for usage in ("analysis", "copy"):
                self.assertTrue(by[usage]["ready"], (usage, by[usage]))
            self.assertIn("尚未测试", by["analysis"].get("note") or "")
            labels = {i["usage"]: i["label"] for i in st["items"]}
            for m in st["missing"]:
                self.assertNotIn(m, (labels.get("analysis"), labels.get("copy")))
            # copy 有独立配置时不得谎称「复用分析模型」
            self.assertNotIn("reused_from", by["copy"])
        finally:
            db.close()


class TestModelStatusEndpointV4113(unittest.TestCase):
    """只读自检端点：打开创意工作台即可拿到三类用途的生效配置与原因。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from main import app
        from models import User
        from auth import hash_password

        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username="v4113").first():
                h, s = hash_password("TestPwd123")
                db.add(User(username="v4113", email="v4113@test.local",
                            display_name="V4113", role="admin",
                            password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login",
                            json={"email": "v4113@test.local", "password": "TestPwd123"})
        cls.auth = {"Authorization": "Bearer " + r.json()["token"]}

    def test_01_endpoint_returns_three_usages_with_reasons(self):
        r = self.client.get("/api/cw/model-status", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIn("items", d)
        usages = {i["usage"] for i in d["items"]}
        self.assertTrue({"analysis", "copy", "image"}.issubset(usages), usages)
        for i in d["items"]:
            self.assertIn("label", i)
            self.assertIn("ready", i)
            self.assertIsInstance(i.get("reason", ""), str)
        self.assertIsInstance(d.get("missing"), list)
        self.assertIsInstance(d.get("ready"), bool)


if __name__ == "__main__":
    unittest.main()
