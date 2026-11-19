"""V4.112 创意工作台「文案 / 图片都生成不出来」修复。

真实故障链（截图里显示「文案未生成成功」「部分图片任务生成失败」）：
- 真实大模型输出的类型不稳定：`industry` 给成 `{"main": "..."}`、`advantages` 给成
  `"a, b, c"`、`channels` 给成 `["Meta"]`；
- `_build_cw_result` 把这些值原样写进 `analysis`，而 `MediaCopyRequest.analysis` /
  `MediaImageRequest.analysis` 是强类型 `LandingAnalysis` → 请求 422；
- 前端把文案异常 `.catch(() => null)` 静默吞掉，只显示「mediaCopy 未返回结果」，
  图片任务也因为「文案失败」被整段跳过 → 表现为文案和图片都生成不出来。

本测试锁住：
1. `analysis_contract` 的收敛规则（只改类型不改语义，幂等，证据不动）；
2. 真实模型形态的分析能被接口接受，文案真的产出、出图任务真的入队；
3. 历史落库的脏分析走同一套兜底（Pydantic before-validator）；
4. 前端把文案失败的真实原因显示出来；10 条路线改为下拉选择。

无模型 / 无网络 / 不发真实费用。
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from auth import hash_password  # noqa: E402
from database import SessionLocal  # noqa: E402
from main import app  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from models import User  # noqa: E402
from analysis_contract import as_channels, as_text, as_text_list, normalize_analysis  # noqa: E402
from schemas import LandingAnalysis  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"

ADMIN_EMAIL = "contract112@recomob.com"
ADMIN_USER = "contract112"
ADMIN_PWD = "TestPwd123"

# 真实模型常见的「类型不对」形态：对象当字符串、字符串当数组、channels 给平台名
MODEL_OUT = {
    "title": "Soundora Air Pro",
    "summary": "Wireless earbuds with 40H battery and ANC.",
    "boxes": {"industry": {"main": "Consumer Electronics"},
              "coreAudience": "urban commuters",
              "purchaseMotivation": "long battery", "priceBand": "$50-80"},
    "brief": {"promotionGoal": "conversions",
              "targetAudience": "urban commuters",
              "sellingPoints": "40H playtime, ANC, IPX5"},
    "recommendedPlatforms": ["Meta"],
}

COPY_OUT = {
    # 带上「up to」限定：证据契约要求承诺必须保留原文限定，否则会被判 needs_revision
    "primary_text": "Up to 40 hours of calm with ANC earbuds and a pocket case.",
    "headline": ["Up to 40H Playtime", "Calm Commutes Start Here", "ANC That Lasts"],
    "description": "Free shipping. 30-day returns.",
    "cta": "Shop Now",
}

DIRTY_ANALYSIS = {
    "url": "https://soundora.example/air-pro",
    "industry": {"main": "Consumer Electronics"},
    "type": {"label": "电商"},
    "audience": "commuters",
    "advantages": "40H playtime, ANC, IPX5",
    "competitors": "A, B",
    "channels": ["Meta"],
    "language": "en",
    "brand": "Soundora",
    "evidence_index": [{"evidence_id": "E001", "quote": "Up to 40 hours of playtime.",
                        "char_start": 0, "char_end": 26}],
    "evidence_ids": ["E001"],
    "evidence_snapshot_id": "evs_test",
    "evidence_gate": "ok",
    "facts": "40 hours of playtime",
}


class FakeLLM:
    """返回固定 JSON 的假模型：不联网、不计费，只用于验证链路契约。"""

    def __init__(self, payload):
        self.payload = payload

    async def chat(self, sys_prompt, user_prompt=None):
        return json.dumps(self.payload, ensure_ascii=False)


class TestAnalysisContractV4112(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="CT",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login",
                            json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}
        cls._orig = {}

    def setUp(self):
        """把两类模型调用都换成假模型（分析 / 文案各一处导入点），并记录原函数。"""
        import media_ad
        import routers
        self._orig["routers"] = routers.get_llm_with_info
        self._orig["media_ad"] = media_ad.get_llm_with_info
        routers.get_llm_with_info = lambda db, usage="analysis": (
            FakeLLM(MODEL_OUT), {"provider": "fake", "model": "fake", "role": usage,
                                 "source": "llm", "fallback": False, "config_id": None})
        # V4.113：文案入口新增 allow_reuse 关键字，桩函数必须一并接受
        media_ad.get_llm_with_info = lambda db, usage="copy", **kw: (
            FakeLLM(COPY_OUT), {"provider": "fake", "model": "fake", "role": usage,
                                "source": "llm", "fallback": False, "config_id": None})

    def tearDown(self):
        import media_ad
        import routers
        routers.get_llm_with_info = self._orig["routers"]
        media_ad.get_llm_with_info = self._orig["media_ad"]

    # ---------------- 收敛规则 ----------------

    def test_01_as_text_accepts_object_and_list(self):
        self.assertEqual(as_text({"main": "Consumer Electronics"}), "Consumer Electronics")
        self.assertEqual(as_text(["a", "b"]), "a；b")
        self.assertEqual(as_text(None), "")
        self.assertEqual(as_text(12), "12")

    def test_02_as_text_list_splits_but_keeps_meaning(self):
        self.assertEqual(as_text_list("40H playtime, ANC, IPX5"),
                         ["40H playtime", "ANC", "IPX5"])
        self.assertEqual(as_text_list("a\nb\nc"), ["a", "b", "c"])
        # 长句不按逗号拆碎
        long_sentence = ("Built for commuters who want calm focus every single day, "
                         "with fast pairing and a pocket-sized charging case included.")
        self.assertEqual(as_text_list(long_sentence), [long_sentence])
        self.assertEqual(as_text_list(None), [])

    def test_03_channels_become_objects(self):
        self.assertEqual(as_channels(["Meta", "Google"]),
                         [{"platform": "Meta", "reason": ""},
                          {"platform": "Google", "reason": ""}])
        self.assertEqual(as_channels([{"platform": "Meta", "reason": "broad reach"}]),
                         [{"platform": "Meta", "reason": "broad reach"}])
        # 去重保序
        self.assertEqual(len(as_channels(["Meta", "Meta"])), 1)

    def test_04_normalize_is_idempotent_and_keeps_evidence(self):
        once = normalize_analysis(DIRTY_ANALYSIS)
        twice = normalize_analysis(once)
        self.assertEqual(once, twice, "收敛必须幂等")
        self.assertIsInstance(once["industry"], str)
        self.assertIsInstance(once["advantages"], list)
        self.assertEqual(once["channels"], [{"platform": "Meta", "reason": ""}])
        # 证据链原样保留，不能被「收敛」改写
        self.assertEqual(once["evidence_index"], DIRTY_ANALYSIS["evidence_index"])
        self.assertEqual(once["evidence_ids"], ["E001"])
        self.assertEqual(once["evidence_snapshot_id"], "evs_test")

    # ---------------- 真实形态的分析能走到生成 ----------------

    def test_05_analyze_output_is_a_valid_landing_analysis(self):
        text = ("Soundora Air Pro wireless earbuds with 40 hours playtime, active noise "
                "cancellation, IPX5 water resistance and free worldwide shipping.")
        r = self.client.post("/api/cw/analyze",
                             json={"text": text, "platforms": ["Meta"]},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        analysis = r.json()["analysis"]
        # 模型给了对象 / 字符串 / 字符串数组，落库前必须已收敛
        self.assertIsInstance(analysis.get("industry"), str)
        self.assertEqual(analysis.get("advantages"), ["40H playtime", "ANC", "IPX5"])
        self.assertEqual(analysis.get("audience"), "urban commuters")
        self.assertEqual(analysis.get("channels"), [{"platform": "Meta", "reason": ""}])
        # 关键回归：这份分析必须能通过强类型校验（此前 422 就死在这一步）
        LandingAnalysis(**analysis)

    def test_06_copy_really_generates_with_dirty_analysis(self):
        r = self.client.post("/api/media-campaign/copy",
                             json={"analysis": DIRTY_ANALYSIS, "platform": "Meta", "lang": "en"},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["fields"].get("headline"), "文案必须真的产出标题")
        self.assertTrue(d["validation"]["valid"], d.get("validation"))
        self.assertEqual(d["validation"]["status"], "ok", d.get("validation"))

    def test_07_image_job_accepts_dirty_analysis(self):
        payload = {
            "images_request": {
                "analysis": DIRTY_ANALYSIS, "platform": "Meta", "lang": "en",
                "copy_fields": {},
                "copy_variants": [{"headline": "H", "sub": "S", "cta": "Shop Now",
                                   "brand": "Soundora", "label": "Meta"}],
                "style_opts": {"creative_direction": "", "content_style": "",
                               "color_scheme": "",
                               "creative_plan": {"routes": [], "supplement": "",
                                                 "platform": "Meta",
                                                 "overlay_mode": "pure", "brief": None}},
                "slots": [{"size": "1080x1080", "placement": "Meta",
                           "spec_id": "", "route_key": ""}],
                "spec_version": "", "total_pixels": 1080 * 1080,
                "overlay_mode": "pure",
            },
            "idempotency_key": "v4112_dirty_analysis",
        }
        r = self.client.post("/api/generation-jobs", json=payload, headers=self.auth)
        self.assertIn(r.status_code, (200, 202), r.text)
        self.assertTrue(r.json().get("job_id"), "出图任务必须真的入队")

    # ---------------- 前端：失败原因可见 + 路线下拉 ----------------

    def test_08_frontend_surfaces_copy_failure_reason(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertNotIn(
            "api.mediaCopy({ analysis, platform: p, lang: 'en', brief: confirmedBrief() }).catch(() => null)",
            page, "文案接口异常不能再被静默吞成 null")
        self.assertIn("文案生成失败：", page)
        self.assertIn("接口未返回结果", page)

    def test_09_routes_are_a_dropdown_not_a_grid(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        start = page.index("图片创意规划（")
        end = page.index("补充创意指令（可选）", start)
        block = page[start:end]
        self.assertIn("cwb-route-picker", block, "10 条路线应改为下拉选择")
        self.assertIn("<select", block)
        self.assertIn("用于生成", block, "下拉后仍需能标记哪条路线参与生成")
        self.assertNotIn('className="cwb-routes"', block, "不应再平铺 10 张路线卡片")
        # 下拉只展开当前一条：卡片不是 map 出来的列表
        self.assertIn("cwb-route-single", block)
        # 数量与换一批能力保留
        self.assertIn("换一批路线", block)
        self.assertIn("routes.filter(r => r.selected).length", page)

    def test_10_styles_for_route_picker(self):
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".cwb-route-picker", css)
        self.assertIn(".cwb-route-select", css)
        self.assertNotIn(".cwb-routes { display: grid", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
