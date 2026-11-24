# -*- coding: utf-8 -*-
"""V4.131 · PublisherCommission 空明细排查与优化专项测试。

覆盖：
1. 测试窗口默认近 7 天（原固定 1 天导致 CJ 延迟数据查不到），支持自定义窗口；
2. 响应回显实际窗口并给出空明细扩窗提示；
3. 明细条数口径独立，0 条不再回退到聚合 count；样例上限 3 → 10；
4. 前端支持窗口输入、修复 record_count || count 回退、空态展示提示；
5. 文档口径同步；既有请求对象与脱敏契约不回归。
"""
import asyncio
import json
import os
import sys
import unittest
from datetime import datetime
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


class TestQueryWindow(unittest.TestCase):
    def test_default_window_is_seven_days(self):
        since, before = routers._test_window()
        sd = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ")
        bd = datetime.strptime(before, "%Y-%m-%dT%H:%M:%SZ")
        self.assertAlmostEqual((bd - sd).total_seconds(), 7 * 86400, delta=10)

    def test_custom_window_passthrough(self):
        since, before = routers._test_window(
            "2026-11-01T00:00:00Z", "2026-11-20T23:59:59Z")
        self.assertEqual(since, "2026-11-01T00:00:00Z")
        self.assertEqual(before, "2026-11-20T23:59:59Z")

    def test_invalid_before_falls_back(self):
        since, before = routers._test_window("", "not-a-date")
        sd = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ")
        bd = datetime.strptime(before, "%Y-%m-%dT%H:%M:%SZ")
        self.assertAlmostEqual((bd - sd).total_seconds(), 7 * 86400, delta=10)


class TestDetailResultV4131(unittest.TestCase):
    SINCE = "2026-11-01T00:00:00Z"
    BEFORE = "2026-11-08T00:00:00Z"

    def _run(self, body):
        with mock.patch.object(advertiser_api.httpx, "AsyncClient") as ac:
            client = ac.return_value.__aenter__.return_value
            client.post.return_value = _ok_response(body)
            return asyncio.run(advertiser_api.test_connection(
                template_code="cj_publisher_commissions", endpoint="https://example.com/query",
                token="SECRET-TOKEN", cid="123456",
                since_event_date=self.SINCE, before_event_date=self.BEFORE))

    def test_window_echoed_in_result(self):
        out = self._run({"data": {"publisherCommissions": {"count": 0, "records": []}}})
        self.assertEqual(out["window_since"], self.SINCE)
        self.assertEqual(out["window_before"], self.BEFORE)

    def test_empty_records_gets_explicit_hint(self):
        out = self._run({"data": {"publisherCommissions": {
            "count": 128, "limit": 10000, "records": []}}})
        self.assertTrue(out["ok"])
        # 包装层可能有 count，但明细条数必须是 0
        self.assertEqual(out["count"], 128)
        self.assertEqual(out["record_count"], 0)
        self.assertEqual(out["sample_records"], [])
        self.assertIn("没有 PublisherCommission 明细", out["hint"])
        self.assertIn("延迟 1–3 天", out["hint"])
        self.assertIn(self.SINCE[:10], out["hint"])

    def test_records_present_has_no_hint(self):
        records = [{"commissionId": "c1", "orderId": "o1", "eventDate": "2026-11-03T10:00:00Z"}]
        out = self._run({"data": {"publisherCommissions": {"count": 1, "records": records}}})
        self.assertEqual(out["record_count"], 1)
        self.assertEqual(out["hint"], "")
        self.assertEqual(out["sample_records"][0]["commissionId"], "c1")
        self.assertNotIn("SECRET-TOKEN", json.dumps(out, ensure_ascii=False))

    def test_sample_capped_at_ten(self):
        records = [{"commissionId": str(i)} for i in range(15)]
        out = self._run({"data": {"publisherCommissions": {"count": 15, "records": records}}})
        self.assertEqual(out["record_count"], 15)
        self.assertEqual(len(out["sample_records"]), 10)

    def test_error_paths_also_carry_window(self):
        out = asyncio.run(advertiser_api.test_connection(
            template_code="unknown", endpoint="", token="", cid="",
            since_event_date=self.SINCE, before_event_date=self.BEFORE))
        self.assertFalse(out["ok"])
        self.assertEqual(out["window_since"], self.SINCE)
        self.assertEqual(out["window_before"], self.BEFORE)

    def test_schema_exposes_window_fields(self):
        out = schemas.ApiTestOut(**{
            "ok": True, "count": 1, "http_code": 200, "tested_at": "2026-11-24T08:00:00Z",
            "window_since": self.SINCE, "window_before": self.BEFORE, "hint": "test",
        })
        self.assertEqual(out.window_since, self.SINCE)
        self.assertEqual(out.hint, "test")
        body = schemas.ApiTestIn(connection_id=1, since_event_date=self.SINCE)
        self.assertEqual(body.since_event_date, self.SINCE)


class TestContracts(unittest.TestCase):
    def test_backend_contracts(self):
        routers_src = _read("backend/routers.py")
        self.assertIn("def _test_window(", routers_src)
        self.assertIn("timedelta(days=7)", routers_src)
        self.assertIn('result.get("record_count", result.get("count", 0))', routers_src)
        self.assertIn("body.since_event_date or \"\"", routers_src)

    def test_frontend_contracts(self):
        page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn('record_count ?? 0', page)
        self.assertNotIn('record_count ||', page)
        self.assertIn('type="date"', page)
        self.assertIn("应用并重新测试", page)
        self.assertIn("windowPayload", page)
        api = _read("frontend/src/api.ts")
        self.assertIn("since_event_date?: string", api)
        self.assertIn("window_since: string", api)

    def test_doc_contract(self):
        doc = _read("docs/广告主数据模块功能开发文档_20261124.html")
        self.assertIn("00 查询窗口", doc)
        self.assertIn("近 7 天", doc)
        self.assertIn("不再回退显示聚合 count", doc)
        self.assertIn("前 <b>10</b> 条", doc)


if __name__ == "__main__":
    unittest.main()
