# -*- coding: utf-8 -*-
"""V4.150 · Rakuten Advertising 佣金流水模板专项测试。

覆盖：官方接口结构、access token 凭据交换、Events transactions 请求构造、
页码分页与实测字段差异、字段映射落库、广告主报表可见性、静态守约与标准工作流文档。
全程使用替身响应与隔离 SQLite，不触达真实上游，不写入真实凭据。
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: F401,E402
import advertiser_api  # noqa: E402
import advertiser_ingest  # noqa: E402
import advertiser_protocol as proto  # noqa: E402
import advertiser_reports as reports  # noqa: E402
import httpx  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiUnifiedFact  # noqa: E402

RAKUTEN = migrations.RAKUTEN_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _sample():
    return {
        "etransaction_id": "CA6C79077E98AB6363074966A33A2363",
        "advertiser_id": 53552,
        "sid": 4752032,
        "order_id": "19248157884806",
        "offer_id": "2103603",
        "sku_number": "TI0000990",
        "sale_amount": -7.15,
        "quantity": 1,
        "commissions": -0.3575,
        "process_date": "Thu Nov 26 2026 07:02:32 GMT+0000 (UTC)",
        "transaction_date": "Tue Nov 24 2026 20:33:08 GMT+0000 (UTC)",
        "transaction_type": "realtime",
        "product_name": "Worry-Free Purchase",
        "u1": "imp-1",
        "currency": "USD",
        "is_event": "N",
        "commission_list_id": None,
        "lock_status": "#N/A",
        "order_auto_lock_date": "2026-12-24",
    }


class TestTemplateContract(unittest.TestCase):
    def test_template_is_config_driven_and_has_no_cid(self):
        tpl = advertiser_api.template_by_code(RAKUTEN)
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["code"], "rakuten_advertising")
        self.assertEqual(tpl["name"], "Rakuten Advertising")
        self.assertEqual(tpl["record_object"], "Transaction")
        # V4.153 起改为三字段采集，前端按 credential_compose 拼成 oauthcc 串
        self.assertEqual([f["key"] for f in tpl["required_fields"]],
                         ["client_id", "client_secret", "sid"])
        self.assertFalse(advertiser_api.requires_cid(RAKUTEN))
        codes = [t["code"] for t in advertiser_api.PRESET_TEMPLATES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_protocol_declares_events_transactions(self):
        p = proto.protocol_of(RAKUTEN)
        self.assertEqual(p["style"], "rest")
        self.assertEqual(p["http_method"], "GET")
        self.assertEqual(p["auth"], "bearer")
        self.assertEqual(p["endpoint_path"], "events/1.0/transactions")
        self.assertEqual(p["external_id_path"], "etransaction_id")
        self.assertEqual(p["date_params"], {
            "since": "process_date_start", "before": "process_date_end"})
        self.assertEqual(p["date_value_format"], "rakuten_datetime")
        self.assertEqual(p["page_param"], "page")
        self.assertTrue(p["complete_when_short"])
        self.assertEqual(p["record_filter"], {"field": "is_event", "equals": "N"})


class TestRequestAndCredential(unittest.TestCase):
    def test_build_request_matches_official_parameters(self):
        req = proto.build_request(
            template_code=RAKUTEN, endpoint="", token="ACCESS", cid="legacy",
            since_event_date="2026-11-19T00:00:00Z",
            before_event_date="2026-11-26T00:00:00Z")
        self.assertEqual(req["method"], "GET")
        self.assertEqual(req["url"], "https://api.linksynergy.com/events/1.0/transactions")
        self.assertEqual(req["headers"]["Authorization"], "Bearer ACCESS")
        self.assertIsNone(req["json_body"])
        self.assertEqual(req["params"]["process_date_start"], "2026-11-19 00:00:00")
        self.assertEqual(req["params"]["process_date_end"], "2026-11-26 00:00:00")
        self.assertEqual(req["params"]["limit"], 300)
        self.assertEqual(req["params"]["page"], 1)
        self.assertNotIn("cid", req["params"])
        self.assertNotIn("legacy", req["params"])

    def test_cursor_is_page_number(self):
        req = proto.build_request(
            template_code=RAKUTEN, endpoint="", token="ACCESS", cid="",
            since_event_date="a", before_event_date="b", since_commission_id="3")
        self.assertEqual(req["params"]["page"], 3)

    def test_credential_exchange_is_config_driven(self):
        seen = {}

        class FakeResp:
            status_code = 200
            text = '{"access_token":"NEW-ACCESS","expires_in":3600}'

            def json(self):
                return json.loads(self.text)

        async def fake_request(self, method, url, data=None, headers=None, **kwargs):
            seen.update({"method": method, "url": url, "data": data, "headers": headers})
            return FakeResp()

        with mock.patch.object(httpx.AsyncClient, "request", new=fake_request):
            access, secrets, note, req_headers = asyncio.run(advertiser_api.resolve_credential(
                RAKUTEN, "oauth:TOKEN-KEY|123456"))

        self.assertEqual(access, "NEW-ACCESS")
        self.assertIn("NEW-ACCESS", secrets)
        self.assertIn("TOKEN-KEY", secrets)
        self.assertIn("交换", note)
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], "https://api.linksynergy.com/token")
        self.assertEqual(seen["data"], {"scope": "123456"})
        self.assertEqual(seen["headers"]["Authorization"], "Bearer TOKEN-KEY")
        self.assertEqual(req_headers, {})

    def test_plain_access_token_passes_through(self):
        access, secrets, note, req_headers = asyncio.run(advertiser_api.resolve_credential(
            RAKUTEN, "PLAIN"))
        self.assertEqual(access, "PLAIN")
        self.assertEqual(secrets, ["PLAIN"])
        self.assertEqual(note, "")
        self.assertEqual(req_headers, {})


class TestParsing(unittest.TestCase):
    def test_top_level_array_is_parsed(self):
        out = proto.parse_response(template_code=RAKUTEN, body=[_sample()])
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["count"], 1)
        self.assertTrue(out["complete"])
        self.assertEqual(out["cursor"], "")

    def test_single_object_response_is_not_mistaken_for_empty(self):
        out = proto.parse_response(template_code=RAKUTEN, body=_sample())
        self.assertEqual(len(out["records"]), 1)

    def test_full_page_returns_next_page_cursor(self):
        body = [dict(_sample(), etransaction_id=f"ID-{i}") for i in range(300)]
        out = proto.parse_response(template_code=RAKUTEN, body=body)
        self.assertEqual(len(out["records"]), 300)
        self.assertFalse(out["complete"])
        self.assertEqual(out["cursor"], "2")

    def test_short_page_finishes(self):
        body = [dict(_sample(), etransaction_id=f"ID-{i}") for i in range(34)]
        out = proto.parse_response(template_code=RAKUTEN, body=body)
        self.assertTrue(out["complete"])
        self.assertEqual(out["cursor"], "")

    def test_duplicate_event_view_is_filtered_without_double_counting(self):
        body = [
            dict(_sample(), etransaction_id="ID-1", is_event="N", commissions=2.0),
            dict(_sample(), etransaction_id="ID-1", is_event="Y", commissions=2.0),
        ]
        out = proto.parse_response(template_code=RAKUTEN, body=body)
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["count"], 1)
        self.assertEqual(float(out["records"][0]["commissions"]), 2.0)

    def test_page_completion_uses_raw_count_after_filtering(self):
        pairs = []
        for i in range(150):
            pairs.extend([
                dict(_sample(), etransaction_id=f"ID-{i}", is_event="N"),
                dict(_sample(), etransaction_id=f"ID-{i}", is_event="Y"),
            ])
        out = proto.parse_response(template_code=RAKUTEN, body=pairs)
        self.assertEqual(len(out["records"]), 150)
        self.assertFalse(out["complete"])
        self.assertEqual(out["cursor"], "2")


class TestMigrationIngestAndReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine("sqlite:///" + self.tmp)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.engine.begin() as conn:
            migrations._migrate_v4127_1(conn)
            migrations._migrate_v4150_1(conn)

    def tearDown(self):
        self.engine.dispose()
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_mapping_covers_real_response_fields(self):
        db = self.Session()
        self.assertEqual(advertiser_ingest.check_coverage(_sample(), db, RAKUTEN), [])
        rows = db.execute(text(
            "SELECT source_path, target_field FROM api_field_map "
            "WHERE template_id=:t AND enabled=1"), {"t": RAKUTEN}).all()
        pairs = {(r[0], r[1]) for r in rows}
        self.assertIn(("etransaction_id", "source_record.external_id"), pairs)
        self.assertIn(("commission_list_id", "ext.commission_list_id"), pairs)
        self.assertIn(("lock_status", "ext.lock_status"), pairs)
        db.close()

    def test_ingest_then_report_sees_rakuten_fact(self):
        db = self.Session()
        db.add(ApiConnection(id=7, owner_id=42, name="Rakuten",
                             template_code=RAKUTEN, status="active"))
        db.commit()
        stats = advertiser_ingest.ingest_records(
            db, records=[_sample()], connection_id=7, template_id=RAKUTEN)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["warnings"], [])
        fact = db.query(ApiUnifiedFact).filter_by(template_id=RAKUTEN).one()
        self.assertEqual(fact.external_id, "CA6C79077E98AB6363074966A33A2363")
        self.assertEqual(str(fact.order_id), "19248157884806")
        self.assertEqual(str(fact.event_date), "2026-11-24")
        self.assertEqual(float(fact.commission_amount_usd), -0.3575)

        kpi = reports.kpi(db, 42, connection_id=7)
        det = reports.details(db, 42, connection_id=7)
        self.assertGreaterEqual(det["total"], 1)
        self.assertIn("net_commission_usd", kpi)
        db.close()


class TestStaticWorkflowContract(unittest.TestCase):
    def test_business_code_has_no_rakuten_branch(self):
        for rel in ("backend/advertiser_ingest.py", "backend/advertiser_scheduler.py",
                    "backend/advertiser_reports.py"):
            code = _read(rel)
            for token in ("rakuten_advertising", "etransaction_id", "commission_list_id"):
                self.assertNotIn(token, code, f"{rel} 不应含渠道硬编码 {token}")
            self.assertNotIn("template_code ==", code)

    def test_workflow_document_exists(self):
        doc = _read("docs/Rakuten_Advertising_API接入说明与广告主API标准工作流.md")
        for token in ("events/1.0/transactions", "access_token", "commission_list_id",
                      "标准工作流", "真实数据验收"):
            self.assertIn(token, doc)


if __name__ == "__main__":
    unittest.main()
