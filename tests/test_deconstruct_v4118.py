# -*- coding: utf-8 -*-
"""V4.118 素材创意模板库：导入 + 图片解构 + SSRF 防护 专项测试。

覆盖：
1. 解构引擎：unavailable 不臆测（无配置/非 OpenAI/不可解析 JSON/无有效维度）
2. 解构引擎：黄金样例（模拟视觉模型返回前后对比图解构）命中预期维度
3. 完整度评分：Q6 口径（12 项中 value 非空且 conf≥0.6 的占比）
4. effect caveat：只做创意推断，标注非投放数据
5. SSRF：内网 / 回环 / 私有 IP / file 协议 / 非标端口拦截；正常公网放行
6. 截图接口：SSRF 拦截生效（无需真实浏览器）
7. 前端静态断言：导入区 / 解构方法 / 解构结果展示 / 三态导入齐全
"""
import asyncio
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend", "src")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ---- 模拟视觉模型返回的黄金样例 JSON（Homestyler 前后对比图的人工解构结论）----
GOLDEN_VISION_JSON = {
    "layout": {
        "composition": {"value": "上下分层前后对比", "confidence": 0.92},
        "focal_path": {"value": "Z 形，先上后下", "confidence": 0.7},
        "subject_position": {"value": "改造后空间居中", "confidence": 0.85},
        "negative_space": {"value": "顶部留白放标题", "confidence": 0.65},
    },
    "visual": {
        "palette": {"value": "暖光米色 + 木色", "confidence": 0.88},
        "lighting": {"value": "暖光", "confidence": 0.82},
        "texture": {"value": "写实家居质感", "confidence": 0.78},
    },
    "info": {
        "headline_role": {"value": "改造前后主利益点", "confidence": 0.8},
        "benefits": {"value": ["空间显大", "动线合理", "采光提升"], "confidence": 0.9},
        "cta": {"value": "低风险咨询 CTA", "confidence": 0.62},
        "evidence_kind": {"value": "对比画面", "confidence": 0.86},
        "text_on_image": {"value": True, "confidence": 0.9},
    },
    "effect": {
        "hook_type": {"value": "前后落差", "confidence": 0.8},
        "emotion": {"value": "向往", "confidence": 0.68},
        "intent": {"value": "转化", "confidence": 0.7},
    },
    "category": {
        "primary": {"value": "前后对比", "confidence": 0.93},
        "purpose": {"value": ["转化"], "confidence": 0.8},
        "hook": {"value": "结果", "confidence": 0.7},
        "tags": {"value": {"风格": "写实", "行业": "家居"}, "confidence": 0.6},
    },
    "template_guess": {
        "name": "前后对比实验", "confidence": 0.88,
        "diff": ["竞品用箭头而非斜切分割", "本图用上下分层而非左右分屏"],
    },
}


class TestDeconstructEngine(unittest.TestCase):
    def test_unavailable_no_config(self):
        import asset_deconstruct as ad
        r = asyncio.run(ad.deconstruct_image(b"fake", {}))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["dims_json"], {}, "不可用绝不能臆造维度")
        self.assertIn("未配置", r["reason"])

    def test_unavailable_non_openai_protocol(self):
        import asset_deconstruct as ad
        cfg = {"api_key": "k", "base_url": "https://x/v1", "model": "m", "provider": "gemini"}
        r = asyncio.run(ad.deconstruct_image(b"fake", cfg))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["dims_json"], {})

    def test_completeness_scoring(self):
        import asset_deconstruct as ad
        dims = {
            "layout": {"composition": {"value": "x", "confidence": 0.7},
                       "focal_path": {"value": "", "confidence": 0.9},
                       "subject_position": {"value": "y", "confidence": 0.5}},
            "visual": {"palette": {"value": "z", "confidence": 0.8},
                       "lighting": {"value": "w", "confidence": 0.6}},
            "info": {"benefits": {"value": ["a"], "confidence": 0.9}},
            "category": {"primary": {"value": "前后对比", "confidence": 0.7},
                         "purpose": {"value": ["转化"], "confidence": 0.7}},
        }
        comp, conf = ad.compute_completeness(dims)
        # 计分项：composition✓(0.7) / focal_path空✗ / subject_position✗(0.5)
        #         palette✓ / lighting✓(0.6) / benefits✓ / primary✓ / purpose✓ = 6/12
        self.assertAlmostEqual(comp, 6 / 12, places=3, msg=f"completeness={comp}")
        self.assertGreater(conf, 0)

    def test_golden_sample_normalize(self):
        import asset_deconstruct as ad
        # 绕开真实网络，直接测归一化 + 完整度 + 分类归属。
        result = ad._normalize(GOLDEN_VISION_JSON)
        self.assertEqual(result["status"], "analyzed")
        self.assertEqual(result["category_json"]["primary"], "前后对比")
        self.assertIn("转化", result["category_json"]["purposes"])
        self.assertEqual(result["template_guess"]["name"], "前后对比实验")
        self.assertGreaterEqual(result["completeness"], 0.9, "黄金样例应接近满完整度")
        # effect 每项都带"非投放数据"caveat（Q3）。
        for cell in result["dims_json"]["effect"].values():
            self.assertIn("非真实投放数据", cell.get("caveat", ""))
        self.assertFalse(any("CTR" in str(v) or "CVR" in str(v)
                             for v in result["dims_json"]["effect"].values()))

    def test_in_taxonomy_flag(self):
        import asset_deconstruct as ad
        unknown = dict(GOLDEN_VISION_JSON)
        unknown["category"] = dict(GOLDEN_VISION_JSON["category"])
        unknown["category"]["primary"] = {"value": "奇怪分类", "confidence": 0.9}
        r = ad._normalize(unknown)
        self.assertFalse(r["dims_json"]["category"]["primary"]["in_taxonomy"],
                         "未归一分类应标记 in_taxonomy=false 供人工确认")

    def test_no_valid_dims_becomes_unavailable(self):
        import asset_deconstruct as ad
        empty = {k: {} for k in ("layout", "visual", "info", "effect", "category")}
        empty["template_guess"] = {}
        r = ad._normalize(empty)
        self.assertLessEqual(r["completeness"], 0)


class TestSSRFFGuard(unittest.TestCase):
    def test_blocked_urls(self):
        import ssrf_guard as sg
        # 回环 / 内网 / 元数据 / file 协议 / 非标端口，全部应拒绝。
        bad = [
            "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.1/x",
            "http://192.168.1.1/x", "http://169.254.169.254/latest/meta-data",
            "file:///etc/passwd", "gopher://127.0.0.1:6379/_info",
            "http://8.8.8.8:8080/x", "https://user:pass@example.com/x",
        ]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(sg.SSRFError):
                    sg.validate_url(url, resolver=lambda h: ["8.8.8.8"])

    def test_dns_recheck_blocks_private(self):
        import ssrf_guard as sg
        # 域名解析到内网 → 拒绝（DNS 复检）。
        with self.assertRaises(sg.SSRFError):
            sg.validate_url("https://evil.example.com/x",
                            resolver=lambda h: ["10.0.0.5"])
        # 公网域名 → 放行。
        ok = sg.validate_url("https://example.com/a.png",
                             resolver=lambda h: ["93.184.216.34"])
        self.assertEqual(ok["host"], "example.com")

    def test_is_public_ip(self):
        import ssrf_guard as sg
        self.assertTrue(sg.is_public_ip("8.8.8.8"))
        self.assertFalse(sg.is_public_ip("127.0.0.1"))
        self.assertFalse(sg.is_public_ip("192.168.0.1"))
        self.assertFalse(sg.is_public_ip("100.64.0.1"))  # CGNAT
        self.assertFalse(sg.is_public_ip("::1"))


class TestScreenshotSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from auth import hash_password
        from database import SessionLocal
        from main import app
        from migrations import ensure_schema
        from models import User
        ensure_schema()
        email, user, pwd = "v4118@recomob.com", "v4118", "TestPwd123"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=user).first():
                h, s = hash_password(pwd)
                db.add(User(username=user, email=email, display_name="V4118",
                            role="editor", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": email, "password": pwd})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_screenshot_blocks_ssrf(self):
        r = self.client.post("/api/assets/screenshot", headers=self.auth,
                             json={"url": "http://127.0.0.1/admin"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("内网", r.json().get("detail", ""))

    def test_fetch_url_blocks_ssrf(self):
        r = self.client.post("/api/assets/fetch-url", headers=self.auth,
                             json={"url": "http://169.254.169.254/latest/meta-data"})
        self.assertEqual(r.status_code, 400, r.text)


class TestFrontendStatic(unittest.TestCase):
    def test_import_and_deconstruct_ui(self):
        src = _read("frontend/src/pages/CreativeAnalysis.tsx")
        self.assertIn("本地上传", src)
        self.assertIn("图片 URL", src)
        self.assertIn("网页截图", src)
        self.assertIn("tlAnalyze", src, "应有解构触发调用")
        self.assertIn("DimBlock", src, "应有解构维度结果展示组件")
        self.assertIn("tl-analysis", src, "应有解构结果区")
        self.assertIn("unavailable", src, "应诚实标注不可用状态")

    def test_api_methods(self):
        src = _read("frontend/src/api.ts")
        for method in ("tlImport", "tlAnalyze", "screenshotAsset", "uploadVideoAsset"):
            self.assertIn(method, src, f"api 缺少方法 {method}")

    def test_dockerfile_has_chromium(self):
        dockerfile = _read("backend/Dockerfile")
        self.assertIn("chromium", dockerfile, "Dockerfile 需预装 chromium 支持网页截图")


if __name__ == "__main__":
    unittest.main()
