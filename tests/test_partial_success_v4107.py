"""V4.107 / 方案F：图片任务服务端恢复 + 部分成功口径回归。

- `job_to_task` 按逐尺寸 task_results 统计「请求 / 合格 / 待处理」并给出逐尺寸原因；
- 前端建批次即订阅，图片结果按 asset_id 从批次详情回填（刷新 / 超时 / 短断网仍可见）；
- 轮询窗口结束但未到终态 → 「仍在处理中」，不写 failed、不计入错误；
- 结果区展示 请求 N / 合格 M / 待处理 K，下载只含可用文件。
无模型 / 无网络。
"""
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _bootstrap  # noqa: E402
from _bootstrap import BACKEND  # noqa: E402
FRONTEND = BACKEND.parent / "frontend" / "src"
sys.path.insert(0, str(BACKEND))

from creative_tasks import job_to_task  # noqa: E402


def _job(kind="images", status="succeeded", task_results=None, images=None, error_code=""):
    return types.SimpleNamespace(
        job_id="j1", batch_id="b1", kind=kind, status=status, stage="render",
        provider_model="m", provider_task_id="", provider_request_id="",
        last_provider_status="", error_code=error_code, error_stage="", error_message="",
        error_action="", attempts=1, retry_of="", draft_id="d1",
        created_at=None, updated_at=None, finished_at=None,
        request_json={"images_request": {}},
        result_json={"task_results": task_results or [], "images": images or []},
    )


class TestPartialSuccessV4107(unittest.TestCase):

    def test_01_tally_counts_partial(self):
        tr = [
            {"status": "ok", "size": "1080x1080", "error": ""},
            {"status": "ok", "size": "1200x628", "error": ""},
            {"status": "needs_attention", "size": "1080x1920", "error": "纯色 / 无画面，已拦截"},
            {"status": "failed", "size": "300x250", "error": "供应商超时"},
        ]
        task = job_to_task(_job(task_results=tr,
                               images=[{"file": "a.png", "url": "/files/a.png"},
                                       {"file": "b.png", "url": "/files/b.png"}]))
        t = task["tally"]
        self.assertEqual(t["requested"], 4)
        self.assertEqual(t["ok"], 2)
        self.assertEqual(t["failed"], 2)
        self.assertEqual(t["pending"], 0)
        self.assertEqual(len(t["issues"]), 2)
        self.assertIn("300x250", t["issues"][1]["size"])
        # 成功数只按可用资产计
        self.assertEqual(task["success_count"], 2)

    def test_02_tally_pending(self):
        tr = [{"status": "ok", "size": "1080x1080"},
              {"status": "running", "size": "1080x1080"}]
        t = job_to_task(_job(status="running", task_results=tr))["tally"]
        self.assertEqual((t["requested"], t["ok"], t["pending"]), (2, 1, 1))

    def test_03_video_has_no_image_tally(self):
        task = job_to_task(_job(kind="video", task_results=[{"status": "ok"}]))
        self.assertEqual(task["tally"], {})
        self.assertEqual(task["assets"], [])

    def test_04_empty_task_results_no_tally(self):
        self.assertEqual(job_to_task(_job())["tally"], {})

    def test_05_frontend_subscribes_and_backfills(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        # 建批次即订阅（不再只依赖 120s 轮询窗口）
        self.assertIn("setPendingBatch(batchId)", page)
        # 按 asset_id 去重回填
        self.assertIn("const seen = new Set(prev.map((x: any) => String(x.file || x.url || '')))", page)
        self.assertIn("s.kind === 'images'", page)
        # 超时不判失败
        self.assertIn("const stillRunning = !TERMINAL.includes(String(st?.status || ''))", page)
        self.assertIn("pendingJobs++", page)
        self.assertIn("仍在后台处理中", page)
        # 部分成功口径展示
        self.assertIn("请求 {imgTally.requested} / 合格 {imgTally.ok} / 待处理 {imgTally.pending || 0}", page)
        self.assertIn("imgTally.issues", page)

    def test_06_download_only_available(self):
        page = (FRONTEND / "pages" / "CreativeWorkbench.tsx").read_text(encoding="utf-8")
        self.assertIn("return assets.filter(a => checked[a.file]).map(a => a.file)", page)
        self.assertIn("...assets.filter(a => a.file).map(a => a.file)", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
