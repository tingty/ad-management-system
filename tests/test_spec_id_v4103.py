"""V4.103 / 方案H：媒体规格标准库 spec_id 稳定引用回归。

- 每条标准库条目有稳定、唯一 spec_id；按 ID 可精确往返解析。
- library_payload / image_targets 透出 spec_id。
- validate_task_matrix 接受 spec_id 字段并透传到规范化 slot（命中时以标准库为准）。
- 前端 slots 构造带 spec_id；结果卡 specOf 读真实 formats/max_bytes。
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

import media_spec_library as msl  # noqa: E402
from media_platforms import validate_task_matrix, canonical_platform  # noqa: E402


class TestSpecIdV4103(unittest.TestCase):

    def test_01_spec_id_stable_and_unique(self):
        entries = msl.all_entries()
        ids = [e.spec_id for e in entries]
        self.assertTrue(all(ids), "每条须有 spec_id")
        self.assertEqual(len(ids), len(set(ids)), "spec_id 必须唯一")
        # 同一条目重复解析稳定
        for e in entries[:8]:
            self.assertEqual(e.spec_id, msl.entry_for_spec_id(e.spec_id).spec_id)

    def test_02_payload_exposes_spec_id(self):
        payload = msl.library_payload()
        self.assertTrue(all(e.get("spec_id") for e in payload["entries"]))
        meta = msl.image_targets("Meta")
        self.assertTrue(meta, "Meta 应有图片规则")
        self.assertTrue(all(row.get("spec_id") for row in meta))

    def test_03_image_target_for_spec_id(self):
        img_entries = [e for e in msl.all_entries() if e.media == "image"]
        e = img_entries[0]
        row = msl.image_target_for_spec_id(e.spec_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["spec_id"], e.spec_id)
        self.assertEqual(row["platform"], e.platform)
        # 视频 spec_id 不应被图片解析命中
        vid = next(x for x in msl.all_entries() if x.media == "video")
        self.assertIsNone(msl.image_target_for_spec_id(vid.spec_id))

    def test_04_task_matrix_accepts_spec_id(self):
        """命中 spec_id 的 slot 被接受并透传，ad_product/asset_role 来自标准库。"""
        entry = next(e for e in msl.all_entries()
                     if e.media == "image" and canonical_platform(e.platform) == "Meta" and e.sizes)
        size = entry.sizes[0]
        slot = {"size": size, "placement": "Meta", "spec_id": entry.spec_id}
        checked = validate_task_matrix("Meta", [slot], variant_count=0)
        row = checked["slots"][0]
        self.assertEqual(row["spec_id"], entry.spec_id)
        self.assertEqual(row["ad_product"], entry.ad_product)
        self.assertEqual(row["asset_role"], entry.asset_role)

    def test_05_task_matrix_spec_id_platform_mismatch_flagged(self):
        """spec_id 平台与本批不一致时该行被标记错误（不静默套用）。"""
        entry = next(e for e in msl.all_entries()
                     if e.media == "image" and canonical_platform(e.platform) == "Moloco" and e.sizes)
        from media_platforms import MediaRuleError
        with self.assertRaises(MediaRuleError):
            validate_task_matrix("Meta", [{"size": entry.sizes[0],
                                           "placement": "Meta", "spec_id": entry.spec_id}])

    def test_06_frontend_slots_and_result_card(self):
        cw = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("spec_id?: string", api.split("slots: {", 1)[1].split("}[]", 1)[0])
        self.assertIn("spec_id: specIdFor(p, size)", cw)
        # 结果卡读真实规格，不再只硬编码 ≤30MB
        self.assertIn("sl?.formats", cw)
        self.assertIn("sl?.max_bytes", cw)
        self.assertIn("fmtBytes", cw)

    def test_07_media_ad_spec_id_priority(self):
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        self.assertIn("image_target_for_spec_id as spec_image_target_for_spec_id", src)
        self.assertIn("spec_image_target_for_spec_id(slot.get(\"spec_id\")", src)
        self.assertIn('"formats": list((lib_match or {}).get("formats") or ())', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
