# -*- coding: utf-8 -*-
"""V4.153 · Rakuten 三字段采集层专项测试。

三字段只是采集层变化：前端按模板声明把 Client ID / Client Secret / SID
拼成 oauthcc:client_id|client_secret|sid 存入既有 token 列；
后端 resolve_credential / 调度 / 报表链路零改动，老连接继续可用。
本测试不触达上游、不写入真实凭据。
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


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestTemplateDeclaration(unittest.TestCase):
    def test_rakuten_declares_three_fields_and_compose_rule(self):
        tpl = advertiser_api.template_by_code(RAKUTEN)
        self.assertEqual(
            [(f["key"], f["type"], f["required"]) for f in tpl["required_fields"]],
            [("client_id", "text", True), ("client_secret", "password", True),
             ("sid", "text", True)],
        )
        rule = tpl["credential_compose"]
        self.assertEqual(rule["target"], "token")
        self.assertEqual(rule["prefix"], "oauthcc:")
        self.assertEqual(rule["delimiter"], "|")
        self.assertEqual(rule["parts"], ["client_id", "client_secret", "sid"])

    def test_other_templates_keep_original_token_field(self):
        for code in ("cj_publisher_commissions", "awin_publisher_transactions",
                     "partnerstack"):
            tpl = advertiser_api.template_by_code(code)
            self.assertNotIn("credential_compose", tpl, code)
            self.assertIn("token", [f["key"] for f in tpl["required_fields"]], code)

    def test_template_metadata_is_serialized_to_frontend(self):
        schema = _read("backend/schemas.py")
        router = _read("backend/routers.py")
        self.assertIn("credential_compose: Optional[dict] = None", schema)
        self.assertIn('"credential_compose": t.get("credential_compose")', router)


class TestFrontendCompositionContract(unittest.TestCase):
    def test_form_renders_declared_fields_and_composes_genericly(self):
        src = _read("frontend/src/pages/AdvertiserApi.tsx")
        for token in ("function composeKeys", "function composeCredential",
                      "tpl?.credential_compose?.parts", "rule.prefix",
                      "rule.delimiter", "credentialKeys(form.template_code).map",
                      "credentialKeys(connections.find", "留空不修改",
                      "完整填写凭据字段", "完整填写全部凭据字段"):
            self.assertIn(token, src, "前端采集层缺少：" + token)
        api = _read("frontend/src/api.ts")
        self.assertIn("credential_compose?:", api)

    def test_no_real_credential_value_hardcoded_in_frontend(self):
        src = _read("frontend/src/pages/AdvertiserApi.tsx")
        # 用拼接方式构造守约片段，避免测试文件本身出现真实凭据的任何字面前缀
        for secret in ("4752032", "o8" + "LC", "zB" + "iq"):
            self.assertNotIn(secret, src)
        # 拼接格式必须来自模板声明，不能把 oauthcc 写死在业务逻辑里
        self.assertNotIn("'oauthcc:' +", src)


class TestComposedCredentialStillWorks(unittest.TestCase):
    def test_frontend_shaped_token_is_accepted_by_backend(self):
        tpl = advertiser_api.template_by_code(RAKUTEN)
        rule = tpl["credential_compose"]
        values = {"client_id": CID, "client_secret": SECRET, "sid": SID}
        token = rule["prefix"] + rule["delimiter"].join(
            values[k] for k in rule["parts"])

        calls = []

        async def fake_request(self, method, url, data=None, headers=None, **kwargs):
            calls.append({"url": url, "data": data, "headers": dict(headers or {})})
            return _FakeResp({"access_token": "NEW-ACCESS", "expires_in": 3600})

        with mock.patch.object(httpx.AsyncClient, "request", new=fake_request):
            access, secrets, note, req_headers = asyncio.run(
                advertiser_api.resolve_credential(RAKUTEN, token))
        self.assertEqual(access, "NEW-ACCESS")
        self.assertEqual(req_headers, {"x-rm-preferred-sid": SID})
        self.assertEqual(calls[0]["data"], {
            "grant_type": "client_credentials", "client_id": CID,
            "client_secret": SECRET, "scope": SID})

    def test_existing_plain_token_connection_unchanged(self):
        access, secrets, note, headers = asyncio.run(
            advertiser_api.resolve_credential(RAKUTEN, "PLAIN-TOKEN"))
        self.assertEqual(access, "PLAIN-TOKEN")
        self.assertEqual(secrets, ["PLAIN-TOKEN"])
        self.assertEqual(note, "")
        self.assertEqual(headers, {})


class TestDocumentation(unittest.TestCase):
    def test_doc_records_three_field_entry(self):
        doc = _read("docs/Rakuten_Advertising_API接入说明与广告主API标准工作流.md")
        for token in ("V4.153", "Client ID", "Client Secret", "SID",
                      "三个独立输入框", "oauthcc:"):
            self.assertIn(token, doc, "文档缺少：" + token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
