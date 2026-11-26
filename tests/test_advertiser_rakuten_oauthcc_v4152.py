# -*- coding: utf-8 -*-
"""V4.152 · Rakuten client_credentials 凭据交换与 SID 请求头专项测试。

真实凭据验证发现：官方 Bearer token-key 换取方式对该 Application 返回 401，
body client_credentials 可用，但换到的 token 必须在业务请求携带 x-rm-preferred-sid。
本测试全程使用替身响应与固定假值，不触达上游、不写入真实凭据。
"""
import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: F401,E402
import advertiser_api  # noqa: E402
import httpx  # noqa: E402

RAKUTEN = "rakuten_advertising"
CID = "cid-example"
SECRET = "secret-example"
SID = "4752032"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _sample():
    return {
        "etransaction_id": "ID-1",
        "is_event": "N",
        "order_id": "ORD-1",
        "commissions": 1.25,
        "currency": "USD",
        "sid": int(SID),
    }


class _FakeResp:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class TestTemplateCredentialContract(unittest.TestCase):
    def test_template_declares_oauthcc_alternate(self):
        tpl = advertiser_api.template_by_code(RAKUTEN)
        self.assertIsNotNone(tpl)
        self.assertEqual([f["key"] for f in tpl["required_fields"]], ["token"])
        self.assertIn("oauthcc:", tpl["required_fields"][0]["label"])

        cfg = tpl["protocol"]["credential"]
        self.assertEqual(cfg["prefix"], "oauth:")
        alts = cfg.get("alternates") or []
        self.assertEqual(len(alts), 1)
        alt = alts[0]
        self.assertEqual(alt["prefix"], "oauthcc:")
        self.assertEqual(alt["parts"], ["client_id", "client_secret", "account_id"])
        self.assertEqual(alt["auth"], "body")
        self.assertEqual(alt["body"]["grant_type"], "client_credentials")
        self.assertEqual(alt["body"]["client_id"], "{client_id}")
        self.assertEqual(alt["body"]["client_secret"], "{client_secret}")
        self.assertEqual(alt["body"]["scope"], "{account_id}")
        self.assertEqual(alt["request_headers"], {"x-rm-preferred-sid": "{account_id}"})


class TestResolveCredential(unittest.TestCase):
    def test_oauthcc_uses_body_credentials_and_returns_sid_header(self):
        calls = []

        async def fake_request(self, method, url, data=None, headers=None, **kwargs):
            calls.append({"method": method, "url": url, "data": data,
                          "headers": dict(headers or {})})
            return _FakeResp(200, {"access_token": "NEW-ACCESS", "expires_in": 3600})

        with mock.patch.object(httpx.AsyncClient, "request", new=fake_request):
            access, secrets, note, req_headers = asyncio.run(
                advertiser_api.resolve_credential(
                    RAKUTEN, f"oauthcc:{CID}|{SECRET}|{SID}"))

        self.assertEqual(access, "NEW-ACCESS")
        self.assertIn(SECRET, secrets)
        self.assertIn("NEW-ACCESS", secrets)
        self.assertIn("交换", note)
        self.assertEqual(req_headers, {"x-rm-preferred-sid": SID})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["url"], "https://api.linksynergy.com/token")
        self.assertEqual(calls[0]["data"], {
            "grant_type": "client_credentials", "client_id": CID,
            "client_secret": SECRET, "scope": SID})
        self.assertNotIn("Authorization", calls[0]["headers"])

    def test_exchange_error_redacts_client_secret(self):
        async def fake_request(self, method, url, data=None, headers=None, **kwargs):
            return _FakeResp(401, {}, text=f"invalid client: {SECRET}")

        with mock.patch.object(httpx.AsyncClient, "request", new=fake_request):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(advertiser_api.resolve_credential(
                    RAKUTEN, f"oauthcc:{CID}|{SECRET}|{SID}"))
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_bad_oauthcc_shape_is_rejected_before_network(self):
        for raw in ("oauthcc:only-one", f"oauthcc:{CID}||{SID}"):
            with self.assertRaises(ValueError):
                asyncio.run(advertiser_api.resolve_credential(RAKUTEN, raw))


class TestEndToEndHeaderInjection(unittest.TestCase):
    def test_test_connection_injects_sid_and_redacts_all_secrets(self):
        calls = []

        async def fake_request(self, method, url, data=None, headers=None, **kwargs):
            calls.append({"method": method, "url": url,
                          "headers": dict(headers or {}), "data": data})
            if url.endswith("/token"):
                return _FakeResp(200, {"access_token": "NEW-ACCESS", "expires_in": 3600})
            sample = [_sample()]
            return _FakeResp(200, sample,
                             text=json.dumps(sample) + " echoed:" + SECRET)

        with mock.patch.object(httpx.AsyncClient, "request", new=fake_request):
            result = asyncio.run(advertiser_api.test_connection(
                template_code=RAKUTEN, endpoint="https://api.linksynergy.com",
                token=f"oauthcc:{CID}|{SECRET}|{SID}", cid="",
                since_event_date="2026-11-19 00:00:00",
                before_event_date="2026-11-26 08:00:00", full_records=True))

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["http_code"], 200)
        self.assertEqual(result["record_count"], 1)
        events = [c for c in calls if "transactions" in c["url"]]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headers"]["Authorization"], "Bearer NEW-ACCESS")
        self.assertEqual(events[0]["headers"]["x-rm-preferred-sid"], SID)
        self.assertNotIn(SECRET, result["response_text"])
        self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))


class TestDocumentContract(unittest.TestCase):
    def test_workflow_documents_real_findings(self):
        doc = _read("docs/Rakuten_Advertising_API接入说明与广告主API标准工作流.md")
        for token in ("oauthcc:", "client_credentials", "x-rm-preferred-sid",
                      "30 天", "4572032", "4752032"):
            self.assertIn(token, doc, f"文档应记录真实验证发现：{token}")


if __name__ == "__main__":
    unittest.main()
