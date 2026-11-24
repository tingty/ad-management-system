# -*- coding: utf-8 -*-
"""V4.132 · P1-B 映射写入与幂等落库专项测试。

覆盖：
1. api_field_map 覆盖检查：未登记字段告警但仍保留原始层；
2. 幂等：同 payload 重跑不重复插行，修正单覆盖更新并重建 items / ext；
3. 派生：主表均价、子表精确单价、订单净额归零判取消单；
4. replay_mapping 保障：dry_run 只预览，apply 幂等；
5. 拉取接口：运行记录、成功/失败状态、统计回写；前端入口契约。
"""
import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_ingest  # noqa: E402
import routers  # noqa: E402
from database import Base  # noqa: E402
from migrations import CJ_FIELD_MAP_SEED, CJ_TEMPLATE_ID  # noqa: E402
from models import (ApiFactExt, ApiFactItem, ApiFetchRun, ApiFieldMap,  # noqa: E402
                    ApiSourceRecord, ApiUnifiedFact)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _record(commission_id="C-1", order_id="O-1", sale="120.00", commission="12.00",
            quantity=2, extra=None):
    record = {
        "commissionId": commission_id, "advertiserName": "Advertiser A",
        "orderId": order_id, "eventDate": "2026-11-20T10:00:00Z",
        "actionStatus": "new", "actionTrackerName": "purchase",
        "saleAmountUsd": sale, "pubCommissionAmountUsd": commission,
        "validationStatus": "PENDING", "original": True,
        "clickDate": "2026-11-19T10:00:00Z", "actionTrackerId": "AT-1",
        "items": [{"sku": "SKU-1", "quantity": quantity,
                   "perItemSaleAmountUsd": "60.00", "totalCommissionUsd": "6.00"}],
        "verticalAttributes": {"brand": "Brand A", "itemName": "Item A"},
    }
    if extra:
        record.update(extra)
    return record


class IngestBase(unittest.TestCase):
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


class TestMappingCoverage(IngestBase):
    def test_seed_rows_loaded(self):
        rows = advertiser_ingest.mapping_rows(self.db)
        self.assertGreater(len(rows), 40)
        self.assertIn(("commissionId", "fact.commission_id", "direct"), rows)

    def test_known_record_has_no_warning(self):
        self.assertEqual(advertiser_ingest.check_coverage(_record(), self.db), [])

    def test_unregistered_field_warns_but_is_kept(self):
        record = _record(extra={"brandNewField": "keep-me"})
        self.assertEqual(advertiser_ingest.check_coverage(record, self.db), ["brandNewField"])
        stats = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        self.assertEqual(stats["inserted"], 1)
        self.assertTrue(any("brandNewField" in w for w in stats["warnings"]))
        source = self.db.query(ApiSourceRecord).first()
        self.assertEqual(source.payload_json["brandNewField"], "keep-me")


class TestIdempotentIngest(IngestBase):
    def test_same_payload_twice_is_unchanged(self):
        record = _record()
        first = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        second = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        self.assertEqual((first["inserted"], first["updated"]), (1, 0))
        self.assertEqual((second["inserted"], second["updated"], second["unchanged"]), (0, 0, 1))
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 1)
        self.assertEqual(self.db.query(ApiFactItem).count(), 1)

    def test_correction_overwrites_and_rebuilds_children(self):
        advertiser_ingest.ingest_records(self.db, records=[_record()], connection_id=1)
        corrected = _record(sale="0.00", commission="0.00", extra={"items": [
            {"sku": "SKU-2", "quantity": 1,
             "perItemSaleAmountUsd": "0.00", "totalCommissionUsd": "0.00"}]})
        stats = advertiser_ingest.ingest_records(self.db, records=[corrected], connection_id=1)
        self.assertEqual((stats["inserted"], stats["updated"]), (0, 1))
        fact = self.db.query(ApiUnifiedFact).first()
        self.assertEqual(float(fact.sale_amount_usd), 0.0)
        items = self.db.query(ApiFactItem).all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].sku, "SKU-2")

    def test_missing_commission_id_is_skipped(self):
        record = _record()
        record.pop("commissionId")
        stats = advertiser_ingest.ingest_records(self.db, records=[record], connection_id=1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 0)


class TestDerivedFields(IngestBase):
    def test_unit_price_and_ext_attributes(self):
        advertiser_ingest.ingest_records(self.db, records=[_record()], connection_id=1)
        fact = self.db.query(ApiUnifiedFact).first()
        item = self.db.query(ApiFactItem).first()
        ext = self.db.query(ApiFactExt).first()
        self.assertEqual(float(fact.unit_price_usd), 60.0)
        self.assertEqual(float(item.unit_price_usd), 60.0)
        self.assertEqual(ext.data_json["vertical_brand"], "Brand A")
        self.assertEqual(fact.campaign_name, "Advertiser A")   # Q3 同源
        self.assertEqual(fact.event_name, "purchase")          # Q4 映射

    def test_order_net_zero_marks_void(self):
        records = [
            _record("C-1", "O-1", "120.00", "12.00"),
            _record("C-2", "O-1", "-120.00", "-12.00"),
        ]
        stats = advertiser_ingest.ingest_records(self.db, records=records, connection_id=1)
        self.assertEqual(stats["void_recalculated"], 2)
        facts = self.db.query(ApiUnifiedFact).all()
        self.assertTrue(all(f.is_void for f in facts))


class TestReplay(IngestBase):
    def test_dry_run_then_apply_is_idempotent(self):
        advertiser_ingest.ingest_records(self.db, records=[_record()], connection_id=1)
        preview = advertiser_ingest.replay_mapping(self.db, connection_id=1, dry_run=True)
        self.assertEqual(preview["mode"], "dry_run")
        self.assertEqual(preview["sources"], 1)
        self.assertEqual(preview["coverage_warnings"], 0)
        applied = advertiser_ingest.replay_mapping(self.db, connection_id=1, dry_run=False)
        self.assertEqual(applied["mode"], "apply")
        self.assertEqual(applied["unchanged"], 1)
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 1)


class TestFetchEndpoint(IngestBase):
    def _connection(self):
        connection = routers.ApiConnection(
            owner_id=1, name="CJ 测试", template_code=CJ_TEMPLATE_ID,
            cid="123456", endpoint="https://commissions.api.cj.com/query",
            token_enc=advertiser_api.encrypt_token("fake-token"),
            token_mask="****", status="draft")
        self.db.add(connection)
        self.db.commit()
        self.db.refresh(connection)
        return connection

    def test_fetch_writes_run_and_stats(self):
        connection = self._connection()
        fake = {
            "ok": True, "error": "", "http_code": 200,
            "all_records": [_record()], "max_commission_id": "C-1", "payload_complete": True,
        }
        with mock.patch.object(advertiser_api, "test_connection", new=mock.AsyncMock(return_value=fake)):
            out = asyncio.run(routers.api_advertiser_fetch(
                connection.id, routers.ApiTestIn(), self.db, SimpleNamespace(id=1)))
        self.assertTrue(out["ok"])
        self.assertEqual(out["inserted"], 1)
        run = self.db.query(ApiFetchRun).first()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.fetched_count, 1)
        self.assertEqual(run.inserted_count, 1)
        self.assertEqual(float(self.db.query(ApiUnifiedFact).first().commission_amount_usd), 12.0)

    def test_failed_upstream_marks_run_failed(self):
        connection = self._connection()
        fake = {"ok": False, "error": "认证失败", "http_code": 401}
        with mock.patch.object(advertiser_api, "test_connection", new=mock.AsyncMock(return_value=fake)):
            out = asyncio.run(routers.api_advertiser_fetch(
                connection.id, routers.ApiTestIn(), self.db, SimpleNamespace(id=1)))
        self.assertFalse(out["ok"])
        self.assertEqual(self.db.query(ApiFetchRun).first().status, "failed")
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 0)

    def test_fetch_runs_scoped_to_owner(self):
        connection = self._connection()
        self.db.add(ApiFetchRun(connection_id=connection.id, status="success"))
        self.db.commit()
        rows = asyncio.run(routers.api_advertiser_fetch_runs(
            connection_id=connection.id, limit=5, db=self.db, _=SimpleNamespace(id=1)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "success")


class TestContracts(unittest.TestCase):
    def test_backend_routes(self):
        routers_src = _read("backend/routers.py")
        for route in ("/advertiser-data/connections/{cid}/fetch",
                      "/advertiser-data/fetch-runs", "/advertiser-data/replay"):
            self.assertIn(route, routers_src)
        ingest_src = _read("backend/advertiser_ingest.py")
        for name in ("check_coverage", "ingest_records", "replay_mapping", "_recalc_void"):
            self.assertIn(f"def {name}(", ingest_src)

    def test_frontend_entry(self):
        api = _read("frontend/src/api.ts")
        self.assertIn("fetchConnection:", api)
        self.assertIn("export interface ApiFetchResult", api)
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn("立即拉取明细", page)
        self.assertIn("advertiserApi.fetchConnection", page)


if __name__ == "__main__":
    unittest.main()
