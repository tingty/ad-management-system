#!/usr/bin/env python3
"""V4.83 / 状态一致性与交付时长验收（零费用、纯本地桩）。

覆盖文档《创意工作台状态一致性与主流媒体素材规格诊断实施方案》P0：
- C05：dashscope_maas 请求真正携带 duration；关闭开关时不携带；
- C05：实测 5.04s / 目标 15s → needs_attention + DURATION_MISMATCH，原片保留但不计合格；
- C04：终态 stage_label 取 status，不再「成功但下载校验中」；
- C03：job_to_task 暴露 retry_of / delivery_status 供前端按当前 attempt 取结果；
- C06：历史导出 ZIP 可并入批次内视频，交付清单标记未达标原片。

用法：python3 scripts/check_video_v483.py
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp(prefix="v483_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TMP, 'v483.db')}"

import providers  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
from models import (CreativeAsset, CreativeBatch, GenerationJob, ModelConfig,
                    User, utcnow)  # noqa: E402
import creative_tasks as ct  # noqa: E402
from creation_history import build_history_zip  # noqa: E402

results: list[dict] = []


def record(name: str, ok: bool, detail: str):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def _box(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + typ + body


def _mp4(seconds: float) -> bytes:
    scale = 1000
    body = b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">I", scale) \
        + struct.pack(">I", int(seconds * scale)) + b"\x00" * 80
    return (_box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2avc1mp41")
            + _box(b"mdat", b"\x00" * 4096) + _box(b"moov", _box(b"mvhd", body)))


def test_body_duration():
    print("\n[1] 时长参数真正进入厂商请求（C05）")
    m = providers.ModelVideo(
        api_key="k", base_url="https://example.invalid", model="wan3.0-video",
        params={"body_shape": "dashscope_maas", "send_duration": "true"})
    body = m._body("prompt", {"aspect": "9:16", "duration": 15})
    record("dashscope_maas 发送 parameters.duration=15",
           body["parameters"].get("duration") == 15,
           str(body["parameters"]))

    m_off = providers.ModelVideo(
        api_key="k", base_url="https://example.invalid", model="wan3.0-video",
        params={"body_shape": "dashscope_maas", "send_duration": "false"})
    off = m_off._body("prompt", {"aspect": "9:16", "duration": 15})
    record("send_duration=false 时不发该字段（兼容旧模型）",
           "duration" not in off["parameters"], str(off["parameters"]))

    m_media = providers.ModelVideo(
        api_key="k", base_url="https://example.invalid", model="wan3.0-video",
        params={"body_shape": "dashscope_maas", "media_input": "true"})
    media = m_media._body("prompt", {"aspect": "9:16", "duration": 15,
                                      "image": "https://example.invalid/ref.png"})
    record("图生视频按配置切到 input.media",
           bool(media["input"].get("media", {}).get("media_url")),
           str(media["input"]))


def test_verdict():
    print("\n[2] 交付时长门（C05）")
    bad = ct._duration_verdict({"duration": 15},
                               {"duration_sec": 5.04, "duration_source": "mvhd"})
    record("5.04s 对 15s 判未达标", (not bad["ok"]) and bad["delivery_status"] == "noncompliant",
           bad["note"])
    good = ct._duration_verdict({"duration": 15},
                                {"duration_sec": 14.8, "duration_source": "mvhd"})
    record("14.8s 对 15s 在容差内判合格", good["ok"] and good["delivery_status"] == "compliant",
           good["note"])
    unknown = ct._duration_verdict({"duration": 15}, {"duration_sec": 0, "duration_source": ""})
    record("探测不到时长不冒充合格", (not unknown["ok"]) and unknown["delivery_status"] == "unverified",
           unknown["note"])


class FakeProvider:
    params: dict = {}

    async def submit_job(self, prompt, meta, evidence):
        return {"mode": "async", "task_id": "tk_v483", "evidence": evidence}

    def plan_request(self, prompt, meta):
        return {"poll_interval": 0.01, "poll_timeout": 1.0}

    async def poll_job(self, task_id, request, evidence):
        return {"state": "succeeded", "status": "SUCCEEDED",
                "media": {"url": "https://example.invalid/fake.mp4"}, "evidence": evidence}


async def fake_save(url, b64, filename, evidence=None):
    path = os.path.join(providers.UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(_mp4(5.04))
    return {"file_path": path, "file_bytes": os.path.getsize(path),
            "duration_sec": 5.04, "duration_source": "mvhd", "evidence": evidence or {}}


async def test_worker_delivery_gate():
    print("\n[3] worker 终态原子写入与视图一致性（C03/C04/C05）")
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.query(ModelConfig).delete()
    db.add(ModelConfig(name="v483", usage="video", usages=["video"], provider="aliyun-maas-video",
                       api_key="sk-test", base_url="https://example.invalid", model="wan3.0-video",
                       params={"body_shape": "dashscope_maas"}, is_active=True))
    u = User(username="qa_v483", email="v483@test.local", display_name="V483", role="admin",
             password_hash="x", salt="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    payload = {
        "product": "测试产品", "platform": "TikTok", "prompt": "产品：测试产品\n时长：15 秒",
        "meta": {"duration": 15, "aspect": "9:16", "product": "测试产品"},
        "plan": {"aspect": "9:16", "duration_sec": 15, "shots": [{"idx": 1, "visual": "特写"}]},
        "analysis": {"product": "测试产品"}, "options": {"duration": 15},
        "aspect": "9:16", "duration": 15,
    }
    batch, job, _ = ct.create_video_batch(db, u, payload, idempotency_key="v483-k1")
    jid, bid = job.job_id, batch.batch_id
    db.close()

    old_provider, old_save = ct._provider, ct.save_video_media
    ct._provider = lambda db, job: FakeProvider()
    ct.save_video_media = fake_save
    try:
        for _ in range(6):
            db = SessionLocal()
            j = db.query(GenerationJob).filter_by(job_id=jid).first()
            if j.status in ct.TERMINAL:
                db.close()
                break
            j.next_poll_at = utcnow().replace(tzinfo=None)
            db.commit()
            db.close()
            await ct.tick()
    finally:
        ct._provider, ct.save_video_media = old_provider, old_save

    db = SessionLocal()
    j = db.query(GenerationJob).filter_by(job_id=jid).first()
    v = ct.job_to_task(j)
    asset = db.query(CreativeAsset).filter(CreativeAsset.job_id == jid).first()
    record("5.04s/15s 判 needs_attention + DURATION_MISMATCH",
           j.status == "needs_attention" and j.error_code == "DURATION_MISMATCH",
           f"status={j.status} code={j.error_code}")
    record("终态 stage=completed，标签不再显示下载校验中",
           j.stage == "completed" and v["stage_label"] == "时长未达标",
           f"stage={j.stage} label={v['stage_label']}")
    record("原片已归档但标 noncompliant（不静默混入合格成品）",
           bool(asset) and asset.status == "noncompliant", f"asset={asset.asset_id if asset else ''}")
    record("工作区快照含实测/目标时长与交付结论",
           v["measured_duration"] == 5.04 and v["requested_duration"] == 15
           and v["delivery_status"] == "noncompliant",
           f"measured={v['measured_duration']} requested={v['requested_duration']} delivery={v['delivery_status']}")
    record("时长未达标不提供无意义的「继续查询」，保留重新下载",
           (not v["can_repoll"]) and v["can_redownload"],
           f"repoll={v['can_repoll']} redownload={v['can_redownload']}")
    b = db.query(CreativeBatch).filter_by(batch_id=bid).first()
    record("批次不算 done（5s 原片不计合格成功）", b.status == "needs_attention",
           f"batch={b.status}")
    db.close()
    return jid, bid


def test_zip_extra(jid: str):
    print("\n[4] 导出 ZIP 并入批次视频（C06）")
    db = SessionLocal()
    a = db.query(CreativeAsset).filter(CreativeAsset.job_id == jid).first()
    extra = [{"file": a.file, "role": "video", "delivery_status": "noncompliant",
              "note": "5.04s / 目标 15s"}]
    buf = build_history_zip([], extra_assets=extra)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        names = z.namelist()
        manifest = z.read("交付清单.json").decode("utf-8")
    record("ZIP 含原片文件", any(n == a.file for n in names), str(names))
    record("ZIP 含交付清单并标记未达标", "noncompliant" in manifest and "5.04s" in manifest,
           manifest[:180])
    db.close()


async def main():
    test_body_duration()
    test_verdict()
    jid, _bid = await test_worker_delivery_gate()
    test_zip_extra(jid)
    failed = [x for x in results if not x["ok"]]
    print("\n" + "=" * 68)
    print(f"V4.83 验收：{len(results) - len(failed)}/{len(results)} 通过")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
