"""V4.114 图片创意规划：单选 + 完整展示 + 「改一句」修改意见作用到出图。

真实缺口（改造前）：
- 10 条路线虽已收进下拉，但初始 `selected: false`，默认一条都不选，且保留
  全选 / 清空 / 已选计数 / 「用于生成」勾选，仍是多选模式；
- 单卡只渲染 angle / description / framework_label / hook / visual_hook / proof / tags，
  漏掉 framework、cta_role，且 proof 被外层条件 `framework_label || hook || visual_hook`
  挡住时整块不显示；
- 「改一句」是把 description 原文塞进输入框直接重写，不是「输入修改意见」，
  一次微调会覆盖整条规划，也没有「意见已作用于图片」的反馈。

本测试锁住：
1. CWRoute 新增 user_note，PATCH 白名单放行并可真实落库，且不改原 description；
2. 出图提示词规则把 user_note 作为本路线最高优先级视觉调整指令单独成行，
   纳入 rule_hash，原描述保留，零文字 / 不编造事实等硬约束仍在；
3. 前端单选（默认第一条、切换收敛）、多选控件移除、全部字段完整渲染、
   修改意见贯通到 creative_plan。
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

import image_prompt_rule  # noqa: E402
from schemas import CWRoute  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from models import CreativePlan, User  # noqa: E402
from auth import hash_password  # noqa: E402

ROUTE = {
    "key": "A", "name": "前后对比实验", "angle": "从使用前到使用后的可观察变化",
    "description": "左右分屏展示使用前后的差异", "tags": ["对比", "实证"],
    "framework": "AIDA", "framework_label": "问题—方案",
    "hook": "首屏给出明显反差", "proof": "真实功能演示，不写数字",
    "visual_hook": "左右分屏对比构图", "cta_role": "叠加位收口，不绘制文字",
    "selected": True,
}


class TestRouteSingleSelectV4114(unittest.TestCase):
    def test_01_schema_has_user_note(self):
        """CWRoute 必须有 user_note 且默认空，历史路线不受影响。"""
        r = CWRoute(key="A", name="路线一")
        self.assertEqual(r.user_note, "")
        self.assertIn("user_note", CWRoute.model_fields)

    def test_02_prompt_rule_consumes_user_note(self):
        """修改意见必须单独成行进入出图提示词，且不覆盖原描述。"""
        base = image_prompt_rule.build_image_prompt_rule(routes=[ROUTE], platform="Meta")
        with_note = image_prompt_rule.build_image_prompt_rule(
            routes=[dict(ROUTE, user_note="把场景换成夜间办公室")], platform="Meta")
        text = with_note["rule_text"]
        self.assertIn("用户对本条路线的修改意见", text)
        self.assertIn("最高优先级", text)
        self.assertIn("把场景换成夜间办公室", text)
        self.assertIn(ROUTE["description"], text, "原规划描述不得被修改意见覆盖")
        self.assertNotEqual(base["rule_hash"], with_note["rule_hash"], "意见须纳入规则指纹")
        self.assertEqual(image_prompt_rule.RULE_VERSION, "4")
        # 硬约束不因新增意见而丢失
        self.assertIn("不绘制任何文字", text)
        self.assertIn("不得据此编造商品事实", text)
        self.assertIn("以修改意见为准", text)

    def test_03_empty_note_keeps_legacy_rule(self):
        """没填意见时不产生多余行，保持旧规则结构。"""
        r = image_prompt_rule.build_image_prompt_rule(routes=[dict(ROUTE, user_note="")])
        self.assertNotIn("用户对本条路线的修改意见", r["rule_text"])
        self.assertEqual(r["routes"][0]["user_note"], "")

    def test_04_frontend_single_select_and_full_fields(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        # 默认选中第一条：分析完成与「换一批路线」两处都要生效
        self.assertEqual(page.count("selected: i === 0"), 2, page.count("selected: i === 0"))
        # 下拉切换自动把选中态收敛为唯一一条
        self.assertIn("selected: j === idx", page)
        # 多选控件已移除，界面有且只展示一条
        self.assertNotIn(">全选<", page)
        self.assertNotIn(">清空<", page)
        self.assertNotIn("cwb-route-usegen", page)
        self.assertIn("cwb-route-single", page)
        self.assertNotIn('className="cwb-routes"', page)
        # 完整字段一个都不能少
        for token in ("curRoute.angle", "curRoute.description", "curRoute.framework_label",
                      "curRoute.framework", "curRoute.hook", "curRoute.proof",
                      "curRoute.visual_hook", "curRoute.cta_role", "curRoute.tags"):
            self.assertIn(token, page, f"单卡缺少字段 {token}")
        self.assertIn("cwb-route-detail", page)
        self.assertIn("当前用于生成", page)
        # 「改一句」= 输入修改意见，保存 user_note，明确作用到图片
        self.assertIn("改一句", page)
        self.assertIn("text: curRoute.user_note || ''", page)
        self.assertIn("{ user_note: note }", page)
        self.assertIn("user_note: r.user_note || ''", page)
        self.assertIn("已作用到本条路线生成的图片", page)
        self.assertIn("user_note?: string", api)
        self.assertIn(".cwb-route-detail", css)
        self.assertIn(".cwb-route-note", css)

    def test_05_patch_whitelist_contains_user_note(self):
        routers = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn('"user_note"', routers)

    def test_06_patch_endpoint_persists_note_without_touching_description(self):
        """真实端点：意见落库、原描述保留、changed 如实标注。"""
        from fastapi.testclient import TestClient
        from main import app

        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username="v4114").first():
                h, s = hash_password("TestPwd123")
                db.add(User(username="v4114", email="v4114@test.local",
                            display_name="V4114", role="admin",
                            password_hash=h, salt=s, active=True))
                db.commit()
            rec = CreativePlan(title="v4114", routes_json=[dict(ROUTE)],
                               status="draft", owner_id=None)
            db.add(rec); db.commit(); db.refresh(rec)
            pid = rec.id
        finally:
            db.close()
        client = TestClient(app)
        login = client.post("/api/auth/login",
                            json={"email": "v4114@test.local", "password": "TestPwd123"})
        auth = {"Authorization": "Bearer " + login.json()["token"]}
        r = client.patch(f"/api/cw/routes/{pid}/A",
                         json={"user_note": "把主色调改成冷色"}, headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        hit = [x for x in data["routes"] if x.get("key") == "A"][0]
        self.assertEqual(hit["user_note"], "把主色调改成冷色")
        self.assertEqual(hit["description"], ROUTE["description"])
        self.assertIn("user_note", data["changed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
