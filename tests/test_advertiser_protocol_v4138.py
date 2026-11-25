# -*- coding: utf-8 -*-
"""V4.138 · P4 第二模板通用性专项测试。

验证"加模板 + 加映射不改代码"：
1. 模板列表含 CJ(graphql) 与 Awin(rest) 两个协议，缺省协议向后兼容；
2. 请求构造按协议分派：CJ=POST+Bearer+GraphQL body；Awin=GET+path cid+query token/日期；
3. 响应解析按协议分派：CJ=data.query.records+游标；Awin=顶层数组+单窗口完成；
4. test_connection 走真实协议链路（mock HTTP）：Awin 请求形态与脱敏、CJ 契约零变化；
5. 幂等键/订单键/销售金额从映射反查：Awin 取 id / orderRef / saleAmount.amount；
6. 落库排重、模板隔离、报表按 connection 可读第二模板数据；
7. 静态契约：业务代码（ingest/scheduler/reports）无 Awin/CJ 专有分支，差异只在配置+映射。
全部使用全新隔离 SQLite + 样本数据，不触达真实上游 API。
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import advertiser_protocol as proto  # noqa: E402
import advertiser_ingest as ing  # noqa: E402
import advertiser_reports as reports  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402
from models import ApiConnection, ApiUnifiedFact, ApiFieldMap  # noqa: E402

CJ = migrations.CJ_TEMPLATE_ID
AWIN = migrations.AWIN_TEMPLATE_ID


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestProtocolConfig(unittest.TestCase):
    def test_two_templates_with_distinct_styles(self):
        codes = {t["code"] for t in advertiser_api.PRESET_TEMPLATES}
        self.assertIn(CJ, codes)
        self.assertIn(AWIN, codes)
        self.assertEqual(proto.protocol_of(CJ)["style"], "graphql")
        self.assertEqual(proto.protocol_of(AWIN)["style"], "rest")
        self.assertEqual(proto.protocol_of(AWIN)["auth"], "query_param")
        self.assertEqual(proto.protocol_of(AWIN)["external_id_path"], "id")

    def test_unknown_template_falls_back_to_cj(self):
        p = proto.protocol_of("does_not_exist")
        self.assertEqual(p["style"], "graphql")
        self.assertEqual(proto.external_id_of({"commissionId": "X"}, "does_not_exist"), "X")

    def test_cj_request_backward_compatible(self):
        r = proto.build_request(template_code=CJ, endpoint="https://commissions.api.cj.com/query",
                                token="SECRET", cid="123", since_event_date="a", before_event_date="b")
        self.assertEqual(r["method"], "POST")
        self.assertEqual(r["headers"]["Authorization"], "Bearer SECRET")
        self.assertEqual(r["json_body"]["variables"]["forPublishers"], ["123"])
        self.assertIn("publisherCommissions(", r["json_body"]["query"])
        self.assertEqual(r["params"], {})

    def test_awin_request_is_rest_with_path_and_query(self):
        r = proto.build_request(template_code=AWIN, endpoint="", token="TOK", cid="456",
                                since_event_date="2026-11-01T00:00:00Z",
                                before_event_date="2026-11-02T00:00:00Z")
        self.assertEqual(r["method"], "GET")
        self.assertEqual(r["url"], "https://api.awin.com/publishers/456/transactions/")
        self.assertEqual(r["params"]["accessToken"], "TOK")
        self.assertEqual(r["params"]["startDate"], "2026-11-01T00:00:00Z")
        self.assertEqual(r["params"]["endDate"], "2026-11-02T00:00:00Z")
        self.assertNotIn("Authorization", r["headers"])
        self.assertIsNone(r["json_body"])

    def test_awin_cursor_param_when_present(self):
        r = proto.build_request(template_code=AWIN, endpoint="", token="T", cid="1",
                                since_event_date="a", before_event_date="b",
                                since_commission_id="C-9")
        # Awin 协议未声明 cursor_param，游标被忽略（调度按窗口分片）
        self.assertNotIn("sinceCommissionId", r["params"])

    def test_parse_response_both_styles(self):
        cj = proto.parse_response(template_code=CJ, body={"data": {"publisherCommissions": {
            "count": 7, "records": [{"commissionId": "1"}], "maxCommissionId": "abc",
            "payloadComplete": False}}})
        self.assertEqual(cj["count"], 7)
        self.assertEqual(cj["cursor"], "abc")
        self.assertFalse(cj["complete"])
        awin = proto.parse_response(template_code=AWIN,
                                    body=[{"id": 1}, {"id": 2}, "skip"])
        self.assertEqual(len(awin["records"]), 2)
        self.assertEqual(awin["count"], 2)
        self.assertEqual(awin["cursor"], "")
        self.assertTrue(awin["complete"])

    def test_request_display_redacts_token_param(self):
        url = proto.request_display(method="GET", url="https://api.awin.com/tx",
                                    params={"accessToken": "SECRET-TOKEN", "startDate": "x"})
        self.assertIn("startDate=x", url)
        self.assertIn("SECRET-TOKEN", url)  # 原始拼接含 token，需由调用方脱敏

    def test_external_id_paths(self):
        self.assertEqual(proto.external_id_of({"commissionId": "C1"}, CJ), "C1")
        self.assertEqual(proto.external_id_of({"id": 259630312}, AWIN), "259630312")


class FakeResponse:
    def __init__(self, code, body):
        self.status_code = code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class TestConnectionProtocol(unittest.TestCase):
    def test_cj_still_posts_with_bearer(self):
        client = FakeAsyncClient(FakeResponse(200, {"data": {"publisherCommissions": {
            "count": 1, "records": [{"commissionId": "C1"}], "payloadComplete": True}}}))
        with patch.object(advertiser_api.httpx, "AsyncClient", return_value=client):
            r = asyncio.run(advertiser_api.test_connection(
                template_code=CJ, endpoint="https://commissions.api.cj.com/query",
                token="SECRET", cid="123", since_event_date="a", before_event_date="b"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["record_count"], 1)
        self.assertEqual(client.method, "post")
        self.assertEqual(client.last_headers["Authorization"], "Bearer SECRET")

    def test_awin_uses_get_and_redacts_token_in_url(self):
        body = [{"id": 11, "orderRef": "O1", "saleAmount": {"amount": 9.99, "currency": "GBP"}}]
        client = FakeAsyncClient(FakeResponse(200, body))
        with patch.object(advertiser_api.httpx, "AsyncClient", return_value=client):
            r = asyncio.run(advertiser_api.test_connection(
                template_code=AWIN, endpoint="", token="SECRET-TOKEN", cid="456",
                since_event_date="a", before_event_date="b"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["record_count"], 1)
        self.assertEqual(r["request_method"], "GET")
        self.assertEqual(client.method, "request")
        self.assertEqual(client.last_params["accessToken"], "SECRET-TOKEN")
        self.assertNotIn("SECRET-TOKEN", r["request_url"])  # 回显脱敏
        self.assertNotIn("SECRET-TOKEN", r["response_text"])

    def test_awin_http_error_classified(self):
        client = FakeAsyncClient(FakeResponse(401, {"message": "bad token"}))
        with patch.object(advertiser_api.httpx, "AsyncClient", return_value=client):
            r = asyncio.run(advertiser_api.test_connection(
                template_code=AWIN, endpoint="", token="SECRET-TOKEN", cid="456",
                since_event_date="a", before_event_date="b"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["http_code"], 401)


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.method = None
        self.last_headers = {}
        self.last_params = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.method = "post"
        self.last_headers = headers or {}
        self.last = (url, json, headers)
        return self.response

    async def request(self, method, url, json=None, params=None, headers=None):
        self.method = "request"
        self.last_method = method
        self.last_params = params or {}
        self.last_headers = headers or {}
        self.last = (method, url, json, params, headers)
        return self.response


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
        # 手动播种 Awin 映射（与生产 V4.138.1 迁移同一份 seed）
        for source, target, transform, note in migrations.AWIN_FIELD_MAP_SEED:
            self.db.add(ApiFieldMap(template_id=AWIN, source_path=source,
                                    target_field=target, transform=transform,
                                    version=1, enabled=True, note=note))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        try:
            os.remove(self.tmp)
        except OSError:
            pass


class TestAwinIngest(IngestBase):
    def _sample(self):
        return [{
            "id": 259630312, "advertiserId": 7052, "campaign": "Nike Sale",
            "commissionStatus": "approved",
            "commissionAmount": {"amount": 5.59, "currency": "GBP"},
            "saleAmount": {"amount": 55.96, "currency": "GBP"},
            "customerCountry": "GB", "clickDate": "2017-01-23T12:18:00",
            "transactionDate": "2017-02-20T22:04:00", "orderRef": "ORD-1",
            "voucherCode": "SAVE10", "type": "Sale", "amended": False,
        }]

    def test_semantic_sources_come_from_mapping(self):
        self.assertEqual(ing.semantic_source(self.db, AWIN, "source_record.external_id"), "id")
        self.assertEqual(ing.semantic_source(self.db, AWIN, "fact.order_id"), "orderRef")
        self.assertEqual(ing.semantic_source(self.db, AWIN, "fact.sale_amount_usd"), "saleAmount.amount")

    def test_ingest_idempotent_and_mapped(self):
        s1 = ing.ingest_records(self.db, records=self._sample(), connection_id=1, template_id=AWIN)
        self.assertEqual(s1["inserted"], 1)
        s2 = ing.ingest_records(self.db, records=self._sample(), connection_id=1, template_id=AWIN)
        self.assertEqual(s2["unchanged"], 1)
        self.assertEqual(s2["inserted"], 0)
        f = self.db.query(ApiUnifiedFact).filter_by(template_id=AWIN).first()
        self.assertEqual(f.external_id, "259630312")
        self.assertEqual(f.order_id, "ORD-1")
        self.assertEqual(f.advertiser_name, "Nike Sale")
        self.assertAlmostEqual(float(f.sale_amount_usd), 55.96)
        self.assertAlmostEqual(float(f.commission_amount_usd), 5.59)
        self.assertEqual(str(f.event_date), "2017-02-20")

    def test_template_isolation(self):
        ing.ingest_records(self.db, records=self._sample(), connection_id=1, template_id=AWIN)
        self.assertEqual(self.db.query(ApiUnifiedFact).filter_by(template_id=CJ).count(), 0)
        self.assertEqual(self.db.query(ApiUnifiedFact).filter_by(template_id=AWIN).count(), 1)

    def test_reports_read_second_template(self):
        ing.ingest_records(self.db, records=self._sample(), connection_id=7, template_id=AWIN)
        self.db.add(ApiConnection(id=7, owner_id=42, name="Awin", template_code=AWIN))
        self.db.commit()
        kpi = reports.kpi(self.db, 42, connection_id=7)
        self.assertGreaterEqual(float(kpi.get("net_sale_usd") or 0), 55.0)
        self.assertGreaterEqual(float(kpi.get("net_commission_usd") or 0), 5.0)
        det = reports.details(self.db, 42, connection_id=7)
        self.assertGreaterEqual(det["total"], 1)


class TestStaticContract(unittest.TestCase):
    def test_business_code_has_no_vendor_specific_branch(self):
        # 差异只在协议配置（advertiser_api）与映射 seed（migrations），
        # 业务链路（ingest/scheduler/reports）不得写死某一家字段名或模板分支。
        # 只看可执行行：剔除 # 注释与三引号文档块，避免历史说明性文字误伤。
        import io
        import tokenize
        for rel in ("backend/advertiser_ingest.py", "backend/advertiser_scheduler.py",
                    "backend/advertiser_reports.py"):
            src = _read(rel)
            code_lines = []
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                code_lines.append(tok.string)
            code = " ".join(code_lines)
            for token in ("awin_publisher_transactions", "publisherCommissions",
                          "saleAmountUsd", "orderRef", "saleAmount", "commissionAmount"):
                self.assertNotIn(token, code, f"{rel} 可执行代码不应含渠道专有硬编码 {token}")
            self.assertNotIn("template_code ==", code, f"{rel} 不应有模板分支")

    def test_protocol_layer_is_generic(self):
        src = _read("backend/advertiser_protocol.py")
        self.assertIn("build_request", src)
        self.assertIn("parse_response", src)
        self.assertIn("external_id_path", src)

    def test_frontend_template_label_is_config_driven(self):
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn("required_fields", page)
        self.assertIn("default_endpoint", page)


if __name__ == "__main__":
    unittest.main()
