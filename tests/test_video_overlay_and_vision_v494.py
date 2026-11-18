"""V4.94：阶段二播放层叠加 + 阶段三成片视觉复核门测试。

无真实模型 / 无网络 / 无数据库；抽帧用例用本机 imageio-ffmpeg 生成的纯色测试片，
不可用时跳过。重点验证：叠加文案只来自黄金词典、视觉工具不可用不冒充已复核、
真实识别出文字才判违规、错拼与词典外文字能被拒绝。
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from brand_lexicon import build_lexicon, build_text_overlay  # noqa: E402
import video_vision_audit as vva  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

ANALYSIS = {
    "product": "NovaX 创作应用", "brand": "NovaX",
    "facts": ["在真实任务中完成创作"],
    "brief": {"cta": "立即下载"},
}


def _rec(texts):
    async def fake(frames, cfg):
        return {"status": "ok", "texts": texts, "model": "fake-vl", "frames_sent": len(frames)}
    return fake


class TestStage2Overlay(unittest.TestCase):
    def test_01_overlay_only_from_lexicon(self):
        lex = build_lexicon(ANALYSIS)
        plan = {"approved_texts": ["FakeBrand"], "cta": "假的行动号召"}
        spec = build_text_overlay(lex, plan, {})
        self.assertTrue(spec["enabled"])
        texts = [i["text"] for i in spec["items"]]
        self.assertEqual(texts, ["NovaX", "立即下载"])
        self.assertNotIn("FakeBrand", texts)
        self.assertEqual(spec["source"], "brand_lexicon")
        self.assertEqual(spec["text_policy"], "none")

    def test_02_no_confirmed_brand_means_no_overlay(self):
        spec = build_text_overlay(build_lexicon({"product": "未知产品"}))
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["items"], [])


class TestStage3Vision(unittest.TestCase):
    def test_03_sample_times_dedup(self):
        times = vva._sample_times(2.0, 3)
        self.assertEqual(len(times), len(set(times)))
        self.assertLess(times[-1], 2.0)

    def test_04_extract_frames_from_real_generated_video(self):
        exe = vva._ffmpeg_exe()
        if not exe:
            self.skipTest("imageio-ffmpeg 不可用")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sample.mp4")
            r = subprocess.run(
                [exe, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2",
                 "-pix_fmt", "yuv420p", path],
                capture_output=True, timeout=40)
            if r.returncode != 0 or not os.path.exists(path):
                self.skipTest("ffmpeg 测试片生成失败")
            frames, info = vva.extract_frames(path, 2.0, 3)
            self.assertEqual(info["status"], "ok")
            self.assertTrue(frames)
            self.assertTrue(all(f.startswith(b"\xff\xd8") for f in frames))

    def test_05_missing_model_cfg_is_unavailable_not_ok(self):
        rep = asyncio.run(vva.recognize_frames([b"\xff\xd8"], None))
        self.assertEqual(rep["status"], "unavailable")
        self.assertIn("未配置", rep["reason"])

    def test_06_parse_texts_tolerates_code_fence(self):
        texts, err = vva._parse_texts('```json\n{"texts":["NovaX", "立即下载"]}\n```')
        self.assertEqual(err, "")
        self.assertEqual(texts, ["NovaX", "立即下载"])
        _, err = vva._parse_texts("我看不到字")
        self.assertNotEqual(err, "")

    def test_07_zero_text_policy_blocks_any_visible_text(self):
        with patch.object(vva, "extract_frames", return_value=([b"f"], {"status": "ok"})), \
             patch.object(vva, "recognize_frames", new=_rec(["NovaX"])):
            rep = asyncio.run(vva.audit_video_vision(
                "x.mp4", build_lexicon(ANALYSIS), "none", {"api_key": "k"}))
        self.assertEqual(rep["status"], "violation")
        self.assertEqual(rep["violations"][0]["type"], "onscreen_text")

    def test_08_approved_only_accepts_exact_lexicon_text(self):
        with patch.object(vva, "extract_frames", return_value=([b"f"], {"status": "ok"})), \
             patch.object(vva, "recognize_frames", new=_rec(["NovaX"])):
            rep = asyncio.run(vva.audit_video_vision(
                "x.mp4", build_lexicon(ANALYSIS), "approved_only", {"api_key": "k"}))
        self.assertEqual(rep["status"], "ok")
        self.assertEqual(rep["violations"], [])

    def test_09_approved_only_rejects_brand_typo(self):
        with patch.object(vva, "extract_frames", return_value=([b"f"], {"status": "ok"})), \
             patch.object(vva, "recognize_frames", new=_rec(["Novax"])):
            rep = asyncio.run(vva.audit_video_vision(
                "x.mp4", build_lexicon(ANALYSIS), "approved_only", {"api_key": "k"}))
        self.assertEqual(rep["status"], "violation")
        self.assertEqual(rep["violations"][0]["type"], "brand_spelling_mismatch")

    def test_10_unavailable_does_not_pretend_passed(self):
        with patch.object(vva, "extract_frames",
                          return_value=([], {"status": "unavailable", "reason": "抽帧失败"})):
            rep = asyncio.run(vva.audit_video_vision("missing.mp4"))
        self.assertEqual(rep["status"], "unavailable")
        self.assertIn("未复核", rep["note"])


class TestWiring(unittest.TestCase):
    def test_11_backend_and_frontend_wiring(self):
        tasks = (BACKEND / "creative_tasks.py").read_text(encoding="utf-8")
        self.assertIn("TEXT_VISION_MISMATCH", tasks)
        self.assertIn("await _vision_audit_of", tasks)
        self.assertIn('"vision_audit": vision', tasks)
        router = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn('"text_overlay": build_text_overlay', router)
        self.assertIn('"vision_audit": vision_audit_cfg', router)
        front = BACKEND.parent / "frontend" / "src"
        self.assertIn("VideoTextOverlay", (front / "pages" / "VideoStudio.tsx").read_text(encoding="utf-8"))
        self.assertIn("vs-overlay-layer", (front / "styles.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
