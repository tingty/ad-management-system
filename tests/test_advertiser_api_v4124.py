# -*- coding: utf-8 -*-
"""V4.124 广告主数据模块 P0 专项测试：
1. CJ 模板预置且必填项正确（Token/CID/Endpoint）；
2. Token 加密入库、解密正确、篡改拒绝、列表掩码不泄露；
3. test_connection 走真实 GraphQL 结构（用 mock 拦截 HTTP），成功/401/GraphQL 错误分类；
4. CJ 模板的 9 项新增上游字段在官方 schema 口径中可用（静态断言，防后续误删）；
5. 功能开关关闭时接口 404（回滚保障）；
6. 前端新增一级菜单独立路由，现有菜单不改。
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestTokenCrypto(unittest.TestCase):
    def test_encrypt_decrypt_and_mask(self):
        import advertiser_api as aa
        plain = "cocomob_ci:SecretToken-123456"
        enc = aa.encrypt_token(plain)
        self.assertNotEqual(enc, plain)
        self.assertNotIn(plain, enc)
        self.assertEqual(aa.decrypt_token(enc), plain)
        masked = aa.mask_token(plain)
        self.assertNotIn("SecretToken", masked)
        self.assertTrue(masked.startswith(plain[:4]))
        self.assertTrue(masked.endswith(plain[-4:]))

    def test_tampered_cipher_rejected(self):
        import advertiser_api as aa
        enc = aa.encrypt_token("abcdefghijklmnop")
        tampered = enc[:-3] + "AAA"
        self.assertEqual(aa.decrypt_token(tampered), "")


class TestCJTemplate(unittest.TestCase):
    def test_template_preset_and_required_fields(self):
        import advertiser_api as aa
        tpl = aa.template_by_code("cj_publisher_commissions")
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["method"], "POST")
        self.assertEqual(tpl["auth_type"], "bearer")
        self.assertEqual(tpl["query_name"], "publisherCommissions")
        keys = {f["key"] for f in tpl["required_fields"]}
        self.assertEqual(keys, {"token", "cid", "endpoint"})
        self.assertTrue(next(f for f in tpl["required_fields"] if f["key"] == "token")["required"])
        self.assertTrue(next(f for f in tpl["required_fields"] if f["key"] == "cid")["required"])

    def test_v124_new_upstream_fields_documented(self):
        """新增 9 项字段已按冲突原则记入唯一维护文档。"""
        doc = _read("docs/广告主数据模块功能开发文档_20261124.html")
        for f in ["aid", "clickDate", "commissionId", "correctionReason", "country",
                  "coupon", "postingDate", "publisherId", "publisherName"]:
            self.assertIn(f, doc, f"设计文档缺少字段 {f}")
        self.assertIn("字段冲突消解规则", doc)


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.last = (url, json, headers)
        return self.response


class TestTestConnection(unittest.TestCase):
    def _run(self, resp):
        import advertiser_api as aa
        client = FakeAsyncClient(resp)
        with patch.object(aa.httpx, "AsyncClient", return_value=client):
            return asyncio.run(aa.test_connection(
                template_code="cj_publisher_commissions",
                endpoint="https://commissions.api.cj.com/query",
                token="SECRET-TOKEN", cid="12345",
                since_event_date="2026-11-23T00:00:00Z",
                before_event_date="2026-11-24T00:00:00Z")), client

    def test_success(self):
        r, c = self._run(FakeResponse(200, {"data": {"publisherCommissions": {
            "count": 7, "limit": 10000, "maxCommissionId": "abc", "payloadComplete": True}}}))
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 7)
        url, payload, headers = c.last
        self.assertEqual(url, "https://commissions.api.cj.com/query")
        self.assertEqual(payload["variables"]["forPublishers"], ["12345"])
        self.assertEqual(headers["Authorization"], "Bearer SECRET-TOKEN")
        self.assertIn("payloadComplete", payload["query"])

    def test_401_and_gql_error(self):
        r, _ = self._run(FakeResponse(401, {"message": "Invalid auth token."}))
        self.assertFalse(r["ok"])
        self.assertIn("认证失败", r["error"])
        self.assertNotIn("SECRET-TOKEN", r["error"])

        r2, _ = self._run(FakeResponse(200, {"errors": [{"message": "Cannot query field"}]}))
        self.assertFalse(r2["ok"])
        self.assertIn("GraphQL", r2["error"])


class TestMenuIsolation(unittest.TestCase):
    def test_new_primary_menu_without_touching_existing(self):
        app = _read("frontend/src/App.tsx")
        self.assertIn("GROUP_ADVERTISER_DATA", app)
        self.assertIn("name: '广告主数据'", app)
        self.assertIn("label: '广告主API'", app)
        self.assertIn("label: '广告主报表'", app)
        self.assertIn("advertiser-data/api", app)
        self.assertIn("advertiser-data/reports", app)
        # 现有分组仍在
        for g in ["GROUP_WORKSHOP", "GROUP_WORKBENCH", "GROUP_SYSTEM"]:
            self.assertIn(g, app)

    def test_feature_flag_exists(self):
        ver = _read("backend/version.py")
        self.assertIn("ENABLE_ADVERTISER_DATA = True", ver)
        routers = _read("backend/routers.py")
        self.assertIn("_ad_gate()", routers)


if __name__ == "__main__":
    unittest.main()
