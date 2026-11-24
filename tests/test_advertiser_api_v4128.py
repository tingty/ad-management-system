# -*- coding: utf-8 -*-
"""V4.128 · API对接「测试」列与右侧详情滑窗专项测试。

覆盖：
1. 后端所有测试返回路径都带完整 request_url / request_body / response_text / response；
2. Token 不进入请求体、结果摘要与响应原文；
3. 连接表新增测试详情列、ensure_schema 幂等、版本记录 V4.128.1；
4. _record_test_result 把完整请求/响应回写连接并可输出到前端；
5. 前端列表最后列为「测试」、点击发起真实测试、右侧滑窗显示请求链接与响应、可关闭；
6. 既有列表 / 双弹窗 / 菜单契约不回归。
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
import advertiser_api  # noqa: E402
import migrations  # noqa: E402
import models  # noqa: E402
import routers  # noqa: E402


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _ok_response(body):
    r = mock.MagicMock()
    r.status_code = 200
    r.text = json.dumps(body, ensure_ascii=False)
    r.json.return_value = body
    return r


class TestBackendDetailContract(unittest.TestCase):
    def _run(self, response, token="SUPER_SECRET_TOKEN"):
        seen_headers = {}

        async def fake_post(client, url, json=None, headers=None):
            seen_headers.update(headers or {})
            return response

        with mock.patch.object(advertiser_api.httpx.AsyncClient, "post", fake_post):
            out = asyncio.run(advertiser_api.test_connection(
                template_code="cj_publisher_commissions",
                endpoint="https://commissions.api.cj.com/query",
                token=token, cid="12345",
                since_event_date="2026-11-23T00:00:00Z",
                before_event_date="2026-11-24T00:00:00Z",
            ))
        self.assertEqual(seen_headers.get("Authorization"), f"Bearer {token}")
        return out

    def test_success_result_has_full_request_and_response(self):
        body = {"data": {"publisherCommissions": {
            "count": 7, "payloadComplete": True, "maxCommissionId": "99", "limit": 10000,
        }}}
        out = self._run(_ok_response(body))
        self.assertTrue(out["ok"])
        self.assertEqual(out["request_url"], "https://commissions.api.cj.com/query")
        self.assertEqual(out["request_method"], "POST")
        self.assertEqual(out["request_body"]["variables"]["forPublishers"], ["12345"])
        self.assertEqual(out["request_body"]["variables"]["sinceEventDate"], "2026-11-23T00:00:00Z")
        self.assertEqual(out["response"]["data"]["publisherCommissions"]["count"], 7)
        self.assertEqual(json.loads(out["response_text"]), body)
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", out["tested_at"]))
        self.assertNotIn("SUPER_SECRET_TOKEN", json.dumps(out, ensure_ascii=False))

    def test_error_result_keeps_full_upstream_response_but_redacts_token(self):
        raw = '{"errors":[{"message":"Invalid auth token SUPER_SECRET_TOKEN"}],"detail":"padding"}'
        r = mock.MagicMock()
        r.status_code = 401
        r.text = raw
        r.json.return_value = json.loads(raw)
        out = self._run(r)
        self.assertFalse(out["ok"])
        self.assertEqual(out["http_code"], 401)
        self.assertEqual(out["response_text"], '{"errors":[{"message":"Invalid auth token ***"}],"detail":"padding"}')
        self.assertIn("request_url", out)
        self.assertNotIn("SUPER_SECRET_TOKEN", json.dumps(out, ensure_ascii=False))

    def test_early_errors_also_use_unified_contract(self):
        out = asyncio.run(advertiser_api.test_connection(
            template_code="unknown", endpoint="", token="", cid="",
            since_event_date="a", before_event_date="b",
        ))
        for key in ("request_url", "request_method", "request_body", "response_text",
                    "response", "tested_at", "http_code", "ok"):
            self.assertIn(key, out)

    def test_schema_accepts_detail_fields(self):
        import schemas
        out = schemas.ApiTestOut(**{
            "ok": True, "count": 1, "http_code": 200,
            "request_url": "https://example.test/query", "request_method": "POST",
            "request_body": {"query": "x"}, "response_text": "{}", "response": {},
            "tested_at": "2026-11-24T07:00:00Z",
        })
        self.assertEqual(out.request_url, "https://example.test/query")
        self.assertEqual(out.response_text, "{}")


class TestPersistence(unittest.TestCase):
    """独立隔离库：只替换 migrations 模块内部引用，不污染全局 database / 环境变量。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = create_engine(
            f"sqlite:///{self.tmp.name}",
            connect_args={"check_same_thread": False, "timeout": 30}, future=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.SessionLocal)
        self._p1.start(); self._p2.start()
        self.first = migrations.ensure_schema()

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_columns_and_version_created_idempotently(self):
        cols = {c["name"] for c in migrations.inspect(self.engine).get_columns("api_connection")}
        for col in ("last_test_url", "last_test_request_body", "last_test_response_text"):
            self.assertIn(col, cols)
        with self.SessionLocal() as db:
            versions = {r[0] for r in db.execute(text("SELECT version FROM schema_migrations")).all()}
        self.assertIn("V4.128.1", versions)
        self.assertEqual(migrations.ensure_schema(), [])

    def test_legacy_database_gets_new_columns(self):
        # 重建旧结构（无 V4.128 三列），ensure_schema 只补列、不破坏已有行
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE api_connection"))
            conn.execute(text("""CREATE TABLE api_connection (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(128), owner_id INTEGER,
                template_code VARCHAR(64), cid VARCHAR(64), endpoint VARCHAR(512),
                token_enc VARCHAR(1024), token_mask VARCHAR(64), status VARCHAR(24),
                last_test_ok BOOLEAN, last_test_at DATETIME, last_test_error TEXT,
                last_test_http_code INTEGER, last_test_count INTEGER, schedule_json JSON,
                created_at DATETIME, updated_at DATETIME)"""))
            conn.execute(text("INSERT INTO api_connection(name, cid) VALUES ('旧连接', '12345')"))
        changed = migrations.ensure_schema()
        self.assertIn("api_connection.last_test_url", changed)
        cols = {c["name"] for c in migrations.inspect(self.engine).get_columns("api_connection")}
        self.assertIn("last_test_response_text", cols)
        with self.SessionLocal() as db:
            self.assertEqual(db.execute(text("SELECT name FROM api_connection")).scalar(), "旧连接")

    def test_record_test_result_writes_detail_and_output_exposes_it(self):
        row = models.ApiConnection()
        routers._record_test_result(row, {
            "ok": False, "http_code": 401, "count": 0, "error": "认证失败",
            "request_url": "https://example.test/query", "request_method": "POST",
            "request_body": {"query": "query X {}"},
            "response_text": '{"errors":[{"message":"bad token"}]}',
        })
        self.assertEqual(row.last_test_url, "https://example.test/query")
        self.assertEqual(row.last_test_request_body, {"query": "query X {}"})
        self.assertIn("bad token", row.last_test_response_text)
        out = routers._connection_out(row)
        self.assertEqual(out["last_test_url"], "https://example.test/query")
        self.assertEqual(out["last_test_request_body"], {"query": "query X {}"})
        self.assertIn("bad token", out["last_test_response_text"])


class TestFrontendDrawer(unittest.TestCase):
    def setUp(self):
        self.page = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.api = _read("frontend/src/api.ts")
        self.css = _read("frontend/src/styles.css")

    def test_list_has_test_as_last_column(self):
        self.assertIn(
            "<thead><tr><th>NO.</th><th>广告主</th><th>模板</th><th>状态</th><th>设置</th><th>测试</th></tr></thead>",
            self.page,
        )
        self.assertIn("onClick={() => void startTest(c.id, c.name)}", self.page)
        self.assertIn("测试中…", self.page)

    def test_drawer_shows_request_and_full_response(self):
        for key in ["ad-drawer", "request_url", "request_method", "response_text",
                    "请求链接", "响应结果", "完整 Endpoint", "上游原文"]:
            self.assertIn(key, self.page)
        self.assertIn('aria-label="接口测试详情"', self.page)
        self.assertIn("pretty(drawerResult?.response_text)", self.page)
        self.assertIn("Authorization: Bearer ****", self.page)

    def test_drawer_can_close_and_is_scoped(self):
        for key in ["setTestDrawer(null)", "ad-drawer-x", "ad-drawer-mask", "onMouseDown"]:
            self.assertIn(key, self.page)
        for key in [".ad-drawer-mask", ".ad-drawer-head", ".ad-drawer-summary",
                    ".ad-url-bar", ".ad-response", "@media (prefers-reduced-motion"]:
            self.assertIn(key, self.css)

    def test_api_contract_kept_in_sync(self):
        for key in ["last_test_url", "last_test_request_body", "last_test_response_text"]:
            self.assertIn(key, self.api)
        for key in ["request_url: string", "request_method: string", "request_body: Record<string, unknown>",
                    "response_text: string", "tested_at: string"]:
            self.assertIn(key, self.api)

    def test_existing_layout_contracts_unchanged(self):
        self.assertIn("新建 API 对接", self.page)
        self.assertIn("设置 · 定期任务", self.page)
        self.assertIn("createAndTestConnection", self.api)
        self.assertIn("type=\"password\"", self.page)
        self.assertNotIn("token_mask", self.page)


if __name__ == "__main__":
    unittest.main()
