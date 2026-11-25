# -*- coding: utf-8 -*-
"""V4.137 · 全系统时间展示统一东八区（北京时间）专项测试。

覆盖：
1. 后端 timeutil：北京时间固定 +08:00，不受运行机器 TZ 影响；
2. 调度钟点用 naive 北京时间，避免与 SystemState 水位字符串混用 aware/naive 报错；
3. 前端统一工具 parseBackendTime / fmtBeijing / beijingToday：
   - 无时区后缀按 UTC 解析（修复少 8 小时的历史缺陷）；
   - 带 Z / +08:00 原样解析；纯日期按北京当天零点；空值与非法值可回退；
   - 在 TZ=UTC 与 TZ=Asia/Shanghai 两种环境时区下输出完全一致；
4. 静态契约：全部时间展示点都改为消费统一工具，不再直接 new Date().toLocaleString()。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from timeutil import (BEIJING_TZ, beijing_display, beijing_iso,  # noqa: E402
                      beijing_naive_now, beijing_now)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestBackendBeijingTime(unittest.TestCase):
    def test_timezone_is_fixed_plus_eight(self):
        self.assertEqual(str(BEIJING_TZ), "Asia/Shanghai")
        self.assertEqual(beijing_now().utcoffset(), timedelta(hours=8))
        self.assertTrue(beijing_iso().endswith("+08:00"))

    def test_naive_clock_matches_beijing_wall_clock(self):
        aware = beijing_now()
        naive = beijing_naive_now()
        self.assertIsNone(naive.tzinfo)
        gap = abs((naive - aware.replace(tzinfo=None)).total_seconds())
        self.assertLess(gap, 3)

    def test_display_format(self):
        self.assertRegex(beijing_display(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertRegex(beijing_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$")

    def test_utc_machine_still_renders_beijing_time(self):
        env = os.environ.copy()
        env["TZ"] = "UTC"
        env["PYTHONPATH"] = os.path.join(ROOT, "backend")
        code = ("from timeutil import beijing_display, beijing_iso; "
                "import json; print(json.dumps([beijing_display(), beijing_iso()]))")
        out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True)
        display, iso = json.loads(out.strip())
        expected = datetime.now(BEIJING_TZ)
        self.assertEqual(display[:10], expected.strftime("%Y-%m-%d"))
        self.assertEqual(display[11:], f"{expected.hour:02d}:{expected.minute:02d}")
        self.assertTrue(iso.endswith("+08:00"))


class TestFrontendTimezoneContract(unittest.TestCase):
    PAGES = (
        "frontend/src/pages/AdvertiserApi.tsx",
        "frontend/src/pages/Logs.tsx",
        "frontend/src/pages/MaterialHistory.tsx",
        "frontend/src/pages/LLMSettings.tsx",
        "frontend/src/pages/AdvertiserReports.tsx",
    )

    def test_shared_util_forces_beijing(self):
        util = _read("frontend/src/datetime.ts")
        self.assertIn("Asia/Shanghai", util)
        self.assertIn("export function fmtBeijing", util)
        self.assertIn("export function parseBackendTime", util)
        self.assertIn("export function beijingToday", util)

    def test_all_display_sites_use_shared_util(self):
        for page in self.PAGES:
            self.assertIn("fmtBeijing", _read(page), page)
        self.assertIn("parseBackendMs", _read("frontend/src/CreativeTasksDrawer.tsx"))

    def test_no_unsafe_new_date_to_locale_string(self):
        for page in self.PAGES:
            self.assertNotIn("new Date(", _read(page), page)
        drawer = _read("frontend/src/CreativeTasksDrawer.tsx")
        self.assertNotIn("new Date(", drawer)

    def test_report_datetime_fields_render_beijing(self):
        page = _read("frontend/src/pages/AdvertiserReports.tsx")
        self.assertIn("fmt === 'datetime'", page)
        self.assertIn("fmt === 'date'", page)


class TestFrontendTimezoneBehaviour(unittest.TestCase):
    """用真实编译后的 datetime.ts 验证，避免测试里复刻一份逻辑自说自话。"""

    @classmethod
    def setUpClass(cls):
        tsc = os.path.join(ROOT, "frontend", "node_modules", ".bin", "tsc")
        if not os.path.exists(tsc) or not shutil.which("node"):
            raise unittest.SkipTest("node / tsc 不可用，跳过前端运行时验证")
        cls.tmp = tempfile.mkdtemp(prefix="tz-v4137-")
        result = subprocess.run(
            [tsc, os.path.join(ROOT, "frontend", "src", "datetime.ts"),
             "--target", "es2020", "--module", "commonjs",
             "--outDir", cls.tmp, "--skipLibCheck"],
            capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(os.path.join(cls.tmp, "datetime.js")):
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("datetime.ts 编译失败：" + result.stderr[:200])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _run(self, tz: str) -> str:
        js = """
const m = require(process.env.TZMOD);
const v = [
  m.fmtBeijing('2026-11-25T02:51:00'),
  m.fmtBeijing('2026-11-25T02:51:00Z'),
  m.fmtBeijing('2026-11-25T10:51:00+08:00'),
  m.fmtBeijing('2026-11-25'),
  m.fmtBeijing(null),
  m.fmtBeijing('bad-value', {fallback: 'raw'}),
  m.fmtBeijing('2026-11-25T02:51:00', {seconds: true}),
  String(m.parseBackendMs('2026-11-25T02:51:00')),
];
console.log(v.join('|'));
"""
        env = os.environ.copy()
        env["TZ"] = tz
        env["TZMOD"] = os.path.join(self.tmp, "datetime.js")
        return subprocess.check_output(["node", "-e", js], env=env, text=True).strip()

    def test_naive_utc_is_rendered_as_beijing(self):
        expected = ("2026-11-25 10:51|2026-11-25 10:51|2026-11-25 10:51|"
                    "2026-11-25 00:00|—|raw|2026-11-25 10:51:00|")
        self.assertTrue(self._run("Asia/Shanghai").startswith(expected))

    def test_output_independent_of_browser_timezone(self):
        self.assertEqual(self._run("Asia/Shanghai"), self._run("UTC"))

    def test_beijing_today_independent_of_machine_timezone(self):
        js = "console.log(require(process.env.TZMOD).beijingToday(-7));"
        values = []
        for tz in ("Asia/Shanghai", "UTC"):
            env = os.environ.copy()
            env["TZ"] = tz
            env["TZMOD"] = os.path.join(self.tmp, "datetime.js")
            values.append(subprocess.check_output(["node", "-e", js], env=env, text=True).strip())
        self.assertEqual(values[0], values[1])
        self.assertRegex(values[0], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
