# -*- coding: utf-8 -*-
"""V4.129 · 明确请求对象 PublisherCommission（订单佣金明细）专项测试。

覆盖：
1. GraphQL 请求体真正请求 publisherCommissions.records，即 Object: PublisherCommission；
2. 请求包含 items 与 advertiser-supplied custom attributes（verticalAttributes）；
3. 模板对外声明 record_object / record_object_desc，游标参数保留给 P1-B；
4. 响应解析 record_count / sample_records，明细样例脱敏且不截断完整响应；
5. 前端滑窗明确标注请求对象并展示明细样例，既有列表/弹窗契约不回归；
6. 唯一维护文档口径与实现一致（eventDate + records）。
"""
import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import advertiser_api  # noqa: E402
import routers  # noqa: E402
import schemas  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _ok_response(body):
    r = mock.MagicMock()
    r.status_code = 200
    r.text = json.dumps(body, ensure_ascii=False)
    r.json.return_value = body
    return r


class TestDetailQuery(unittest.TestCase):
    def test_payload_requests_publisher_commission_records(self):
        payload = advertiser_api.build_detail_payload(
            "12345", "2026-11-23T00:00:00Z", "2026-11-24T00:00:00Z")
        q = payload["query"]
        self.assertTrue(q.lstrip().startswith("query PublisherCommission("))
        self.assertIn("publisherCommissions(", q)
        self.assertIn("records {", q)
        self.assertIn("items {", q)
        self.assertIn("verticalAttributes {", q)
        for field in ("aid", "clickDate", "commissionId", "orderId", "original",
                      "originalActionId", "advertiserName", "actionTrackerName",
                      "eventDate", "pubCommissionAmountUsd", "quantity", "sku"):
            self.assertIn(field, q)
        self.assertEqual(payload["variables"]["forPublishers"], ["12345"])
        self.assertEqual(payload["variables"]["sinceEventDate"], "2026-11-23T00:00:00Z")
        self.assertEqual(payload["variables"]["beforeEventDate"], "2026-11-24T00:00:00Z")
        self.assertNotIn("sinceCommissionId", payload["variables"])
        self.assertNotIn("SECRET", json.dumps(payload))

    def test_stats_only_query_is_gone(self):
        self.assertFalse(hasattr(advertiser_api, "_TEST_QUERY"))
        q = advertiser_api.build_test_payload("1", "a", "b")["query"]
        self.assertIn("records {", q)

    def test_cursor_supported_for_p1b(self):
        payload = advertiser_api.build_detail_payload("1", "a", "b", "999")
        self.assertEqual(payload["variables"]["sinceCommissionId"], "999")

    def test_template_declares_record_object(self):
        tpl = advertiser_api.template_by_code("cj_publisher_commissions")
        self.assertEqual(tpl["record_object"], "PublisherCommission")
        self.assertIn("advertiser-supplied custom attributes", tpl["record_object_desc"])
        rows = asyncio.run(routers.api_advertiser_templates(_=None))
        self.assertEqual(rows[0]["record_object"], "PublisherCommission")
        self.assertIn("publisher commission event", rows[0]["record_object_desc"])
        out = schemas.ApiTemplateOut(**rows[0])
        self.assertEqual(out.record_object, "PublisherCommission")


class TestDetailResult(unittest.TestCase):
    TOKEN = "SECRET_TOKEN_123"

    def _run(self, body):
        async def fake_post(client, url, json=None, headers=None):
            return _ok_response(body)

        with mock.patch.object(advertiser_api.httpx.AsyncClient, "post", fake_post):
            return asyncio.run(advertiser_api.test_connection(
                template_code="cj_publisher_commissions",
                endpoint="https://commissions.api.cj.com/query",
                token=self.TOKEN, cid="12345",
                since_event_date="2026-11-23T00:00:00Z",
                before_event_date="2026-11-24T00:00:00Z",
            ))

    def test_records_parsed_with_redaction(self):
        body = {"data": {"publisherCommissions": {
            "count": 2, "payloadComplete": True, "maxCommissionId": "c2", "limit": 10000,
            "records": [
                {"commissionId": "c1", "orderId": "o1",
                 "advertiserName": f"{self.TOKEN} Ads", "eventDate": "2026-11-23T01:00:00Z",
                 "original": True, "items": [{"sku": self.TOKEN, "quantity": 1}]},
                {"commissionId": "c2", "orderId": "o1", "original": False, "items": []},
            ],
        }}}
        out = self._run(body)
        self.assertTrue(out["ok"])
        self.assertEqual(out["record_object"], "PublisherCommission")
        self.assertEqual(out["record_count"], 2)
        self.assertEqual(len(out["sample_records"]), 2)
        self.assertIn("***", out["sample_records"][0]["advertiserName"])
        self.assertIn("***", out["sample_records"][0]["items"][0]["sku"])
        self.assertNotIn(self.TOKEN, json.dumps(out, ensure_ascii=False))
        self.assertEqual(json.loads(out["response_text"]), out["response"])
        self.assertNotIn(self.TOKEN, out["response_text"])

    def test_sample_capped_at_three(self):
        records = [{"commissionId": str(i)} for i in range(5)]
        body = {"data": {"publisherCommissions": {"count": 5, "records": records}}}
        out = self._run(body)
        self.assertEqual(out["record_count"], 5)
        self.assertEqual(len(out["sample_records"]), 3)

    def test_error_paths_keep_detail_contract(self):
        out = asyncio.run(advertiser_api.test_connection(
            template_code="unknown", endpoint="", token="", cid="",
            since_event_date="a", before_event_date="b"))
        self.assertEqual(out["record_object"], "PublisherCommission")
        self.assertEqual(out["record_count"], 0)
        self.assertEqual(out["sample_records"], [])

    def test_schema_exposes_detail_fields(self):
        out = schemas.ApiTestOut(**{
            "ok": True, "count": 2, "http_code": 200, "tested_at": "2026-11-24T08:00:00Z",
            "record_object": "PublisherCommission", "record_count": 2,
            "sample_records": [{"commissionId": "c1"}],
        })
        self.assertEqual(out.record_count, 2)
        self.assertEqual(out.sample_records, [{"commissionId": "c1"}])


class TestFrontendAndDocs(unittest.TestCase):
    def setUp(self):
        self.page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.api = _read("frontend/src/api.ts")
        self.css = _read("frontend/src/styles.css")
        self.doc = _read("docs/广告主数据模块功能开发文档_20261124.html")

    def test_drawer_marks_request_object_and_sample_records(self):
        for key in ("PublisherCommission", "请求对象", "订单佣金明细", "sample_records",
                    "ad-object-banner", "ad-sample-table", "records[]", "不是 count 统计报表"):
            self.assertIn(key, self.page)
        self.assertIn("publisherCommissions.records", self.page)
        self.assertIn("原始单", self.page)
        self.assertIn("修正单", self.page)
        for key in (".ad-object-banner", ".ad-sample-table"):
            self.assertIn(key, self.css)

    def test_api_types_and_existing_contracts(self):
        for key in ("record_object: string", "record_count: number",
                    "sample_records: Record<string, unknown>[]"):
            self.assertIn(key, self.api)
        for key in ("<th>测试</th>", "startTest(c.id, c.name)", "新建 API 对接",
                    "设置 · 定期任务", "pretty(drawerResult?.response_text)"):
            self.assertIn(key, self.page)

    def test_document_matches_event_date_and_records(self):
        self.assertIn("sinceEventDate:$from, beforeEventDate:$to", self.doc)
        self.assertIn("records: [PublisherCommission!]!", self.doc)
        self.assertIn("advertiser-supplied custom attributes", self.doc)
        self.assertNotIn("sincePostingDate:$from", self.doc)


if __name__ == "__main__":
    unittest.main()
