"""V4.98：素材提示管理（三类通用模板 / 六层心理链条 / 变量来源）。

验证：三条模板变量严格对应系统真实生成逻辑（不臆造）、一句话意图、
六层自动匹配、注册表合入、以及接口按 module 分组返回与自动匹配端点。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from material_prompt_manage import (  # noqa: E402
    MATERIAL_PROMPTS, PSYCHOLOGICAL_LAYERS, LAYER_ORDER, VARIABLE_SOURCES,
    variables_of, auto_match_layers, material_prompt_entries,
)
from services import PROMPT_REGISTRY  # noqa: E402
from models import User  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402

ADMIN_EMAIL = "mpmtest@recomob.com"
ADMIN_USER = "mpmtest"
ADMIN_PWD = "TestPwd123"


class TestMaterialPromptPure(unittest.TestCase):

    def test_01_three_types_with_intent(self):
        self.assertEqual(len(MATERIAL_PROMPTS), 3)
        types = {x["func_type"] for x in MATERIAL_PROMPTS}
        self.assertEqual(types, {"copy", "image", "video"})
        for x in MATERIAL_PROMPTS:
            self.assertTrue(x.get("intent"), f"{x['key']} 缺一句话意图")
            self.assertTrue(x.get("psychological_layers"), f"{x['key']} 缺心理链条")

    def test_02_copy_variables_match_real_generation(self):
        names = {v["name"] for v in variables_of("copy")}
        # 文案链路真实变量（services.MEDIA_COPY_SYS / media_ad.compose_copy_prompt）
        self.assertEqual(names, {"PLATFORM", "LANGUAGE", "SCHEMA", "LIMITS", "CREATIVE", "CONTEXT"})

    def test_03_image_variables_match_real_generation(self):
        names = {v["name"] for v in variables_of("image")}
        # 图片链路真实变量（media_ad._media_image_prompt variables dict）
        self.assertEqual(names, {"INDUSTRY", "SITE_TYPE", "AUDIENCE", "STRENGTHS",
                                 "COMPETITORS", "PLATFORM", "MOOD", "STYLE",
                                 "PALETTE", "BRAND_CONTEXT"})

    def test_04_video_variables_match_real_fields(self):
        names = {v["name"] for v in variables_of("video")}
        # 视频链路真实字段（routers._cw_video_request_build）
        self.assertEqual(names, {"PRODUCT", "PROMOTION_GOAL", "SELLING_POINTS",
                                 "DURATION", "ASPECT", "SHOTS", "EVIDENCE_CONTEXT", "PROMPT_HINT"})

    def test_05_no_unregistered_variables(self):
        # 模板里出现的每个变量都必须在来源表登记（防止臆造变量）
        import re
        for x in MATERIAL_PROMPTS:
            ptype = x["func_type"]
            src = VARIABLE_SOURCES[ptype]
            used = set(re.findall(r"\[\[([A-Z_]+)\]\]", x["content"]))
            self.assertTrue(used, f"{ptype} 模板无变量")
            self.assertTrue(used <= set(src), f"{ptype} 出现未登记变量：{used - set(src)}")

    def test_06_six_layers_and_order(self):
        self.assertEqual([l["key"] for l in PSYCHOLOGICAL_LAYERS], LAYER_ORDER)
        self.assertEqual(len(PSYCHOLOGICAL_LAYERS), 6)
        for x in MATERIAL_PROMPTS:
            keys = x["psychological_layers"].split(",")
            self.assertTrue(set(keys) <= set(LAYER_ORDER))

    def test_07_auto_match_by_analysis(self):
        r = auto_match_layers({"analysis": {
            "audience": "young", "advantages": ["long battery"],
            "competitors": ["X"], "channels": [{"platform": "Meta"}],
        }})
        # 有竞品→痛点，有人群→渴望，有卖点→证据+能力，有渠道→降本，恒有行动收口
        self.assertEqual(set(r["layers"]), set(LAYER_ORDER))
        r2 = auto_match_layers({"analysis": {}})
        self.assertEqual(r2["layers"], ["cta"], "空分析只保留行动收口")

    def test_08_registry_integration(self):
        keys = {p["key"] for p in PROMPT_REGISTRY if p.get("module") == "素材提示管理"}
        self.assertEqual(keys, {"material_prompt_copy", "material_prompt_image", "material_prompt_video"})
        self.assertEqual(len(material_prompt_entries()), 3)


class TestMaterialPromptApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_schema()
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(username=ADMIN_USER).first():
                h, s = hash_password(ADMIN_PWD)
                db.add(User(username=ADMIN_USER, email=ADMIN_EMAIL, display_name="MPM",
                            role="admin", password_hash=h, salt=s, active=True))
                db.commit()
        finally:
            db.close()
        cls.client = TestClient(app)
        r = cls.client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD})
        cls.auth = {"Authorization": f"Bearer {r.json()['token']}"}

    def test_09_meta_endpoint(self):
        r = self.client.get("/api/settings/material-prompts/meta", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(len(d["types"]), 3)
        self.assertEqual(len(d["layers"]), 6)
        self.assertIn("copy", d["variables"])

    def test_10_prompts_by_module(self):
        r = self.client.get("/api/settings/prompts?module=素材提示管理", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(len(d), 3)
        copy = next(x for x in d if x["func_type"] == "copy")
        self.assertTrue(copy.get("intent"))
        self.assertTrue(copy.get("psychological_layers"))

    def test_11_match_layers_endpoint(self):
        r = self.client.post("/api/settings/material-prompts/match-layers",
                             json={"analysis": {"audience": "a", "advantages": ["x"]}},
                             headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("渴望激发", r.json()["labels"])

    def test_12_edit_intent_and_layers_persist(self):
        key = "material_prompt_copy"
        before = self.client.get("/api/settings/prompts?module=素材提示管理", headers=self.auth).json()
        row = next(x for x in before if x["key"] == key)
        r = self.client.put(f"/api/settings/prompts/{key}", headers=self.auth, json={
            "content": row["content"], "intent": "测试意图",
            "psychological_layers": "pain,cta",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["intent"], "测试意图")
        self.assertEqual(r.json()["psychological_layers"], "pain,cta")
        # 恢复默认，避免污染其他测试
        self.client.post(f"/api/settings/prompts/{key}/reset", headers=self.auth)


if __name__ == "__main__":
    unittest.main(verbosity=2)
