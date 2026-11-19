"""V4.99 / V4.110：创意工作台输入区排版与素材类型下拉交互。

无模型 / 无网络：以静态源码断言固定回归——
1) 输入区已删除「素材图片选择 / 参考图 / 品牌」三块组件，不得残留；
2) 图生视频的参考图上传迁到视频规划区，上传、缩略图、URL 输入仍在同一个控件容器内
   （旧问题是说明行掉进 84px 标签列被折成窄条）；
3) 素材类型多选下拉在点击自身之外区域 / Esc 后收起，监听随展开状态清理。
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
VS = FRONTEND / "pages" / "VideoStudio.tsx"
CSS = FRONTEND / "styles.css"


class TestInputLayoutV499(unittest.TestCase):
    def test_01_input_form_has_no_removed_components(self):
        src = TSX.read_text(encoding="utf-8")
        for gone in ('<select id="cwb-ov"', 'htmlFor="cwb-ov"', '>参考图</label>', '>品牌</label>',
                     'placeholder="品牌名称（可留空让模型推断）"', "onRefFile", "onBrandLogo"):
            self.assertNotIn(gone, src, f"输入区不应再出现：{gone}")
        self.assertNotIn("cwb-brand-row", src)
        self.assertNotIn("cwb-brand-logo-preview", src)

    def test_02_video_reference_upload_lives_in_video_panel(self):
        vs = VS.read_text(encoding="utf-8")
        self.assertIn('className="vs-ref-edit"', vs)
        self.assertIn('className="vs-ref-row"', vs)
        self.assertIn("onRefFile", vs)
        # 上传 / 缩略图 / 移除 / URL 都在同一容器内，不拆成表单网格的并列子元素
        start = vs.index('className="vs-ref-edit"')
        end = vs.index(")}", vs.index('placeholder="或粘贴图片 URL（自动下载）"'))
        block = vs[start:end]
        for token in ("cwb-ref-upload", "vs-ref-thumb", "cwb-ref-clear", "cwb-ref-url"):
            self.assertIn(token, block)
        # 参考图只在「图生视频」下出现
        self.assertIn("options.mode === 'image_to_video'", vs)

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
