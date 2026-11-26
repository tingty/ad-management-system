# -*- coding: utf-8 -*-
"""V4.146 · 模仿创作视频：源视频获取专项测试。

覆盖：SSRF 流式下载（注入替身，无真实外网）、重定向到内网拦截、体积上限、
content-type 早拒、ffmpeg 元数据解析、源视频 sha256 幂等登记、任务创建的费用安全、
owner 隔离、端点与前端双入口静态断言。本版不产生费用：不调用大模型、不提交生成。
"""
import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: E402
import migrations  # noqa: E402
from models import CreativeAssetSource, GenerationJob  # noqa: E402


# ---- SSRF 流式下载替身 ----------------------------------------------------
class _FakeResp:
    def __init__(self, status, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.content = b"".join(chunks)  # 兼容 fetch_remote_bytes 读 resp.content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self, _n):
        for c in self._chunks:
            yield c


def _streamer(mapping):
    """mapping: url -> _FakeResp；签名符合 ssrf_guard.fetch_remote_file 的 streamer。"""
    def fn(_client, url):
        return mapping[url]
    return fn


PUBLIC_RESOLVER = lambda h: ["93.184.216.34"]  # noqa: E731  公网 IP，供注入使用


class TestSourceFetchSSRF(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="imv_v4146_")
        self.out = os.path.join(self.tmpdir, "src.mp4")

    def test_stream_download_writes_bytes(self):
        import ssrf_guard as sg
        url = "https://cdn.example.com/a.mp4"
        resp = _FakeResp(200, {"content-type": "video/mp4"}, [b"abc", b"def", b"ghi"])
        r = asyncio.run(sg.fetch_remote_file(
            url, self.out, resolver=PUBLIC_RESOLVER, streamer=_streamer({url: resp})))
        self.assertEqual(r["bytes"], 9)
        self.assertEqual(r["content_type"], "video/mp4")
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), b"abcdefghi")
        self.assertFalse(os.path.exists(self.out + ".part"))

    def test_redirect_to_private_blocked(self):
        import ssrf_guard as sg
        first = "https://cdn.example.com/a.mp4"
        # 第一跳 302 到内网 IP → 第二跳 validate_url 必须拒绝
        r1 = _FakeResp(302, {"location": "http://127.0.0.1/secret"})
        with self.assertRaises(sg.SSRFError):
            asyncio.run(sg.fetch_remote_file(
                first, self.out, resolver=PUBLIC_RESOLVER,
                streamer=_streamer({first: r1})))
        self.assertFalse(os.path.exists(self.out))

    def test_max_bytes_enforced_and_tmp_cleaned(self):
        import ssrf_guard as sg
        url = "https://cdn.example.com/big.mp4"
        resp = _FakeResp(200, {"content-type": "video/mp4"}, [b"x" * 8])
        with self.assertRaises(sg.SSRFError):
            asyncio.run(sg.fetch_remote_file(
                url, self.out, max_bytes=4, resolver=PUBLIC_RESOLVER,
                streamer=_streamer({url: resp})))
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.out + ".part"))

    def test_content_type_html_rejected(self):
        import ssrf_guard as sg
        url = "https://cdn.example.com/wrong"
        resp = _FakeResp(200, {"content-type": "text/html"}, [b"<html>error</html>"])
        with self.assertRaises(sg.SSRFError):
            asyncio.run(sg.fetch_remote_file(
                url, self.out, resolver=PUBLIC_RESOLVER,
                streamer=_streamer({url: resp})))

    def test_existing_fetch_remote_bytes_unchanged(self):
        """图片链路的旧函数不受影响（仍返回 bytes，非落盘）。"""
        import ssrf_guard as sg
        url = "https://cdn.example.com/a.png"
        resp = _FakeResp(200, {"content-type": "image/png"}, [b"png"])
        r = asyncio.run(sg.fetch_remote_bytes(
            url, resolver=PUBLIC_RESOLVER,
            fetcher=lambda _c, _u: asyncio.sleep(0, result=resp)))
        self.assertEqual(r["content"], b"png")


class TestSourceMetadata(unittest.TestCase):
    def test_probe_real_video(self):
        import imitate_video as iv
        sample = os.path.join(ROOT, "backend", "uploads", "93_TikTok_pain_en_full.mp4")
        if not os.path.isfile(sample):
            self.skipTest("仓库示例视频不存在，跳过元数据实测")
        m = iv.probe_source_video(sample)
        self.assertAlmostEqual(m["duration_sec"] or 0, 18.0, delta=1.0)
        self.assertEqual(m["width"], 1080)
        self.assertEqual(m["height"], 1080)
        self.assertEqual(m["aspect_ratio"], "1:1")
        self.assertEqual(m["fps"], "30")
        self.assertFalse(m["has_audio"])

    def test_file_sha256(self):
        import imitate_video as iv
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello video")
            p = f.name
        try:
            self.assertEqual(len(iv.file_sha256(p)), 64)
        finally:
            os.remove(p)


class TestTaskCreationSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = "/tmp/admp_imitate_v4146_%s.db" % os.getpid()
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
        self.user = SimpleNamespace(id=7, username="tester")

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_create_task_no_paid_fields(self):
        import imitate_video as iv
        db = self.Session()
        snap = {"name": "参考片", "file": "/files/a.mp4", "source": "url",
                "file_hash": "abc", "duration_sec": 18.0, "aspect_ratio": "1:1"}
        r = iv.create_task(db, self.user, source_snapshot=snap,
                           options={"target_platform": "TikTok"}, rights_ack=True)
        job = db.query(GenerationJob).filter_by(job_id=r["job_id"]).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.kind, "imitate_video")
        self.assertEqual(job.stage, "source_acquiring")
        self.assertIsNone(job.provider_config_id)
        self.assertIsNone(job.provider_task_id)
        self.assertIsNone(job.next_poll_at)   # worker 不会领取 → 绝不计费
        self.assertEqual(job.owner_id, 7)
        self.assertTrue(job.request_json["rights_ack"])
        self.assertEqual(job.request_json["target_platform"], "TikTok")
        db.close()

    def test_owner_isolation_get_task(self):
        import imitate_video as iv
        db = self.Session()
        for owner in (7, 8):
            db.add(GenerationJob(job_id=f"imv_{owner}", kind="imitate_video",
                                 owner_id=owner, status="queued",
                                 stage="source_acquiring", request_json={"name": str(owner)}))
        db.commit()
        self.assertIsNotNone(iv.get_task(db, self.user, "imv_7"))
        self.assertIsNone(iv.get_task(db, self.user, "imv_8"))
        db.close()

    def test_source_register_idempotent_by_hash(self):
        import imitate_video as iv
        db = self.Session()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"video-bytes"); p = f.name
        try:
            verdict = {"container": "mp4", "bytes": 11, "duration": 18.0}
            meta = {"duration_sec": 18.0, "width": 1080, "height": 1080,
                    "aspect_ratio": "1:1", "fps": "30", "has_audio": False}
            iv._register_source(db, self.user, path=p, source="upload",
                                source_url="", name="x", verdict=verdict, meta=meta)
            iv._register_source(db, self.user, path=p, source="upload",
                                source_url="", name="x", verdict=verdict, meta=meta)
            n = db.query(CreativeAssetSource).filter_by(owner_id=7).count()
            self.assertEqual(n, 1)   # 同 sha256 不重复登记
        finally:
            os.remove(p)
            db.close()

    def test_no_paid_symbols_in_module(self):
        with open(os.path.join(ROOT, "backend", "imitate_video.py"), encoding="utf-8") as f:
            src = f.read()
        for sym in ("get_llm_with_info", "get_video", "submit_job", "generate_video"):
            self.assertNotIn(sym, src, f"本模块不得出现付费符号 {sym}")


class TestEndpointsAndFrontend(unittest.TestCase):
    def test_router_endpoints_registered(self):
        with open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8") as f:
            src = f.read()
        for ep in ('@router.post("/imitate-video/source/fetch-url")',
                   '@router.post("/imitate-video/jobs")',
                   '@router.get("/imitate-video/jobs/{job_id}/source")'):
            self.assertIn(ep, src)

    def test_frontend_double_entry_and_preview(self):
        with open(os.path.join(ROOT, "frontend", "src", "pages", "ImitateVideo.tsx"),
                  encoding="utf-8") as f:
            ui = f.read()
        for token in ("视频链接", "本地上传", "<video", "rightsAck",
                      "fetchSource", "createJob", "sourceUrl"):
            self.assertIn(token, ui)
        with open(os.path.join(ROOT, "frontend", "src", "api.ts"), encoding="utf-8") as f:
            api = f.read()
        for token in ("ImitateSource", "fetchSource:", "createJob:", "sourceUrl:"):
            self.assertIn(token, api)


if __name__ == "__main__":
    unittest.main()
