"""V4.116 回归锁：

A. 顶部去重——主标题与说明只由 App.tsx 全局 page-head 呈现一次，
   创意工作台组件内不再重复渲染「创意工作台 / 输入产品链接…」标题与说明。

B. 补充创意指令（imageSupplement）二次点击生效：
   用户在第一次「确认并批量生成」后补填的补充指令，再次点击时必须携带最新内容。
   链路：textarea 双向绑定 -> 每次 batchGenerate 新建 style_opts.creative_plan.supplement
   -> 新的 idempotency_key（不命中幂等）-> 后端裸 dict 路由 -> DB 快照持久化
   -> worker 读快照 -> build_image_prompt_rule 渲染进 rule_text -> 拼入 bg_prompt -> provider。
   本测试验证：payload 构造每次读最新 state、key 每次唯一、后端不丢字段、规则随补充变化、
   界面有「已采纳」可见反馈。不调用付费模型。
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

from schemas import MediaImageRequest  # noqa: E402
from creative_config import resolve_creative_config  # noqa: E402
from image_prompt_rule import build_image_prompt_rule, render_image_prompt_rule  # noqa: E402


class TestHeaderDedupV4116(unittest.TestCase):
    def test_01_component_no_duplicate_header(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        # 组件内不得再出现 cwb-title-only / cwb-intro 的标签渲染
        self.assertNotIn('<h2 className="cwb-title-only">创意工作台</h2>', page)
        self.assertNotIn('<p className="cwb-intro">输入产品链接并选择投放平台', page)
        # 顶部只剩动作按钮容器
        self.assertIn("cwb-top-actions-only", page)

    def test_02_global_desc_is_single_short_line(self):
        app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("输入落地页 / 应用链接或产品信息并选择推广媒体，AI 自动完成产品分析、创意规划与素材生成。", app)
        # 旧的两行长说明（含「对话式流程，人工仅介入」）应被移除
        self.assertNotIn("对话式流程，人工仅介入必要输入与重要决策", app)


class TestSupplementSecondClickV4116(unittest.TestCase):
    def test_03_payload_reads_latest_supplement_state(self):
        """style_opts.creative_plan.supplement 直接读 imageSupplement state（非 Mock / 非旧值常量）。"""
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("supplement: imageSupplement || '',", page)
        # textarea 双向绑定到同一个 state
        self.assertIn("value={imageSupplement}", page)
        self.assertIn("onChange={e => setImageSupplement(e.target.value)}", page)

    def test_04_each_click_new_idempotency_key(self):
        """每次点击/每个任务生成全新幂等键，二次点击不会命中第一次的幂等去重。"""
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("idempotency_key: `cw_${p}_${genIdx}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`", page)

    def test_05_backend_keeps_nested_supplement(self):
        """后端 style_opts 为通用 dict，嵌套 creative_plan.supplement 不被 Pydantic 丢弃。"""
        analysis = {
            "url": "https://example.com", "industry": "Beauty", "type": "ecommerce",
            "audience": "US women", "competitors": [], "advantages": ["Vegan"],
            "channels": [], "evidence_gate": "ok",
        }
        req = MediaImageRequest(
            analysis=analysis, platform="Meta",
            style_opts={"creative_plan": {
                "routes": [{"key": "A", "name": "路线一"}],
                "supplement": "强调续航，采用俯拍构图", "platform": "Meta", "overlay_mode": "pure",
            }},
        )
        dumped = req.model_dump()
        self.assertEqual(
            dumped["style_opts"]["creative_plan"]["supplement"],
            "强调续航，采用俯拍构图",
        )

    def test_06_rule_changes_with_supplement(self):
        """补充指令变化 -> rule_text / rule_hash 变化（证明未被旧规则缓存）。"""
        routes = [{"key": "A", "name": "路线一", "angle": "前后对比", "description": "强对比", "tags": ["转化"]}]
        first = build_image_prompt_rule(routes=routes, supplement="暖色调", platform="Meta")
        second = build_image_prompt_rule(routes=routes, supplement="俯拍构图 + 冷色调", platform="Meta")
        self.assertIn("暖色调", render_image_prompt_rule(first))
        self.assertIn("俯拍构图 + 冷色调", render_image_prompt_rule(second))
        self.assertNotEqual(first["rule_hash"], second["rule_hash"])
        # 经 creative_config 收口后 config_id 也随补充指令变化
        c1 = resolve_creative_config({"creative_plan": {"routes": routes, "supplement": "暖色调", "platform": "Meta"}})
        c2 = resolve_creative_config({"creative_plan": {"routes": routes, "supplement": "俯拍构图 + 冷色调", "platform": "Meta"}})
        self.assertNotEqual(c1["config_id"], c2["config_id"])

    def test_07_visible_applied_feedback(self):
        """界面给出「已确认采纳 / 实时生效」反馈，用户可见二次点击会带最新指令。"""
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("cwb-supp-applied", page)
        self.assertIn("已确认采纳，将随本次点击一并生效", page)
        self.assertIn("cwb-supp-live", page)
        self.assertIn("改后可再次点击，按最新内容重新生成", page)
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".cwb-supp-live", css)
        self.assertIn(".cwb-supp-applied", css)


if __name__ == "__main__":
    unittest.main()
