# -*- coding: utf-8 -*-
"""V4.142 · 报表明细导出专项测试。

覆盖：
1. export_rows 与 details 共用 _detail_where：同一筛选结果一致（所见即所得）；
2. 表头读 api_field_label：顺序 / 中文名 / 单位，前端零硬编码；
3. 值格式化与页面 cell() 一致：decimal2 两位 + 单位、enum/bool 翻译、
   datetime 按东八区、date 保持业务日；
4. build_export_csv：UTF-8 BOM、CSV 转义、末尾筛选口径说明；
5. owner 隔离：他人连接数据不出现在导出；
6. 上限截断：超过 EXPORT_MAX_ROWS 标记 truncated；
7. 路由契约 + 静态契约：前端用已提交 applied 条件导出、按钮存在。
全部使用全新隔离 SQLite，不触达真实 CJ API、不污染全局库。
"""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_reports as reports  # noqa: E402
import advertiser_api  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiUnifiedFact, ApiSourceRecord  # noqa: E402

CJ = migrations.CJ_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class ExportBase(unittest.TestCase):
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
            self.db.add(__import__("models").ApiFieldMap(
                template_id=CJ, source_path=source, target_field=target,
                transform=transform, version=1, enabled=True, note=note))
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
              event="purchase", status="new", conn_id=None, click=None):
        src = ApiSourceRecord(
            template_id=CJ, connection_id=conn_id or self.conn1.id,
            external_id=f"COMM-{order}-{sale}",
            payload_json={"commissionId": f"COMM-{order}-{sale}", "orderId": order})
        self.db.add(src); self.db.flush()
        f = ApiUnifiedFact(
            template_id=CJ, connection_id=conn_id or self.conn1.id,
            source_record_id=src.id, external_id=src.external_id,
            commission_id=src.external_id, order_id=order,
            advertiser_name=adv, campaign_name=brand, event_name=event,
            action_status=status, event_date=date.fromisoformat(day),
            sale_amount_usd=sale, commission_amount_usd=comm,
            click_date=click, is_void=0, original=True)
        self.db.add(f); self.db.flush()
        return f

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self.tmp)
        except OSError:
            pass


class TestReportExport(ExportBase):
    def test_export_and_details_share_filter(self):
        self._fact(order="O-1", sale=100, comm=10, day="2026-11-20", adv="Adv A")
        self._fact(order="O-2", sale=50, comm=5, day="2026-11-21", adv="Adv B")
        self.db.commit()
        flt = dict(date_from="2026-11-20", date_to="2026-11-20", advertiser_name="Adv A")
        exp = reports.export_rows(self.db, 1, **flt)
        det = reports.details(self.db, 1, **flt)
        self.assertEqual(exp["total"], 1)
        self.assertEqual(det["total"], 1)
        self.assertEqual(exp["exported"], 1)
        self.assertEqual(exp["rows"][0][exp["header"].index("广告主名称")], "Adv A")

    def test_columns_from_labels_config(self):
        self._fact(order="O-1", sale=100, comm=10, day="2026-11-20")
        self.db.commit()
        exp = reports.export_rows(self.db, 1)
        # 表头来自 api_field_label 的 label（不是 column_key），首列为佣金ID
        self.assertEqual(exp["header"][0], "ID / 佣金ID")
        self.assertIn("销售金额", exp["header"])
        self.assertNotIn("sale_amount_usd", exp["header"])
        cols = [c["column_key"] for c in exp["columns"]]
        self.assertIn("sale_amount_usd", cols)

    def test_values_formatted_like_page(self):
        self._fact(order="O-1", sale=86.3, comm=8.63, day="2026-11-20",
                   status="locked",
                   click=datetime(2026, 11, 20, 2, 5))  # UTC → 北京 10:05
        self.db.commit()
        exp = reports.export_rows(self.db, 1)
        row = dict(zip(exp["header"], exp["rows"][0]))
        self.assertEqual(row["销售金额"], "86.30 USD")
        self.assertEqual(row["佣金金额"], "8.63 USD")
        self.assertEqual(row["订单状态"], "锁定")  # enum_map
        self.assertEqual(row["日期（事件日期）"], "2026-11-20")  # date 不套时区
        self.assertEqual(row["点击日期"], "2026-11-20 10:05")  # datetime +8h

    def test_owner_isolation(self):
        self._fact(order="O-MINE", sale=10, comm=1, day="2026-11-20")
        self._fact(order="OTHER", sale=20, comm=2, day="2026-11-20",
                   conn_id=self.conn2.id)
        self.db.commit()
        exp = reports.export_rows(self.db, 1)
        self.assertEqual(exp["total"], 1)
        flat = " ".join(cell for r in exp["rows"] for cell in r)
        self.assertIn("O-MINE", flat)
        self.assertNotIn("OTHER", flat)

    def test_csv_bom_and_note(self):
        self._fact(order="O-1", sale=100, comm=10, day="2026-11-20")
        self.db.commit()
        exp = reports.export_rows(self.db, 1)
        exp["note"] = "佣金明细导出（当前筛选） | 日期=2026-11-20 ~ 2026-11-20 | 共 1 条，导出 1 条"
        raw = reports.build_export_csv(exp)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM
        text = raw.decode("utf-8-sig")
        self.assertIn("ID / 佣金ID", text)
        self.assertIn("佣金明细导出（当前筛选）", text)

    def test_keyword_filter_applies_to_export(self):
        self._fact(order="O-ALPHA", sale=100, comm=10, day="2026-11-20")
        self._fact(order="O-BETA", sale=200, comm=20, day="2026-11-20")
        self.db.commit()
        exp = reports.export_rows(self.db, 1, keyword="ALPHA")
        self.assertEqual(exp["total"], 1)
        self.assertIn("O-ALPHA", exp["rows"][0])

    def test_truncation_flag(self):
        original = reports.EXPORT_MAX_ROWS
        reports.EXPORT_MAX_ROWS = 2
        try:
            for i in range(5):
                self._fact(order=f"O-{i}", sale=10, comm=1, day="2026-11-20")
            self.db.commit()
            exp = reports.export_rows(self.db, 1)
            self.assertEqual(exp["total"], 5)
            self.assertEqual(exp["exported"], 2)
            self.assertTrue(exp["truncated"])
        finally:
            reports.EXPORT_MAX_ROWS = original


class TestReportExportContracts(unittest.TestCase):
    def test_router_export_endpoint_exists(self):
        router = _read("backend/routers.py")
        self.assertIn('@router.get("/advertiser-data/reports/export")', router)
        self.assertIn("advertiser_reports.export_rows(", router)
        self.assertIn("build_export_csv", router)

    def test_frontend_exports_committed_filter(self):
        page = _read("frontend/src/pages/AdvertiserReports.tsx")
        api = _read("frontend/src/api.ts")
        self.assertIn("reportExport(applied)", page)  # 用已提交条件，不是草稿
        self.assertIn("导出 CSV", page)
        self.assertIn("reportExport:", api)
        self.assertIn("downloadFile", api)
        self.assertIn("Content-Disposition", api)

    def test_shared_filter_is_single_source(self):
        src = _read("backend/advertiser_reports.py")
        self.assertIn("def _detail_where(", src)
        self.assertIn("where, params = _detail_where(", src)
        # details 与 export_rows 都调用同一个 helper（至少两处）
        self.assertGreaterEqual(src.count("where, params = _detail_where("), 2)


if __name__ == "__main__":
    unittest.main()
