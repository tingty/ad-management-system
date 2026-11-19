"""V4.106 / 方案D：参考图角色区分与产品保真回归。

- style_reference（默认）行为不变：只学配色，生成全新画面；
- product_reference（保真）：必须有商品图 + 投放授权 + 供应商具备参考编辑能力，
  任一缺失在调用付费模型前 needs_input，绝不用通用商品或文生图重画替代；
- 供应商侧只对声明了 reference_edit 的部署走 /images/edits（真编辑），失败不静默退回文生图。
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

import reference_image as ri  # noqa: E402


class TestReferenceRoleV4106(unittest.TestCase):

    def test_01_normalize_role_defaults_to_style(self):
        self.assertEqual(ri.normalize_role(""), ri.ROLE_STYLE)
        self.assertEqual(ri.normalize_role("whatever"), ri.ROLE_STYLE)
        self.assertEqual(ri.normalize_role("product_reference"), ri.ROLE_PRODUCT)
        self.assertEqual(ri.normalize_role("商品保真"), ri.ROLE_PRODUCT)

    def test_02_style_role_always_allowed(self):
        gate = ri.reference_requirement(ri.ROLE_STYLE, False, False, False)
        self.assertEqual(gate["status"], "ok")
        self.assertEqual(gate["code"], "style_only")

    def test_03_product_missing_asset_blocks(self):
        gate = ri.reference_requirement(ri.ROLE_PRODUCT, False, True, True)
        self.assertEqual(gate["status"], "needs_input")
        self.assertEqual(gate["code"], "product_asset_missing")
        self.assertIn("上传", gate["required_action"])

    def test_04_product_unlicensed_blocks(self):
        gate = ri.reference_requirement(ri.ROLE_PRODUCT, True, True, False)
        self.assertEqual(gate["code"], "asset_not_authorized")
        self.assertIn("授权", gate["note"])

    def test_05_product_without_edit_capability_blocks(self):
        gate = ri.reference_requirement(ri.ROLE_PRODUCT, True, False, True)
        self.assertEqual(gate["code"], "model_not_capable")
        self.assertIn("参考图编辑能力", gate["note"])
        # 明确不得用通用商品替代
        self.assertIn("不会用通用商品替代", gate["note"])

    def test_06_product_all_conditions_pass(self):
        gate = ri.reference_requirement(ri.ROLE_PRODUCT, True, True, True)
        self.assertEqual(gate["status"], "ok")
        self.assertEqual(gate["code"], "product_reference")
        self.assertIn("保留商品型号", gate["note"])

    def test_07_fidelity_block_is_explicit(self):
        block = ri.render_product_fidelity_block({"accent": "#112233"})
        for token in ("reference-edit", "exact model", "silhouette",
                      "Never restyle", "Do not draw text"):
            self.assertIn(token, block)
        self.assertIn("#112233", block)
        # 纯函数：无输入也不崩
        self.assertIn("reference-edit", ri.render_product_fidelity_block(None))

    def test_08_capability_defaults_false_and_overridable(self):
        from image_capabilities import capability_of
        for key in ("openai_image", "generic_image", "dashscope_maas", "template"):
            self.assertFalse(capability_of(key, {}).get("supports_reference_edit"), key)
        self.assertTrue(capability_of("openai_image", {"reference_edit": True})["supports_reference_edit"])
        self.assertFalse(capability_of("openai_image", {"reference_edit": False})["supports_reference_edit"])

    def test_09_provider_edit_path_is_real_not_text2img(self):
        import inspect
        import providers
        self.assertTrue(hasattr(providers, "_post_image_edit"))
        src = inspect.getsource(providers._post_image_edit)
        self.assertIn("/images/edits", src)
        self.assertIn("files=", src)
        for cls in (providers.OpenAIImage, providers.GenericImageProvider,
                    providers.TemplateImage, providers.DashScopeMaaSImageProvider):
            params = list(inspect.signature(cls.generate).parameters)
            self.assertIn("reference", params, cls.__name__)
        # 编辑失败不得静默退回文生图：OpenAIImage 在 reference 分支失败直接 return None
        gen_src = inspect.getsource(providers.OpenAIImage.generate)
        edit_part = gen_src.split("if reference and os.path.isfile(reference):")[1]
        head = edit_part.split("try:")[0] + edit_part.split("return None")[0]
        self.assertNotIn("/images/generations", head)

    def test_10_media_ad_gate_and_prompt(self):
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        for token in ("reference_requirement(", "render_product_fidelity_block",
                      'reference_mode == "product_reference"',
                      '"status": "needs_input"', "reference_role"):
            self.assertIn(token, src, f"media_ad.py 缺少 {token}")
        # 只有商品保真模式才把参考图字节交给供应商
        self.assertIn("reference=(reference_path", src)

    def test_11_routers_gate_wired(self):
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        self.assertIn("_enforce_reference_gate(db, req.style_opts)", src)
        self.assertIn('body.get("images_request") or {}).get("style_opts")', src)
        self.assertIn('"reference_gate": gate["code"]', src)

    def test_12_frontend_wiring(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        for token in ("refRole", "refAuthorized", "product_reference",
                      "style_opts.reference_role", "style_opts.reference_authorized",
                      "我确认拥有该商品素材的投放授权"):
            self.assertIn(token, page, f"CreativeWorkbench.tsx 缺少 {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
