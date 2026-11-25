# -*- coding: utf-8 -*-
"""V4.141 · 广告主报表交互优化专项。

覆盖：
1. 时间区间默认「本月」，进入页面即自动加载默认数据；
2. 删除「重置」按钮，新增「查询」按钮且使用全局 .btn primary 样式；
3. 草稿条件与已提交条件分离：选择筛选后必须点「查询」才生效；
4. 下钻抽屉加宽，扩展字段 / 原始 JSON 使用可完整滚动查阅的大区样式。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

PAGE = "frontend/src/pages/AdvertiserReports.tsx"
CSS = "frontend/src/styles.css"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestSubmitQueryContract(unittest.TestCase):
    """筛选交互：默认本月、查询才生效、按钮样式统一。"""

    @classmethod
    def setUpClass(cls):
        cls.page = _read(PAGE)

    def test_default_range_is_this_month(self):
        self.assertIn("const DEFAULT_RANGE: ReportRangeKey = 'thisMonth'", self.page)
        self.assertIn("useState<ReportRangeKey>(DEFAULT_RANGE)", self.page)
        # 默认区间用于初始日期输入框与首次加载条件
        self.assertIn("reportRange(DEFAULT_RANGE)", self.page)
        self.assertIn("date_from: initialWindow.from", self.page)
        self.assertIn("date_to: initialWindow.to", self.page)

    def test_first_load_uses_applied_without_waiting_for_click(self):
        # 加载 effect 依赖 applied + page，首次渲染即以初始 applied 触发一次
        self.assertIn("useState<ReportFilter>(() => ({", self.page)
        self.assertIn("advertiserApi.reportKpi(applied)", self.page)
        self.assertIn("advertiserApi.reportDetails({ ...applied, page })", self.page)
        self.assertIn("}, [applied, page])", self.page)
        # 草稿的筛选控件不再各自 setPage(1) 触发刷新
        self.assertNotIn("setConnectionId(e.target.value ? Number(e.target.value) : ''); setPage(1)", self.page)
        self.assertNotIn("setRangeKey(''); setDateFrom(e.target.value); setPage(1)", self.page)

    def test_query_button_replaces_reset_and_uses_global_style(self):
        self.assertIn("function commitQuery()", self.page)
        self.assertIn('setApplied({', self.page)
        self.assertNotIn("function resetFilter()", self.page)
        self.assertNotIn(">重置<", self.page)
        self.assertIn('className="btn primary" onClick={commitQuery}', self.page)
        # 查询按钮在筛选栏对齐输入框高度
        css = _read(CSS)
        self.assertIn(".ad-filter-bar > .btn { height: 30px;", css)

    def test_draft_changes_do_not_call_set_applied(self):
        # 只有 commitQuery 写 applied，草稿 onChange 只改本地 state
        self.assertEqual(self.page.count("setApplied("), 1)
        self.assertIn("onClick={commitQuery}", self.page)


class TestDrilldownDrawerContract(unittest.TestCase):
    """下钻抽屉：加宽 + 大 JSON 区 + 分区卡片 + 全局按钮。"""

    @classmethod
    def setUpClass(cls):
        cls.page = _read(PAGE)
        cls.css = _read(CSS)

    def test_drawer_is_wide_and_sectioned(self):
        self.assertIn('className="ad-drawer ad-drawer-wide"', self.page)
        self.assertIn(".ad-drawer-wide { width: min(1080px, 96vw); }", self.css)
        self.assertIn("ad-drawer-sec-head", self.page)
        self.assertIn("ad-drawer-title", self.page)
        self.assertIn("ad-drawer-x", self.page)

    def test_json_blocks_are_large_and_scrollable(self):
        self.assertIn('className="ad-json-large"', self.page)
        # 扩展字段 + 原始 JSON 两处都用大区
        self.assertEqual(self.page.count('className="ad-json-large"'), 2)
        # 原始层 payload_json 可能是 JSON 字符串，先反序列化再缩进，避免整行转义
        self.assertIn("function prettyPayload", self.page)
        self.assertIn("prettyPayload(data.ext)", self.page)
        self.assertIn("prettyPayload(data.source.payload_json)", self.page)
        self.assertIn(".ad-json-large { margin: 0;", self.css)
        self.assertIn("min-height: 160px; max-height: 52vh;", self.css)
        self.assertIn("overflow: auto;", self.css)
        # 锁表头/事实行不会被 JSON 撑破
        self.assertIn("ad-drill-table-wrap", self.page)
        self.assertIn(".ad-drill-table-wrap { overflow-x: auto;", self.css)

    def test_drawer_footer_uses_global_button(self):
        self.assertIn('className="ad-drawer-foot"', self.page)
        self.assertIn('className="btn primary" onClick={onClose}', self.page)


class TestDefaultRangeRuntime(unittest.TestCase):
    """用真实编译后的 datetime.ts 验证默认「本月」边界随日期变化。"""

    @classmethod
    def setUpClass(cls):
        tsc = os.path.join(ROOT, "frontend", "node_modules", ".bin", "tsc")
        if not os.path.exists(tsc) or not shutil.which("node"):
            raise unittest.SkipTest("node / tsc 不可用，跳过前端运行时验证")
        cls.tmp = tempfile.mkdtemp(prefix="range-v4141-")
        result = subprocess.run(
            [tsc, os.path.join(ROOT, "frontend", "src", "datetime.ts"),
             "--target", "es2020", "--module", "commonjs",
             "--outDir", cls.tmp, "--skipLibCheck"],
            capture_output=True, text=True)
        if result.returncode != 0:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("datetime.ts 编译失败：" + result.stderr[:200])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _range(self, iso_now):
        js = """
const m = require(process.env.TZMOD);
console.log(JSON.stringify(m.reportRange('thisMonth', new Date(process.env.NOW))));
"""
        env = os.environ.copy()
        env["TZMOD"] = os.path.join(self.tmp, "datetime.js")
        env["NOW"] = iso_now
        env["TZ"] = "UTC"
        return json.loads(subprocess.check_output(["node", "-e", js], env=env, text=True))

    def test_this_month_starts_on_first_and_ends_today(self):
        r = self._range("2026-11-25T04:05:00Z")  # 北京 11-25 12:05
        self.assertEqual(r["fromDate"], "2026-11-01")
        self.assertEqual(r["toDate"], "2026-11-25")
        self.assertEqual(r["from"], "2026-10-31T16:00:00.000Z")
        self.assertEqual(r["to"], "2026-11-25T15:59:59.000Z")

    def test_this_month_rolls_over_at_month_boundary(self):
        r = self._range("2026-12-01T00:30:00Z")  # 北京 12-01 08:30
        self.assertEqual(r["fromDate"], "2026-12-01")
        self.assertEqual(r["toDate"], "2026-12-01")
        self.assertEqual(r["from"], "2026-11-30T16:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
