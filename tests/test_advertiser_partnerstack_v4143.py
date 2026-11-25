# -*- coding: utf-8 -*-
"""V4.143 · PartnerStack Partner API 模板专项测试。

按官方 OpenAPI（GET /v2/rewards）验证：
1. 模板声明 Bearer、REST GET、company_key 可选、默认 Endpoint；
2. 请求参数：min_created/max_created 为毫秒 epoch，limit/order_by 固定，
   starting_after 使用上一页最后一条 Reward key；
3. 响应解析：data.items / data.total / data.has_more，游标从最后一条 key 取；
4. test_connection 无 CID 可测、Token 只进 Header、错误分类正常；
5. 字段映射落库：分转美元、毫秒时间转日期、source.key 作订单键、幂等排重；
6. 报表可读新模板数据；业务代码无渠道专有硬编码。
"""
import asyncio
import io
import os
import sys
import tempfile
import tokenize
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_ingest as ing  # noqa: E402
import advertiser_protocol as proto  # noqa: E402
import advertiser_reports as reports  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiFieldMap, ApiUnifiedFact  # noqa: E402

PS = migrations.PARTNERSTACK_TEMPLATE_ID
CJ = migrations.CJ_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _reward_body(*, has_more=False):
    return {
        "data": {
            "has_more": has_more,
            "total": 1,
            "items": [{
                "key": "rwrd_test001",
                "created_at": 1795168800000,  # 2026-11-20 10:00:00Z
                "updated_at": 1795168800000,
                "amount": 1250,
                "currency": "USD",
                "reward_status": "approved",
                "payment_status": "available",
                "description": "10% recurring commission",
                "creation_source": "transaction",
                "created_by": "system",
                "decline_reason": None,
                "withdrawn": False,
                "company": {"id": 123, "key": "co_test", "name": "Demo Brand"},
                "customer": {"key": "cus_test", "name": "Acme", "sub_ids": ["click-1"]},
                "partnership_key": "part_test",
                "source": {"key": "tran_test", "type": "transaction"},
                "transaction": {
                    "amount": 10000, "amount_usd": 10000, "currency": "USD",
                    "created_at": 1795168800000, "category_key": "subscription",
                    "product_key": "monthly_plan", "archived": False,
                },
            }],
        },
        "message": "Page returned successfully",
        "status": 200,
    }


class TestPartnerStackTemplate(unittest.TestCase):
    def test_template_config(self):
        tpl = advertiser_api.template_by_code(PS)
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["vendor"], "PartnerStack")
        self.assertEqual(tpl["auth_type"], "bearer")
        self.assertEqual(tpl["default_endpoint"], "https://api.partnerstack.com/api")
        self.assertFalse(advertiser_api.requires_cid(PS))
        self.assertTrue(advertiser_api.requires_cid(CJ))
        fields = {f["key"]: f for f in tpl["required_fields"]}
        self.assertTrue(fields["token"]["required"])
        self.assertFalse(fields["cid"]["required"])

    def test_request_uses_epoch_ms_and_optional_company_key(self):
        r = proto.build_request(
            template_code=PS, endpoint="", token="SECRET", cid="",
            since_event_date="2026-11-01T00:00:00Z",
            before_event_date="2026-11-20T00:00:00Z")
        self.assertEqual(r["method"], "GET")
        self.assertEqual(r["url"], "https://api.partnerstack.com/api/v2/rewards")
        self.assertEqual(r["headers"]["Authorization"], "Bearer SECRET")
        self.assertEqual(r["params"]["min_created"], 1793491200000)
        self.assertEqual(r["params"]["max_created"], 1795132800000)
        self.assertEqual(r["params"]["limit"], 250)
        self.assertEqual(r["params"]["order_by"], "-created_at")
        self.assertNotIn("company_key", r["params"])
        self.assertIsNone(r["json_body"])

    def test_request_cursor_and_company_filter(self):
        r = proto.build_request(
            template_code=PS, endpoint="", token="SECRET", cid="co_abc",
            since_event_date="a", before_event_date="b",
            since_commission_id="rwrd_prev")
        self.assertEqual(r["params"]["company_key"], "co_abc")
        self.assertEqual(r["params"]["starting_after"], "rwrd_prev")

    def test_parse_response_cursor_from_last_record_and_has_more(self):
        parsed = proto.parse_response(template_code=PS, body=_reward_body(has_more=True))
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["cursor"], "rwrd_test001")
        self.assertFalse(parsed["complete"])
        done = proto.parse_response(template_code=PS, body=_reward_body(has_more=False))
        self.assertTrue(done["complete"])
        self.assertEqual(done["cursor"], "rwrd_test001")


class FakeResponse:
    def __init__(self, code, body):
        self.status_code = code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.method = None
        self.last_params = {}
        self.last_headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.method = "post"
        self.last_headers = headers or {}
        return self.response

    async def request(self, method, url, json=None, params=None, headers=None):
        self.method = "request"
        self.last_method = method
        self.last_params = params or {}
        self.last_headers = headers or {}
        return self.response


class TestConnection(unittest.TestCase):
    def test_get_bearer_without_cid(self):
        client = FakeAsyncClient(FakeResponse(200, _reward_body()))
        with patch.object(advertiser_api.httpx, "AsyncClient", return_value=client):
            r = asyncio.run(advertiser_api.test_connection(
                template_code=PS, endpoint="", token="SECRET", cid="",
                since_event_date="2026-11-01T00:00:00Z",
                before_event_date="2026-11-20T00:00:00Z", full_records=True))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["request_method"], "GET")
        self.assertEqual(client.method, "request")
        self.assertEqual(client.last_headers["Authorization"], "Bearer SECRET")
        self.assertEqual(r["record_count"], 1)
        self.assertEqual(r["all_records"][0]["key"], "rwrd_test001")
        self.assertNotIn("SECRET", r["request_url"])

    def test_unauthorized(self):
        client = FakeAsyncClient(FakeResponse(401, {"message": "invalid key", "status": 401}))
        with patch.object(advertiser_api.httpx, "AsyncClient", return_value=client):
            r = asyncio.run(advertiser_api.test_connection(
                template_code=PS, endpoint="", token="BAD", cid="",
                since_event_date="a", before_event_date="b"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["http_code"], 401)


class IngestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.engine = create_engine("sqlite:///" + self.tmp)
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text(migrations.ORDER_VIEW_SQL))
            migrations._seed_field_labels(conn)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        for source, target, transform, note in migrations.PARTNERSTACK_FIELD_MAP_SEED:
            self.db.add(ApiFieldMap(template_id=PS, source_path=source, target_field=target,
                                    transform=transform, version=1, enabled=True, note=note))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


class TestPartnerStackIngest(IngestBase):
    def _sample(self):
        return _reward_body()["data"]["items"]

    def test_semantic_sources(self):
        self.assertEqual(ing.semantic_source(self.db, PS, "source_record.external_id"), "key")
        self.assertEqual(ing.semantic_source(self.db, PS, "fact.order_id"), "source.key")
        self.assertEqual(ing.semantic_source(self.db, PS, "fact.sale_amount_usd"),
                         "transaction.amount_usd")

    def test_mapping_and_idempotency(self):
        first = ing.ingest_records(self.db, records=self._sample(), connection_id=1, template_id=PS)
        self.assertEqual(first["inserted"], 1)
        second = ing.ingest_records(self.db, records=self._sample(), connection_id=1, template_id=PS)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(second["inserted"], 0)
        fact = self.db.query(ApiUnifiedFact).filter_by(template_id=PS).first()
        self.assertEqual(fact.external_id, "rwrd_test001")
        self.assertEqual(fact.order_id, "tran_test")
        self.assertEqual(fact.advertiser_name, "Demo Brand")
        self.assertEqual(fact.event_name, "transaction")
        self.assertEqual(str(fact.event_date), "2026-11-20")
        self.assertAlmostEqual(float(fact.commission_amount_usd), 12.50)
        self.assertAlmostEqual(float(fact.sale_amount_usd), 100.00)

    def test_report_reads_partnerstack(self):
        ing.ingest_records(self.db, records=self._sample(), connection_id=9, template_id=PS)
        self.db.add(ApiConnection(id=9, owner_id=42, name="PartnerStack", template_code=PS))
        self.db.commit()
        kpi = reports.kpi(self.db, 42, connection_id=9)
        self.assertGreaterEqual(float(kpi.get("net_commission_usd") or 0), 12.0)
        det = reports.details(self.db, 42, connection_id=9)
        self.assertGreaterEqual(det["total"], 1)

    def test_coverage_all_official_fields_registered(self):
        self.assertEqual(ing.check_coverage(self._sample()[0], self.db, PS), [])


class TestStaticContract(unittest.TestCase):
    def test_business_code_has_no_partnerstack_specific_branch(self):
        for rel in ("backend/advertiser_ingest.py", "backend/advertiser_scheduler.py",
                    "backend/advertiser_reports.py"):
            code = []
            for tok in tokenize.generate_tokens(io.StringIO(_read(rel)).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                code.append(tok.string)
            joined = " ".join(code)
            for token in ("partnerstack_partner_rewards", "reward_status", "min_created",
                          "starting_after"):
                self.assertNotIn(token, joined, f"{rel} 不应含渠道专有硬编码 {token}")


if __name__ == "__main__":
    unittest.main()
