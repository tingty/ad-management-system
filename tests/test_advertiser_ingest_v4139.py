# -*- coding: utf-8 -*-
"""V4.139 · 真实 CJ 明细落库(JSON 序列化)回归专项。

真实接口返回的 lockingDate / 金额字段经 _convert 产出 datetime / Decimal，
SQLAlchemy JSON 列不能直接序列化；本专项用真实字段形态验证修复。
"""
import inspect
import os
import sys
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_ingest  # noqa: E402
import advertiser_protocol  # noqa: E402
from database import Base  # noqa: E402
from migrations import CJ_FIELD_MAP_SEED, CJ_TEMPLATE_ID  # noqa: E402
from models import ApiFactExt, ApiFactItem, ApiFieldMap, ApiSourceRecord, ApiUnifiedFact  # noqa: E402


def real_cj_record() -> dict:
    """按真实 CJ publisherCommissions.records 字段构造（含日期与小数金额）。"""
    return {
        "commissionId": "3900847692",
        "advertiserName": "Coofandy",
        "advertiserId": "7636568",
        "orderId": "19534334001393",
        "eventDate": "2026-11-23T02:38:19Z",
        "clickDate": "2026-11-22T22:00:51Z",
        "lockingDate": "2026-12-10T08:00:00Z",
        "lockingMethod": "FIXED_DATE",
        "actionStatus": "new",
        "actionTrackerName": "Website Purchase",
        "actionTrackerId": "498694",
        "saleAmountUsd": "20",
        "saleAmountPubCurrency": "20",
        "pubCommissionAmountUsd": "2",
        "pubCommissionAmountPubCurrency": "2",
        "validationStatus": "AUTOMATED",
        "original": True,
        "initiatingBrowser": "Chrome",
        "initiatingDeviceName": "Chrome - OS X",
        "initiatingDeviceType": "Desktop",
        "isCrossDevice": False,
        "reviewedStatus": "0",
        "shopperId": "Y26110k5ZfiXknkvC4f1dY02qF8g23vCXf",
        "source": "CLICK",
        "websiteId": "101879839",
        "websiteName": "COCOMOB Performance Marketing",
        "items": [{
            "sku": "amj009559_dgr_xxxl",
            "quantity": 1,
            "perItemSaleAmountPubCurrency": "20",
            "totalCommissionPubCurrency": "2",
            "perItemSaleAmountUsd": "20",
            "totalCommissionUsd": "2",
        }],
        "verticalAttributes": {"custCountry": "US"},
    }


class TestSchedulerCursorCompatibility(unittest.TestCase):
    def test_test_connection_accepts_cursor_keyword(self):
        params = inspect.signature(advertiser_api.test_connection).parameters
        self.assertIn("since_commission_id", params)
        self.assertEqual(params["since_commission_id"].default, "")

    def test_cursor_reaches_graphql_variables(self):
        req = advertiser_protocol.build_request(
            template_code=CJ_TEMPLATE_ID, endpoint="https://commissions.api.cj.com/query",
            token="T", cid="1", since_event_date="a", before_event_date="b",
            since_commission_id="3900847692")
        self.assertEqual(req["json_body"]["variables"]["sinceCommissionId"], "3900847692")


class TestRealCjJsonSerialization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.tmp}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        for source, target, transform, note in CJ_FIELD_MAP_SEED:
            self.db.add(ApiFieldMap(
                template_id=CJ_TEMPLATE_ID, source_path=source, target_field=target,
                transform=transform, version=1, enabled=True, note=note))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_real_record_ingests_without_json_error(self):
        record = real_cj_record()
        stats = advertiser_ingest.ingest_records(
            self.db, records=[record], connection_id=1)
        self.assertEqual((stats["inserted"], stats["updated"], stats["skipped"]), (1, 0, 0))
        fact = self.db.query(ApiUnifiedFact).one()
        self.assertEqual(float(fact.sale_amount_usd), 20.0)
        self.assertEqual(self.db.query(ApiFactItem).count(), 1)
        ext = self.db.query(ApiFactExt).one()
        self.assertEqual(ext.data_json["locking_date"], "2026-12-10T08:00:00")
        self.assertEqual(ext.data_json["sale_amount_pub_currency"], "20")
        self.assertEqual(ext.data_json["item_total_commission_pub_currency"], ["2"])
        self.db.expire_all()
        self.assertEqual(self.db.query(ApiSourceRecord).count(), 1)

    def test_real_record_repull_is_unchanged(self):
        record = real_cj_record()
        first = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        second = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        self.assertEqual((first["inserted"], second["unchanged"]), (1, 1))
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 1)
        self.assertEqual(self.db.query(ApiFactExt).count(), 1)


if __name__ == "__main__":
    unittest.main()
