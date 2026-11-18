"""V4.95：创意文案展示区按截图样式（字段标题按平台定义 + 独立描边输入框）。

无模型 / 无网络：验证 Meta 字段 label 对齐后台原文案面板（正文 / 广告标题 / 描述）、
字数表带字段 key 供精确匹配、前端组件按 schema 顺序渲染且保留字数与信息图标。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
sys.path.insert(0, str(HERE.parent / "backend"))

from media_ad import copy_schema_for, _char_table  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"


class TestCopyLabelsV495(unittest.TestCase):
    def test_01_meta_labels_match_ad_manager(self):
        labels = {s["key"]: s["label"] for s in copy_schema_for("Meta", "")}
        self.assertEqual(labels["primary_text"], "正文")
        self.assertEqual(labels["headline"], "广告标题")
        self.assertEqual(labels["description"], "描述")

    def test_02_meta_keys_and_limits_unchanged(self):
        schema = copy_schema_for("Meta", "")
        self.assertEqual([s["key"] for s in schema],
                         ["primary_text", "headline", "description", "cta"])
        self.assertEqual(schema[0]["max"], 125)
        self.assertEqual(schema[1]["max"], 40)
        self.assertEqual(schema[2]["max"], 30)

    def test_03_other_platforms_use_own_terms(self):
        # 标题按媒体平台定义：Google 用 RSA，其他平台保持各自术语
        google = {s["key"]: s["label"] for s in copy_schema_for("Google", "RSA")}
        self.assertEqual(google["headline"], "RSA 标题")

    def test_04_char_table_carries_field_key(self):
        schema = copy_schema_for("Meta", "")
        rows = _char_table({"primary_text": "Explore the promotion",
                            "headline": ["Explore the Gift Card Promotion", "Learn more"]}, schema)
        self.assertTrue(rows)
        self.assertTrue(all("key" in r for r in rows))
        self.assertIn("key", rows[0])
        by_key = {}
        for r in rows:
            by_key.setdefault(r["key"], []).append(r)
        self.assertEqual(by_key["primary_text"][0]["text"], "Explore the promotion")
        self.assertEqual(len(by_key["headline"]), 2)
        self.assertTrue(all(r["field"].startswith("广告标题") for r in by_key["headline"]))


class TestCopyDisplayWiringV495(unittest.TestCase):
    def test_05_frontend_renders_platform_schema_cards(self):
        src = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("function CopyFieldCards", src)
        self.assertIn("<CopyFieldCards c={c} />", src)
        # 按 schema 顺序（platform 定义）渲染，而非对象插入顺序
        self.assertIn("schema.map(s => s.key)", src)
        # 字数按 key 精确匹配，兼容旧数据 label
        self.assertIn("r.key === k", src)
        self.assertNotIn("const charMap", src)
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".cwb-copy-card-box", css)
        self.assertIn(".cwb-copy-info", css)
        self.assertIn(".cwb-copy-cards", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
