# -*- coding: utf-8 -*-
"""V4.130 · 请求对象变更后的数据库/映射/报表影响评估修复专项。

覆盖：
1. 补齐官方 Item 对象的 perItemSaleAmountUsd（子表精确单价依赖）；
2. 请求字段集合全部登记到 api_field_map（fact / item / ext / __skip__）；
3. V4.130.1 幂等 seed 与 verify_schema 映射行数；
4. 关键映射口径：advertiserName 双目标、Q4 事件名、Q3 品牌名 skip、净额取消单；
5. 数据库 20 字段与订单视图未改列，报表骨架仍为 P3 占位、无字段硬编码；
6. 文档清除 REVERSED 残留，统一 eventDate 水位与官方枚举。
"""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import advertiser_api  # noqa: E402
import migrations  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _requested_fields() -> set[str]:
    """从明细字段清单提取请求字段名，带 items[] / verticalAttributes 前缀。"""
    fields = set()
    section = None
    for raw in advertiser_api.PUBLISHER_COMMISSION_FIELDS.splitlines():
        line = raw.strip()
        if line == "items {":
            section = "items"
            continue
        if line == "verticalAttributes {":
            section = "vertical"
            continue
        if line == "}":
            section = None
            continue
        if not line or "{" in line or "}" in line:
            continue
        if section == "items":
            fields.add("items[]." + line)
        elif section == "vertical":
            fields.add("verticalAttributes." + line)
        else:
            fields.add(line)
    return fields


class TestRequestAndMappingCoverage(unittest.TestCase):
    def test_item_usd_precise_price_requested(self):
        q = advertiser_api.build_detail_payload("1", "a", "b")["query"]
        self.assertIn("perItemSaleAmountUsd", q)
        self.assertIn("perItemSaleAmountPubCurrency", q)

    def test_every_requested_field_is_registered(self):
        requested = _requested_fields()
        registered = {s for s, _t, _r, _n in migrations.CJ_FIELD_MAP_SEED}
        missing = requested - registered
        self.assertEqual(missing, set(), f"请求字段未登记映射：{sorted(missing)}")
        self.assertIn("items[].perItemSaleAmountUsd", requested)
        self.assertIn("verticalAttributes.campaignName", requested)

    def test_key_mapping_semantics(self):
        rows = {(s, t): r for s, t, r, _n in migrations.CJ_FIELD_MAP_SEED}
        self.assertEqual(rows[("advertiserName", "fact.advertiser_name")], "direct")
        self.assertEqual(rows[("advertiserName", "fact.campaign_name")], "direct")
        self.assertEqual(rows[("actionTrackerName", "fact.event_name")], "direct")
        self.assertEqual(rows[("eventDate", "fact.event_date")], "utc_date")
        self.assertEqual(rows[("items[].perItemSaleAmountUsd", "item.unit_price_usd")], "direct")
        self.assertEqual(rows[("verticalAttributes.campaignName", "__skip__")], "skip")
        self.assertEqual(rows[("actionType", "__skip__")], "skip")
        self.assertEqual(rows[("__derived__is_void", "fact.is_void")], "derived")
        self.assertIn(("originalActionId", "fact.original_action_id"), rows)


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = create_engine(
            f"sqlite:///{self.tmp.name}",
            connect_args={"check_same_thread": False, "timeout": 30}, future=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.SessionLocal)
        self._p1.start(); self._p2.start()
        migrations.ensure_schema()

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_seed_is_idempotent_and_versioned(self):
        expected = len(migrations.CJ_FIELD_MAP_SEED)
        with self.SessionLocal() as db:
            count = db.execute(text("SELECT COUNT(*) FROM api_field_map WHERE template_id=:t"),
                               {"t": migrations.CJ_TEMPLATE_ID}).scalar()
            versions = {r[0] for r in db.execute(text("SELECT version FROM schema_migrations")).all()}
        self.assertEqual(count, expected)
        self.assertIn("V4.130.1", versions)
        self.assertEqual(migrations.ensure_schema(), [])
        with self.SessionLocal() as db:
            again = db.execute(text("SELECT COUNT(*) FROM api_field_map WHERE template_id=:t"),
                               {"t": migrations.CJ_TEMPLATE_ID}).scalar()
        self.assertEqual(again, expected)

    def test_verify_schema_exposes_map_count(self):
        v = migrations.verify_schema()
        self.assertEqual(v["map_count"], len(migrations.CJ_FIELD_MAP_SEED))
        self.assertTrue(v["view_ok"])
        self.assertEqual(v["business_fields"], 20)

    def test_order_view_still_uses_existing_fact_columns(self):
        with self.SessionLocal() as db:
            sql = db.execute(text("SELECT sql FROM schema_view_def WHERE name=:n"),
                             {"n": migrations.ORDER_VIEW_NAME}).scalar()
        for col in ("sale_amount_usd", "commission_amount_usd", "event_date", "order_id"):
            self.assertIn(col, sql)


class TestDatabaseAndReportImpact(unittest.TestCase):
    def test_no_new_fact_columns_needed(self):
        source = _read("backend/models.py")
        cls = source.split("class ApiUnifiedFact(Base):", 1)[1].split("class ApiFactItem", 1)[0]
        for col in ("commission_id", "advertiser_name", "campaign_name", "sale_amount_usd",
                    "commission_amount_usd", "unit_price_usd", "event_date", "posting_date"):
            self.assertIn(col, cls)
        self.assertNotIn("item_quantity", cls)
        self.assertIn("增量水位按 eventDate", cls)

    def test_report_page_uses_config_driven_labels(self):
        """V4.135 / P3 起报表已实现：从占位符断言改为验证「表头不硬编码、读配置驱动」。

        字段中文名由后端 api_field_label 的 labels 接口下发，前端只消费 column_key，
        因此页面允许出现 column_key 常量，但不得写死中文展示文案作为表头。
        """
        page = _read("frontend/src/pages/AdvertiserReports.tsx")
        self.assertIn("advertiserApi.reportLabels", page)
        self.assertIn("advertiserApi.reportKpi", page)
        self.assertIn("api_field_label", page)
        for hardcoded in ("净销售金额</", ">佣金金额<", "表头硬编码"):
            self.assertNotIn(hardcoded, page)

    def test_docs_corrected(self):
        design = _read("docs/广告主API统一数据存储表结构设计_20261124.html")
        feature = _read("docs/广告主数据模块功能开发文档_20261124.html")
        self.assertNotIn("action_status = 'REVERSED'", design)
        self.assertNotIn("PENDING/BOOKED/PAID/REVERSED", design)
        self.assertIn("closed / extended / locked / new", design)
        self.assertIn("perItemSaleAmountUsd", design)
        self.assertIn("CJ_FIELD_MAP_SEED", feature)
        self.assertNotIn("sincePostingDate:$from", feature)


if __name__ == "__main__":
    unittest.main()
