# -*- coding: utf-8 -*-
"""V4.121 素材创意模板库：视频解构（抽帧 + 分镜/钩子/字幕/节奏）专项测试。

覆盖：
1. 框架版本 / 视频专属维度键固定，完整度仍用统一 12 项口径；
2. 诚实降级：无帧 / 各帧解构不可用 / 字幕 OCR 不可用都不臆造内容；
3. 真实视觉通道聚合：逐帧解构结果合成视频维度，分类与 purpose/hook 跨帧合并；
4. 归并复用：视频框架进入同一套归并键与 golden 完整度，骨架溯源记录视频框架；
5. 接口集成：视频可解构落 unavailable / 成功落库；
6. 前端静态断言：视频解构按钮放开、视频维度分区、字幕 caveat 展示。
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend", "src")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _vision_result(primary="前后对比", purposes=None, hooks=None, comp=0.92):
    """一份模拟的真实视觉解构结果（结构与 asset_deconstruct._normalize 一致）。"""
    return {
        "framework_version": "asset-deconstruct/1.0",
        "status": "analyzed", "completeness": comp, "confidence": 0.86,
        "dims_json": {
            "layout": {"composition": {"value": "左右分屏对比", "confidence": 0.9},
                       "subject_position": {"value": "右侧改造后", "confidence": 0.8}},
            "visual": {"palette": {"value": "冷色调", "confidence": 0.8}},
            "info": {"benefits": {"value": ["空间显大"], "confidence": 0.9},
                     "headline_role": {"value": "前后主利益点", "confidence": 0.8}},
            "effect": {"hook_type": {"value": "结果", "confidence": 0.85}},
            "category": {"primary": {"value": primary, "confidence": 0.9},
                         "purpose": {"value": purposes or ["转化"], "confidence": 0.8},
                         "hook": {"value": hooks or ["结果"], "confidence": 0.8}},
        },
        "category_json": {"primary": primary, "purposes": purposes or ["转化"],
                          "hooks": hooks or ["结果"], "taxonomy_version": "asset-category/1.0"},
        "template_guess": {"name": "前后对比模板", "confidence": 0.8, "diff": []},
        "model_info": {"provider": "openai", "model": "vision-test", "role": "vision"},
    }


async def _fake_vision(_frame, _cfg):
    return _vision_result()


async def _fake_ocr(*_args):
    return {"status": "ok", "texts": ["立即下载"]}


class TestVideoDeconstructRules(unittest.TestCase):
    def test_framework_and_video_dim_keys(self):
        import asset_video_deconstruct as avd
        self.assertEqual(avd.FRAMEWORK_VERSION, "asset-video-deconstruct/1.0")
        self.assertEqual(set(avd.VIDEO_DIM_KEYS), {
            "shot_sequence", "hook_moment", "subtitle_strategy", "rhythm",
            "frame_count", "duration_sec"})

    def test_no_frames_unavailable(self):
        import asset_video_deconstruct as avd
        r = asyncio.run(avd.deconstruct_video([], {}, duration_sec=10))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["dims_json"], {}, "无帧绝不臆造分镜 / 字幕")
        self.assertEqual(r["framework_version"], "asset-video-deconstruct/1.0")

    def test_all_frames_failed_unavailable(self):
        import asset_deconstruct as ad
        import asset_video_deconstruct as avd
        unavailable = ad._unavailable("视觉模型不可用")
        async def always_unavailable(_frame, _cfg):
            return unavailable
        with patch.object(ad, "deconstruct_image", side_effect=always_unavailable):
            r = asyncio.run(avd.deconstruct_video([b"a", b"b"], {}, duration_sec=8))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["dims_json"], {})
        self.assertIn("均不可用", r["reason"])

    def test_aggregate_reuses_real_vision_and_ocr(self):
        import asset_deconstruct as ad
        import asset_video_deconstruct as avd
        ocr = {"status": "ok", "texts": ["免费试用", "立即咨询", "立即咨询"]}
        with patch.object(ad, "deconstruct_image", side_effect=_fake_vision):
            r = asyncio.run(avd.deconstruct_video(
                [b"a", b"b", b"c"], {"api_key": "k"}, duration_sec=15.0,
                times=[0.5, 7.5, 14.4], ocr=ocr))
        self.assertEqual(r["status"], "analyzed")
        self.assertEqual(r["framework_version"], "asset-video-deconstruct/1.0")
        video = r["dims_json"]["video"]
        self.assertEqual(video["frame_count"]["value"], 3)
        self.assertEqual(video["duration_sec"]["value"], 15.0)
        self.assertIn("分镜1", video["shot_sequence"]["value"])
        self.assertIn("分镜3", video["shot_sequence"]["value"])
        self.assertIn("免费试用", video["subtitle_strategy"]["value"])
        self.assertEqual(video["subtitle_strategy"]["value"].count("立即咨询"), 1, "OCR 文本需去重")
        self.assertIn("非逐帧精算", video["rhythm"]["caveat"])
        self.assertEqual(r["category_json"]["primary"], "前后对比")
        self.assertEqual(r["model_info"]["frames_sent"], 3)
        # 完整度口径仍为统一 12 项，视频专属维度不另行放大分数。
        self.assertLessEqual(r["completeness"], 1.0)
        self.assertGreaterEqual(r["completeness"], 0.5)

    def test_subtitle_unavailable_is_honest(self):
        import asset_deconstruct as ad
        import asset_video_deconstruct as avd
        with patch.object(ad, "deconstruct_image", side_effect=_fake_vision):
            r = asyncio.run(avd.deconstruct_video(
                [b"a"], {}, duration_sec=5, ocr={"status": "unavailable", "reason": "未配置视觉模型"}))
        sub = r["dims_json"]["video"]["subtitle_strategy"]
        self.assertEqual(sub["value"], "")
        self.assertEqual(sub["confidence"], 0.0)
        self.assertIn("未臆造字幕内容", sub["caveat"])

    def test_partial_frames_marked(self):
        import asset_deconstruct as ad
        import asset_video_deconstruct as avd
        bad = ad._unavailable("该帧识别失败")
        async def side(_frame, _cfg):
            return bad if _frame == b"bad" else _vision_result()
        with patch.object(ad, "deconstruct_image", side_effect=side):
            r = asyncio.run(avd.deconstruct_video([b"good", b"bad"], {}, duration_sec=6))
        self.assertEqual(r["status"], "analyzed")
        self.assertIn("1/2 帧解构成功", r["dims_json"]["video"]["shot_sequence"]["caveat"])
        self.assertEqual(r["model_info"]["frames_usable"], 1)


class TestMergeReuseV4121(unittest.TestCase):
    def test_video_framework_enters_same_merge_key(self):
        import asset_video_deconstruct as avd
        import asset_merge as am
        analysis = {
            "status": "analyzed", "framework_version": avd.FRAMEWORK_VERSION,
            "completeness": 0.92,
            "category_json": {"primary": "前后对比", "purposes": ["转化"], "hooks": ["结果"]},
        }
        e = am.eligibility(analysis)
        self.assertTrue(e["eligible"], e["reason"])
        self.assertEqual((e["primary"], e["purpose"], e["hook"]), ("前后对比", "转化", "结果"))

    def test_unknown_framework_still_rejected(self):
        import asset_merge as am
        analysis = {"status": "analyzed", "framework_version": "unknown/9.9", "completeness": 0.9,
                    "category_json": {"primary": "前后对比", "purposes": ["转化"], "hooks": ["结果"]}}
        self.assertIn("不匹配", am.eligibility(analysis)["reason"])

    def test_taxonomy_exposes_both_frameworks(self):
        import asset_merge as am
        import asset_video_deconstruct as avd
        t = am.taxonomy()
        self.assertIn("asset-deconstruct/1.0", t["supported_deconstruct_frameworks"])
        self.assertIn(avd.FRAMEWORK_VERSION, t["supported_deconstruct_frameworks"])
        self.assertEqual(t["video_deconstruct_framework"], avd.FRAMEWORK_VERSION)

    def test_skeleton_traces_video_framework(self):
        import asset_merge as am
        import asset_video_deconstruct as avd
        analysis = _vision_result()
        analysis["id"] = 9
        analysis["framework_version"] = avd.FRAMEWORK_VERSION
        skeleton = am.build_skeleton(analysis)
        self.assertEqual(skeleton["source_framework"], avd.FRAMEWORK_VERSION)
        self.assertEqual(skeleton["golden_analysis_id"], 9)


class TestVideoAnalyzeApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User
        ensure_schema()
        email, user, pwd = "v4121@recomob.com", "v4121", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4121",
                            role="editor", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def _new_asset(self, title):
        r = self.client.post("/api/template-library/assets", headers=self.auth, json={
            "title": title, "media_kind": "video", "source_type": "video",
            "file": "/files/v4121_test.mp4", "duration_sec": 12.0,
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_video_analyze_unavailable_lands_record(self):
        # 文件存在但抽帧不可用 → 落 unavailable，不抛 500、不臆造维度。
        from routers import UPLOAD_DIR
        fake = os.path.join(UPLOAD_DIR, "v4121_test.mp4")
        with open(fake, "wb") as f:
            f.write(b"not-a-real-video")
        try:
            aid = self._new_asset("抽帧不可用视频")
            with patch("video_vision_audit.extract_frames",
                       return_value=([], {"status": "unavailable", "reason": "测试抽帧失败"})):
                r = self.client.post(f"/api/template-library/analyze/{aid}", headers=self.auth)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["status"], "unavailable")
            self.assertEqual(body["framework_version"], "asset-video-deconstruct/1.0")
            self.assertEqual(body["dims_json"], {})
            self.assertEqual(body["completeness"], 0, "不可用不得有完整度分数")
        finally:
            if os.path.exists(fake):
                os.remove(fake)

    def test_video_analyze_success_with_real_channels_patched(self):
        from routers import UPLOAD_DIR
        import video_vision_audit as vva
        fake = os.path.join(UPLOAD_DIR, "v4121_test.mp4")
        with open(fake, "wb") as f:
            f.write(b"fake")
        try:
            aid = self._new_asset("视频解构成功样例")
            with patch("video_vision_audit.extract_frames",
                       return_value=([b"a", b"b"], {"status": "ok", "times": [0.5, 11.4]})), \
                 patch.object(vva, "recognize_frames",
                              side_effect=_fake_ocr), \
                 patch("creative_tasks._vision_model_cfg", return_value={"api_key": "k", "model": "m"}), \
                 patch("asset_deconstruct.deconstruct_image", side_effect=_fake_vision):
                r = self.client.post(f"/api/template-library/analyze/{aid}", headers=self.auth)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["status"], "analyzed")
            self.assertEqual(body["framework_version"], "asset-video-deconstruct/1.0")
            self.assertIn("video", body["dims_json"])
            self.assertIn("立即下载", body["dims_json"]["video"]["subtitle_strategy"]["value"])
            self.assertEqual(body["category_json"]["primary"], "前后对比")
        finally:
            if os.path.exists(fake):
                os.remove(fake)


class TestFrontendStaticV4121(unittest.TestCase):
    def test_video_deconstruct_ui(self):
        src = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertIn("视频解构（分镜/钩子/字幕/节奏）", src, "解构结果区应有视频维度分区")
        self.assertIn("shot_sequence: '分镜序列'", src)
        self.assertIn("subtitle_strategy: '字幕/画面文字'", src)
        self.assertNotIn("视频解构将在 V4.121 提供", src, "视频解构入口不应再被拦截")
        self.assertNotIn("解构在 V4.121", src, "导入提示不应再说解构留待后续版本")

    def test_backend_no_video_defer_message(self):
        src = _read("backend/routers.py")
        self.assertNotIn("视频解构将在 V4.121 提供", src)


if __name__ == "__main__":
    unittest.main()
