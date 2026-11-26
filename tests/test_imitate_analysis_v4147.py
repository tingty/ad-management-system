# -*- coding: utf-8 -*-
"""V4.147 · 模仿创作视频分析脚本 A1–A10 专项测试。

覆盖：Pillow 取色、A1–A10 归一化完整性、去代码围栏 JSON 解析、缓存命中零模型调用、
真实视觉归纳（httpx 替身，断言 messages 含 image_url）、不可用不臆造、A6 取色兜底、
worker 分析分支不进视频提交、422 硬门端点、抽帧自定义时间点。
全程无真实付费调用（HTTP 层与视觉通道全部替身）。
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: E402
import migrations  # noqa: E402
from models import ImitateAnalysisScript, GenerationJob  # noqa: E402


def _jpeg(color=(180, 60, 60), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _full_script() -> dict:
    return {k: {} for k in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10")}


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestColorAndNormalize(unittest.TestCase):
    def test_dominant_colors_hex(self):
        import imitate_analysis_script as ias
        r = ias.dominant_colors(_jpeg((200, 40, 40)))
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["colors"])
        self.assertRegex(r["colors"][0]["hex"], r"^#[0-9A-F]{6}$")

    def test_normalize_fills_all_a_keys(self):
        import imitate_analysis_script as ias
        out = ias._normalize_script({"A4": {"shots": [{"index": 1}]}, "unknown": 1})
        for k in ias.A_KEYS:
            self.assertIn(k, out)
        self.assertEqual(len(out["A4"]["shots"]), 1)
        self.assertNotIn("unknown", out)
        self.assertIsInstance(out["A9"]["promise_numbers"], list)

    def test_parse_script_strips_fence(self):
        import imitate_analysis_script as ias
        raw = "```json\n" + json.dumps({"A1": {"duration": 15}}) + "\n```"
        data, reason = ias._parse_script(raw)
        self.assertEqual(reason, "")
        self.assertEqual(data["A1"]["duration"], 15)
        bad, reason = ias._parse_script("不是 JSON")
        self.assertEqual(bad, {})
        self.assertTrue(reason)


class TestAnalyzeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = "/tmp/admp_imitate_v4147_%s.db" % os.getpid()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)
        self.engine = create_engine("sqlite:///" + self.tmp,
                                    connect_args={"check_same_thread": False, "timeout": 30},
                                    future=True)
        self.Session = sessionmaker(bind=self.engine, autoflush=False,
                                    autocommit=False, future=True)
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.Session)
        self._p1.start(); self._p2.start()
        migrations.ensure_schema()
        self.video = os.path.join(ROOT, "backend", "uploads", "93_TikTok_pain_en_full.mp4")
        self.cfg = {"provider": "openai", "api_key": "k", "base_url": "https://x/v1",
                    "model": "vision-real"}
        self.job = SimpleNamespace(
            job_id="imv_test", kind="imitate_video", owner_id=3, owner_name="u",
            request_json={"file_path": self.video, "file_hash": "hash123",
                          "duration_sec": 18.0, "aspect_ratio": "1:1", "width": 1080,
                          "height": 1080, "source_url": "https://cdn/x.mp4"},
        )

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def _patch_pipeline(self):
        """替换抽帧/OCR/6 维，保留真实归纳逻辑（仅替 HTTP 层）。"""
        import imitate_analysis_script as ias
        fr = [_jpeg(), _jpeg((40, 80, 180)), _jpeg((200, 200, 60))]
        return (
            mock.patch("video_vision_audit.extract_frames",
                       return_value=(fr, {"status": "ok", "times": [0.0, 9.0, 17.5]})),
            mock.patch("video_vision_audit.recognize_frames",
                       new=mock.AsyncMock(return_value={"status": "ok", "texts": ["立即下载"]})),
            mock.patch("asset_video_deconstruct.deconstruct_video",
                       new=mock.AsyncMock(return_value={"dims_json": {"video": {}, "visual": {}}})),
        )

    def test_analyze_success_stores_full_script(self):
        import imitate_analysis_script as ias
        import httpx
        db = self.Session()
        payload = {"choices": [{"message": {"content": json.dumps({
            "A1": {"duration": 18}, "A4": {"shots": [{"index": 1, "tc_start": "00:00.0"}]},
            "A6": {"primary": "暖色"}, "A10": {"why_effective": ["钩子强"]},
        })}}]}
        p1, p2, p3 = self._patch_pipeline()
        with p1, p2, p3, mock.patch("httpx.AsyncClient.post",
                                           new=mock.AsyncMock(return_value=_FakeResponse(payload))):
            r = asyncio.run(ias.analyze_and_store(db, self.job, model_cfg=self.cfg))
            # 找到真实调用的模型 payload，断言含 image_url
            post = __import__("httpx").AsyncClient.post
            self.assertTrue(post.called)
            sent = post.call_args.kwargs["json"]
            content = sent["messages"][1]["content"]
            self.assertTrue(any(isinstance(c, dict) and c.get("type") == "image_url"
                                for c in content))
            self.assertEqual(sent["temperature"], 0)
        self.assertEqual(r["status"], "ok")
        self.assertFalse(r.get("cached"))
        self.assertEqual(len(r["script_json"]), 10)  # A1–A10 齐全
        self.assertEqual(r["script_json"]["A4"]["shots"][0]["index"], 1)
        # A6 模型给的是中文，取色兜底应写入十六进制
        self.assertRegex(r["script_json"]["A6"]["primary"], r"^#[0-9A-F]{6}$")
        row = db.query(ImitateAnalysisScript).filter_by(script_id=r["script_id"]).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "analyzed")
        self.assertEqual(row.file_hash, "hash123")
        db.close()

    def test_cache_hit_skips_model(self):
        import imitate_analysis_script as ias
        db = self.Session()
        # 先落一条 analyzed
        db.add(ImitateAnalysisScript(script_id="s_cached", owner_id=3,
                                     file_hash="hash123", status="analyzed",
                                     script_json=_full_script(),
                                     meta_json={"model": "vision-real"}))
        db.commit()
        p1, p2, p3 = self._patch_pipeline()
        with p1, p2, p3, mock.patch("httpx.AsyncClient.post",
                                           new=mock.AsyncMock(side_effect=AssertionError("不应调用模型"))):
            r = asyncio.run(ias.analyze_and_store(db, self.job, model_cfg=self.cfg))
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["cached"])
        self.assertEqual(r["script_id"], "s_cached")
        db.close()

    def test_unavailable_when_no_cfg(self):
        import imitate_analysis_script as ias
        db = self.Session()
        r = asyncio.run(ias.analyze_and_store(db, self.job, model_cfg=None))
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("未配置", r["reason"])
        self.assertNotIn("script_json", r)
        db.close()

    def test_unavailable_when_wrong_protocol(self):
        import imitate_analysis_script as ias
        db = self.Session()
        bad = dict(self.cfg, provider="anthropic")
        r = asyncio.run(ias.analyze_and_store(db, self.job, model_cfg=bad))
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("OpenAI", r["reason"])
        db.close()

    def test_model_error_returns_unavailable_not_fake(self):
        import imitate_analysis_script as ias
        db = self.Session()
        p1, p2, p3 = self._patch_pipeline()
        with p1, p2, p3, mock.patch("httpx.AsyncClient.post",
                                           new=mock.AsyncMock(side_effect=RuntimeError("boom"))):
            r = asyncio.run(ias.analyze_and_store(db, self.job, model_cfg=self.cfg))
        self.assertEqual(r["status"], "unavailable")
        self.assertIn("调用失败", r["reason"])
        self.assertEqual(db.query(ImitateAnalysisScript).count(), 0)  # 不落假脚本
        db.close()


class TestWorkerAndEndpoints(unittest.TestCase):
    def test_worker_analysis_branch_never_calls_provider(self):
        """分析分支完成后停在 analysis_ready，绝不进入提交（付费）分支。"""
        import creative_tasks as ct
        job = SimpleNamespace(
            kind="imitate_video", stage="analysis_pending", cancel_requested=False,
            request_json={}, evidence_json={}, result_json={}, job_id="imv_x",
            status="queued", progress=0, error_code=None, error_message=None,
            next_poll_at=None, updated_at=None,
        )
        with mock.patch("imitate_analysis_script.analyze_and_store",
                        new=mock.AsyncMock(return_value={"status": "ok", "script_id": "s1"})), \
             mock.patch.object(ct, "_provider", side_effect=AssertionError("不得进入视频提交")):
            fake_db = mock.Mock()
            asyncio.run(ct._drive(fake_db, job))
        self.assertEqual(job.stage, "analysis_ready")
        self.assertIsNone(job.next_poll_at)

    def test_endpoints_registered(self):
        with open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8") as f:
            src = f.read()
        for ep in ('@router.post("/imitate-video/jobs/{job_id}/analyze")',
                   '@router.get("/imitate-video/jobs/{job_id}/analysis-script")'):
            self.assertIn(ep, src)

    def test_422_gate_present_in_analyze_endpoint(self):
        with open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('missing_models(db, ["analysis"])', src)
        self.assertIn('"blocked": "model_not_ready"', src)

    def test_no_mock_or_fallback_in_summarize(self):
        """归纳走自建 httpx：实际代码（剔除 docstring）不得引用 Mock/Fallback 入口。"""
        import ast
        with open(os.path.join(ROOT, "backend", "imitate_analysis_script.py"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # 剔除模块/函数/类的 docstring 字符串节点，只保留真实语句
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    node.body = body[1:]
        code = ast.unparse(tree)
        for sym in ("MockLLM", "FallbackLLM", "get_llm_with_info"):
            self.assertNotIn(sym, code)

    def test_extract_frames_custom_times(self):
        import video_vision_audit as vva
        with mock.patch.object(vva, "_ffmpeg_exe", return_value="/fake/ffmpeg"), \
             mock.patch("os.path.exists", return_value=True), \
             mock.patch.object(vva.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0, stdout=b"jpeg", stderr=b"")):
            frames, finfo = vva.extract_frames("/fake.mp4", 18.0, count=3, times=[1.0, 5.0, 9.0, 13.0])
        self.assertEqual(len(frames), 4)
        self.assertEqual(finfo["times"], [1.0, 5.0, 9.0, 13.0])


if __name__ == "__main__":
    unittest.main()
