# -*- coding: utf-8 -*-
"""V4.135 · P3 广告主报表专项测试。

覆盖：
1. 表头配置读 api_field_label（列顺序 / 单位 / 格式 / 枚举 / visible），前端零硬编码；
2. KPI 读订单最终视图口径：净额 / 订单数（一个订单一行）/ 取消单 / 平均客单价 / 除零保护；
3. 趋势按事件日期聚合、维度 EXISTS 筛选；
4. 维度排行按订单取维度代表值，原始+修正单不重复计单；
5. 明细列表分页 / 动态表头 / 关键词与维度筛选；
6. 下钻链路：事实行 → 商品子表 / 扩展层 → 原始 JSON + 字段映射规则；
7. owner 隔离：不同用户只见自己的连接数据，越权下钻 found=False；
8. 静态契约：前端页面消费 labels 接口、不硬编码中文字段名、无 ROAS/ROI 伪指标。
全部使用全新隔离 SQLite + 种子数据，不触达真实 CJ API、不污染全局库。
"""
import os
import sys
import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_reports  # noqa: E402
import advertiser_api  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import (ApiConnection, ApiUnifiedFact, ApiFactItem, ApiFactExt,  # noqa: E402
                    ApiSourceRecord, ApiFieldMap)

CJ = migrations.CJ_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class ReportBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.tmp}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        # 建订单最终视图 + 展示名种子（与生产 ensure_schema 同一套函数）
        with self.engine.begin() as conn:
            conn.execute(text(migrations.ORDER_VIEW_SQL))
            migrations._seed_field_labels(conn)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        for source, target, transform, note in migrations.CJ_FIELD_MAP_SEED:
            self.db.add(ApiFieldMap(template_id=CJ, source_path=source,
                                    target_field=target, transform=transform,
                                    version=1, enabled=True, note=note))
        self.conn1 = ApiConnection(
            owner_id=1, name="CJ 主账号", template_code=CJ, cid="CID-1",
            endpoint="https://commissions.api.cj.com/query",
            token_enc=advertiser_api.encrypt_token("t1"), status="active")
        self.conn2 = ApiConnection(
            owner_id=2, name="他人账号", template_code=CJ, cid="CID-2",
            endpoint="https://commissions.api.cj.com/query",
            token_enc=advertiser_api.encrypt_token("t2"), status="active")
        self.db.add_all([self.conn1, self.conn2])
        self.db.commit()
        self.db.refresh(self.conn1); self.db.refresh(self.conn2)

    def _fact(self, *, order, sale, comm, day, adv="Adv A", brand="Brand A",
              event="purchase", status="new", conn_id=None, void=False, ext_id=None):
        src = ApiSourceRecord(
            template_id=CJ, connection_id=conn_id or self.conn1.id,
            external_id=f"COMM-{order}-{sale}",
            payload_json={"commissionId": f"COMM-{order}-{sale}", "orderId": order,
                          "advertiserName": adv, "saleAmountUsd": sale})
        self.db.add(src); self.db.flush()
        f = ApiUnifiedFact(
            template_id=CJ, connection_id=conn_id or self.conn1.id,
            source_record_id=src.id, external_id=src.external_id,
            commission_id=src.external_id, order_id=order,
            advertiser_name=adv, campaign_name=brand, event_name=event,
            action_status=status, event_date=date.fromisoformat(day),
            sale_amount_usd=sale, commission_amount_usd=comm,
            is_void=1 if void else 0, original=True)
        self.db.add(f); self.db.flush()
        return f

    def tearDown(self):
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


class TestReportLabels(ReportBase):
    def test_labels_from_config_with_order_unit_format_enum(self):
        labels = advertiser_reports.field_labels(self.db, "fact")
        keys = [c["column_key"] for c in labels["columns"]]
        self.assertEqual(keys, sorted(keys, key=lambda k: next(
            c["sort_no"] for c in labels["all"] if c["column_key"] == k)))
        sale = next(c for c in labels["all"] if c["column_key"] == "sale_amount_usd")
        self.assertEqual(sale["label"], "销售金额")
        self.assertEqual(sale["unit"], "USD")
        self.assertEqual(sale["format"], "decimal2")
        status = next(c for c in labels["all"] if c["column_key"] == "action_status")
        self.assertEqual(status["format"], "enum")
        self.assertIn("new", status["enum_map"])
        self.assertIn("roas", labels["unavailable_metrics"])

    def test_order_final_scope_labels(self):
        labels = advertiser_reports.field_labels(self.db, "order_final")
        keys = {c["column_key"] for c in labels["columns"]}
        self.assertIn("net_sale_usd", keys)
        self.assertIn("is_void", keys)
        self.assertTrue(all(c["visible"] for c in labels["columns"]))


class TestReportKpi(ReportBase):
    def setUp(self):
        super().setUp()
        # O-1: 原始 + 负修正 → 净额归零 → 视图判为取消单（一个订单一行）
        self._fact(order="O-1", sale="100.00", comm="10.00", day="2026-11-20")
        self._fact(order="O-1", sale="-100.00", comm="-10.00", day="2026-11-20")
        self._fact(order="O-2", sale="200.00", comm="20.00", day="2026-11-21",
                   adv="Adv B", brand="Brand B")
        self._fact(order="O-3", sale="50.00", comm="5.00", day="2026-11-20")
        self.db.commit()

    def test_kpi_reads_order_final_view(self):
        r = advertiser_reports.kpi(self.db, 1)
        self.assertEqual(r["source_view"], "v_api_order_final")
        self.assertEqual(r["order_count"], 3)          # 不是 4 条明细
        self.assertEqual(r["detail_count"], 4)
        self.assertEqual(r["void_count"], 1)           # O-1 正负相抵
        self.assertEqual(r["net_sale_usd"], 250.0)     # 0 + 200 + 50
        self.assertEqual(r["net_commission_usd"], 25.0)
        self.assertEqual(r["avg_order_value_usd"], 125.0)  # 250 / (3-1)

    def test_kpi_date_filter(self):
        r = advertiser_reports.kpi(self.db, 1, date_from="2026-11-21")
        self.assertEqual(r["order_count"], 1)
        self.assertEqual(r["net_sale_usd"], 200.0)

    def test_kpi_empty_safe_and_owner_isolation(self):
        empty = advertiser_reports.kpi(self.db, 999)
        self.assertEqual(empty["order_count"], 0)
        self.assertEqual(empty["avg_order_value_usd"], 0.0)  # 除零保护
        other = advertiser_reports.kpi(self.db, 2)
        self.assertEqual(other["order_count"], 0)             # 看不到 conn1 数据


class TestReportTrendRankings(ReportBase):
    def setUp(self):
        super().setUp()
        self._fact(order="O-1", sale="100.00", comm="10.00", day="2026-11-20", adv="Adv A")
        self._fact(order="O-2", sale="200.00", comm="20.00", day="2026-11-21", adv="Adv B")
        self._fact(order="O-3", sale="50.00", comm="5.00", day="2026-11-20", adv="Adv A")
        self.db.commit()

    def test_trend_by_event_date(self):
        r = advertiser_reports.trend(self.db, 1)
        self.assertEqual(r["total"], 2)
        p20, p21 = r["points"]
        self.assertEqual(p20["event_date"], "2026-11-20")
        self.assertEqual(p20["net_sale_usd"], 150.0)
        self.assertEqual(p20["order_count"], 2)
        self.assertEqual(p21["net_sale_usd"], 200.0)

    def test_trend_dimension_filter(self):
        r = advertiser_reports.trend(self.db, 1, dimension="advertiser_name",
                                     dimension_value="Adv B")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["points"][0]["net_sale_usd"], 200.0)

    def test_rankings_no_double_count(self):
        r = advertiser_reports.rankings(self.db, 1, dimension="advertiser_name")
        self.assertEqual(r["dimension_label"], "广告主名称")
        by_name = {i["name"]: i for i in r["items"]}
        self.assertEqual(by_name["Adv A"]["order_count"], 2)
        self.assertEqual(by_name["Adv A"]["net_sale_usd"], 150.0)
        self.assertEqual(by_name["Adv B"]["net_commission_usd"], 20.0)
        self.assertEqual(r["items"][0]["name"], "Adv B")  # 佣金降序

    def test_rankings_invalid_dimension_falls_back(self):
        r = advertiser_reports.rankings(self.db, 1, dimension="__evil__; DROP TABLE")
        self.assertEqual(r["dimension"], advertiser_reports.DEFAULT_DIMENSION)


class TestReportDetailsDrilldown(ReportBase):
    def setUp(self):
        super().setUp()
        f = self._fact(order="O-1", sale="120.00", comm="12.00", day="2026-11-20")
        self.fact_id = f.id
        self.db.add(ApiFactItem(fact_id=f.id, sku="SKU-1", quantity=2,
                                unit_price_usd=60.0, commission_usd=6.0))
        self.db.add(ApiFactExt(fact_id=f.id, template_id=CJ,
                               data_json={"vertical_brand": "Brand A"}))
        self._fact(order="O-2", sale="80.00", comm="8.00", day="2026-11-21", adv="Adv B")
        self.db.commit()

    def test_details_pagination_and_dynamic_columns(self):
        r = advertiser_reports.details(self.db, 1, page=1, page_size=1)
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["total_pages"], 2)
        self.assertEqual(len(r["rows"]), 1)
        self.assertIn("order_id", r["rows"][0])
        cols = {c["column_key"]: c for c in r["columns"]}
        self.assertEqual(cols["order_id"]["label"], "订单号")
        self.assertEqual(cols["commission_amount_usd"]["format"], "decimal2")

    def test_details_filters(self):
        r = advertiser_reports.details(self.db, 1, advertiser_name="Adv B")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["rows"][0]["order_id"], "O-2")
        kw = advertiser_reports.details(self.db, 1, keyword="O-1")
        self.assertEqual(kw["total"], 1)
        self.assertEqual(kw["rows"][0]["order_id"], "O-1")

    def test_drilldown_chain(self):
        d = advertiser_reports.drilldown(self.db, 1, self.fact_id)
        self.assertTrue(d["found"])
        self.assertEqual(d["chain"],
                         ["api_unified_fact", "api_fact_item / api_fact_ext", "api_source_record"])
        self.assertEqual(d["fact"]["order_id"], "O-1")
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["sku"], "SKU-1")
        self.assertEqual(d["ext"]["vertical_brand"], "Brand A")
        self.assertIsNotNone(d["source"]["payload_json"])
        self.assertGreater(len(d["field_maps"]), 20)  # 映射规则随报表下钻可查

    def test_drilldown_owner_isolation(self):
        d = advertiser_reports.drilldown(self.db, 2, self.fact_id)
        self.assertFalse(d["found"])


class TestReportStaticContract(ReportBase):
    def test_frontend_uses_labels_and_no_hardcoded_metrics(self):
        page = _read("frontend/src/pages/AdvertiserReports.tsx")
        self.assertIn("advertiserApi.reportLabels", page)
        self.assertIn("advertiserApi.reportKpi", page)
        self.assertIn("advertiserApi.reportDetails", page)
        self.assertIn("advertiserApi.reportDrilldown", page)
        # 字段中文名来自后端配置，不在前端写死常见表头
        self.assertNotIn("净销售金额</", page)
        self.assertNotIn(">佣金金额<", page)
        for bad in ("ROAS", "ROI", "CTR", "CVR"):
            self.assertNotIn(bad, page)

    def test_backend_declares_unavailable_metrics(self):
        self.assertIn("spend", advertiser_reports.UNAVAILABLE_METRICS)
        self.assertIn("roas", advertiser_reports.UNAVAILABLE_METRICS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
