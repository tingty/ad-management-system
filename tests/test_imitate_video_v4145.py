# -*- coding: utf-8 -*-
"""V4.145 · 模仿创作视频骨架：菜单 / kind / 表 / 迁移 / 路由 / 任务引擎专项测试。

本版不产生费用：测试只验证结构、静态断言与只读列表，不调用大模型、不提交视频生成。
"""
import os
import sys
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import _bootstrap  # noqa: E402  DATABASE_URL -> 临时 SQLite
import migrations  # noqa: E402
from models import ImitateAnalysisScript, GenerationJob  # noqa: E402
from database import Base  # noqa: E402


class TestImitateSkeleton(unittest.TestCase):
    def setUp(self):
        self.tmp = "/tmp/admp_imitate_v4145_%s.db" % os.getpid()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)
        self.engine = create_engine(
            "sqlite:///" + self.tmp,
            connect_args={"check_same_thread": False, "timeout": 30}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False,
                                         autocommit=False, future=True)
        self._p1 = mock.patch.object(migrations, "engine", self.engine)
        self._p2 = mock.patch.object(migrations, "SessionLocal", self.SessionLocal)
        self._p1.start()
        self._p2.start()
        migrations.ensure_schema()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        self.engine.dispose()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_new_table_created(self):
        names = set(migrations.inspect(self.engine).get_table_names())
        self.assertIn("imitate_analysis_script", names)
        cols = {c["name"] for c in migrations.inspect(self.engine).get_columns(
            "imitate_analysis_script")}
        for expected in ("script_id", "job_id", "file_hash", "script_json",
                         "creation_json", "owner_id", "status"):
            self.assertIn(expected, cols)

    def test_migration_version_and_seed(self):
        with self.SessionLocal() as db:
            versions = {r[0] for r in db.execute(
                text("SELECT version FROM schema_migrations")).all()}
            self.assertIn("V4.145.1", versions)
            enabled = db.execute(text(
                "SELECT value FROM system_state WHERE key='imitate_video_enabled'")).scalar()
            self.assertEqual(str(enabled), "1")
        # 幂等：第二次 ensure_schema 无新增列
        self.assertEqual(migrations.ensure_schema(), [])

    def test_worker_claims_imitate_kind(self):
        import creative_tasks
        self.assertIn("imitate_video", creative_tasks.VIDEO_KINDS)
        self.assertIn("video", creative_tasks.VIDEO_KINDS)
        # 三处 worker 过滤统一用 in_(VIDEO_KINDS)，不再硬编码 == "video"
        with open(os.path.join(ROOT, "backend/creative_tasks.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('GenerationJob.kind == "video"', src)
        self.assertIn("GenerationJob.kind.in_(VIDEO_KINDS)", src)

    def test_job_to_task_treats_imitate_as_video(self):
        import creative_tasks
        job = GenerationJob(job_id="iv-1", kind="imitate_video", status="succeeded",
                            stage="completed", request_json={"source": "url", "name": "demo"},
                            result_json={"assets": []})
        task = creative_tasks.job_to_task(job)
        self.assertEqual(task.get("kind"), "imitate_video")
        self.assertEqual(task.get("stage_label"), "已完成")

    def test_list_tasks_owner_isolation(self):
        import imitate_video
        from models import User
        with self.SessionLocal() as db:
            owner = User(id=1, username="u1", role="editor")
            other = User(id=2, username="u2", role="editor")
            db.add_all([
                GenerationJob(job_id="iv-a", kind="imitate_video", owner_id=1,
                              status="running", stage="analyzing",
                              request_json={"source": "https://x/a.mp4", "name": "A"}),
                GenerationJob(job_id="iv-b", kind="imitate_video", owner_id=2,
                              status="queued", request_json={}),
                GenerationJob(job_id="vd-c", kind="video", owner_id=1,
                              status="succeeded", request_json={}),
            ])
            db.commit()
            mine = imitate_video.list_tasks(db, owner)
            self.assertEqual([t["job_id"] for t in mine], ["iv-a"])
            self.assertEqual(mine[0]["status"], "running")
            self.assertEqual(mine[0]["stage"], "analyzing")
            self.assertEqual(mine[0]["name"], "A")
            theirs = imitate_video.list_tasks(db, other)
            self.assertEqual([t["job_id"] for t in theirs], ["iv-b"])

    def test_no_paid_call_in_module(self):
        # V4.145 骨架模块不得出现任何模型调用 / 出片提交
        with open(os.path.join(ROOT, "backend/imitate_video.py"), encoding="utf-8") as f:
            src = f.read()
        for banned in ("get_llm_with_info", "get_video", "submit_job", "generate_video"):
            self.assertNotIn(banned, src)

    def test_frontend_menu_and_labels(self):
        with open(os.path.join(ROOT, "frontend/src/App.tsx"), encoding="utf-8") as f:
            app = f.read()
        self.assertIn("'imitatevideo'", app)
        self.assertIn("GROUP_IMITATE_VIDEO", app)
        self.assertIn("ImitateVideo />", app)
        with open(os.path.join(ROOT, "frontend/src/CreativeTasksDrawer.tsx"),
                  encoding="utf-8") as f:
            drawer = f.read()
        self.assertIn("imitate_video:", drawer)
        with open(os.path.join(ROOT, "frontend/src/api.ts"), encoding="utf-8") as f:
            api = f.read()
        self.assertIn("/api/imitate-video/tasks", api)
        self.assertTrue(os.path.exists(os.path.join(
            ROOT, "frontend/src/pages/ImitateVideo.tsx")))

    def test_router_endpoint_registered(self):
        with open(os.path.join(ROOT, "backend/routers.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('import imitate_video', src)
        self.assertIn('@router.get("/imitate-video/tasks")', src)


if __name__ == "__main__":
    unittest.main()
