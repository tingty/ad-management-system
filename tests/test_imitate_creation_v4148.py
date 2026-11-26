# -*- coding: utf-8 -*-
"""V4.148 · 模仿创作视频创作脚本 C1–C8 与确认闸门专项测试。

覆盖：规格库选项、C1–C8 归一化、商业信息不逐字复制、承诺数字/绝对化用语阻断、
真实文本模型统一路由（替身）+ 拒绝 Mock/Fallback、缓存、模型门、确认闸门幂等、
编辑后重新计价、worker 不进视频提交分支、迁移与前后端静态契约。
全程无真实付费调用。
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: E402
import migrations  # noqa: E402
from models import ImitateAnalysisScript  # noqa: E402


def _analysis() -> dict:
    return {
        "A1": {"duration": 18, "aspect_ratio": "9:16", "resolution": "1080x1920"},
        "A4": {"shots": [
            {"index": 1, "tc_start": "00:00.0", "tc_end": "00:03.0", "duration": 3,
             "shot_size": "近景", "subject_action": "拿起手机", "camera": "推镜",
             "movement_path": "中心向左", "transition": "硬切"},
            {"index": 2, "tc_start": "00:03.0", "tc_end": "00:08.0", "duration": 5,
             "shot_size": "中景", "subject_action": "展示使用场景", "camera": "跟拍",
             "movement_path": "横移", "transition": "叠化"},
        ]},
        "A6": {"primary": "#112233", "secondary": "#445566", "accent": "#778899",
               "tone": "清爽", "light_type": "自然光"},
        "A7": {"brand": "OriginalBrand", "copy": "限时半价抢购",
               "sales": "销量第一", "promotion": "买一送一",
               "voiceover_transcript": "原片旁白", "subtitle_style": "白色粗体"},
        "A9": {"promise_numbers": [], "absolute_terms": [], "unverified_claims": [],
               "needs_evidence": []},
        "A10": {"why_effective": ["钩子前置"]},
    }


class _FakeLLM:
    def __init__(self, raw, fallback=False):
        self.raw = raw
        self.used_fallback = fallback
        self.error_type = "mock_fallback" if fallback else ""
        self.retries = 0
        self.exception_type = ""
        self.calls = 0
        self.last = None

    async def chat(self, system, user, **kw):
        self.calls += 1
        self.last = (system, user)
        return self.raw


class TestSpecAndNormalize(unittest.TestCase):
    def test_video_spec_options_from_library(self):
        import imitate_creation_script as ics
        opts = ics.video_spec_options()
        self.assertTrue(opts)
        for row in opts[:5]:
            self.assertTrue(row["spec_id"].startswith("sp-"))
            self.assertTrue(row["platform"])
            self.assertTrue(row["aspect_ratios"] or row["sizes"])

    def test_resolve_target_spec_uses_spec_id(self):
        import imitate_creation_script as ics
        opts = ics.video_spec_options()
        job = SimpleNamespace(request_json={"target_spec_id": opts[0]["spec_id"]})
        spec, reason = ics.resolve_target_spec(job)
        self.assertEqual(reason, "")
        self.assertEqual(spec["spec_id"], opts[0]["spec_id"])
        self.assertEqual(spec["platform"], opts[0]["platform"])

    def test_resolve_target_spec_without_choice_is_honest(self):
        import imitate_creation_script as ics
        spec, reason = ics.resolve_target_spec(SimpleNamespace(request_json={}))
        self.assertEqual(spec, {})
        self.assertIn("目标投放平台", reason)

    def test_normalize_fills_c1_c8_and_keeps_code_frozen_fields(self):
        import imitate_creation_script as ics
        opts = ics.video_spec_options()
        opts = [o for o in opts if o["verification"] != "C"] or opts
        spec, _ = ics.resolve_target_spec(SimpleNamespace(
            request_json={"target_spec_id": opts[0]["spec_id"]}))
        job = SimpleNamespace(request_json={"structure_fidelity": "high",
                                            "target_spec_id": opts[0]["spec_id"]})
        out = ics.normalize_creation({
            "C2": {"fidelity": "low", "hook": "新钩子"},
            "C3": {"shots": [{"visual_prompt": "新画面"}]},
            "C5": {"toggles": {"brand": True},
                   "items": [{"type": "brand", "rewritten": "NewBrand"}]},
            "C8": {"estimated_cost": {"amount": 0.01}, "spec_id": "sp-hacked"},
        }, analysis=_analysis(), job=job, spec=spec)
        for k in ics.C_KEYS:
            self.assertIn(k, out)
        self.assertEqual(out["C1"]["spec_id"], spec["spec_id"])   # 代码冻结
        self.assertEqual(out["C2"]["fidelity"], "high")           # 用户选项硬约束
        self.assertEqual(out["C2"]["hook"], "新钩子")
        self.assertEqual(len(out["C3"]["shots"]), 1)
        self.assertEqual(out["C3"]["shots"][0]["visual_prompt"], "新画面")
        self.assertEqual(out["C8"]["spec_id"], spec["spec_id"])
        self.assertNotEqual(out["C8"]["estimated_cost"]["amount"], 0.01)

    def test_compliance_flags_verbatim_and_promise_numbers(self):
        import imitate_creation_script as ics
        spec = {"spec_id": "sp-test", "verification": "A"}
        job = SimpleNamespace(request_json={"structure_fidelity": "medium"})
        script = ics.normalize_creation({
            "C5": {"toggles": {"brand": True, "sales": True},
                   "items": [
                       {"type": "brand", "rewritten": "OriginalBrand"},
                       {"type": "sales", "rewritten": "销量第一，100% 有效"},
                   ]},
        }, analysis=_analysis(), job=job, spec=spec)
        issues = script["C7"]["blocking_issues"]
        self.assertIn("VERBATIM_COMMERCIAL_TEXT:brand", issues)
        self.assertIn("ABSOLUTE_TERM_UNREMOVED", issues)
        self.assertIn("PROMISE_NUMBER_UNREMOVED", issues)
        blocked = ics.validate_for_confirm(script)
        self.assertTrue(any("VERBATIM" in x for x in blocked))


class TestCreationFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = create_engine("sqlite:///" + self.tmp.name,
                                    connect_args={"check_same_thread": False, "timeout": 30},
                                    future=True)
        self.Session = sessionmaker(bind=self.engine, autoflush=False,
                                    autocommit=False, future=True)
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.Session)
        self._p1.start(); self._p2.start()
        migrations.ensure_schema()
        import imitate_creation_script as ics
        self.ics = ics
        opts = ics.video_spec_options()
        opts = [o for o in opts if o["verification"] != "C"] or opts
        self.spec, _ = ics.resolve_target_spec(SimpleNamespace(
            request_json={"target_spec_id": opts[0]["spec_id"]}))
        self.spec_id = self.spec["spec_id"]
        self.job = SimpleNamespace(
            job_id="imv_v4148", kind="imitate_video", owner_id=7, owner_name="tester",
            request_json={"target_spec_id": self.spec_id, "structure_fidelity": "high",
                          "creation_options": {"brand": True}},
            result_json={"analysis_script_id": "ias_v4148"},
            status="queued", stage="creation_pending", progress=50,
            error_code=None, error_stage=None, error_message=None, error_action=None,
            provider_config_id=None, provider_task_id=None, next_poll_at=None,
            lease_until=None, cancel_requested=False, evidence_json={},
        )

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _row(self, script_json=None, creation_json=None):
        db = self.Session()
        row = ImitateAnalysisScript(
            script_id="ias_v4148", owner_id=7, owner_name="tester",
            job_id="imv_v4148", file_hash="hash_v4148", status="analyzed",
            script_json=script_json or _analysis(), creation_json=creation_json,
        )
        db.add(row)
        db.commit()
        return db

    def _llm_pair(self, data=None, fallback=False):
        out = data or {
            "C2": {"fidelity": "high", "hook": "新钩子"},
            "C3": {"shots": [
                {"visual_prompt": "镜头一：产品出现在晨光桌面"},
                {"visual_prompt": "镜头二：手持设备完成一次操作"},
            ]},
            "C5": {"toggles": {"brand": True},
                   "items": [{"type": "brand", "rewritten": "NewBrand"}]},
            "C6": {"voiceover_text": "用更轻的方式开始一天"},
        }
        llm = _FakeLLM("```json\n" + json.dumps(out, ensure_ascii=False) + "\n```", fallback)
        info = {"provider": "openai", "model": "text-real", "config_id": 9,
                "request_id": "req_v4148", "resolved_from": "", "source": "llm",
                "fallback": False, "role": "copy"}
        return llm, info

    def test_generate_stores_full_script_and_cache_skips_model(self):
        db = self._row()
        llm, info = self._llm_pair()
        r = asyncio.run(self.ics.generate_and_store(db, self.job, llm_pair=(llm, info)))
        self.assertEqual(r["status"], "ok")
        self.assertFalse(r["cached"])
        for k in self.ics.C_KEYS:
            self.assertIn(k, r["script_json"])
        self.assertEqual(r["script_json"]["C8"]["model_usage"], "copy")
        self.assertFalse(r["meta_json"]["fallback"])
        self.assertEqual(llm.calls, 1)
        self.assertIn("C1..C8", llm.last[0])
        llm2, info2 = self._llm_pair()
        hit = asyncio.run(self.ics.generate_and_store(db, self.job, llm_pair=(llm2, info2)))
        self.assertEqual(hit["status"], "ok")
        self.assertTrue(hit["cached"])
        self.assertEqual(llm2.calls, 0)
        db.close()

    def test_fallback_is_rejected_not_saved(self):
        db = self._row()
        llm, info = self._llm_pair(fallback=True)
        r = asyncio.run(self.ics.generate_and_store(db, self.job, llm_pair=(llm, info)))
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("Fallback", r["reason"])
        self.assertIsNone(db.query(ImitateAnalysisScript).first().creation_json)
        db.close()

    def test_model_gate_strict_on_empty_db(self):
        db = self.Session()
        missing = self.ics.creation_model_gate(db)
        self.assertTrue(missing)
        self.assertTrue(any(i.get("usage") == "copy" for i in missing))
        db.close()

    def test_confirm_freezes_idempotency_and_blocks_verbatim(self):
        spec, _ = self.ics.resolve_target_spec(SimpleNamespace(
            request_json={"target_spec_id": self.spec_id}))
        valid = self.ics.normalize_creation({
            "C5": {"toggles": {"brand": True},
                   "items": [{"type": "brand", "rewritten": "NewBrand"}]},
        }, analysis=_analysis(), job=self.job, spec=spec)
        db = self._row(creation_json={"status": "ready", "script_json": valid,
                                      "meta_json": {"model": "text-real"}})
        job = SimpleNamespace(job_id="imv_v4148", owner_id=7, result_json={
            "analysis_script_id": "ias_v4148", "creation_script_id": "ias_v4148"},
            provider_config_id=None, provider_task_id=None, next_poll_at=None)
        blocked = self.ics.confirm_creation_script(db, job, fee_ack=False)
        self.assertEqual(blocked["status"], "blocked")
        out = self.ics.confirm_creation_script(db, job, fee_ack=True)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["idempotency_key"])
        self.assertTrue(out["cost_estimate"]["is_estimate"])
        again = self.ics.confirm_creation_script(db, job, fee_ack=True)
        self.assertTrue(again.get("idempotent"))
        self.assertEqual(again["idempotency_key"], out["idempotency_key"])
        self.assertIsNone(job.provider_config_id)
        self.assertIsNone(job.provider_task_id)
        self.assertIsNone(job.next_poll_at)
        db.close()

    def test_verbatim_script_cannot_confirm(self):
        spec, _ = self.ics.resolve_target_spec(SimpleNamespace(
            request_json={"target_spec_id": self.spec_id}))
        bad = self.ics.normalize_creation({
            "C5": {"toggles": {"brand": True},
                   "items": [{"type": "brand", "rewritten": "OriginalBrand"}]},
        }, analysis=_analysis(), job=self.job, spec=spec)
        db = self._row(creation_json={"status": "ready", "script_json": bad,
                                      "meta_json": {}})
        job = SimpleNamespace(job_id="imv_v4148", owner_id=7, result_json={
            "analysis_script_id": "ias_v4148", "creation_script_id": "ias_v4148"})
        out = self.ics.confirm_creation_script(db, job, fee_ack=True)
        self.assertEqual(out["status"], "blocked")
        self.assertTrue(any("VERBATIM" in x for x in out.get("issues") or []))
        db.close()

    def test_revise_recalculates_cost_and_invalidates_idempotency(self):
        spec, _ = self.ics.resolve_target_spec(SimpleNamespace(
            request_json={"target_spec_id": self.spec_id}))
        script = self.ics.normalize_creation({}, analysis=_analysis(),
                                              job=self.job, spec=spec)
        db = self._row(creation_json={"status": "confirmed", "script_json": script,
                                      "meta_json": {"idempotency_key": "old-key",
                                                    "status": "confirmed"}})
        job = SimpleNamespace(job_id="imv_v4148", owner_id=7, result_json={
            "analysis_script_id": "ias_v4148", "creation_script_id": "ias_v4148"},
            request_json=self.job.request_json)
        out = self.ics.revise_creation_script(db, job, patch={
            "C2": {"fidelity": "low"},
            "C3": {"shots": [{"visual_prompt": "只保留一个镜头"}]},
        })
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["script_json"]["C8"]["shot_count"], 1)
        self.assertNotIn("idempotency_key", out["meta_json"])
        db.close()

    def test_migration_v4148_applied(self):
        db = self.Session()
        row = db.execute(text("SELECT version FROM schema_migrations WHERE version='V4.148.1'")).first()
        self.assertIsNotNone(row)
        state = db.execute(text("SELECT value FROM system_state WHERE key='imitate_creation_enabled'")).first()
        self.assertEqual(state[0], "1")
        db.close()


class TestWorkerAndContracts(unittest.TestCase):
    def test_worker_creation_branch_never_calls_provider(self):
        import creative_tasks as ct
        job = SimpleNamespace(
            kind="imitate_video", stage="creation_pending", cancel_requested=False,
            request_json={}, evidence_json={}, result_json={}, job_id="imv_x",
            status="queued", progress=50, error_code=None, error_message=None,
            next_poll_at=None, updated_at=None,
        )
        with mock.patch("imitate_creation_script.generate_and_store",
                        new=mock.AsyncMock(return_value={"status": "ok", "script_id": "c1"})), \
             mock.patch.object(ct, "_provider", side_effect=AssertionError("不得进入视频提交")):
            fake_db = mock.Mock()
            asyncio.run(ct._drive(fake_db, job))
        self.assertEqual(job.stage, "awaiting_confirm")
        self.assertIsNone(job.next_poll_at)

    def test_endpoints_and_422_gate_registered(self):
        with open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8") as f:
            src = f.read()
        for ep in ('@router.get("/imitate-video/video-specs")',
                   '@router.post("/imitate-video/jobs/{job_id}/create-script")',
                   '@router.get("/imitate-video/jobs/{job_id}/creation-script")',
                   '@router.patch("/imitate-video/jobs/{job_id}/creation-script")',
                   '@router.post("/imitate-video/jobs/{job_id}/confirm")'):
            self.assertIn(ep, src)
        self.assertIn("creation_model_gate(db)", src)
        self.assertIn('"blocked": "model_not_ready"', src)
        self.assertIn('"blocked": "creation_gate"', src)

    def test_confirm_does_not_set_paid_fields(self):
        with open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8") as f:
            src = f.read()
        start = src.index('@router.post("/imitate-video/jobs/{job_id}/confirm")')
        block = src[start:start + 2800]
        self.assertIn("job.provider_config_id = job.provider_task_id = None", block)
        self.assertIn("job.next_poll_at = None", block)
        self.assertNotIn("submit_job", block)

    def test_frontend_contract_present(self):
        base = os.path.join(ROOT, "frontend", "src")
        with open(os.path.join(base, "api.ts"), encoding="utf-8") as f:
            api = f.read()
        with open(os.path.join(base, "pages", "ImitateVideo.tsx"), encoding="utf-8") as f:
            page = f.read()
        for sym in ("ImitateCreationScript", "videoSpecs", "createCreationScript",
                    "updateCreationScript", "confirmCreation"):
            self.assertIn(sym, api)
        for label in ("创作脚本 C1–C8", "确认闸门", "结构保持度", "删除", "上移"):
            self.assertIn(label, page)

    def test_no_mock_llm_constructed_in_creation_module(self):
        import ast
        with open(os.path.join(ROOT, "backend", "imitate_creation_script.py"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    node.body = body[1:]
        code = ast.unparse(tree)
        self.assertNotIn("MockLLM(", code)
        self.assertIn("finalize_invocation", code)


if __name__ == "__main__":
    unittest.main()
