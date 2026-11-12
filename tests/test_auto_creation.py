"""V4.45 / D1–D3：默认自动创作的可运行回归（A01–A08 + N03 + A10/A13/A15）。

后端全部是纯函数断言，不调用模型、不连生产库；前端会话用例通过 esbuild
把 `creationSession.ts` 打包后交给 node 真实执行，验证默认 auto、旧会话迁移
与计划版本失效。四种状态分开记录：本文件只提供「代码已实现 + 模拟测试通过」。
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from creation_planner import (build_recommendation, render_visual_summary,
                              build_structured_concepts, PLANNER_VERSION,
                              ASSET_LABELS)
from industry_profiles import (INDUSTRY_PROFILES, PROFILE_SCHEMA_VERSION,
                               list_profiles, resolve_profile, scene_policy)
from claims import EvidenceSnapshot, qualifier_hits
from media_platforms import SPEC_VERSION, validate_platform, MediaRuleError

ROOT = Path(_bootstrap.ROOT)
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"


def _analysis(**kw):
    """模拟一次真实落地页分析结果：含唯一 [E###] 命名空间的可定位原文快照。"""
    a = {
        "url": "https://www.anker.com/charger",
        "final_url": "https://www.anker.com/charger",
        "brand": "Anker", "brand_status": "confirmed",
        "type": "ecommerce", "industry": "consumer electronics",
        "audience": "多设备通勤用户",
        "facts": ["Qi2 certified foldable charging station",
                  "magnetic stand with soft night light"],
        "evidence_index": [
            {"evidence_id": "E001", "quote": "Qi2 certified foldable charging station "
             "with up to 20% less battery aging in battery care mode, laboratory tested, "
             "results may vary", "char_start": 0, "char_end": 120},
            {"evidence_id": "E002", "quote": "magnetic stand with soft night light",
             "char_start": 121, "char_end": 160},
        ],
    }
    a.update(kw)
    return a


def _rec(**kw):
    plats = kw.pop("platforms", ["Meta"])
    return build_recommendation(_analysis(**kw), plats)


class TestAutoRecommendation(unittest.TestCase):
    """A01：新建会话的自动策划结果可直接展示，只需确认媒体。"""

    def test_01_contract_is_complete_and_deterministic(self):
        r = _rec()
        for key in ("schema_version", "status", "recommended_visual_summary",
                    "rationale", "missing_inputs", "blocking_reasons",
                    "product_profile", "visual_brief", "structured_concepts",
                    "coverage_summary", "quality_gate", "delivery_grade",
                    "pricing_gate", "plan_id", "plan_version"):
            self.assertIn(key, r, key)
        self.assertEqual(r["schema_version"], PLANNER_VERSION)
        self.assertEqual(r["mode"], "auto")
        self.assertLessEqual(len(r["rationale"]), 3)
        self.assertTrue(r["product_profile"]["source"])
        self.assertEqual(r["plan_id"], _rec()["plan_id"], "策划必须确定性可复现")
        self.assertEqual(r["plan_version"], _rec()["plan_version"])

    def test_02_summary_is_readable_and_never_dangling(self):
        for facts in (
            ["Qi2 certified foldable charging station", "magnetic stand"],
            ["可折叠磁吸床头充电站支持多设备同时充电并自动断电保护，适配主流手机与耳机，附带一年有限质保与全球联保服务条款说明文字继续加长以触发限长截断", "另一条很长的中文细节描述用于检验截断边界处理是否正确且不应该出现逗号或分号结尾的残句"],
            [],
        ):
            r = _rec(facts=facts)
            s = r["recommended_visual_summary"]
            self.assertGreaterEqual(len(s), 60)
            self.assertLessEqual(len(s), 120)
            self.assertTrue(s.endswith("。"), s)
            self.assertFalse(s.rstrip("。").endswith(("，", "；", "、")), s)
            self.assertIn("主体", s)
            self.assertIn("构图", s)

    def test_03_summary_and_brief_share_one_object(self):
        from creation_planner import SUBJECT_SHORT
        r = _rec()
        brief = r["visual_brief"]
        # 描述由 brief 确定性渲染，主体使用 brief.entity_type 对应的短版，不另起一次生成
        self.assertIn(SUBJECT_SHORT[brief["entity_type"]], r["recommended_visual_summary"])
        self.assertEqual(brief["version"], PLANNER_VERSION)
        self.assertEqual(brief["required_tasks"], r["coverage_summary"]["required_tasks"])
        self.assertEqual(render_visual_summary(brief), r["recommended_visual_summary"])
        self.assertIn("构图", r["recommended_visual_summary"])
        self.assertIn("放置", r["recommended_visual_summary"])

    def test_04_coverage_uses_real_platform_catalog(self):
        r = build_recommendation(_analysis(), ["Meta", "Moloco"])
        self.assertEqual(r["coverage_summary"]["platforms"], ["Meta", "Moloco"])
        self.assertGreater(r["coverage_summary"]["required_tasks"], 0)
        self.assertGreater(len(r["coverage_summary"]["asset_roles"]), 1)
        self.assertEqual(r["coverage_summary"]["spec_version"], SPEC_VERSION)
        self.assertFalse(r["coverage_summary"]["spec_verified"])

    def test_05_planner_has_no_model_or_network_calls(self):
        src = (BACKEND / "creation_planner.py").read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "openai", "get_llm",
                          "FallbackLLM", "generate_images"):
            self.assertNotIn(forbidden, src, forbidden)


class TestCrossIndustryProfiles(unittest.TestCase):
    """A03：电商 / 软件 / 旅游 / B2B 主体与场景各自匹配，不随机套实体动作。"""

    def test_06_four_industries_have_distinct_subject_and_scene(self):
        out = {}
        for key in ("ecommerce", "subscription", "travel_local", "b2b_service"):
            a = _analysis(industry_profile=key, type=key)
            r = build_recommendation(a, ["Meta"])
            b = r["visual_brief"]
            out[key] = (b["subject"], b["scene"], b["subject_asset"])
            self.assertGreater(len(b["forbidden_inferences"]), 0, key)
            self.assertIn(b["subject_asset"], ASSET_LABELS, key)
        self.assertEqual(len({x[0] for x in out.values()}), 4)
        self.assertEqual(len({x[1] for x in out.values()}), 4)
        self.assertEqual(out["ecommerce"][2], "official_sku_image")
        self.assertEqual(out["subscription"][2], "real_ui")

    def test_07_no_hash_action_pool_and_profile_is_versioned(self):
        src = (BACKEND / "creative_config.py").read_text(encoding="utf-8")
        self.assertNotIn("_ACTION_POOL", src)
        self.assertNotIn("_SETTING_POOL", src)
        for key, p in INDUSTRY_PROFILES.items():
            self.assertEqual(p["profile_id"], key)
            self.assertEqual(p["version"], PROFILE_SCHEMA_VERSION)
        self.assertTrue(all("version" in x and "profile_id" in x for x in list_profiles()))
        self.assertEqual(_rec()["industry_profile_version"], PROFILE_SCHEMA_VERSION)

    def test_08_scene_policy_is_declared_not_random(self):
        for key in INDUSTRY_PROFILES:
            p = scene_policy(resolve_profile(key=key))
            self.assertTrue(p["allowed_scene_types"], key)
            self.assertTrue(p["default_action"], key)
            self.assertTrue(p["forbidden_inferences"], key)
            # 通用兜底画像必须显式禁止「随机加入人物 / 实体产品」制造多样性
            self.assertIn("随机", " ".join(
                scene_policy(resolve_profile(key="general"))["forbidden_inferences"]))


class TestBlockingAndEvidence(unittest.TestCase):
    """A04 / A06 / A08 / A10：阻断项必须在策划阶段显式给出。"""

    def test_09_multi_product_page_needs_input(self):
        r = _rec(type="marketplace collection blog 多商品目录页")
        self.assertEqual(r["status"], "needs_input")
        self.assertTrue(r["product_profile"]["multi_product_page"])
        self.assertTrue(any("A04" in x for x in r["blocking_reasons"]))
        self.assertEqual(r["product_profile"]["sku_or_plan"], "", "不得拼接多个 SKU")

    def test_10_missing_evidence_blocks(self):
        a = _analysis()
        a.pop("evidence_index")
        r = build_recommendation(a, ["Meta"])
        self.assertEqual(r["status"], "needs_input")
        self.assertTrue(any("证据快照" in x for x in r["blocking_reasons"]))
        self.assertEqual(r["evidence"]["review_status"], "legacy_unverified")

    def test_11_unlocatable_quantified_claim_is_removed(self):
        r = _rec(facts=["电池老化最多降低 20%，需开启护理模式", "磁吸支架"],
                 evidence_index=[{"evidence_id": "E001", "quote": "magnetic stand only",
                                  "char_start": 0, "char_end": 20}])
        c = r["structured_concepts"][0]
        self.assertEqual(c["claim_status"], "unsupported")
        self.assertEqual(c["claim_ids"], [])
        self.assertNotIn("20", c["promise"])
        self.assertTrue(any("A06" in x for x in r["missing_inputs"]))
        self.assertIn(c["concept_id"], r["claim_audit"]["unsupported"])

    def test_12_invalid_evidence_ids_are_not_accepted(self):
        r = _rec(evidence_index=[{"evidence_id": "EV_S001", "quote": "legacy id",
                                  "char_start": 0, "char_end": 10}])
        self.assertEqual(r["status"], "needs_input")
        self.assertEqual(r["evidence"]["count"], 0)

    def test_13_unknown_platform_is_rejected(self):
        r = build_recommendation(_analysis(), ["NotAPlatform"])
        self.assertEqual(r["status"], "needs_input")
        self.assertTrue(any("未知媒体平台" in x for x in r["blocking_reasons"]))
        with self.assertRaises(MediaRuleError):
            validate_platform("NotAPlatform")
        router = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn("validate_platform", router)

    def test_14_missing_product_asset_is_draft_only(self):
        r = _rec()
        self.assertEqual(r["status"], "draft_only")
        self.assertEqual(r["product_profile"]["assets"], [])
        self.assertTrue(any("官方商品图" in x for x in r["missing_inputs"]))
        self.assertTrue(any("A08" in x for x in r["missing_inputs"]))
        self.assertEqual(r["delivery_grade"], "draft")
        self.assertFalse(r["quality_gate"]["deliverable"])
        self.assertIn("草案", r["quality_gate"]["note"])


class TestQualifiersAndPricing(unittest.TestCase):
    """A05 / A07：限定条件与地区报价不得扩大或臆测。"""

    def test_15_hard_qualifiers_are_propagated(self):
        r = _rec()
        frags = r["claim_audit"]["must_preserve_qualifiers"]
        self.assertTrue(any("up to" in x.lower() for x in frags), frags)
        self.assertTrue(any("laboratory" in x.lower() or "battery care" in x.lower()
                            for x in frags), frags)
        for c in r["structured_concepts"]:
            self.assertEqual(c["must_preserve_qualifiers"], frags)
        self.assertIn("upper_bound", qualifier_hits(
            EvidenceSnapshot.from_analysis(_analysis()).source_text()))

    def test_16_summary_never_shows_bare_quantified_claim(self):
        r = _rec(facts=["电池老化最多降低 20%，需开启护理模式，实验室条件下结果可能不同",
                        "磁吸支架与夜间柔光"])
        s = r["recommended_visual_summary"]
        self.assertNotIn("20%", s)
        self.assertIn("非量化表达", s)

    def test_17_price_terms_do_not_produce_regional_price(self):
        a = _analysis(facts=["仅售 $29.99 per month，billed annually，terms apply",
                             "磁吸支架"], type="subscription")
        r = build_recommendation(a, ["Meta"],
                                 workspace_defaults={"country": "BR"})
        g = r["pricing_gate"]
        self.assertTrue(g["has_price_terms"])
        self.assertFalse(g["price_statement_allowed"])
        self.assertFalse(g["region_confirmed"])
        self.assertEqual(g["region_source"], "workspace_default")
        self.assertTrue(any("A05" in x for x in r["missing_inputs"]))
        self.assertNotIn("$", r["recommended_visual_summary"])

    def test_18_defaults_are_never_inferred_from_page_language(self):
        a = _analysis(language="pt-BR", url="https://www.anker.com.br/charger")
        r = build_recommendation(a, ["Meta"])
        self.assertEqual(r["workspace_defaults"]["country"], "US")
        self.assertEqual(r["workspace_defaults"]["language"], "en")


class TestPlanVersionAndDeliveryGate(unittest.TestCase):
    """A13 / A15 / N03：计划版本失效与草案交付门。"""

    def test_19_plan_version_changes_with_planning_inputs(self):
        base = _rec()
        changed = build_recommendation(_analysis(facts=["完全不同的产品事实"]), ["Meta"])
        self.assertNotEqual(base["plan_version"], changed["plan_version"])
        other = build_recommendation(_analysis(), ["Meta"],
                                     workspace_defaults={"country": "DE"})
        self.assertNotEqual(base["plan_version"], other["plan_version"])

    def test_20_concepts_are_distinct_and_evidence_bound(self):
        a = _analysis(facts=["Qi2 certified foldable charging station",
                             "magnetic stand with soft night light",
                             "one year limited warranty"],
                      evidence_index=[
                          {"evidence_id": "E001", "quote": "Qi2 certified foldable charging station",
                           "char_start": 0, "char_end": 40},
                          {"evidence_id": "E002", "quote": "magnetic stand with soft night light",
                           "char_start": 41, "char_end": 80},
                          {"evidence_id": "E003", "quote": "one year limited warranty",
                           "char_start": 81, "char_end": 105},
                      ])
        r = build_recommendation(a, ["Meta"],
                                 workspace_defaults={"concept_count": 3})
        cs = r["structured_concepts"]
        self.assertEqual(len(cs), 3)
        self.assertEqual(len({c["purchase_reason"] for c in cs}), 3)
        self.assertEqual(len({c["axis"] for c in cs}), 3)
        for c in cs:
            self.assertTrue(c["claim_ids"], c)
            self.assertTrue(c["claim_audit"]["ok"], c)
            self.assertTrue(c["claim_ids"][0].startswith("E"))

    def test_21_all_auto_outputs_are_marked_draft(self):
        for key in INDUSTRY_PROFILES:
            r = build_recommendation(_analysis(industry_profile=key), ["Meta"])
            self.assertEqual(r["delivery_grade"], "draft", key)
            self.assertFalse(r["quality_gate"]["deliverable"], key)
            checks = {c["key"]: c["passed"] for c in r["quality_gate"]["checks"]}
            self.assertFalse(checks["per_image_review"], "D5 逐图质检尚未上线")
            self.assertFalse(checks["official_spec"], "官方规格尚未核验")

    def test_22_frontend_grades_and_plan_are_archived(self):
        studio = (FRONTEND / "pages" / "MediaAdStudio.tsx").read_text(encoding="utf-8")
        # 草案等级始终随任务归档
        self.assertIn("delivery_grade: s.recommendation.delivery_grade", studio)
        # V4.46 回归修复：plan_id / plan_version 仅在计划已确认(planApproved)时附加，
        # 避免未确认计划（D5 CreationPlan 未创建/未 confirm）触发后端 422 中断自动链路
        self.assertIn("s.planApproved && s.planId", studio)
        self.assertIn("plan_version: s.planVersion", studio)
        panel = (FRONTEND / "pages" / "AutoCreationPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("不计可投放", panel)
        self.assertIn("rec.structured_concepts", panel)


class TestFrontendSession(unittest.TestCase):
    """A01 / A02 / A13 / D3：真实执行打包后的前端会话中枢。"""

    def test_23_session_store(self):
        esbuild = ROOT / "frontend" / "node_modules" / ".bin" / "esbuild"
        node = shutil.which("node")
        if not esbuild.exists() or not node:
            self.skipTest("缺少 node 或本地 esbuild，跳过前端会话用例")
        script = Path(__file__).resolve().parent / "frontend" / "auto_creation_session.mjs"
        with tempfile.TemporaryDirectory(prefix="admp_session_") as td:
            out = Path(td) / "creationSession.mjs"
            bundled = subprocess.run(
                [str(esbuild), str(FRONTEND / "creationSession.ts"),
                 "--bundle", "--format=esm", "--platform=node",
                 '--define:process.env.NODE_ENV="production"',
                 f"--outfile={out}"],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(bundled.returncode, 0, bundled.stderr[-1200:])
            run = subprocess.run([node, str(script), str(out)],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            payload = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertTrue(payload["ok"])
            self.assertGreaterEqual(len(payload["checks"]), 6, payload)

    def test_24_frontend_defaults_and_migration_in_source(self):
        session = (FRONTEND / "creationSession.ts").read_text(encoding="utf-8")
        self.assertIn("mode: 'auto'", session)
        self.assertIn("SESSION_VERSION = 3", session)
        self.assertIn("legacy ? {", session)
        self.assertIn("mode: 'custom' as const", session)
        self.assertIn("admb:creationSession:v2:", session)
        panel = (FRONTEND / "pages" / "AutoCreationPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("autoContinue: true", panel, "只有显式确认才允许自动串联")
        creation = (FRONTEND / "pages" / "MaterialCreation.tsx").read_text(encoding="utf-8")
        self.assertIn("自动创作", creation)
        self.assertIn("定制创作", creation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
