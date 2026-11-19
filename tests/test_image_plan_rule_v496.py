"""V4.96：图片创意规划 10 条 + 所选路线与补充指令统一为单一提示词规则。

无模型 / 无网络：验证 count 参数化、A–J 兜底、规则主干+修饰+补充+硬约束、
CreativeConfig 快照收口、提示词注入顺序（零文字契约兜底）、前端接线。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from image_prompt_rule import build_image_prompt_rule, render_image_prompt_rule  # noqa: E402
from creative_config import resolve_creative_config  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"


class TestImagePlanRuleV496(unittest.TestCase):
    def test_01_rule_merges_routes_and_supplement(self):
        rule = build_image_prompt_rule(
            routes=[
                {"key": "A", "name": "痛点对比", "angle": "前后对比", "description": "强对比", "tags": ["转化"]},
                {"key": "C", "name": "续航自由", "angle": "场景证明"},
            ],
            supplement="强调续航卖点，采用生活方式叙事",
            platform="Meta",
        )
        text = render_image_prompt_rule(rule)
        self.assertIn("主干路线 A", text)
        self.assertIn("辅助路线", text)
        self.assertIn("C「续航自由」", text)
        self.assertIn("强调续航卖点", text)
        self.assertIn("优先级最高", text)
        self.assertIn("Meta", text)
        self.assertIn("不绘制任何文字", text)
        self.assertTrue(rule["rule_hash"])

    def test_02_supplement_alone_and_empty(self):
        only = build_image_prompt_rule(supplement="暖色调", platform="Meta")
        self.assertIn("仅按补充指令", render_image_prompt_rule(only))
        empty = build_image_prompt_rule()
        self.assertEqual(render_image_prompt_rule(empty), "")
        self.assertEqual(empty["rule_hash"], "")

    def test_03_rule_snapshot_changes_config_id(self):
        base = resolve_creative_config({})
        a = resolve_creative_config({"creative_plan": {
            "routes": [{"key": "A", "name": "路线一"}], "supplement": "", "platform": "Meta"}})
        b = resolve_creative_config({"creative_plan": {
            "routes": [{"key": "A", "name": "路线一"}], "supplement": "暖色调", "platform": "Meta"}})
        self.assertEqual(base["prompt_rule"]["rule_hash"], "", "无规则时空 hash，保持旧行为")
        self.assertTrue(a["prompt_rule"]["rule_hash"])
        self.assertNotEqual(a["prompt_rule"]["rule_hash"], b["prompt_rule"]["rule_hash"])
        self.assertNotEqual(a["config_id"], b["config_id"])

    def test_04_prompt_rule_injected_before_contract(self):
        import re
        from media_ad import _media_image_prompt
        cfg = resolve_creative_config({
            "creative_plan": {"routes": [{"key": "A", "name": "路线一"}],
                              "supplement": "强调续航", "platform": "Meta"}})
        prompt = _media_image_prompt(
            {"industry": "消费电子", "type": "电商", "audience": "都市白领",
             "advantages": ["续航"], "competitors": []},
            "Meta", cfg, {}, overlay_mode="pure")
        # V4.101：规则块随 RULE_VERSION 升级（v1→v2 新增主干框架细项）。
        # 断言标记存在且在零文字契约之前兜底，不锁死具体版本号，避免后续版本升级再误伤。
        rule_match = re.search(r"\[CreativePlanRule v\d+\]", prompt)
        self.assertIsNotNone(rule_match, "提示词须包含创意规则块")
        rule_marker = rule_match.group(0)
        self.assertIn("强调续航", prompt)
        rule_pos = prompt.index(rule_marker)
        contract_pos = prompt.find("[PromptContract]")
        self.assertGreater(contract_pos, rule_pos, "零文字契约必须在规则块之后兜底")
        # V4.101 新增：规则块须显式写出主干转化框架（钩子 / 证据 / 视觉钩子 / 收口）。
        self.assertIn("主干转化框架", prompt)

    def test_05_backend_count_and_keys(self):
        routers = (BACKEND / "routers.py").read_text(encoding="utf-8")
        schemas = (BACKEND / "schemas.py").read_text(encoding="utf-8")
        self.assertIn("count: int = 3", schemas)
        self.assertIn("min(10, int(req.count or 3))", routers)
        self.assertIn("chr(65 + i) for i in range(10)", routers)
        self.assertNotIn('keys = ["A", "B", "C"]', routers)
        self.assertNotIn("[:3]", routers.split("_CW_ROUTES_SYS")[1].split("def api_cw_routes")[0][-200:] if "def api_cw_routes" in routers.split("_CW_ROUTES_SYS")[1] else routers)

    def test_06_fallback_ten_routes(self):
        routers = (BACKEND / "routers.py").read_text(encoding="utf-8")
        # V4.101：原「痛点对比实验」框架化后拆为「前后对比实验」+「半路受阻痛点」，
        # 差异化语义未丢；其余三条名称保持不变。
        for name in ("前后对比实验", "半路受阻痛点", "价值锚定对照", "户外挑战验证", "开箱第一视角"):
            self.assertIn(name, routers, "兜底须含 10 条差异化路线：%s" % name)
        # V4.101 新增：10 条兜底路线均已框架化，须带 framework / hook / cta_role 等转化字段。
        block = routers.split("_CW_FALLBACK_ROUTES = [", 1)[1].split("\n]", 1)[0]
        for field in ("framework", "hook", "proof", "visual_hook", "cta_role"):
            self.assertEqual(block.count('"%s":' % field), 10,
                             "10 条兜底路线均须标注 %s" % field)

    def test_07_frontend_wiring(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn("count: 10", page)
        self.assertIn("count?: number", api)
        self.assertIn("selected: false", page)
        self.assertIn("creative_plan", page)
        self.assertIn("imageSupplement", page)
        # 补充指令不得再借用视频状态
        self.assertNotIn("value={vs.options.prompt_hint || ''}\n", page)
        self.assertIn("maxLength={500}", page)
        self.assertIn("cwb-route-count", css)
        self.assertIn("minmax(300px, 1fr)", css)

    def test_08_supplement_visual_only_guard(self):
        text = render_image_prompt_rule(build_image_prompt_rule(
            routes=[{"key": "A", "name": "路线一"}],
            supplement="把价格改成 9.9 并写上品牌名", platform="Meta"))
        # 用户录入的原文保留（便于追溯），但规则必须显式禁止绘制文字与编造价格
        self.assertIn("把价格改成 9.9", text)
        self.assertIn("不得据此编造商品事实、价格", text)
        self.assertIn("画面内不绘制任何文字", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
