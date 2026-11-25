# -*- coding: utf-8 -*-
"""V4.140 · 广告主报表筛选口径统一专项。

覆盖：
1. date_to 纯日期按北京时间整天结束边界比较，当天明细不再被 00:00 截断；
2. 带 +08:00 的快捷区间换算为 UTC 后与库内时间可比；
3. 关键词 / 维度筛选同时作用于 KPI 与明细，两块口径一致；
4. 前端快捷时间区间工具与筛选栏静态契约。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_reports as reports  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiFieldMap, ApiUnifiedFact  # noqa: E402

CJ = migrations.CJ_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class FilterBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.tmp}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(migrations.ORDER_VIEW_SQL))
            migrations._seed_field_labels(conn)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        for source, target, transform, note in migrations.CJ_FIELD_MAP_SEED:
            self.db.add(ApiFieldMap(template_id=CJ, source_path=source,
                                    target_field=target, transform=transform,
                                    version=1, enabled=True, note=note))
        self.conn = ApiConnection(
            owner_id=1, name="CJ 主账号", template_code=CJ, cid="CID-1",
            endpoint="https://commissions.api.cj.com/query",
            token_enc=advertiser_api.encrypt_token("t1"), status="active")
        self.db.add(self.conn)
        self.db.commit(); self.db.refresh(self.conn)
        self._seed_facts()

    def _fact(self, order, ext, event, adv, sale):
        self.db.add(ApiUnifiedFact(
            template_id=CJ, connection_id=self.conn.id, external_id=ext,
            commission_id=ext, order_id=order, advertiser_name=adv,
            campaign_name="Brand A", event_name="purchase", action_status="new",
            event_date=datetime.fromisoformat(event), sale_amount_usd=sale,
            commission_amount_usd=sale / 10, original=True))
        self.db.flush()

    def _seed_facts(self):
        # 库内为 UTC：北京 11-20 19:50 / 11-21 07:30 / 11-21 09:00
        self._fact("O-1", "C-1", "2026-11-20T11:50:08", "Coofandy", 100)
        self._fact("O-2", "C-2", "2026-11-20T23:30:00", "Coofandy", 200)
        self._fact("O-3", "C-3", "2026-11-21T01:00:00", "OtherAdv", 50)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


class TestReportFilters(FilterBase):
    def test_date_to_plain_date_includes_whole_day(self):
        k = reports.kpi(self.db, 1, date_from="2026-11-20", date_to="2026-11-20")
        d = reports.details(self.db, 1, date_from="2026-11-20", date_to="2026-11-20")
        self.assertEqual(k["order_count"], 2)
        self.assertEqual(d["total"], 2)

    def test_beijing_iso_window_converts_to_utc(self):
        # 事实表 event_date 是 Date（无时刻），用跨天窗口验证换算：
        # 北京 11-21 整天 = UTC 11-20 16:00 ~ 11-21 15:59:59，只含 O-3。
        k = reports.kpi(self.db, 1,
                        date_from="2026-11-21T00:00:00+08:00",
                        date_to="2026-11-21T23:59:59+08:00")
        self.assertEqual(k["order_count"], 1)
        self.assertEqual(k["net_sale_usd"], 50.0)
        self.assertEqual(reports._boundary("2026-11-21T00:00:00+08:00", end=False),
                         "2026-11-20 16:00:00")
        self.assertEqual(reports._boundary("2026-11-21T23:59:59+08:00", end=True),
                         "2026-11-21 15:59:59")

    def test_keyword_filters_kpi_and_details_together(self):
        k = reports.kpi(self.db, 1, keyword="OtherAdv")
        d = reports.details(self.db, 1, keyword="OtherAdv")
        self.assertEqual(k["order_count"], 1)
        self.assertEqual(k["net_sale_usd"], 50.0)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["rows"][0]["order_id"], "O-3")

    def test_dimension_filters_kpi_and_details_together(self):
        k = reports.kpi(self.db, 1, advertiser_name="Coofandy")
        d = reports.details(self.db, 1, advertiser_name="Coofandy")
        self.assertEqual(k["order_count"], 2)
        self.assertEqual(k["net_sale_usd"], 300.0)
        self.assertEqual(d["total"], 2)

    def test_keyword_and_dimension_are_combined(self):
        k = reports.kpi(self.db, 1, advertiser_name="Coofandy", keyword="C-2")
        self.assertEqual(k["order_count"], 1)
        self.assertEqual(k["net_sale_usd"], 200.0)


class TestFrontendFilterContract(unittest.TestCase):
    def test_range_options_and_boundary_source(self):
        page = _read("frontend/src/pages/AdvertiserReports.tsx")
        for label in ("今日", "昨日", "近七天", "本月", "上月（整月）"):
            self.assertIn(f">{label}<", page)
        self.assertIn("reportRange", page)
        self.assertIn("reportWindow", page)
        self.assertNotIn("new Date(", page)  # 时间计算统一在 datetime.ts
        # 菜单描述不能继续宣传已移除的趋势 / 排行子模块
        self.assertNotIn("趋势与维度排行", _read("frontend/src/App.tsx"))

    def test_shared_time_util_exports_range_helpers(self):
        util = _read("frontend/src/datetime.ts")
        self.assertIn("export function reportRange", util)
        self.assertIn("export function reportWindow", util)
        self.assertIn("ReportRangeKey", util)


class TestFrontendRangeBehaviour(unittest.TestCase):
    """用真实编译后的 datetime.ts 验证五个区间的北京日期与 UTC 边界。"""

    @classmethod
    def setUpClass(cls):
        tsc = os.path.join(ROOT, "frontend", "node_modules", ".bin", "tsc")
        if not os.path.exists(tsc) or not shutil.which("node"):
            raise unittest.SkipTest("node / tsc 不可用，跳过前端运行时验证")
        cls.tmp = tempfile.mkdtemp(prefix="range-v4140-")
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

    def test_all_ranges(self):
        js = """
const m = require(process.env.TZMOD);
const now = new Date('2026-11-25T04:05:00Z');  // 北京 2026-11-25 12:05
const out = {};
for (const k of ['today','yesterday','last7','thisMonth','lastMonth']) {
  out[k] = m.reportRange(k, now);
}
console.log(JSON.stringify(out));
"""
        env = os.environ.copy()
        env["TZMOD"] = os.path.join(self.tmp, "datetime.js")
        env["TZ"] = "UTC"
        data = json.loads(subprocess.check_output(["node", "-e", js], env=env, text=True))
        self.assertEqual(data["today"], {
            "fromDate": "2026-11-25", "toDate": "2026-11-25",
            "from": "2026-11-24T16:00:00.000Z", "to": "2026-11-25T04:00:00.000Z"})
        self.assertEqual(data["yesterday"], {
            "fromDate": "2026-11-24", "toDate": "2026-11-24",
            "from": "2026-11-23T16:00:00.000Z", "to": "2026-11-24T15:59:59.000Z"})
        self.assertEqual(data["last7"]["fromDate"], "2026-11-19")
        self.assertEqual(data["last7"]["toDate"], "2026-11-25")
        self.assertEqual(data["thisMonth"]["fromDate"], "2026-11-01")
        self.assertEqual(data["lastMonth"]["fromDate"], "2026-10-01")
        self.assertEqual(data["lastMonth"]["toDate"], "2026-10-31")
        self.assertEqual(data["lastMonth"]["to"], "2026-10-31T15:59:59.000Z")


if __name__ == "__main__":
    unittest.main()
