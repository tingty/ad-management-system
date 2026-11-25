# -*- coding: utf-8 -*-
"""V4.134 · P2 自动调度 + P1-C 历史回填专项测试。

覆盖：
1. 历史回填按 ≤31 天分片、相邻片重叠一天、重复执行幂等；
2. sinceCommissionId 游标翻页直到 payloadComplete；
3. 跨批次全量 is_void 重算（recalc_all_voids）；
4. 调度水位：到期才跑、未到期不重复请求，失败写运行记录不静默；
5. 运行记录 run_mode 区分手动 / 定时 / 回填，迁移版本可重复执行；
6. 回填接口 owner 隔离与前端入口契约。
全部使用全新隔离 SQLite + 模拟上游响应，不触达真实 CJ API。
"""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_ingest  # noqa: E402
import advertiser_scheduler  # noqa: E402
import migrations  # noqa: E402
import routers  # noqa: E402
from database import Base  # noqa: E402
from migrations import CJ_FIELD_MAP_SEED, CJ_TEMPLATE_ID  # noqa: E402
from models import (ApiConnection, ApiFetchRun, ApiFetchTask, ApiFieldMap,  # noqa: E402
                    ApiUnifiedFact, SystemState)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _record(commission_id="C-1", order_id="O-1", sale="120.00", commission="12.00"):
    return {
        "commissionId": commission_id, "advertiserName": "Advertiser A",
        "orderId": order_id, "eventDate": "2026-11-20T10:00:00Z",
        "actionStatus": "new", "actionTrackerName": "purchase",
        "saleAmountUsd": sale, "pubCommissionAmountUsd": commission,
        "validationStatus": "PENDING", "original": True,
        "clickDate": "2026-11-19T10:00:00Z", "actionTrackerId": "AT-1",
        "items": [{"sku": "SKU-1", "quantity": 2,
                   "perItemSaleAmountUsd": "60.00", "totalCommissionUsd": "6.00"}],
        "verticalAttributes": {"brand": "Brand A", "itemName": "Item A"},
    }


def _response(records, complete=True, max_id="", ok=True, error=""):
    return {"ok": ok, "error": error, "http_code": 200 if ok else 401,
            "count": len(records), "all_records": records,
            "payload_complete": complete, "max_commission_id": max_id}


class SchedulerBase(unittest.TestCase):
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
        self.conn = ApiConnection(
            owner_id=1, name="CJ 主账号", template_code=CJ_TEMPLATE_ID, cid="CID-1",
            endpoint="https://commissions.api.cj.com/query",
            token_enc=advertiser_api.encrypt_token("test-token"), token_mask="test****oken",
            status="active", last_test_ok=True,
            schedule_json={"enabled": True, "frequency": "daily", "hour": 2,
                           "lookback_days": 7, "backfill_days": 90},
            config_updated_at=datetime.utcnow())
        self.db.add(self.conn)
        self.db.commit()
        self.db.refresh(self.conn)

        patcher = mock.patch.object(advertiser_scheduler, "SessionLocal", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)
        delay_patcher = mock.patch.object(advertiser_scheduler, "page_delay", return_value=0)
        delay_patcher.start()
        self.addCleanup(delay_patcher.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def _fake(self, handler):
        return mock.patch.object(advertiser_api, "test_connection", side_effect=handler)


class TestBackfill(SchedulerBase):
    def test_slices_are_within_cj_window_limit(self):
        calls = []

        async def fake(**kwargs):
            calls.append(kwargs)
            return _response([])

        with self._fake(fake):
            result = asyncio.run(advertiser_scheduler.backfill(self.db, self.conn, days=90))
        self.assertTrue(result["ok"])
        self.assertEqual(result["slices"], 3)
        self.assertEqual(len(calls), 3)
        for call in calls:
            since = datetime.strptime(call["since_event_date"], "%Y-%m-%dT%H:%M:%SZ")
            before = datetime.strptime(call["before_event_date"], "%Y-%m-%dT%H:%M:%SZ")
            self.assertLessEqual((before - since).days, 31)
        # 第二 / 第三片各向前重叠一天，边界数据由幂等吸收
        first_end = datetime.strptime(calls[0]["before_event_date"], "%Y-%m-%dT%H:%M:%SZ")
        second_start = datetime.strptime(calls[1]["since_event_date"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual((first_end - second_start).days, 1)

    def test_cursor_pagination_until_payload_complete(self):
        calls = []

        async def fake(**kwargs):
            calls.append(kwargs.get("since_commission_id") or "")
            if not calls[-1]:
                return _response([_record("C-1")], complete=False, max_id="C-1")
            return _response([_record("C-2")], complete=True, max_id="C-2")

        with self._fake(fake):
            result = asyncio.run(advertiser_scheduler.backfill(self.db, self.conn, days=30))
        self.assertEqual(calls, ["", "C-1"])
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 2)
        run = self.db.query(ApiFetchRun).order_by(ApiFetchRun.id.desc()).first()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.cursor_json["pages"], 2)

    def test_repeat_backfill_is_idempotent(self):
        async def fake(**kwargs):
            return _response([_record()])

        with self._fake(fake):
            first = asyncio.run(advertiser_scheduler.backfill(self.db, self.conn, days=31))
            second = asyncio.run(advertiser_scheduler.backfill(self.db, self.conn, days=31))
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(self.db.query(ApiUnifiedFact).count(), 1)

    def test_failed_slice_creates_failed_run_without_silence(self):
        async def fake(**kwargs):
            return _response([], ok=False, error="认证失败（HTTP 401）")

        with self._fake(fake):
            result = asyncio.run(advertiser_scheduler.backfill(self.db, self.conn, days=31))
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])
        failed = self.db.query(ApiFetchRun).filter_by(status="failed").count()
        self.assertGreaterEqual(failed, 1)
        self.assertIn("401", self.db.query(ApiFetchRun).filter_by(status="failed").first().error)


class TestVoidRecalc(SchedulerBase):
    def test_cross_batch_void_recalculation(self):
        advertiser_ingest.ingest_records(self.db, records=[_record()], connection_id=self.conn.id)
        fact = self.db.query(ApiUnifiedFact).filter_by(order_id="O-1").first()
        self.assertFalse(bool(fact.is_void))
        # 模拟历史遗留：修正单迟到前的旧判定
        fact.is_void = True
        self.db.commit()
        changed = advertiser_ingest.recalc_all_voids(self.db, connection_id=self.conn.id)
        self.assertGreaterEqual(changed, 1)
        self.db.refresh(fact)
        self.assertFalse(bool(fact.is_void))

        # 正负相抵后整单应判为取消单
        advertiser_ingest.ingest_records(
            self.db, records=[_record("C-2", sale="-120.00", commission="-12.00")],
            connection_id=self.conn.id)
        self.db.refresh(fact)
        self.assertTrue(bool(fact.is_void))


class TestScheduler(SchedulerBase):
    def test_due_respects_watermark(self):
        calls = []

        async def fake(**kwargs):
            calls.append(kwargs)
            return _response([_record()])

        # 6 小时频率 + 最近刚跑过的水位 → 本轮不触发
        self.conn.schedule_json["frequency"] = "6h"
        self.db.add(SystemState(
            key=f"adv_fetch_last_{self.conn.id}", value=datetime.now().isoformat()))
        self.db.commit()
        with self._fake(fake):
            first = asyncio.run(advertiser_scheduler.run_due())
        self.assertEqual(first["ran"], 0)
        self.assertFalse(calls)

        # 水位推到昨天 → 到期，执行一次并写回水位
        self.db.query(SystemState).filter_by(
            key=f"adv_fetch_last_{self.conn.id}").update(
            {"value": (datetime.now() - timedelta(days=1)).isoformat()})
        self.db.commit()
        with self._fake(fake):
            second = asyncio.run(advertiser_scheduler.run_due())
        self.assertEqual(second["ran"], 1)
        self.assertTrue(calls)
        self.assertEqual(self.db.query(ApiFetchTask).count(), 1)
        task = self.db.query(ApiFetchTask).first()
        self.assertEqual(task.status, "idle")
        self.assertIsNotNone(task.last_run_at)
        self.assertEqual(
            self.db.query(ApiFetchRun).filter_by(run_mode="scheduled").count(), 1)

    def test_unverified_connection_is_skipped(self):
        calls = []

        async def fake(**kwargs):
            calls.append(1)
            return _response([])

        self.conn.last_test_ok = False
        self.db.commit()
        with self._fake(fake):
            result = asyncio.run(advertiser_scheduler.run_due())
        self.assertEqual(result["ran"], 0)
        self.assertFalse(calls)

    def test_failed_scheduled_run_marks_task_error(self):
        async def fake(**kwargs):
            return _response([], ok=False, error="GraphQL 错误")

        self.conn.schedule_json["frequency"] = "6h"
        self.db.commit()
        with self._fake(fake):
            result = asyncio.run(advertiser_scheduler.run_due())
        self.assertEqual(result["ran"], 1)
        task = self.db.query(ApiFetchTask).first()
        self.assertEqual(task.status, "error")
        run = self.db.query(ApiFetchRun).filter_by(run_mode="scheduled").first()
        self.assertEqual(run.status, "failed")


class TestContract(SchedulerBase):
    def test_backfill_endpoint_rejects_foreign_connection(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(routers.api_advertiser_backfill(
                self.conn.id, SimpleNamespace(days=31), self.db,
                SimpleNamespace(id=999)))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_backfill_endpoint_accepts_owner(self):
        async def fake(**kwargs):
            return _response([])

        with self._fake(fake):
            result = asyncio.run(routers.api_advertiser_backfill(
                self.conn.id, SimpleNamespace(days=31), self.db,
                SimpleNamespace(id=1)))
        self.assertTrue(result["ok"])
        self.assertEqual(result["days"], 31)

    def test_scheduler_info_exposes_task_state(self):
        advertiser_scheduler.upsert_task(self.db, self.conn)
        self.db.commit()
        info = advertiser_scheduler.scheduler_info()
        self.assertIn("enabled", info)
        self.assertEqual(len(info["tasks"]), 1)
        self.assertEqual(info["tasks"][0]["connection_id"], self.conn.id)

    def test_migration_version_registered_and_idempotent(self):
        versions = [v for v, _, _ in migrations.MIGRATIONS]
        self.assertIn("V4.134.1", versions)
        with self.engine.begin() as conn:
            note = migrations._migrate_v4134_1(conn)
        self.assertIn("run_mode", note)

    def test_frontend_exposes_backfill_and_run_log(self):
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        api = _read("frontend/src/api.ts")
        css = _read("frontend/src/styles.css")
        for key in ["历史回填", "运行记录", "backfillConnection", "ad-run-log"]:
            self.assertIn(key, page + api + css)
        self.assertIn("/backfill", api)
        self.assertIn("/scheduler", api)
        self.assertNotIn("自动调度执行按版本规划在后续阶段接入", page)


if __name__ == "__main__":
    unittest.main()
