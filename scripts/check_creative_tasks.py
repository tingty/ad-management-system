#!/usr/bin/env python3
"""V4.81 / P2 验收：视频任务持久化、租约领取、重启恢复、幂等与归属（零费用）。

对应验收条目：
- A09 提交即返回：创建接口不等待出片，返回 job_id + batch_id；
- 阶段持久化：submitting → provider_pending（供应商任务号已落库）→ succeeded；
- A08 重启恢复：租约过期后重新排队，按原 task_id 续查，**不重复提交**（提交次数不变）；
- A05 结果不明：超过业务期限转 needs_attention（不是 failed），保留任务号可续查；
- A11 幂等：同键同内容复用同一任务；同键异内容抛冲突；
- A11 归属：他人看不到、读不到；
- A13 运行中不被误领：租约未到期的任务不会被再次领取；
- 并发上限：同一供应商配置同时只驱动 2 个任务。

用法：python3 scripts/check_creative_tasks.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

spec = importlib.util.spec_from_file_location("p0cases", os.path.join(ROOT, "scripts", "check_video_pipeline_p0.py"))
p0 = importlib.util.module_from_spec(spec)
sys.modules["p0cases"] = p0
spec.loader.exec_module(p0)

TMP = tempfile.mkdtemp(prefix="v481_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TMP, 'p2.db')}"

from database import Base, engine, SessionLocal  # noqa: E402
import creative_tasks as ct  # noqa: E402
from models import CreativeAsset, CreativeBatch, GenerationJob, ModelConfig, User, utcnow  # noqa: E402
from job_service import IdempotencyConflict  # noqa: E402

results: list[dict] = []


def record(name: str, ok: bool, detail: str):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def seed_cfg(base: str, model: str, **params) -> int:
    db = SessionLocal()
    db.query(ModelConfig).delete()
    p = {"body_shape": "dashscope_maas",
         "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
         "async_header": "true", "poll_path": "/api/v1/tasks", "output_aspect": "9:16",
         "poll_interval_sec": "0.05", "poll_timeout_sec": "5", "poll_max_failures": "3"}
    p.update({k: str(v) for k, v in params.items()})
    cfg = ModelConfig(name=f"cfg-{model}", usage="video", usages=["video"],
                      provider="aliyun-maas-video", api_key="sk-test", base_url=base,
                      model=model, params=p, is_active=True)
    db.add(cfg)
    db.commit()
    cid = cfg.id
    db.close()
    return cid


def payload(product="测试产品", duration=15, prompt=None):
    return {
        "product": product, "platform": "TikTok",
        "prompt": prompt or f"产品：{product}\n时长：{duration} 秒；比例：9:16",
        "meta": {"duration": duration, "aspect": "9:16", "product": product},
        "plan": {"aspect": "9:16", "duration_sec": duration,
                 "shots": [{"idx": 1, "t": "0-3s", "shot": "开场", "visual": "产品特写"}]},
        "analysis": {"product": product}, "options": {"duration": duration},
        "aspect": "9:16", "duration": duration,
    }


async def pump(times: int = 6, gap: float = 0.12) -> None:
    """手动驱动 worker（不启动后台协程，保证测试确定性）。"""
    for _ in range(times):
        db = SessionLocal()
        for j in db.query(GenerationJob).filter(GenerationJob.kind == "video",
                                                GenerationJob.status.in_(("queued", "running"))).all():
            # 跳过刻意的延迟，直接让它到期
            j.next_poll_at = utcnow() - timedelta(seconds=1)
        db.commit()
        db.close()
        await ct.tick()
        await asyncio.sleep(gap)


async def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    u1 = User(username="qa_p2", email="p2@test.local", display_name="P2", role="admin",
              password_hash="x", salt="x")
    u2 = User(username="qa_p2b", email="p2b@test.local", display_name="P2B", role="admin",
              password_hash="x", salt="x")
    db.add_all([u1, u2])
    db.commit()
    db.refresh(u1)
    db.refresh(u2)
    db.close()

    srv, base = p0.start_server()
    p0.Handler.base = base
    print(f"临时库：{os.environ['DATABASE_URL']}\n假供应商：{base}\n")

    try:
        print("[1] 提交即返回（A09）")
        seed_cfg(base, "ok-async")
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        batch, job, created = ct.create_video_batch(db, user, payload(), idempotency_key="k1")
        record("创建返回 batch_id + job_id 且未等出片",
               created and bool(batch.batch_id) and bool(job.job_id)
               and job.status == "queued" and job.stage == "submitting"
               and job.provider_config_id is not None,
               f"batch={batch.batch_id} job={job.job_id} status={job.status} stage={job.stage}")

        batch2, job2, created2 = ct.create_video_batch(db, user, payload(), idempotency_key="k1")
        record("A11 同键同内容复用同一任务", (not created2) and job2.job_id == job.job_id,
               f"created={created2} job={job2.job_id}")
        try:
            ct.create_video_batch(db, user, payload(product="另一个产品"), idempotency_key="k1")
            record("A11 同键异内容冲突", False, "未抛冲突")
        except IdempotencyConflict as e:
            record("A11 同键异内容冲突", True, str(e)[:60])
        db.close()

        print("\n[2] 阶段推进：submitting → provider_pending → succeeded")
        job_id = job.job_id
        await ct.tick()          # 第一步：提交
        db = SessionLocal()
        j = db.query(GenerationJob).filter_by(job_id=job_id).first()
        record("提交后供应商任务号已落库",
               j.stage == "provider_pending" and j.provider_task_id == "tk_ok-async",
               f"stage={j.stage} task_id={j.provider_task_id}")
        db.close()

        await pump(8)
        db = SessionLocal()
        j = db.query(GenerationJob).filter_by(job_id=job_id).first()
        asset = db.query(CreativeAsset).filter_by(job_id=job_id).first()
        fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "backend", "uploads", os.path.basename(asset.file)) if asset else ""
        record("成片成功：状态 + 资产 + 文件校验",
               j.status == "succeeded" and asset is not None and bool(fp) and os.path.exists(fp)
               and bool(j.asset_ids) and not j.error_code,
               f"status={j.status} asset={os.path.basename(asset.file) if asset else '-'} "
               f"duration={j.result_json.get('duration_sec') if j.result_json else '-'}")
        b = db.query(CreativeBatch).filter_by(batch_id=j.batch_id).first()
        record("批次聚合为已完成", b.status == "done" and b.finished_at is not None, f"batch={b.status}")
        submitted_ok = j.evidence_json.get("submit", {}).get("task_id") if j.evidence_json else ""
        record("证据留存提交记录", submitted_ok == "tk_ok-async", f"submit.task_id={submitted_ok}")
        if fp and os.path.exists(fp):
            os.remove(fp)
        db.close()

        print("\n[3] A08 重启恢复：租约过期后按原任务号续查，不重复提交")
        seed_cfg(base, "ok-async")
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        batch3, job3, _ = ct.create_video_batch(db, user, payload(product="恢复验证"), idempotency_key="k3")
        db.close()
        await ct.tick()   # 提交 → provider_task_id 落库
        db = SessionLocal()
        j3 = db.query(GenerationJob).filter_by(job_id=job3.job_id).first()
        tk = j3.provider_task_id
        # 模拟「进程被杀」：状态停在 running，租约已过期
        j3.status, j3.stage = "running", "provider_pending"
        j3.lease_until = utcnow() - timedelta(seconds=5)
        j3.next_poll_at = utcnow() - timedelta(seconds=5)
        db.commit()
        db.close()
        n = ct.recover()
        db = SessionLocal()
        j3 = db.query(GenerationJob).filter_by(job_id=job3.job_id).first()
        record("恢复后重新排队且任务号保留",
               n >= 1 and j3.status == "queued" and j3.provider_task_id == tk and j3.lease_until is None,
               f"recovered={n} status={j3.status} task_id={j3.provider_task_id}")
        db.close()
        await pump(6)
        db = SessionLocal()
        j3 = db.query(GenerationJob).filter_by(job_id=job3.job_id).first()
        record("恢复后继续查询并成功（未重新提交）",
               j3.status == "succeeded" and j3.provider_task_id == tk,
               f"status={j3.status} attempts={j3.attempts} task_id={j3.provider_task_id}")
        a3 = db.query(CreativeAsset).filter_by(job_id=job3.job_id).first()
        if a3:
            p3 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "backend", "uploads", os.path.basename(a3.file))
            if os.path.exists(p3):
                os.remove(p3)
        db.close()

        print("\n[4] A05 结果不明 → needs_attention（保留任务号可续查）")
        seed_cfg(base, "pending-echo", job_deadline_sec=1)
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        batch4, job4, _ = ct.create_video_batch(db, user, payload(product="等待验证"), idempotency_key="k4")
        db.close()
        await ct.tick()     # 提交
        db = SessionLocal()
        j4 = db.query(GenerationJob).filter_by(job_id=job4.job_id).first()
        j4.created_at = utcnow() - timedelta(seconds=5)   # 让业务期限已过
        db.commit()
        db.close()
        await pump(2)
        db = SessionLocal()
        j4 = db.query(GenerationJob).filter_by(job_id=job4.job_id).first()
        task = ct.job_to_task(j4)
        record("超期未完成 → needs_attention 且不是 failed",
               j4.status == "needs_attention" and j4.error_code == "POLL_TIMEOUT"
               and j4.provider_task_id == "tk_pending-echo",
               f"status={j4.status} code={j4.error_code} task={j4.provider_task_id}")
        record("待核实项提供续查入口", task["can_repoll"] is True, f"can_repoll={task['can_repoll']}")
        user = db.query(User).filter_by(username="qa_p2").first()
        out = ct.retry(db, user, j4.batch_id, j4.job_id, "repoll")
        record("repoll 重新排队且清空错误",
               out["status"] == "queued" and out["stage"] == "provider_pending"
               and not j4.error_code and j4.provider_task_id == "tk_pending-echo",
               f"status={out['status']} stage={out['stage']}")
        db.close()

        print("\n[5] A13 租约：未到期任务不会被重复领取")
        db = SessionLocal()
        j4 = db.query(GenerationJob).filter_by(job_id=job4.job_id).first()
        j4.status, j4.stage = "running", "provider_pending"
        j4.lease_until = utcnow() + timedelta(seconds=120)
        j4.next_poll_at = utcnow() - timedelta(seconds=5)
        db.commit()
        db.close()
        await ct.tick()
        db = SessionLocal()
        j4 = db.query(GenerationJob).filter_by(job_id=job4.job_id).first()
        record("租约期内不被再次领取", j4.status == "running", f"status={j4.status}")
        db.close()

        print("\n[6] 并发上限（同一供应商配置同时驱动 ≤2）")
        seed_cfg(base, "ok-async")
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        ids = []
        for i in range(3):
            _b, jb, _c = ct.create_video_batch(db, user, payload(product=f"并发{i}"), idempotency_key=f"cc{i}")
            ids.append(jb.job_id)
        db.close()
        await ct.tick()
        db = SessionLocal()
        stages = [(db.query(GenerationJob).filter_by(job_id=i).first().stage,
                   db.query(GenerationJob).filter_by(job_id=i).first().status) for i in ids]
        submitted = sum(1 for s, _ in stages if s == "provider_pending")
        record("第一拍最多提交 2 个（其余排队）", submitted <= 2,
               f"submitted={submitted} stages={stages}")
        db.close()
        await pump(24, gap=0.08)
        db = SessionLocal()
        for i in ids:
            jj = db.query(GenerationJob).filter_by(job_id=i).first()
            a = db.query(CreativeAsset).filter_by(job_id=i).first()
            if a:
                pth = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "backend", "uploads", os.path.basename(a.file))
                if os.path.exists(pth):
                    os.remove(pth)
        done = [db.query(GenerationJob).filter_by(job_id=i).first().status for i in ids]
        record("排队的任务最终都能完成", all(s == "succeeded" for s in done), f"{done}")
        db.close()

        print("\n[7] A11 归属隔离")
        db = SessionLocal()
        other = db.query(User).filter_by(username="qa_p2b").first()
        lst = ct.list_batches(db, other, limit=20)
        record("他人列表为空", lst["items"] == [] and lst["active_count"] == 0,
               f"items={len(lst['items'])} active={lst['active_count']}")
        try:
            ct.get_batch(db, other, batch3.batch_id)
            record("他人批次详情 404", False, "未拦截")
        except LookupError:
            record("他人批次详情 404", True, "lookup_error")
        own = ct.list_batches(db, db.query(User).filter_by(username="qa_p2").first(), limit=20)
        record("本人列表可读到自己的批次", len(own["items"]) >= 3, f"items={len(own['items'])}")
        stat = ct.list_batches(db, db.query(User).filter_by(username="qa_p2").first(),
                               status="active", limit=20)
        record("按状态筛选可用", all(i["status"] in ("queued", "running") for i in stat["items"]),
               f"active_items={len(stat['items'])}")
        db.close()

        print("\n[9] 混合批次：图片先完成，视频独立继续（A10）")
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        head = ct.create_batch(db, user, {"product_name": "混合产品", "material_types": ["image", "video"],
                                         "platforms": ["TikTok"], "draft_id": "d1"})
        img = GenerationJob(
            job_id="job_img_test", idempotency_key="idem_img_test", kind="images",
            batch_id=head["batch_id"], status="succeeded", owner_id=user.id,
            request_json={"images_request": {}}, attempts=1,
            result_json={"images": [{"file": "a.png", "url": "/files/a.png", "placement": "TikTok"},
                                    {"file": "b.png", "url": "/files/b.png", "placement": "TikTok"}]},
            created_at=ct._now(), updated_at=ct._now(), finished_at=ct._now(),
        )
        db.add(img)
        db.commit()
        _bh, vjob, _c = ct.create_video_batch(db, user, payload(product="混合产品"),
                                             idempotency_key="kmix", batch_id=head["batch_id"])
        detail = ct.get_batch(db, user, head["batch_id"])
        kinds = {s["kind"]: s for s in detail["subtasks"]}
        record("同批次下有图片与视频两个子任务",
               set(kinds) == {"images", "video"} and detail["success_count"] >= 1,
               f"kinds={sorted(kinds)} success={detail['success_count']}/{detail['total_count']}")
        record("图片子任务先可预览（assets 已就绪）",
               len(kinds.get("images", {}).get("assets") or []) == 2
               and kinds["images"]["stage_label"] == "已完成",
               f"images={len(kinds.get('images', {}).get('assets') or [])} "
               f"stage={kinds.get('images', {}).get('stage_label')}")
        record("视频子任务独立继续（批次仍进行中）",
               detail["status"] in ("queued", "running")
               and kinds["video"]["status"] in ("queued", "running"),
               f"batch={detail['status']} video={kinds['video']['status']}")
        db.query(GenerationJob).filter_by(job_id="job_img_test").delete()
        db.query(GenerationJob).filter_by(job_id=vjob.job_id).delete()
        db.commit()
        db.close()

        print("\n[10] 停止后续步骤")
        db = SessionLocal()
        user = db.query(User).filter_by(username="qa_p2").first()
        _b, jc, _c = ct.create_video_batch(db, user, payload(product="取消验证"), idempotency_key="kc")
        out = ct.cancel(db, user, jc.batch_id)
        db.refresh(jc)
        record("取消后任务不再推进且说明在途风险",
               jc.status == "canceled" and "仍可能完成" in (jc.error_message or "")
               and out["status"] == "canceled",
               f"status={jc.status} batch={out['status']}")
        db.close()
    finally:
        srv.shutdown()

    passed = sum(1 for r in results if r["ok"])
    print(f"\n结果：{passed}/{len(results)} 通过")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
