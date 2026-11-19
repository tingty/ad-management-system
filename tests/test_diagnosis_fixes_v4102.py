"""V4.102：诊断报告 7 项确定性缺陷修复回归。

B01 批次状态漂移（终态重算 + 历史重算迁移）/
B03 逐图索引与错误丢失（task_index / provider_error / stage）/
B06 提示词管理会话键写错 / B05 保存文案误导 /
C04 纯图模式旧版式 composition 与零文字契约冲突 /
Q02 imageio-ffmpeg 依赖未声明 / S01 通用任务接口越权。

无模型 / 无网络：静态源码断言 + 临时数据库行为测试。
"""
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from creative_config import brief_prompt_block  # noqa: E402
from media_ad import _media_image_prompt  # noqa: E402
from models import GenerationJob, CreativeBatch  # noqa: E402
from database import SessionLocal  # noqa: E402
from migrations import ensure_schema  # noqa: E402
import job_service as js  # noqa: E402

USER = SimpleNamespace(id=7, display_name="测试账号", username="tester")
OTHER = SimpleNamespace(id=8, display_name="另一账号", username="other")


class TestFrontendAndDeps(unittest.TestCase):
    """B05 / B06 / Q02：静态源码断言。"""

    def test_b06_session_key_fixed(self):
        page = (FRONTEND / "pages" / "MaterialPromptManage.tsx").read_text(encoding="utf-8")
        self.assertIn("sessionStorage.getItem('admb_cw_session_v1')", page)
        self.assertNotIn("sessionStorage.getItem('cw_session_v1')", page)

    def test_b05_save_message_not_misleading(self):
        page = (FRONTEND / "pages" / "MaterialPromptManage.tsx").read_text(encoding="utf-8")
        self.assertNotIn("下一次生成相关提示词时生效", page)
        self.assertIn("不会改变出图出片", page)

    def test_q02_imageio_ffmpeg_declared(self):
        req = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("imageio-ffmpeg", req)

    def test_resetall_clears_supplement(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("setImageSupplement('')", page)


class TestC04PurePromptNoConflict(unittest.TestCase):
    """C04：纯图模式不得注入 copy block / negative space 旧版式指令。"""

    def test_pure_mode_replaces_composition(self):
        brief = {"concept_id": "c1", "composition": "copy block on the lower-left; generous negative space"}
        pure = brief_prompt_block(brief, overlay_mode="pure")
        self.assertIn("no copy block", pure)
        self.assertNotIn("generous negative space", pure)
        self.assertNotIn("copy block on the lower-left", pure)

    def test_overlay_mode_keeps_composition(self):
        brief = {"concept_id": "c1", "composition": "copy sits on a solid bottom panel"}
        overlay = brief_prompt_block(brief, overlay_mode="image_text")
        self.assertIn("copy sits on a solid bottom panel", overlay)

    def test_mia_image_prompt_pure_has_no_layout_conflict(self):
        prompt = _media_image_prompt(
            {"industry": "消费电子", "type": "电商", "audience": "都市白领",
             "advantages": ["续航"], "competitors": []},
            "Meta", {}, {"concept_id": "c1", "composition": "generous negative space"},
            overlay_mode="pure")
        self.assertNotIn("generous negative space", prompt)
        self.assertIn("no copy block", prompt)


class TestB03TaskResultFields(unittest.TestCase):
    """B03：common 携带 task_index / target_id / stage；task_results 透出 provider_error。"""

    def test_common_fields_present_in_source(self):
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        self.assertIn('"task_index": t["idx"]', src)
        self.assertIn('"stage": "image_render"', src)
        self.assertIn('"target_id": f"{t[\'placement\']}::{t[\'size\']}"', src)
        # 内容拦截分支保留 provider_error
        self.assertIn('"provider_error": provider_error,', src)
        # task_results 组装透出
        self.assertIn('"stage": s.get("stage", "")', src)
        self.assertIn('"provider_error": s.get("provider_error", "")', src)

    def test_skipped_task_index_survives(self):
        """内容体检拦截项也应带 task_index（来自 common），job_service 才能收敛子任务。"""
        src = (BACKEND / "media_ad.py").read_text(encoding="utf-8")
        block = src.split("if not content_check.get(\"ok\"):", 1)[1].split("return {", 1)[1].split("}}", 1)[0]
        self.assertIn("**common", block, "拦截分支必须继承 common（含 task_index）")


class TestB01BatchRecount(unittest.TestCase):
    """B01：图片任务终态触发批次重算；历史重算迁移可用。"""

    def setUp(self):
        ensure_schema()
        self.db = SessionLocal()
        self.db.query(GenerationJob).delete()
        self.db.query(CreativeBatch).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_recount_helper_exists_with_lazy_import(self):
        import job_service as js_mod
        self.assertTrue(hasattr(js_mod, "_touch_batch_status"))
        self.assertIn("from creative_tasks import _recount",
                      inspect.getsource(js_mod._touch_batch_status))

    def test_all_succeeded_batch_becomes_done(self):
        from creative_tasks import recount_all_batches
        batch = CreativeBatch(batch_id="cb_test_v4102", owner_id=7, status="queued",
                              product_name="测试", platforms=["Meta"], material_types=["image"])
        self.db.add(batch)
        self.db.commit()
        job = GenerationJob(job_id="job_test_v4102", idempotency_key="idem_v4102",
                            kind="images", status="succeeded", owner_id=7,
                            batch_id="cb_test_v4102", created_at=js.utcnow(), updated_at=js.utcnow())
        self.db.add(job)
        self.db.commit()
        changed = recount_all_batches(self.db)
        self.db.refresh(batch)
        self.assertGreaterEqual(changed, 1)
        self.assertEqual(batch.status, "done")

    def test_active_job_keeps_batch_running(self):
        from creative_tasks import recount_all_batches
        batch = CreativeBatch(batch_id="cb_active_v4102", owner_id=7, status="queued",
                              product_name="测试", platforms=["Meta"], material_types=["image"])
        self.db.add(batch)
        self.db.commit()
        job = GenerationJob(job_id="job_active_v4102", idempotency_key="idem_active_v4102",
                            kind="images", status="running", owner_id=7,
                            batch_id="cb_active_v4102", created_at=js.utcnow(), updated_at=js.utcnow())
        self.db.add(job)
        self.db.commit()
        recount_all_batches(self.db)
        self.db.refresh(batch)
        self.assertEqual(batch.status, "running")


class TestS01OwnerFilter(unittest.TestCase):
    """S01：_job_row 带 owner 校验；list 按 owner 过滤；admin 放行。"""

    def setUp(self):
        ensure_schema()
        self.db = SessionLocal()
        self.db.query(GenerationJob).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_job_row_rejects_other_owner(self):
        from fastapi import HTTPException
        from routers import _job_row
        job = GenerationJob(job_id="job_owner_v4102", idempotency_key="idem_owner_v4102",
                            kind="images", status="queued", owner_id=7,
                            created_at=js.utcnow(), updated_at=js.utcnow())
        self.db.add(job)
        self.db.commit()
        # 本人可读
        row = _job_row(self.db, "job_owner_v4102", USER)
        self.assertEqual(row.job_id, "job_owner_v4102")
        # 他人 404
        with self.assertRaises(HTTPException) as cm:
            _job_row(self.db, "job_owner_v4102", OTHER)
        self.assertEqual(cm.exception.status_code, 404)
        # admin 放行
        admin = SimpleNamespace(id=99, role="admin")
        row = _job_row(self.db, "job_owner_v4102", admin)
        self.assertEqual(row.job_id, "job_owner_v4102")

    def test_list_filters_by_owner(self):
        src = (BACKEND / "routers.py").read_text(encoding="utf-8")
        block = src.split("@router.get(\"/generation-jobs\")", 1)[1].split("@router.get(\"/generation-jobs/{job_id}\")", 1)[0]
        self.assertIn("GenerationJob.owner_id == getattr(user, \"id\", None)", block)
        self.assertIn('getattr(user, "role", "") != "admin"', block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
