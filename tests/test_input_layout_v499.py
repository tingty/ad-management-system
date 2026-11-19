"""V4.99：创意工作台输入区排版与素材类型下拉交互。

无模型 / 无网络：以静态源码断言固定两处回归——
1) 参考图说明不再作为两列表单网格的第三个子元素掉进 84px 标签列被折成窄条；
2) 素材类型多选下拉在点击自身之外区域 / Esc 后收起，监听随展开状态清理。
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
TSX = FRONTEND / "pages" / "CreativeWorkbench.tsx"
CSS = FRONTEND / "styles.css"


def _reference_block(src: str) -> str:
    start = src.index("{/* 参考图（upload / URL）")
    end = src.index("{/* 品牌：", start)
    return src[start:end]


class TestInputLayoutV499(unittest.TestCase):
    def test_01_reference_hint_inside_control_column(self):
        block = _reference_block(TSX.read_text(encoding="utf-8"))
        self.assertIn('<div className="cwb-ov-col">', block)
        self.assertIn('<div className="cwb-ref-row cwb-ref-row2">', block)
        self.assertIn('<span className="cwb-field-hint">仅学习配色与画面质感', block)
        self.assertLess(block.index('<div className="cwb-ov-col">'),
                        block.index('<div className="cwb-ref-row cwb-ref-row2">'))
        self.assertLess(block.index('<div className="cwb-ref-row cwb-ref-row2">'),
                        block.index('<span className="cwb-field-hint">仅学习配色与画面质感'))

    def test_02_no_third_grid_child(self):
        # 旧写法：ref-row 与 hint 是表单网格的两个并列子元素，hint 掉进标签列
        src = TSX.read_text(encoding="utf-8")
        self.assertNotIn('</div>\n                <span className="cwb-field-hint">仅学习配色与画面质感', src)

    def test_03_grid_is_two_columns(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: 84px 1fr", css)
        self.assertIn(".cwb-ov-col { display: flex; flex-direction: column; gap: 6px; }", css)


class TestMaterialTypeDropdownV499(unittest.TestCase):
    def test_04_outside_click_closes(self):
        src = TSX.read_text(encoding="utf-8")
        self.assertIn("const mtRef = useRef<HTMLDivElement>(null)", src)
        self.assertIn('<div className="cwb-mt" ref={mtRef}>', src)
        self.assertIn("document.addEventListener('mousedown', closeOnOutside)", src)
        self.assertIn("document.addEventListener('touchstart', closeOnOutside)", src)
        self.assertIn("!mtRef.current.contains(e.target as Node)", src)
        self.assertIn("setMtOpen(false)", src)

    def test_05_esc_and_listener_cleanup(self):
        src = TSX.read_text(encoding="utf-8")
        self.assertIn("document.addEventListener('keydown', closeOnEsc)", src)
        self.assertIn("e.key === 'Escape'", src)
        self.assertIn("document.removeEventListener('mousedown', closeOnOutside)", src)
        self.assertIn("document.removeEventListener('touchstart', closeOnOutside)", src)
        self.assertIn("document.removeEventListener('keydown', closeOnEsc)", src)
        self.assertIn("}, [mtOpen])", src)

    def test_06_hint_tells_user_how_to_close(self):
        src = TSX.read_text(encoding="utf-8")
        self.assertIn("点击空白处收起", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
