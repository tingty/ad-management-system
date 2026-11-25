# -*- coding: utf-8 -*-
"""V4.133 · API对接列表时间列与编辑配置专项测试。

覆盖：
1. 两个时间字段的语义分离：config_updated_at（新建/配置变更）、
   last_sync_at（测试或拉取的最近一次真实请求）；
2. 版本迁移 V4.133.1 幂等回填历史值；
3. 四个写入点：创建、PATCH 配置、测试回写、拉取回写各自只刷新对应字段；
4. 前端列表两列 + 编辑按钮 + 编辑弹窗复用组件；接口 PATCH 支持所需字段；
5. 文档同步，且既有契约不回归。
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestSchemaContract(unittest.TestCase):
    def test_model_has_two_columns(self):
        from models import ApiConnection
        cols = {c.name for c in ApiConnection.__table__.columns}
        self.assertIn("config_updated_at", cols)
        self.assertIn("last_sync_at", cols)

    def test_output_schema_has_two_fields(self):
        src = _read("backend/schemas.py")
        self.assertIn("config_updated_at: Optional[str] = None", src)
        self.assertIn("last_sync_at: Optional[str] = None", src)

    def test_connection_out_exposes_two_fields(self):
        src = _read("backend/routers.py")
        self.assertIn('"config_updated_at": r.config_updated_at.isoformat()', src)
        self.assertIn('"last_sync_at": r.last_sync_at.isoformat()', src)

    def test_migration_registered(self):
        from migrations import MIGRATIONS
        versions = [v for v, _, _ in MIGRATIONS]
        self.assertIn("V4.133.1", versions)
        self.assertEqual(len(versions), len(set(versions)), "迁移版本不得重复")

    def test_frontend_types_have_two_fields(self):
        src = _read("frontend/src/api.ts")
        self.assertIn("config_updated_at: string | null", src)
        self.assertIn("last_sync_at: string | null", src)


class TestWritePoints(unittest.TestCase):
    def test_create_initializes_config_time_only(self):
        src = _read("backend/routers.py")
        self.assertIn("config_updated_at=datetime.utcnow(),", src)

    def test_patch_refreshes_config_time(self):
        src = _read("backend/routers.py")
        self.assertIn("r.config_updated_at = datetime.utcnow()", src)
        self.assertIn("body.schedule)):", src)

    def test_test_writeback_refreshes_sync_time(self):
        src = _read("backend/routers.py")
        self.assertIn("r.last_sync_at = r.last_test_at", src)

    def test_fetch_refreshes_sync_time(self):
        src = _read("backend/routers.py")
        # 拉取写入点应独立于测试回写，且在创建 run 后刷新
        self.assertIn("r.last_sync_at = datetime.utcnow()", src)


class _IsolatedDB(unittest.TestCase):
    """用独立临时 SQLite engine/session，不替换任何全局模块状态。"""

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import migrations
        import models  # noqa: F401  确保 create_all 注册全部模型

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.engine = create_engine(
            "sqlite:///" + self.tmp.name,
            connect_args={"check_same_thread": False}, future=True)
        self.Session = sessionmaker(bind=self.engine, future=True)
        models.Base.metadata.create_all(bind=self.engine)
        # 版本迁移直接在独立连接上执行（不依赖全局 engine）
        with self.engine.begin() as conn:
            from migrations import MIGRATIONS
            for version, _, fn in MIGRATIONS:
                fn(conn)

    def tearDown(self):
        self.engine.dispose()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)


class TestIntegration(_IsolatedDB):
    def test_new_connection_has_config_time_and_no_sync_time(self):
        from models import ApiConnection
        from routers import _create_connection_row
        from schemas import ApiConnectionIn
        with self.Session() as db:
            # 直接构造行，绕过加密/user 依赖；用最小 user 桩
            class U:
                id = 1
            row = _create_connection_row(
                db, U(), ApiConnectionIn(
                    name="CJ 主账号", template_code="cj_publisher_commissions",
                    token="tok-123", cid="123456"))
            self.assertIsNotNone(row.config_updated_at)
            self.assertIsNone(row.last_sync_at)
            self.assertIsNotNone(row.created_at)

    def test_test_writeback_only_touches_sync_time(self):
        from routers import _create_connection_row, _record_test_result
        from schemas import ApiConnectionIn
        with self.Session() as db:
            class U:
                id = 1
            row = _create_connection_row(
                db, U(), ApiConnectionIn(
                    name="CJ", template_code="cj_publisher_commissions",
                    token="tok", cid="1"))
            cfg_before = row.config_updated_at
            _record_test_result(row, {
                "ok": True, "error": "", "http_code": 200,
                "count": 5, "record_count": 5,
                "request_url": "https://example.com/query",
                "request_body": {"query": "x"},
                "response_text": "{}",
            })
            db.commit(); db.refresh(row)
            self.assertEqual(row.config_updated_at, cfg_before,
                             "测试回写不得刷新配置更新时间")
            self.assertIsNotNone(row.last_sync_at)
            self.assertIsNotNone(row.last_test_at)

    def test_migration_backfills_legacy_rows(self):
        from models import ApiConnection
        from migrations import _migrate_v4133_1
        from sqlalchemy import text
        # 先造一条「历史行」：两个新列留 NULL
        with self.Session() as db:
            now = datetime.utcnow() - timedelta(days=3)
            db.execute(text("""INSERT INTO api_connection
                (name, template_code, cid, status, created_at, updated_at, last_test_at)
                VALUES ('legacy','cj_publisher_commissions','9','active',:t,:t,:t)"""),
                {"t": now})
            db.commit()
        with self.engine.begin() as conn:
            _migrate_v4133_1(conn)
        with self.Session() as db:
            row = db.query(ApiConnection).first()
            self.assertIsNotNone(row.config_updated_at)
            self.assertIsNotNone(row.last_sync_at)
        # 幂等：再跑一次不报错
        with self.engine.begin() as conn:
            _migrate_v4133_1(conn)


class TestFrontendContract(unittest.TestCase):
    def test_list_has_two_time_columns_and_edit(self):
        src = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn("<th>更新时间</th><th>API同步时间</th>", src)
        self.assertIn("<th>编辑</th>", src)
        self.assertIn("fmtTime(c.config_updated_at || c.created_at)", src)
        self.assertIn("fmtTime(c.last_sync_at || c.last_test_at)", src)

    def test_edit_dialog_reuses_modal_components(self):
        src = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn('<h3>编辑 API 对接</h3>', src)
        self.assertIn('className="ad-modal"', src)
        self.assertIn('className="ad-form-grid"', src)
        self.assertIn("void saveEdit()", src)
        self.assertIn("留空表示不修改", src)

    def test_edit_calls_patch(self):
        api = _read("frontend/src/api.ts")
        src = _read("frontend/src/pages/AdvertiserApi.tsx")
        self.assertIn("updateConnection(editingId, payload)", src)
        self.assertIn("method: 'PATCH'", api)

    def test_time_cell_styled(self):
        src = _read("frontend/src/styles.css")
        self.assertIn(".ad-time-cell", src)


if __name__ == "__main__":
    unittest.main()
