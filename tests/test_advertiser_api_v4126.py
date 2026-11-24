# -*- coding: utf-8 -*-
"""V4.126 · API对接弹窗表单组件样式统一专项测试。

覆盖：
1. 新建弹窗与设置弹窗的输入框、下拉框、数字框共用同一组尺寸/颜色/边框/焦点样式；
2. 统一后的控件不再受全局 select 的 13.5px / 8px padding / 白底差异影响；
3. 复选框不在统一规则内，保持原有的行内勾选样式；
4. 页面结构未被样式调整破坏，仍为双弹窗 + 列表。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestModalFormControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _read("frontend/src/styles.css")
        cls.page = _read("frontend/src/pages/AdvertiserApi.tsx")
        marker = "/* V4.126 弹窗表单控件统一"
        cls.i = cls.css.find(marker)
        tail = cls.css[cls.i:] if cls.i >= 0 else ""
        next_comment = tail.find("\n/*", 5)
        cls.block = tail[:next_comment] if next_comment > 0 else tail

    def test_unified_rule_exists_for_inputs_and_selects(self):
        self.assertGreater(self.i, 0, "缺少 V4.126 表单控件统一样式块")
        self.assertIn(".ad-modal .ad-form-grid input:not([type=\"checkbox\"]):not([type=\"radio\"]),", self.block)
        self.assertIn(".ad-modal .ad-form-grid select {", self.block)

    def test_same_height_border_radius_background_and_font(self):
        for prop in ["height: 38px", "padding: 0 12px", "border: 1px solid var(--border)",
                     "border-radius: 8px", "background: var(--card)", "color: var(--text)",
                     "font-size: 14px"]:
            self.assertIn(prop, self.block, f"统一样式缺少 {prop}")

    def test_focus_state_is_shared(self):
        self.assertIn(":focus:not([type=\"checkbox\"]):not([type=\"radio\"])", self.block)
        self.assertIn(".ad-modal .ad-form-grid select:focus", self.block)
        self.assertIn("outline: none", self.block)
        self.assertIn("border-color: var(--primary)", self.block)
        self.assertIn("box-shadow: 0 0 0 3px", self.block)

    def test_checkbox_excluded_and_number_inputs_covered(self):
        self.assertIn('.ad-check-line input { width: auto; }', self.css)
        self.assertIn('type="checkbox"', self.page)
        self.assertIn('type="number"', self.page)
        self.assertNotIn("width: 150px", self.block)
        self.assertIn("min-width: 0", self.block, "需覆盖全局 select 的 min-width:150px")

    def test_no_later_rule_splits_the_appearance_again(self):
        # 防止后续新增样式再次把输入框/下拉框拆成两套外观
        later = self.css[self.i + len(self.block):]
        self.assertNotIn(".ad-modal .ad-form-grid select", later)
        self.assertNotIn(".ad-modal .ad-form-grid input", later)


class TestPageStructureUnchanged(unittest.TestCase):
    def test_two_modals_still_render(self):
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertEqual(page.count('<div className="ad-modal"'), 2)
        self.assertEqual(page.count('className="ad-form-grid"'), 2)
        self.assertEqual(page.count('className="ad-modal-foot"'), 2)


if __name__ == "__main__":
    unittest.main()
