# -*- coding: utf-8 -*-
"""V4.127 · 广告主数据 P1-A：统一事实表建表 + 版本化迁移骨架专项测试。

覆盖：
1. 空库建表：9 张表 + 订单视图；20 业务字段；金额 Numeric(18,6)；
2. 幂等：ensure_schema 可重复执行，版本只应用一次；
3. 历史库补列：模拟旧库缺列时自动补齐；
4. 冲突比对：commissionId 复用不建列、correctionReason/postingDate 提升可见、6 列新建、无 item_quantity；
5. 保障一：20 行 fact 展示名种子 + 6 行 order_final 种子，重复执行不重复；
6. 视图净额与 is_void：正负相抵判取消单，不使用 REVERSED；
7. 保障三：rename_column 一次同步物理列 / 映射 / 展示名 / 视图，并记版本；代码引用审计生效。
"""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
import migrations  # noqa: E402
from database import Base  # noqa: E402

NEW_TABLES = [
    "schema_migrations", "schema_view_def", "api_source_record", "api_unified_fact",
    "api_fact_item", "api_fact_ext", "api_field_map", "api_field_label",
    "api_fetch_task", "api_fetch_run",
]
TECH_COLS = {
    "id", "source_record_id", "external_id", "template_id", "connection_id",
    "run_id", "original", "original_action_id", "created_at", "updated_at",
}
BUSINESS_COLS = [
    "commission_id", "advertiser_name", "order_id", "event_date", "campaign_name",
    "action_status", "event_name", "sale_amount_usd", "commission_amount_usd",
    "unit_price_usd", "validation_status", "is_void", "ad_id", "click_date",
    "correction_reason", "country", "coupon", "posting_date", "publisher_id", "publisher_name",
]


class _IsolatedDB(unittest.TestCase):
    """每个测试用独立 SQLite 文件；只替换 migrations 模块内部的 engine/session，
    不改动全局 database 模块与环境变量，避免污染其他测试。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = create_engine(
            f"sqlite:///{self.tmp.name}",
            connect_args={"check_same_thread": False, "timeout": 30}, future=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.migrations = migrations
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.SessionLocal)
        self._p1.start(); self._p2.start()
        self.migrations.ensure_schema()

    def tearDown(self):
        self._p2.stop(); self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def q(self, sql, params=None):
        with self.SessionLocal() as db:
            return db.execute(text(sql), params or {}).all()


class TestEmptyDatabase(_IsolatedDB):
    def test_all_tables_and_view_created(self):
        names = set(self.migrations.inspect(self.engine).get_table_names())
        for t in NEW_TABLES:
            self.assertIn(t, names, f"缺少表 {t}")
        self.assertIn("v_api_order_final", set(self.migrations.inspect(self.engine).get_view_names()))

    def test_twenty_business_fields_and_numeric_precision(self):
        cols = {c["name"]: c for c in self.migrations.inspect(self.engine).get_columns("api_unified_fact")}
        self.assertEqual(len(set(cols) - TECH_COLS), 20)
        for c in BUSINESS_COLS:
            self.assertIn(c, cols, f"缺少业务字段 {c}")
        for c in ("sale_amount_usd", "commission_amount_usd", "unit_price_usd"):
            self.assertEqual(str(cols[c]["type"]), "NUMERIC(18, 6)")
        # 可空字段不得 NOT NULL
        for c in ("ad_id", "click_date", "correction_reason", "country", "coupon"):
            self.assertTrue(cols[c]["nullable"], f"{c} 应为可空")

    def test_conflict_resolution_rules(self):
        cols = {c["name"] for c in self.migrations.inspect(self.engine).get_columns("api_unified_fact")}
        self.assertIn("commission_id", cols)          # commissionId 复用
        self.assertIn("correction_reason", cols)      # 已有技术列提升可见，不另建
        self.assertIn("posting_date", cols)
        for c in ("ad_id", "click_date", "country", "coupon", "publisher_id", "publisher_name"):
            self.assertIn(c, cols)                    # 6 个无冲突新列
        self.assertNotIn("item_quantity", cols)       # 已确认删除


class TestIdempotencyAndLegacy(_IsolatedDB):
    def test_ensure_schema_idempotent(self):
        self.assertEqual(self.migrations.ensure_schema(), [])
        ver = [r[0] for r in self.q("SELECT version FROM schema_migrations")]
        self.assertIn("V4.127.1", ver)       # V4.128 起允许后续版本追加，本版仍只应用一次
        self.assertEqual(ver.count("V4.127.1"), 1)

    def test_legacy_database_missing_columns_get_added(self):
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE api_unified_fact DROP COLUMN publisher_name"))
        cols = {c["name"] for c in self.migrations.inspect(self.engine).get_columns("api_unified_fact")}
        self.assertNotIn("publisher_name", cols)
        added = self.migrations.ensure_schema()
        self.assertIn("api_unified_fact.publisher_name", added)
        cols = {c["name"] for c in self.migrations.inspect(self.engine).get_columns("api_unified_fact")}
        self.assertIn("publisher_name", cols)

    def test_verify_schema_reports_ok(self):
        v = self.migrations.verify_schema()
        self.assertTrue(v["tables_ok"])
        self.assertTrue(v["view_ok"])
        self.assertEqual(v["business_fields"], 20)
        self.assertEqual(v["label_count"], 20)
        self.assertIn("V4.127.1", v["versions"])


class TestFieldLabels(_IsolatedDB):
    def test_twenty_fact_labels_and_six_order_labels(self):
        fact = self.q("SELECT column_key, label, visible, enum_map_json FROM api_field_label WHERE scope='fact'")
        self.assertEqual(len(fact), 20)
        labels = {r[0]: r[1] for r in fact}
        self.assertEqual(labels["campaign_name"], "品牌名称")     # ← advertiserName 口径
        self.assertEqual(labels["action_status"], "订单状态")
        enum_map = json.loads([r[3] for r in fact if r[0] == "action_status"][0])
        self.assertIn("new", enum_map)
        self.assertNotIn("REVERSED", enum_map)
        self.assertEqual(len(self.q("SELECT 1 FROM api_field_label WHERE scope='order_final'")), 6)

    def test_promoted_hidden_fields_are_visible(self):
        vis = {r[0]: r[1] for r in self.q(
            "SELECT column_key, visible FROM api_field_label WHERE scope='fact' "
            "AND column_key IN ('correction_reason','posting_date')")}
        self.assertEqual(vis, {"correction_reason": 1, "posting_date": 1})

    def test_seed_does_not_duplicate_on_rerun(self):
        self.migrations.ensure_schema()
        self.assertEqual(len(self.q("SELECT 1 FROM api_field_label WHERE scope='fact'")), 20)


class TestOrderView(_IsolatedDB):
    def test_net_amount_and_void_detection(self):
        base = dict(template_id="cj_publisher_commissions", connection_id=1, order_id="69461063",
                    event_date="2026-11-01", commission_id="c1")
        rows = [
            (dict(base, sale_amount_usd="61.742", commission_amount_usd="1.852", original=1),),
            (dict(base, commission_id="c2", sale_amount_usd="-61.742",
                  commission_amount_usd="-1.852", original=0),),
        ]
        with self.SessionLocal() as db:
            for (data,) in rows:
                keys = ",".join(data)
                marks = ",".join(f":{k}" for k in data)
                db.execute(text(f"INSERT INTO api_unified_fact({keys}) VALUES({marks})"), data)
            db.commit()
        v = self.q("SELECT net_sale_usd, net_commission_usd, is_void, detail_count FROM v_api_order_final")
        self.assertEqual(len(v), 1)
        self.assertEqual(Decimal(str(v[0][0])), Decimal("0"))
        self.assertEqual(Decimal(str(v[0][1])), Decimal("0"))
        self.assertEqual(v[0][2], 1)          # 正负相抵 → 取消单
        self.assertEqual(v[0][3], 2)

    def test_non_zero_order_not_void(self):
        with self.SessionLocal() as db:
            db.execute(text("""INSERT INTO api_unified_fact
                (template_id, connection_id, order_id, commission_id, sale_amount_usd, commission_amount_usd)
                VALUES ('cj',1,'o2','c3', 10.5, 0.3)"""))
            db.commit()
        self.assertEqual(self.q("SELECT is_void FROM v_api_order_final")[0][0], 0)


class TestRenameColumn(_IsolatedDB):
    def test_audit_finds_column_references(self):
        hits = self.migrations.audit_column_references("posting_date")
        self.assertIsInstance(hits, list)
        # 通用词不误报（providers.py 里的英文 coupon 不应命中）
        self.assertEqual(self.migrations.audit_column_references("coupon"), [])

    def test_rename_syncs_four_places_and_records_version(self):
        with self.SessionLocal() as db:
            db.execute(text("""INSERT INTO api_field_map(template_id, source_path, target_field, transform)
                VALUES ('cj','saleAmountUsd','fact.sale_amount_usd','decimal')"""))
            db.commit()
        result = self.migrations.rename_column("sale_amount_usd", "net_sale_amount_usd", force=True)
        self.assertEqual(result["new"], "net_sale_amount_usd")
        cols = {c["name"] for c in self.migrations.inspect(self.engine).get_columns("api_unified_fact")}
        self.assertNotIn("sale_amount_usd", cols)
        self.assertIn("net_sale_amount_usd", cols)
        self.assertEqual(self.q("SELECT target_field FROM api_field_map")[0][0], "fact.net_sale_amount_usd")
        sql = self.q("SELECT sql FROM schema_view_def WHERE name=:n", {"n": "v_api_order_final"})[0][0]
        self.assertIn("net_sale_amount_usd", sql)
        self.assertNotIn("f.sale_amount_usd", sql)
        versions = [r[0] for r in self.q("SELECT version FROM schema_migrations")]
        self.assertTrue(any("rename-" in v for v in versions))

    def test_rename_rejects_invalid_identifier_and_duplicate(self):
        with self.assertRaises(ValueError):
            self.migrations.rename_column(";DROP TABLE", "x")
        with self.assertRaises(RuntimeError):
            self.migrations.rename_column("not_exist_col", "x", force=True)


class TestSourceContract(unittest.TestCase):
    def test_models_and_changelog_declare_contract(self):
        models = open(os.path.join(ROOT, "backend", "models.py"), encoding="utf-8").read()
        self.assertIn("class ApiUnifiedFact(Base):", models)
        self.assertIn("Numeric(18, 6)", models)
        # 数量只在商品子表 quantity，事实表无 item_quantity
        self.assertIn("class ApiFactItem(Base):", models)
        self.assertNotIn("item_quantity", models)
        doc = open(os.path.join(ROOT, "docs", "广告主数据模块功能开发文档_20261124.html"), encoding="utf-8").read()
        for key in ("api_unified_fact", "api_source_record", "schema_migrations", "v_api_order_final"):
            self.assertIn(key, doc)


if __name__ == "__main__":
    unittest.main()
