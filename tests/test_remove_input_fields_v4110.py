"""V4.110：创意工作台输入区删除「素材图片选择 / 参考图 / 品牌」。

需求：三个组件当前没有使用场景，删除组件与子功能，并确认前后端没有残留、
关联功能（分析 / 文案 / 图片 / 视频）仍能正常工作。

本测试锁定删除边界：
- 输入区不再有这三块 UI，也没有对应 state / handler / payload 字段；
- 图片生成固定「纯图片」，不再有叠加模式选择（后端能力保留给其它链路）；
- 参考图只剩视频「图生视频」一条用途，上传入口在视频规划区，父级提交仍带 reference_image；
- 后端图片侧参考链路（模块 / 闸门 / 供应商编辑 / 能力声明）彻底移除；
- brand_logo 前后端字段全部清掉，但 analysis.brand（事实字段）保留。

无模型 / 无网络 / 不写库。
"""
import inspect
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))


class TestRemovedInputFieldsV4110(unittest.TestCase):

    # ---------- 前端 ----------
    def test_01_workbench_state_removed(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        for gone in ("setReferenceImage", "referenceName", "refUploading", "refRole",
                     "refAuthorized", "selectedBrand", "brandLogo", "brandLogoName",
                     "brandUploading", "injectLogo", "overlayMode"):
            self.assertNotIn(gone, src, f"输入区 state 未删净：{gone}")

    def test_02_image_request_is_pure_and_has_no_reference(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("overlay_mode: 'pure'", src)
        for gone in ("style_opts.reference_image", "brand_logo:", "logo: (injectLogo"):
            self.assertNotIn(gone, src)
        # 出现两处：creative_plan 与 images_request 都固定纯图片
        self.assertGreaterEqual(src.count("overlay_mode: 'pure'"), 2)

    def test_03_video_reference_upload_in_video_panel(self):
        vs = (FRONTEND / "pages" / "VideoStudio.tsx").read_text(encoding="utf-8")
        self.assertIn("onReferenceChange", vs)
        self.assertIn("api.uploadAsset(file)", vs)
        self.assertIn("reference_image: referenceImage || ''", vs)
        self.assertIn("image_to_video", vs)
        cw = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("const [videoRef, setVideoRef] = useState('')", cw)
        self.assertIn("reference_image: videoRef || ''", cw)
        self.assertIn("onReferenceChange={setVideoRef}", cw)

    def test_04_api_types_drop_brand_logo(self):
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertNotIn("brand_logo", api)
        self.assertIn("reference_image?: string", api, "视频仍需要图生视频参考图")

    def test_05_brand_fact_still_flows(self):
        # 品牌输入删了，但分析结论里的 brand 仍是文案 / 图片的事实来源
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("kind: 'brand'", src, "品牌事实仍应写入素材库（来自文案结果）")
        self.assertNotIn("setSelectedBrand", src)

    # ---------- 后端 ----------
    def test_06_image_reference_module_gone(self):
        self.assertFalse((BACKEND / "reference_image.py").exists(),
                         "图片参考图模块应已删除")
        for name in ("routers.py", "media_ad.py"):
            src = (BACKEND / name).read_text(encoding="utf-8")
            self.assertNotIn("reference_image import", src, name)
            self.assertNotIn("_enforce_reference_gate", src, name)

    def test_07_providers_have_no_reference_edit(self):
        import providers
        self.assertFalse(hasattr(providers, "_post_image_edit"))
        for cls in (providers.OpenAIImage, providers.GenericImageProvider,
                    providers.TemplateImage, providers.DashScopeMaaSImageProvider):
            params = list(inspect.signature(cls.generate).parameters)
            self.assertNotIn("reference", params, cls.__name__)
        src = inspect.getsource(providers)
        self.assertNotIn("/images/edits", src)

    def test_08_capability_flag_gone(self):
        src = (BACKEND / "image_capabilities.py").read_text(encoding="utf-8")
        self.assertNotIn("supports_reference_edit", src)

    def test_09_brand_logo_gone_from_schemas(self):
        src = (BACKEND / "schemas.py").read_text(encoding="utf-8")
        self.assertNotIn("brand_logo", src)
        # 图生视频参考图字段保留
        self.assertIn("reference_image", src)

    def test_10_media_ad_no_image_reference_branch(self):
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        for gone in ("reference_requirement", "analyze_reference_style",
                     "render_product_fidelity_block", "reference_path",
                     "product_reference"):
            self.assertNotIn(gone, src, f"图片侧残留：{gone}")
        self.assertIn('reference_mode = "none"', src)
        # 视频资产闸门属于图生视频，保留
        gates = (BACKEND / "video_claims.py").read_text(encoding="utf-8")
        self.assertIn("def video_asset_gate", gates)

    def test_11_image_pipeline_still_builds_prompt(self):
        # 删除参考图后，图片提示词仍由文案 + 行业约束 + 契约拼成，不因缺参报错
        import media_ad
        for fn in ("_media_image_prompt", "generate_media_images"):
            self.assertTrue(hasattr(media_ad, fn), fn)
        params = list(inspect.signature(media_ad._media_image_prompt).parameters)
        self.assertNotIn("style_block", params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
