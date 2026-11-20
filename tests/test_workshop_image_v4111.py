"""V4.111 素材工作坊出图修复：可选尺寸必须能真正出图。

覆盖此前的真实故障链：
- 工作坊尺寸只查素材标准库，执行期 `validate_task_matrix()` 却按旧规则目录判定，
  Google 1200x1200 / TikTok 640x640 等「界面能选、任务必败」的组合被摆到界面上；
- 任务 failed 后页面只表现为「没有图片」，拿不到任何原因；
- 缩略图直接用服务端返回的文件系统路径，浏览器必然 404。

本测试锁住三件事：
1. `platform_options()` 给出的每个组合都能通过执行期同一套媒体规则；
2. spec_id 命中标准库时，库里的合法尺寸不再被旧目录误拒，且不能借此绕过尺寸门；
3. 前端渲染走 `api.fileUrl`，任务失败时把原因显示出来。

无模型 / 无网络 / 不发真实费用。
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

import workshop  # noqa: E402
from media_platforms import validate_task_matrix, MediaRuleError  # noqa: E402


class TestWorkshopImageV4111(unittest.TestCase):

    def test_01_every_offered_size_is_executable(self):
        """核心回归：界面给出的每个「平台 + 尺寸」都必须能通过出图执行期校验。"""
        failed = []
        offered = 0
        for p in workshop.platform_options():
            for s in p["sizes"]:
                offered += 1
                try:
                    validate_task_matrix(p["platform"],
                                         [{"size": s["size"], "spec_id": s["spec_id"]}])
                except MediaRuleError as e:
                    failed.append((p["platform"], s["size"], e.errors))
        self.assertGreater(offered, 0, "平台尺寸不能为空")
        self.assertEqual(failed, [], f"存在「可选但出图必败」的尺寸：{failed}")

    def test_02_google_main_material_sizes_are_offered(self):
        """Google 的主素材尺寸曾被旧目录整段挡掉，界面只剩展示横幅甚至没有平台。"""
        opts = {o["platform"]: o for o in workshop.platform_options()}
        self.assertIn("Google", opts, "Google 不应从工作坊消失")
        sizes = {s["size"] for s in opts["Google"]["sizes"]}
        for size in ("1200x1200", "1200x628", "1200x1500", "960x1200"):
            self.assertIn(size, sizes)
        # 每个尺寸都带标准库 spec_id，出图任务才可精确复用同一规格
        for s in opts["Google"]["sizes"]:
            self.assertTrue(s["spec_id"], f"{s['size']} 缺少 spec_id")

    def test_03_spec_size_allowed_and_not_a_bypass(self):
        """spec_id 命中标准库时放行其登记尺寸；无 spec_id 或尺寸不属于该 spec 仍拒绝。"""
        entry = next(e for e in __import__("media_spec_library").LIBRARY
                     if e.platform == "Google" and e.media == "image"
                     and "1200x1200" in (e.sizes or ()))
        # 1) 带正确 spec_id → 放行（旧目录没有 1200x1200）
        out = validate_task_matrix("Google", [{"size": "1200x1200",
                                              "spec_id": entry.spec_id}])
        self.assertEqual(out["slots"][0]["size"], "1200x1200")
        self.assertEqual(out["slots"][0]["asset_role"], entry.asset_role)
        # 2) 不带 spec_id → 旧目录仍拒（不能空手绕过尺寸门）
        with self.assertRaises(MediaRuleError):
            validate_task_matrix("Google", [{"size": "1200x1200"}])
        # 3) 带 spec_id 但尺寸不在该 spec 登记内 → 拒（防止伪造 spec_id）
        with self.assertRaises(MediaRuleError):
            validate_task_matrix("Google", [{"size": "999x999",
                                             "spec_id": entry.spec_id}])

    def test_04_cross_platform_spec_rejected(self):
        """A 平台的 spec_id 不能给 B 平台用。"""
        google = next(o for o in workshop.platform_options() if o["platform"] == "Google")
        spec_id = google["sizes"][0]["spec_id"]
        with self.assertRaises(MediaRuleError):
            validate_task_matrix("Meta", [{"size": "1080x1080", "spec_id": spec_id}])

    def test_05_resolve_targets_stays_in_sync(self):
        """resolve_targets 与 options 同源：选中的尺寸必然可执行。"""
        rows = [{"platform": p["platform"], "sizes": [s["size"] for s in p["sizes"]]}
                for p in workshop.platform_options()]
        targets, errors = workshop.resolve_targets(rows)
        self.assertEqual(errors, [])
        self.assertTrue(targets)
        for t in targets:
            self.assertTrue(t.get("spec_id"), "任务必须带 spec_id")

    def test_06_frontend_uses_file_url_and_shows_reason(self):
        page = (FRONTEND / "pages" / "MaterialWorkshop.tsx").read_text(encoding="utf-8")
        # 缩略图与预览都必须经过 api.fileUrl，直接塞服务端文件路径会 404
        self.assertIn("api.fileUrl(it.url || it.file)", page)
        self.assertIn("api.fileUrl(preview.url || preview.file)", page)
        self.assertNotIn("<img src={it.url}", page)
        self.assertNotIn("<img src={preview.url}", page)
        # 任务失败必须把原因显示出来
        self.assertIn("jobNote", page)
        self.assertIn("outcome_note", page)

    def test_07_preflight_validation_before_queue(self):
        """路由在入队前用同一套规则预校验，必败组合不进付费队列。"""
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        start = src.index('@router.post("/workshop/generate")')
        end = src.index('"images_skipped": (not image_ready)')
        block = src[start:end]
        self.assertIn("validate_task_matrix(platform, [s.model_dump() for s in slots])", block)
        self.assertIn("尺寸未通过媒体规则", block)
        # 校验必须发生在 create_job 之前
        self.assertLess(block.index("validate_task_matrix"),
                        block.index("job_service.create_job"))

    def test_08_overlay_text_fits_real_layout_budget(self):
        """超长文案必须被收敛到**实际版式**预算内，否则整批图会被判 needs_revision。"""
        from media_ad import build_overlay_text, fit_overlay_text

        headline = ("Premium Wireless Earbuds with 40H Playtime and Active Noise "
                    "Cancellation for Daily Commute and Travel")
        sub = ("Experience studio-quality sound with active noise cancellation, IPX5 water "
               "resistance and a pocket-sized charging case. Designed for commuters who want "
               "calm focus every day, with fast pairing and long battery life.")
        # 未收敛时确认确实超预算（复现原故障）
        before = build_overlay_text(headline, sub, "Shop Now", 1080, 1080, layout="hero")
        self.assertFalse(before["ok"], "该用例本身应当超预算，否则测不到收敛逻辑")
        h, s, c = fit_overlay_text(headline, sub, "Shop Now", 1080, 1080, layout="hero")
        self.assertLessEqual(len(h), before["budget"]["headline_chars"])
        self.assertLessEqual(len(s), before["budget"]["sub_chars"])
        self.assertTrue(build_overlay_text(h, s, c, 1080, 1080, layout="hero")["ok"])
        # 收敛只发生在图上：文案原文不做改写，Cta 完整保留
        self.assertTrue(headline.startswith(h.rstrip("…")[:10]))
        self.assertEqual(c, "Shop Now")

    def test_09_endpoint_enables_auto_fit_only_for_workshop(self):
        """自动收敛是工作坊显式开启的能力，其它链路保持「超预算就阻断」。"""
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        start = src.index('@router.post("/workshop/generate")')
        end = src.index('"images_skipped": (not image_ready)')
        # V4.120：默认模式仍显式开启 fit_overlay；按模板创作时用同一开关叠加模板视觉路线。
        self.assertRegex(src[start:end], r'style_opts\s*=\s*\{"fit_overlay": True\}')

        media = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        # 默认关闭：只有显式传入才收敛
        self.assertIn('auto_fit_overlay = bool(style_opts.get("fit_overlay"))', media)
        # 未开启时仍按原策略阻断，不输出省略号残图
        self.assertIn("if strict_text and not overlay[\"ok\"]", media)



if __name__ == "__main__":
    unittest.main(verbosity=2)
