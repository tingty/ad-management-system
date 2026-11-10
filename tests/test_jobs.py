"""N05 / A16 / A18 / A19：子任务预登记、幂等作用域与冲突、重启恢复与分项重试。"""
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from sqlalchemy.orm.attributes import flag_modified
from database import SessionLocal
from migrations import ensure_schema
from models import GenerationJob, utcnow
import job_service as js

USER = SimpleNamespace(id=7, display_name="测试账号", username="tester")
OTHER = SimpleNamespace(id=8, display_name="另一账号", username="other")


def payload(size="1080x1080", count=1):
    return {
        "images_request": {
            "analysis": {"url": "https://shop.example.com/p", "language": "en"},
            "platform": "Facebook", "lang": "en",
            "copy_fields": {"headline": "已确认标题"},
            "slots": [{"size": size, "placement": "信息流 Feed", "placement_id": "feed",
                       "concept_index": 0} for _ in range(count)],
            "spec_version": "", "total_pixels": None,
        },
        "archive": {"history_id": None, "platform": "Facebook", "lang": "en"},
    }


def fresh_db():
    ensure_schema()
    db = SessionLocal()
    db.query(GenerationJob).delete()
    db.commit()
    return db


class TestJobPersistence(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()

    def tearDown(self):
        self.db.close()

    def test_01_subtasks_prefilled_before_run(self):
        job, created = js.create_job(self.db, payload(count=3), USER, idempotency_key="k1")
        self.assertTrue(created)
        self.assertEqual(len(job.subtasks_json), 3)
        self.assertTrue(all(x["status"] == "pending" for x in job.subtasks_json))
        self.assertTrue(all(x["input_hash"] for x in job.subtasks_json))
        self.assertTrue(job.payload_hash)

    def test_02_same_key_same_payload_returns_original(self):
        a, c1 = js.create_job(self.db, payload(), USER, idempotency_key="same")
        b, c2 = js.create_job(self.db, payload(), USER, idempotency_key="same")
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(a.job_id, b.job_id)

    def test_03_same_key_different_payload_conflicts(self):
        js.create_job(self.db, payload(count=1), USER, idempotency_key="conflict")
        with self.assertRaises(js.IdempotencyConflict) as ctx:
            js.create_job(self.db, payload(count=2), USER, idempotency_key="conflict")
        self.assertNotEqual(ctx.exception.expected, ctx.exception.actual)

    def test_04_key_scoped_by_owner(self):
        a, _ = js.create_job(self.db, payload(), USER, idempotency_key="shared")
        b, c2 = js.create_job(self.db, payload(), OTHER, idempotency_key="shared")
        self.assertTrue(c2)
        self.assertNotEqual(a.job_id, b.job_id)
        self.assertTrue(a.idempotency_key.startswith("u7:"))
        self.assertTrue(b.idempotency_key.startswith("u8:"))
        self.assertEqual(js.raw_key(a.idempotency_key), "shared")

    def test_05_payload_hash_canonical(self):
        self.assertEqual(js.payload_hash_of({"a": 1, "b": 2}),
                         js.payload_hash_of({"b": 2, "a": 1}))
        self.assertNotEqual(js.payload_hash_of({"a": 1}), js.payload_hash_of({"a": 2}))

    def test_06_recover_classifies_subtasks(self):
        job, _ = js.create_job(self.db, payload(count=2), USER, idempotency_key="recover")
        # JSON 列须显式标记变更：浅拷贝 list 后原地改 dict 不会被 ORM 追踪
        subs = [dict(x) for x in job.subtasks_json]
        subs[0]["status"] = "running"
        job.subtasks_json = subs
        flag_modified(job, "subtasks_json")
        job.status = "running"
        self.db.commit()
        n = js.recover_interrupted()
        self.assertGreaterEqual(n, 1)
        self.db.expire_all()
        row = self.db.query(GenerationJob).filter_by(job_id=job.job_id).first()
        self.assertEqual(row.status, "failed")
        statuses = [x["status"] for x in row.subtasks_json]
        self.assertIn("unknown_outcome", statuses)
        self.assertIn("failed", statuses)
        results = (row.result_json or {}).get("task_results") or []
        self.assertTrue(any(x["status"] == "failed" for x in results))
        self.assertIn("unknown_outcome", row.error)

    def test_07_retry_after_recovery(self):
        job, _ = js.create_job(self.db, payload(count=2), USER, idempotency_key="retry")
        # JSON 列须显式标记变更：浅拷贝 list 后原地改 dict 不会被 ORM 追踪
        subs = [dict(x) for x in job.subtasks_json]
        subs[0]["status"] = "running"
        job.subtasks_json = subs
        flag_modified(job, "subtasks_json")
        job.status = "running"
        self.db.commit()
        js.recover_interrupted()
        self.db.expire_all()
        row = self.db.query(GenerationJob).filter_by(job_id=job.job_id).first()
        retry, msg = js.retry_failed(self.db, row, USER)
        self.assertIsNotNone(retry, msg)
        req = (retry.request_json or {}).get("images_request") or {}
        self.assertEqual(len(req["slots"]), 1)
        self.assertIn("失败项", msg)

    def test_08_job_dict_exposes_subtask_counts(self):
        job, _ = js.create_job(self.db, payload(count=2), USER, idempotency_key="dict")
        d = js.job_to_dict(job, include_result=False)
        self.assertEqual(d["subtask_counts"].get("pending"), 2)
        self.assertEqual(d["idempotency_key"], "dict")


if __name__ == "__main__":
    unittest.main()
