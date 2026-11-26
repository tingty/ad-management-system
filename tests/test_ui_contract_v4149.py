# -*- coding: utf-8 -*-
"""V4.149 · 系统级 UI 统一规范静态回归。

约束：
1. 新增/重构模块必须复用 frontend/src/ui.tsx 的 Ui* 组件；
2. 控件外观复用创意工作台 cwb-* 样式，禁止各模块另写一套；
3. 页面布局默认从上到下，模块内不再出现左右平铺的 ad-panel-head / 原生表单标签。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"


class TestSystemUiContractV4149(unittest.TestCase):
    def test_01_shared_ui_components_exist(self):
        ui = (FRONTEND / "ui.tsx").read_text(encoding="utf-8")
        for name in ("UiButton", "UiLinkButton", "UiInput", "UiSelect", "UiTextarea",
                     "UiFormRow", "UiCard", "UiPanel", "UiActionRow", "UiStack", "UiCheckRow"):
            self.assertTrue(
                "export function %s" % name in ui or "export const %s" % name in ui,
                "缺少共享组件 %s" % name,
            )

    def test_02_controls_reuse_creative_workbench_classes(self):
        ui = (FRONTEND / "ui.tsx").read_text(encoding="utf-8")
        for token in ("ui-input cwb-input", "ui-select cwb-select",
                      "ui-textarea cwb-supplement-input", "cwb-start", "cwb-link-btn"):
            self.assertIn(token, ui)

    def test_03_styles_define_vertical_system_layout(self):
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        self.assertIn("V4.149 系统级 UI 组件统一规范", css)
        for cls in (".ui-page", ".ui-card", ".ui-form", ".ui-form-row",
                    ".ui-action-row", ".ui-panel", ".ui-task-card", ".ui-script-details"):
            self.assertIn(cls, css)
        self.assertIn("flex-direction: column", css)
        self.assertIn("--ui-control-h: 40px", css)

    def test_04_imitate_page_has_no_raw_form_controls(self):
        src = (FRONTEND / "pages" / "ImitateVideo.tsx").read_text(encoding="utf-8")
        for tag in ("<input", "<select", "<textarea", "<button"):
            self.assertNotIn(tag, src)
        for token in ("ui-page", "UiCard", "UiFormRow", "UiInput", "UiSelect", "UiButton"):
            self.assertIn(token, src)

    def test_05_imitate_page_has_no_old_horizontal_panels(self):
        src = (FRONTEND / "pages" / "ImitateVideo.tsx").read_text(encoding="utf-8")
        self.assertNotIn("ad-panel-head", src)
        self.assertNotIn("display: 'flex'", src)
        self.assertNotIn("display: 'grid'", src)
        self.assertIn('className="ui-task-list"', src)
        self.assertIn('className="ui-script-list"', src)

    def test_06_no_inline_style_spacing_in_imitate_page(self):
        src = (FRONTEND / "pages" / "ImitateVideo.tsx").read_text(encoding="utf-8")
        self.assertEqual([], re.findall(r"style=\{\{[^}]*margin", src))
        self.assertEqual([], re.findall(r"style=\{\{[^}]*padding", src))


if __name__ == "__main__":
    unittest.main(verbosity=2)
