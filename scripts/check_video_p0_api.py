#!/usr/bin/env python3
"""V4.79 / P0 接口层验收：诊断四态 + 任务状态语义 + 证据落盘（本地假供应商，零费用）。

对应验收条目：
- A01 诊断四态：no_config / text_model / ready（以及 contract_missing 的判定分支）
- A13 任务状态：出片失败 → needs_attention（不再 done + videos=[]），成功 → done
- A14 证据落盘：失败结果带 evidence 且写盘，含 submit / polls / download
- 结果字段：error_code / error_action / error_task_id / stage 完整，videos 为空，分镜仍在

用法：python3 scripts/check_video_p0_api.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

# 复用确定性用例里的假供应商
spec = importlib.util.spec_from_file_location("p0cases", os.path.join(ROOT, "scripts", "check_video_pipeline_p0.py"))
p0 = importlib.util.module_from_spec(spec)
sys.modules["p0cases"] = p0
spec.loader.exec_module(p0)

TMP = tempfile.mkdtemp(prefix="v479_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TMP, 'api.db')}"

from database import Base, engine, SessionLocal  # noqa: E402
import models  # noqa: E402
from models import GenerationJob, ModelConfig, User  # noqa: E402
import routers  # noqa: E402
from schemas import CWVideoGenerateRequest  # noqa: E402

results: list[dict] = []


def record(name: str, ok: bool, detail: str):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def seed(**kw) -> ModelConfig:
    db = SessionLocal()
    base = {
        "name": kw.get("name", "cfg"), "usage": kw.get("usage", "video"),
        "usages": kw.get("usages", ["video"]), "provider": kw.get("provider", "aliyun-maas-video"),
        "api_key": kw.get("api_key", "sk-test"), "base_url": kw.get("base_url", ""),
        "model": kw.get("model", "ok-async"), "params": kw.get("params", {}),
        "is_active": kw.get("is_active", True),
    }
    c = ModelConfig(**base)
    db.add(c)
    db.commit()
    db.refresh(c)
    db.close()
    return c


def wipe():
    db = SessionLocal()
    db.query(ModelConfig).delete()
    db.commit()
    db.close()


async def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user = db.query(User).first()
    if not user:
        user = User(username="qa", email="qa@test.local", display_name="QA",
                    role="admin", password_hash="x", salt="x")
        db.add(user)
        db.commit()
        db.refresh(user)
    uid = user.id
    print(f"临时库：{os.environ['DATABASE_URL']}  user_id={uid}")

    srv, base = p0.start_server()
    p0.Handler.base = base
    print(f"假供应商：{base}\n")

    video_params = {
        "body_shape": "dashscope_maas",
        "endpoint": "/api/v1/services/aigc/video-generation/video-synthesis",
        "async_header": "true", "poll_path": "/api/v1/tasks", "output_aspect": "9:16",
        "poll_interval_sec": "0.2", "poll_timeout_sec": "2", "poll_max_failures": "3",
    }

    try:
        print("[1] 诊断四态（F01 / A01）")
        wipe()
        d = routers.api_cw_video_diagnose(db=db, user=user)
        record("A01 无配置 → no_config 且给唯一动作",
               d.get("state") == "no_config" and bool(d.get("action")), f"state={d.get('state')}")
        wipe()
        seed(name="deepseek 文本", provider="openai", model="deepseek-chat",
             base_url="https://api.deepseek.com/v1", usages=["video"])
        d = routers.api_cw_video_diagnose(db=db, user=user)
        record("A01 只有文本模型 → text_model", d.get("state") == "text_model",
               f"state={d.get('state')} skipped={len(d.get('skipped') or [])}")

        wipe()
        seed(name="阿里千问视频模型", provider="aliyun-maas-video", model="ok-async",
             base_url=base, params=video_params)
        d = routers.api_cw_video_diagnose(db=db, user=user)
        record("A01 配置齐全 → ready", d.get("state") == "ready",
               f"state={d.get('state')} model={d.get('model')} config_id={d.get('config_id')}")

        print("\n[2] 出片失败语义（F03 / A13）")
        wipe()
        seed(name="阿里千问视频模型", provider="aliyun-maas-video", model="pending-echo",
             base_url=base, params=video_params)
        req = CWVideoGenerateRequest(
            analysis={"product": "测试产品"},
            platform="TikTok",
            plan={"aspect": "9:16", "duration_sec": 15,
                  "shots": [{"idx": 1, "t": "0-3s", "shot": "开场", "visual": "产品特写"}]},
            options={"duration": 15, "aspect": "9:16"},
        )
        res = await routers._cw_video_generate_impl(req, db, db.query(User).first())
        ok = (res.error_code == "POLL_TIMEOUT" and not res.videos
              and bool(res.error_action) and res.error_task_id == "tk_pending-echo"
              and bool(res.storyboard.get("shots")))
        record("A13 失败结果：error_code + 动作 + 任务号 + 分镜兜底", ok,
               f"code={res.error_code} videos={len(res.videos)} task={res.error_task_id} shots={len(res.storyboard.get('shots') or [])}")

        log = (res.evidence or {}).get("log_file") or ""
        p = os.path.join(routers.CW_VIDEO_EVIDENCE_DIR, log) if log else ""
        persisted = bool(p and os.path.exists(p))
        detail = f"log={log or '-'}"
        if persisted:
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            detail += f" keys={sorted(saved.keys())} polls={len(saved.get('polls') or [])}"
            persisted = bool(saved.get("submit")) and bool(saved.get("polls")) and "model" in saved
        record("A14 证据落盘（含 submit / polls）", persisted, detail)

        print("\n[3] 后台任务状态（V4.81 起改由持久化任务承载）")
        # 任务状态语义（needs_attention / done / 越权 404）已迁到 creative_tasks，
        # 由 scripts/check_creative_tasks.py 覆盖；这里只校验「入队即可查到」这一条链路。
        import creative_tasks
        payload = {
            "product": "测试产品", "platform": "TikTok",
            "prompt": "产品：测试产品", "meta": {"duration": 15, "aspect": "9:16"},
            "plan": {"aspect": "9:16", "duration_sec": 15, "shots": []},
            "analysis": {"product": "测试产品"}, "options": {}, "aspect": "9:16", "duration": 15,
        }
        batch, pjob, created = creative_tasks.create_video_batch(
            db, db.query(User).first(), payload, idempotency_key="p0api")
        record("A13 入队即落库（status=queued / stage=submitting / 带批次）",
               created and pjob.status == "queued" and pjob.stage == "submitting"
               and bool(pjob.batch_id),
               f"batch={pjob.batch_id} status={pjob.status} stage={pjob.stage}")

        print("\n[4] 兼容响应结构")
        out = routers._cw_video_job_out(pjob)
        record("兼容视图字段齐全（job_id / status / stage / result / batch_id）",
               out.job_id == pjob.job_id and out.status == "queued" and out.batch_id == pjob.batch_id
               and out.result is not None and bool(out.stage),
               f"status={out.status} stage={out.stage} storyboard_shots={len(out.result.storyboard.get('shots') or [])}")

        print("\n[5] 越权读任务（F06）")
        other = User(username="other", email="o@test.local", display_name="O", role="editor", password_hash="x", salt="x")
        db.add(other); db.commit(); db.refresh(other)
        try:
            routers.api_cw_video_get_job(pjob.job_id, db=db, user=other)
            record("A15 他人任务不可读", False, "未拦截")
        except Exception as e:
            record("A15 他人任务不可读", getattr(e, "status_code", 0) == 404,
                   f"{type(e).__name__}: {e}")
        db.query(GenerationJob).filter_by(job_id=pjob.job_id).delete()
        db.commit()

    finally:
        srv.shutdown()
        db.close()

    passed = sum(1 for r in results if r["ok"])
    print(f"\n结果：{passed}/{len(results)} 通过")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
