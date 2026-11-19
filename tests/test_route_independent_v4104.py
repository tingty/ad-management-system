"""V4.104 / 方案B：每条创意路线完全独立生成回归。

- build_concept 绑定 route.key：不同路线的 concept_id / concept_key 不共享，
  且路线价值切入（angle/hook/visual_hook/proof）进入承诺与画面语义。
- build_visual_brief 写出 route_key / route_visual_hook，subject/scene_detail 随路线变化。
- image_prompt_rule 废弃辅助路线融合，只渲染本组第一条独立路线，规则版本升 v3。
- 前端每组只传当前路线一条，slots 带 route_key。
无模型 / 无网络。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from creative_config import build_concept, build_visual_brief, resolve_creative_config  # noqa: E402
from image_prompt_rule import build_image_prompt_rule, render_image_prompt_rule, RULE_VERSION  # noqa: E402


VARIANT = {"headline": "Long battery", "sub": "20h battery life", "cta": "Learn More"}
ANALYSIS = {"audience": "commuters", "facts": ["real product fact"]}
PROFILE = {"key": "consumer_electronics", "visual_subject": "device",
           "entity_type": "physical"}


class TestRouteIndependentV4104(unittest.TestCase):

    def test_01_concept_key_differs_by_route(self):
        a = build_concept(VARIANT, 0, ANALYSIS, PROFILE,
                          route={"key": "A", "name": "痛点对比", "hook": "battery anxiety"})
        b = build_concept(VARIANT, 0, ANALYSIS, PROFILE,
                          route={"key": "B", "name": "场景代入", "hook": "commute scenario"})
        c = build_concept(VARIANT, 0, ANALYSIS, PROFILE)
        self.assertNotEqual(a["concept_key"], b["concept_key"])
        self.assertNotEqual(a["concept_id"], b["concept_id"])
        self.assertTrue(a["concept_key"].startswith("ck_"))
        self.assertEqual(a["route_key"], "A")
        # 无路线时行为兼容旧版（C1）
        self.assertEqual(c["concept_id"], "C1")

    def test_02_route_semantics_injected_into_promise(self):
        a = build_concept(VARIANT, 0, ANALYSIS, PROFILE,
                          route={"key": "A", "angle": "前后对比", "hook": "battery anxiety",
                                 "visual_hook": "split screen", "proof": "lab test"})
        self.assertIn("前后对比", a["core_promise"])
        self.assertIn("battery anxiety", a["core_promise"])
        self.assertIn("lab test", a["evidence"])
        self.assertEqual(a["route_visual_hook"], "split screen")

    def test_03_visual_brief_carries_route(self):
        concept = build_concept(VARIANT, 0, ANALYSIS, PROFILE,
                                route={"key": "A", "name": "路线A", "visual_hook": "split screen"})
        brief = build_visual_brief(concept, ANALYSIS, PROFILE, {}, 1080, 1080)
        self.assertEqual(brief["route_key"], "A")
        self.assertEqual(brief["route_visual_hook"], "split screen")
        self.assertIn("split screen", brief["subject"])
        self.assertIn("split screen", brief["scene_detail"])

    def test_04_rule_drops_auxiliary_routes(self):
        self.assertEqual(RULE_VERSION, "4")
        rule = build_image_prompt_rule(routes=[
            {"key": "A", "name": "路线A", "framework": "aida"},
            {"key": "B", "name": "路线B", "framework": "pas"},
        ], platform="Meta")
        text = render_image_prompt_rule(rule)
        self.assertIn("本组独立路线 A", text)
        self.assertNotIn("辅助路线", text)
        self.assertNotIn("路线B", text)
        self.assertIn("主干转化框架", text)  # 框架细项保留（V4.101 能力不丢）

    def test_05_config_id_differs_by_route(self):
        cfg_a = resolve_creative_config({"creative_plan": {"routes": [
            {"key": "A", "name": "路线A", "framework": "aida"}]}})
        cfg_b = resolve_creative_config({"creative_plan": {"routes": [
            {"key": "B", "name": "路线B", "framework": "aida"}]}})
        self.assertNotEqual(cfg_a["config_id"], cfg_b["config_id"])

    def test_06_frontend_single_route_and_route_key(self):
        cw = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("route_key: route?.key || ''", cw)
        self.assertIn("routes: (route ? [route] : [])", cw)
        self.assertNotIn("activeRoutes.filter(r => r !== route)", cw)
        # schema 接受 route_key
        self.assertIn("route_key: str = \"\"", (BACKEND / "schemas.py").read_text(encoding="utf-8"))

    def test_07_build_concept_backward_compatible(self):
        # 4 参调用（历史测试 / 自动创作链路）仍工作
        concept = build_concept(VARIANT, 2, ANALYSIS, PROFILE)
        self.assertEqual(concept["concept_id"], "C3")
        self.assertEqual(concept["route_key"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
