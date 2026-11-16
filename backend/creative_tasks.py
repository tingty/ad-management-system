"""V4.81 / P2：持久化创意任务（创作批次 + 视频子任务）与后台 worker。

V4.79 之前视频任务只活在 `routers._CW_VIDEO_JOBS` 这个进程内字典里：刷新页面靠前端
sessionStorage 续命，服务重启就全丢，多进程部署还会「查到另一个进程 404」。本模块把任务
搬进数据库，并用租约 + `next_poll_at` 驱动一个后台 worker：

- 提交只做「落库 + 立即返回 job_id」，HTTP 请求不再等出片（A09 同账号可继续下一份创作）；
- 供应商任务号在拿到的那一刻就落库，重启后按号继续查询，**不重复提交收费任务**（A08/A05）；
- 阶段如实细分 submitting / provider_pending / downloading / validating，不换算成假百分比；
- 成功条件与 P0 一致：必须落盘并通过 `save_video_media` 校验、资产行已持久化；
- 请求结果不明（超时、连续查询失败）进 `needs_attention` 待核实，保留供应商任务号可续查；
  只有「提交后未及回写就崩溃」这种真不明的情况才要求人工核实，绝不自动重提。

事实边界（不夸大）：worker 是**单进程协程**，不是分布式队列；租约用于避免多 worker /
多进程重复消费，图片仍走 `job_service` 的老链路，本次只把视频纳入持久队列。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional
from datetime import timedelta

from sqlalchemy.orm import Session

from database import SessionLocal
from models import GenerationJob, CreativeBatch, CreativeAsset, utcnow
from job_service import IdempotencyConflict, payload_hash_of
from providers import (
    VideoPipelineError, save_video_media, video_provider_of_config,
)

# ---------------- 常量 ----------------
ACTIVE = ("queued", "running")
TERMINAL = ("succeeded", "failed", "canceled", "needs_attention")
LEASE_SECONDS = 300          # 单次领取的租约：足够覆盖一次下载 + 校验
WORKER_TICK = 1.5            # worker 轮询间隔（秒）
VIDEO_CONCURRENCY = 2        # 同一供应商配置下并发出片上限（超出的排队，不无限 create_task）
MAX_CLAIM_PER_TICK = 4
DEFAULT_POLL_INTERVAL = 3.0
MAX_POLL_INTERVAL = 15.0
# 结果不明但**可续查**的错误码：保持任务在待核实，可「继续查询」取回原成片
NEEDS_ATTENTION_CODES = {"POLL_TIMEOUT", "POLL_UNREACHABLE", "DOWNLOAD_FAILED",
                         "RATE_LIMITED", "PROVIDER_ERROR", "STORAGE_FAILED", "SUBMIT_UNKNOWN"}

STAGE_LABEL = {
    "submitting": "提交中",
    "provider_pending": "模型生成中",
    "downloading": "下载校验中",
    "validating": "下载校验中",
}

_RUNNING: set[str] = set()      # 本进程正在驱动的 job_id，避免同一 tick 内被重复领取
_WORKER: asyncio.Task | None = None


def _now():
    """当前 UTC 时间（**naive**）。

    SQLite 的 DATETIME 不保存时区，写进去再读出来是无时区值；如果一边用 aware 一边用
    naive 比较，会直接抛 "can't compare offset-naive and offset-aware datetimes"。
    本模块统一用 naive UTC，读出来的库值也按同一形态参与比较。
    """
    return utcnow().replace(tzinfo=None)


def _n(dt):
    """把库里的时间规整成 naive（用于与 `_now()` 比较）。"""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (None if v is None else str(v))


# ============================ 创建 ============================
def create_batch(db: Session, user, payload: dict) -> dict:
    """先建批次头（图片与视频都要排队时用）：返回 batch_id 供各子任务挂载。"""
    batch = CreativeBatch(
        batch_id=_uid("cb_"), owner_id=getattr(user, "id", None),
        owner_name=(getattr(user, "display_name", None) or getattr(user, "username", "") or ""),
        draft_id=str(payload.get("draft_id") or "")[:40],
        product_name=str(payload.get("product_name") or "")[:200],
        source_url=str(payload.get("source_url") or "")[:1000],
        material_types=[str(x) for x in (payload.get("material_types") or [])][:4],
        platforms=[str(x) for x in (payload.get("platforms") or [])][:8],
        status="queued", created_at=_now(), updated_at=_now(),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch_to_dict(batch, [])


def _attach_batch(db: Session, user, batch_id: str, material: str,
                  platforms: list) -> Optional[CreativeBatch]:
    """把子任务挂到已存在的批次上（只允许挂自己的批次）。"""
    batch = (db.query(CreativeBatch)
             .filter_by(batch_id=batch_id, owner_id=getattr(user, "id", None)).first())
    if not batch:
        return None
    types = list(batch.material_types or [])
    if material and material not in types:
        types.append(material)
    batch.material_types = types
    plats = list(batch.platforms or [])
    for p in platforms or []:
        if p and p not in plats:
            plats.append(p)
    batch.platforms = plats[:8]
    batch.updated_at = _now()
    return batch


def create_video_batch(db: Session, user, payload: dict, *, idempotency_key: str = "",
                       draft_id: str = "", batch_id: str = "") -> tuple[CreativeBatch, GenerationJob, bool]:
    """创建视频子任务（可挂到已有批次）。同幂等键 + 同内容 → 返回原任务（不重复收费）。"""
    owner = getattr(user, "id", None)
    raw = (idempotency_key or "").strip()[:180]
    key = f"u{int(owner or 0)}:v:{raw}" if raw else _uid("idem_")
    snapshot = {
        "product": str(payload.get("product") or ""),
        "platform": str(payload.get("platform") or ""),
        "prompt": str(payload.get("prompt") or ""),
        "meta": payload.get("meta") or {},
        "plan": payload.get("plan") or {},
        "analysis": payload.get("analysis") or {},
        "options": payload.get("options") or {},
        "source_url": str(payload.get("source_url") or ""),
        "aspect": str(payload.get("aspect") or ""),
        "duration": int(payload.get("duration") or 15),
        "reference_image": str(payload.get("reference_image") or ""),
    }
    digest = payload_hash_of(snapshot)

    if raw:
        old = db.query(GenerationJob).filter_by(idempotency_key=key).first()
        if old:
            if old.payload_hash and old.payload_hash != digest:
                raise IdempotencyConflict(old.job_id, old.payload_hash, digest)
            batch = db.query(CreativeBatch).filter_by(batch_id=old.batch_id).first()
            return batch, old, False

    filename = f"cw_video_{int(owner or 0)}_{int(_now().timestamp())}_{uuid.uuid4().hex[:8]}.mp4"
    batch = _attach_batch(db, user, batch_id, "video",
                          [snapshot["platform"]] if snapshot["platform"] else []) if batch_id else None
    if batch is None:
        batch = CreativeBatch(
            batch_id=_uid("cb_"), owner_id=owner,
            owner_name=(getattr(user, "display_name", None) or getattr(user, "username", "") or ""),
            draft_id=draft_id or "", product_name=snapshot["product"][:200],
            source_url=snapshot["source_url"][:1000],
            material_types=["video"],
            platforms=[snapshot["platform"]] if snapshot["platform"] else [],
            status="queued", created_at=_now(), updated_at=_now(),
        )
        db.add(batch)
        db.flush()

    cfg = _video_config(db)
    job = GenerationJob(
        job_id=_uid("job_"), idempotency_key=key, payload_hash=digest,
        kind="video", batch_id=batch.batch_id, status="queued", stage="submitting",
        owner_id=owner,
        owner_name=batch.owner_name,
        provider_config_id=getattr(cfg, "id", None),
        provider_model=getattr(cfg, "model", None),
        request_json={**snapshot, "filename": filename},
        next_poll_at=_now(), attempts=0, progress=0,
        created_at=_now(), updated_at=_now(),
    )
    db.add(job)
    db.flush()
    _recount(db, batch)
    db.commit()
    db.refresh(batch)
    db.refresh(job)
    return batch, job, True


def _video_config(db: Session):
    """取当前生效的视频模型配置（与 providers.get_video 同一判定，但这里要拿 id 落库）。"""
    try:
        from providers import _active_config
        cfg = _active_config(db, "video")
        if cfg and cfg.api_key and cfg.base_url and cfg.model:
            return cfg
    except Exception:
        pass
    return None


# ============================ 查询视图 ============================
IMG_STAGE_LABEL = {"queued": "排队中", "running": "生成中", "succeeded": "已完成",
                  "partial_success": "部分完成", "failed": "失败", "canceled": "已停止"}


def job_to_task(job: GenerationJob) -> dict:
    """子任务视图：图片与视频共用一套字段，前端只按 kind 区分展示。"""
    meta = job.request_json or {}
    result = job.result_json or {}
    is_video = (job.kind or "") == "video"
    assets = [a for a in (result.get("assets") or []) if isinstance(a, dict)]
    if not is_video and not assets:
        # 图片任务的结果是 images 数组；统一映射成 assets，前端不必写两套渲染
        assets = [{"asset_id": a.get("asset_id") or a.get("file") or "",
                   "url": a.get("url") or f"/files/{a.get('file')}",
                   "caption": a.get("placement") or "", "kind": "image",
                   "size": a.get("size") or ""}
                  for a in (result.get("images") or []) if isinstance(a, dict)]
    stage_label = (STAGE_LABEL.get(job.stage or "") or (job.stage or "")) if is_video \
        else IMG_STAGE_LABEL.get(job.status or "", job.status or "")
    return {
        "job_id": job.job_id,
        "batch_id": job.batch_id or "",
        "kind": job.kind or "",
        "status": job.status or "",
        "stage": job.stage or "",
        "stage_label": stage_label,
        "success_count": len(assets),
        "provider_model": job.provider_model or "",
        "provider_task_id": job.provider_task_id or "",
        "provider_request_id": job.provider_request_id or "",
        "last_provider_status": job.last_provider_status or "",
        "error_code": job.error_code or "",
        "error_stage": job.error_stage or "",
        "error_message": job.error_message or "",
        "error_action": job.error_action or "",
        "can_repoll": bool(job.provider_task_id) and job.status in ("needs_attention", "failed"),
        "can_redownload": bool((result.get("media") or {}).get("url")
                               or (result.get("media") or {}).get("b64")),
        "assets": assets,
        "duration_sec": result.get("duration_sec") or 0,
        "duration_source": result.get("duration_source") or "",
        "note": result.get("note") or "",
        "attempts": int(job.attempts or 0),
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "finished_at": _iso(job.finished_at),
    }


def batch_to_dict(batch: CreativeBatch, jobs: list[GenerationJob]) -> dict:
    subs = [job_to_task(j) for j in jobs]
    ok = sum(1 for s in subs if s["status"] in ("succeeded", "partial_success"))
    active = [s for s in subs if s["status"] in ACTIVE]
    head = next((s for s in active), None) or (subs[0] if subs else None)
    return {
        "batch_id": batch.batch_id,
        "product_name": batch.product_name or "",
        "source_url": batch.source_url or "",
        "material_types": batch.material_types or [],
        "platforms": batch.platforms or [],
        "status": batch.status or "",
        "draft_id": batch.draft_id or "",
        "created_at": _iso(batch.created_at),
        "updated_at": _iso(batch.updated_at),
        "finished_at": _iso(batch.finished_at),
        "success_count": ok,
        "total_count": len(subs),
        "active_stage": (head or {}).get("stage", ""),
        "active_stage_label": (head or {}).get("stage_label", ""),
        "error_code": next((s["error_code"] for s in subs if s["error_code"]), ""),
        "error_action": next((s["error_action"] for s in subs if s["error_action"]), ""),
        "subtasks": subs,
    }


def list_batches(db: Session, user, *, status: str = "", cursor: str = "",
                 limit: int = 20) -> dict:
    """本人创作批次列表；status = active / done / needs（进行中 / 已完成 / 需处理）。"""
    limit = max(1, min(int(limit or 20), 50))
    q = db.query(CreativeBatch).filter(CreativeBatch.owner_id == getattr(user, "id", None))
    groups = {
        "active": ("queued", "running"),
        "done": ("done", "partial"),
        "needs": ("needs_attention", "failed", "canceled"),
    }
    if status in groups:
        q = q.filter(CreativeBatch.status.in_(groups[status]))
    if cursor:
        try:
            q = q.filter(CreativeBatch.id < int(cursor))
        except (TypeError, ValueError):
            pass
    rows = q.order_by(CreativeBatch.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    jobs = _jobs_of(db, [b.batch_id for b in rows])
    items = [batch_to_dict(b, jobs.get(b.batch_id, [])) for b in rows]
    active_count = (db.query(CreativeBatch)
                    .filter(CreativeBatch.owner_id == getattr(user, "id", None),
                            CreativeBatch.status.in_(groups["active"]))
                    .count())
    return {"items": items, "next_cursor": (str(rows[-1].id) if more and rows else ""),
            "active_count": active_count}


def _jobs_of(db: Session, batch_ids: list[str]) -> dict[str, list[GenerationJob]]:
    if not batch_ids:
        return {}
    out: dict[str, list[GenerationJob]] = {}
    for j in (db.query(GenerationJob)
              .filter(GenerationJob.batch_id.in_(batch_ids))
              .order_by(GenerationJob.id.asc()).all()):
        out.setdefault(j.batch_id, []).append(j)
    return out


def get_batch(db: Session, user, batch_id: str) -> dict:
    batch = (db.query(CreativeBatch)
             .filter_by(batch_id=batch_id, owner_id=getattr(user, "id", None)).first())
    if not batch:
        raise LookupError("batch_not_found")
    return batch_to_dict(batch, _jobs_of(db, [batch.batch_id]).get(batch.batch_id, []))


def active_count(db: Session, user) -> int:
    return (db.query(CreativeBatch)
            .filter(CreativeBatch.owner_id == getattr(user, "id", None),
                    CreativeBatch.status.in_(ACTIVE)).count())


# ============================ 重试 ============================
def retry(db: Session, user, batch_id: str, job_id: str, action: str) -> dict:
    """分项重试：repoll（继续查询原任务）/ redownload（只重下）/ regenerate（重新生成）。"""
    batch = (db.query(CreativeBatch)
             .filter_by(batch_id=batch_id, owner_id=getattr(user, "id", None)).first())
    if not batch:
        raise LookupError("batch_not_found")
    job = (db.query(GenerationJob)
           .filter_by(job_id=job_id, batch_id=batch_id,
                      owner_id=getattr(user, "id", None)).first())
    if not job:
        raise LookupError("job_not_found")
    if job.status in ACTIVE:
        raise ValueError("任务仍在执行中，无需重试")

    if action == "repoll":
        if not job.provider_task_id:
            raise ValueError("该任务没有供应商任务号，无法续查；请重新生成")
        job.status, job.stage = "queued", "provider_pending"
        job.next_poll_at, job.lease_until = _now(), None
        _clear_error(job)
    elif action == "redownload":
        media = (job.result_json or {}).get("media") or {}
        if not (media.get("url") or media.get("b64")):
            raise ValueError("该任务没有保留成片地址，无法只重下；请继续查询或重新生成")
        job.status, job.stage = "queued", "downloading"
        job.next_poll_at, job.lease_until = _now(), None
        _clear_error(job)
    elif action == "regenerate":
        # 重新生成 = 新的执行 ID + 新的供应商任务（会产生新费用），与上面两种严格区分
        snap = dict(job.request_json or {})
        snap["filename"] = (f"cw_video_{int(job.owner_id or 0)}_"
                            f"{int(_now().timestamp())}_{uuid.uuid4().hex[:8]}.mp4")
        new = GenerationJob(
            job_id=_uid("job_"), idempotency_key=_uid("idem_"),
            payload_hash=job.payload_hash, kind="video", batch_id=batch.batch_id,
            status="queued", stage="submitting", owner_id=job.owner_id,
            owner_name=job.owner_name, provider_config_id=job.provider_config_id,
            provider_model=job.provider_model, request_json=snap, retry_of=job.job_id,
            next_poll_at=_now(), attempts=0, progress=0,
            created_at=_now(), updated_at=_now(),
        )
        db.add(new)
        _recount(db, batch)
        db.commit()
        db.refresh(new)
        return job_to_task(new)
    else:
        raise ValueError("未知的重试动作：" + str(action))

    job.updated_at = _now()
    _recount(db, batch)
    db.commit()
    db.refresh(job)
    return job_to_task(job)


def cancel(db: Session, user, batch_id: str, job_id: str = "") -> dict:
    """停止后续步骤（不做供应商取消：厂商无取消接口时，在途任务仍可能完成并计费）。"""
    batch = (db.query(CreativeBatch)
             .filter_by(batch_id=batch_id, owner_id=getattr(user, "id", None)).first())
    if not batch:
        raise LookupError("batch_not_found")
    q = db.query(GenerationJob).filter_by(batch_id=batch_id,
                                          owner_id=getattr(user, "id", None))
    if job_id:
        q = q.filter_by(job_id=job_id)
    rows = q.all()
    for j in rows:
        if j.status in ACTIVE:
            j.cancel_requested = True
            j.status = "canceled"
            j.stage = "canceled"
            j.finished_at = _now()
            j.error_code, j.error_stage = "CANCELED", j.stage
            j.error_message = "已停止后续步骤；若供应商已在渲染，该任务仍可能完成并计费"
            j.error_action = ""
            j.updated_at = _now()
    _recount(db, batch)
    db.commit()
    return get_batch(db, user, batch_id)


def _clear_error(job: GenerationJob):
    job.error_code = job.error_stage = job.error_message = job.error_action = ""
    job.finished_at = None


# ============================ 批次聚合 ============================
def _recount(db: Session, batch: CreativeBatch, commit: bool = False):
    jobs = _jobs_of(db, [batch.batch_id]).get(batch.batch_id, [])
    states = [j.status or "" for j in jobs]
    if not jobs:
        batch.status = "queued"
    elif any(s in ACTIVE for s in states):
        batch.status = "running" if any(s == "running" for s in states) else "queued"
    elif any(s == "needs_attention" for s in states):
        batch.status = "needs_attention"
    elif all(s == "succeeded" for s in states):
        batch.status = "done"
    elif any(s in ("succeeded", "partial_success") for s in states):
        batch.status = "partial"
    elif all(s == "canceled" for s in states):
        batch.status = "canceled"
    else:
        batch.status = "failed"
    if batch.status in ("done", "partial", "failed", "canceled") and not batch.finished_at:
        batch.finished_at = _now()
    batch.updated_at = _now()
    if commit:
        db.commit()


# ============================ 执行 ============================
def _claim(batch_ids_limit: int = MAX_CLAIM_PER_TICK) -> list[str]:
    """领取到期任务：租约原子的 UPDATE，再按供应商配置限制并发。"""
    db = SessionLocal()
    claimed: list[str] = []
    try:
        now = _now()
        # 已在跑（本进程）或他进程租约未到期的任务不领
        busy = {}
        for j in (db.query(GenerationJob)
                  .filter(GenerationJob.kind == "video",
                          GenerationJob.status == "running").all()):
            if _n(j.lease_until) and _n(j.lease_until) > now:
                busy[j.provider_config_id] = busy.get(j.provider_config_id, 0) + 1
        rows = (db.query(GenerationJob)
                .filter(GenerationJob.kind == "video",
                        GenerationJob.status.in_(ACTIVE),
                        GenerationJob.next_poll_at.isnot(None),
                        GenerationJob.next_poll_at <= now)
                .order_by(GenerationJob.next_poll_at.asc())
                .limit(batch_ids_limit * 6).all())
        for j in rows:
            if len(claimed) >= batch_ids_limit:
                break
            if j.job_id in _RUNNING:
                continue
            if busy.get(j.provider_config_id, 0) >= VIDEO_CONCURRENCY:
                continue
            upd = (db.query(GenerationJob)
                   .filter(GenerationJob.job_id == j.job_id,
                           GenerationJob.status.in_(ACTIVE))
                   .filter((GenerationJob.lease_until.is_(None))
                           | (GenerationJob.lease_until < now))
                   .update({"lease_until": now + timedelta(seconds=LEASE_SECONDS),
                            "heartbeat_at": now,
                            "next_poll_at": now + timedelta(seconds=WORKER_TICK),
                            "status": "running",
                            "attempts": (j.attempts or 0) + 1,
                            "updated_at": now}, synchronize_session=False))
            db.commit()
            if upd:
                claimed.append(j.job_id)
                busy[j.provider_config_id] = busy.get(j.provider_config_id, 0) + 1
    finally:
        db.close()
    return claimed


async def run_one(job_id: str) -> None:
    if job_id in _RUNNING:
        return
    _RUNNING.add(job_id)
    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter_by(job_id=job_id).first()
        if not job or job.status not in ACTIVE:
            return
        await _drive(db, job)
    except Exception as e:                     # 兜底：任何未分类异常都要落到任务上，不能静默
        try:
            db.rollback()
            job = db.query(GenerationJob).filter_by(job_id=job_id).first()
            if job:
                _fail(db, job, VideoPipelineError(
                    "PROVIDER_ERROR", f"后台执行异常：{type(e).__name__}: {e}", stage=job.stage or ""))
        except Exception:
            pass
    finally:
        # 释放租约：本次领取的这一步已经做完，下一次由 next_poll_at 决定何时再领。
        # 不释放的话，同一个任务会被自己的 300s 租约挡在门外，直到租约过期才能续查。
        try:
            db.query(GenerationJob).filter_by(job_id=job_id).update(
                {"lease_until": None}, synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()
        _RUNNING.discard(job_id)


async def _drive(db: Session, job: GenerationJob) -> None:
    if job.cancel_requested:
        job.status, job.stage, job.finished_at = "canceled", "canceled", _now()
        _recount(db, _batch_of(db, job), commit=True)
        return

    snap = job.request_json or {}
    evidence = dict(job.evidence_json or {})
    evidence.setdefault("polls", [])
    stage = job.stage or "submitting"

    if stage in ("submitting", ""):
        prov = _provider(db, job)
        if prov is None:
            _fail(db, job, VideoPipelineError(
                "CONFIG_MISSING", "视频模型配置已失效（被删除或不再启用）", stage="config"))
            return
        try:
            sub = await prov.submit_job(snap.get("prompt") or "", snap.get("meta") or {}, evidence)
        except VideoPipelineError as e:
            _fail(db, job, e)
            return
        job.evidence_json = sub.get("evidence") or evidence
        job.provider_request_id = (sub.get("request_id") or "")[:200]
        job.attempts = int(job.attempts or 0)
        if sub["mode"] == "sync":
            job.result_json = {"media": sub.get("media") or {}}
            job.stage, job.status = "downloading", "running"
        else:
            # 供应商任务号在第一时间落库：重启后据此续查，绝不重新提交
            job.provider_task_id = (sub.get("task_id") or "")[:200]
            job.stage, job.status = "provider_pending", "running"
            job.last_provider_status = "PENDING"
        job.next_poll_at = _now()
        job.updated_at = _now()
        db.commit()
        return

    if stage == "provider_pending":
        task_id = job.provider_task_id or ""
        prov = _provider(db, job)
        if prov is None:
            _fail(db, job, VideoPipelineError(
                "CONFIG_MISSING", "视频模型配置已失效（被删除或不再启用）", stage="config"))
            return
        if not task_id:
            # 有任务号才有资格查询；没号说明上次提交结果不明，交给人工核实，禁止自动重提
            _fail(db, job, VideoPipelineError(
                "SUBMIT_UNKNOWN", "上次提交未记录供应商任务号（可能在回写前中断）",
                stage="submit"))
            return
        request = prov.plan_request(snap.get("prompt") or "", snap.get("meta") or {})
        # 业务期限：超过后转「待核实」而不是判失败 —— 供应商可能仍在渲染，保留任务号可续查
        deadline_sec = float((getattr(prov, "params", {}) or {}).get("job_deadline_sec")
                             or max(request["poll_timeout"] * 2, 300))
        waited = (_now() - (_n(job.created_at) or _now())).total_seconds()
        if waited > deadline_sec:
            _fail(db, job, VideoPipelineError(
                "POLL_TIMEOUT",
                f"已等待 {int(waited)} 秒仍未出片（task_id={task_id}），厂商侧可能仍在渲染",
                stage="provider_pending", task_id=task_id, evidence=job.evidence_json or {}))
            return
        try:
            r = await prov.poll_job(task_id, request, evidence)
        except VideoPipelineError as e:
            _fail(db, job, e)
            return
        job.evidence_json = r.get("evidence") or evidence
        job.last_provider_status = (r.get("status") or "")[:40] or job.last_provider_status
        if r["state"] == "succeeded":
            job.result_json = {"media": r.get("media") or {}}
            job.stage, job.status = "downloading", "running"
            job.next_poll_at = _now()
        elif r["state"] == "failed":
            _fail(db, job, VideoPipelineError(
                "PROVIDER_REJECTED",
                f"厂商回报任务失败（{r.get('status')}）：{r.get('message') or ''}",
                stage="provider_pending", task_id=task_id, evidence=job.evidence_json))
            return
        else:
            interval = min(request["poll_interval"] * max(1, int(job.attempts or 1)) ** 0.35,
                           MAX_POLL_INTERVAL)
            job.next_poll_at = _now() + timedelta(seconds=interval)
            if r["state"] == "unreachable":
                job.last_provider_status = ("查询失败：" + (r.get("reason") or ""))[:40]
        job.updated_at = _now()
        db.commit()
        return

    if stage in ("downloading", "validating"):
        media = ((job.result_json or {}).get("media") or {})
        filename = snap.get("filename") or f"cw_video_{uuid.uuid4().hex[:8]}.mp4"
        job.stage = "downloading"
        db.commit()
        try:
            saved = await save_video_media(media.get("url") or "", media.get("b64") or "",
                                           filename, evidence)
        except VideoPipelineError as e:
            _fail(db, job, e)
            return
        except Exception as e:
            _fail(db, job, VideoPipelineError(
                "STORAGE_FAILED", f"成片落盘异常：{type(e).__name__}: {e}", stage="downloading"))
            return
        job.stage = "validating"
        asset = _archive(db, job, saved, snap)
        job.asset_ids = [asset.asset_id]
        job.status, job.finished_at = "succeeded", _now()
        job.error_code = job.error_stage = job.error_message = job.error_action = ""
        job.result_json = {
            "media": media,
            "assets": [{"asset_id": asset.asset_id, "url": f"/files/{asset.file}",
                        "caption": snap.get("product") or "", "kind": "video",
                        "duration_sec": saved.get("duration_sec") or 0,
                        "duration_source": saved.get("duration_source") or ""}],
            "duration_sec": saved.get("duration_sec") or 0,
            "duration_source": saved.get("duration_source") or "",
            "note": _duration_note(snap, saved),
        }
        job.evidence_json = saved.get("evidence") or evidence
        job.updated_at = _now()
        _recount(db, _batch_of(db, job), commit=True)
        return


def _duration_note(snap: dict, saved: dict) -> str:
    planned = int(snap.get("duration") or 0)
    actual = float(saved.get("duration_sec") or 0)
    if planned and actual and abs(actual - planned) >= 1.0:
        return f"⚠️ 实测成片时长 {actual:.1f}s，与所选 {planned}s 不一致（厂商按自身模板输出）。"
    return ""


def _archive(db: Session, job: GenerationJob, saved: dict, snap: dict) -> CreativeAsset:
    file = os.path.basename(saved.get("file_path") or "")
    asset = CreativeAsset(
        asset_id=_uid("asset_"), job_id=job.job_id, history_id=None,
        owner_id=job.owner_id, file=file, size="video",
        placement=str(snap.get("aspect") or ""), concept_id=job.batch_id or "",
        spec_version="video/v1", status="ok",
        meta_json={"kind": "video", "bytes": saved.get("file_bytes"),
                   "duration_sec": saved.get("duration_sec"),
                   "duration_source": saved.get("duration_source")},
        created_at=_now(),
    )
    db.add(asset)
    db.flush()
    return asset


def _provider(db: Session, job: GenerationJob):
    from models import ModelConfig
    cfg = None
    if job.provider_config_id:
        cfg = db.query(ModelConfig).filter_by(id=job.provider_config_id).first()
    if cfg is None:
        cfg = _video_config(db)
    return video_provider_of_config(cfg)


def _batch_of(db: Session, job: GenerationJob) -> CreativeBatch:
    batch = db.query(CreativeBatch).filter_by(batch_id=job.batch_id).first()
    if batch is None:
        batch = CreativeBatch(batch_id=job.batch_id or _uid("cb_"), owner_id=job.owner_id,
                              status="queued", created_at=_now(), updated_at=_now())
        db.add(batch)
        db.flush()
    return batch


def _fail(db: Session, job: GenerationJob, err: VideoPipelineError) -> None:
    """失败落库：区分「可续查的待核实」与「真失败」，两者都能给出唯一动作。"""
    job.error_code = err.error_code
    job.error_stage = err.stage or job.stage or ""
    job.error_message = (err.message or "")[:2000]
    job.error_action = err.action or ""
    if err.task_id:
        job.provider_task_id = err.task_id[:200]
    job.evidence_json = err.evidence or job.evidence_json
    code = err.error_code or ""
    if code in NEEDS_ATTENTION_CODES:
        job.status = "needs_attention"
    else:
        job.status = "failed"
    job.stage = job.error_stage or job.stage
    job.next_poll_at = None
    job.finished_at = _now()
    job.updated_at = _now()
    _recount(db, _batch_of(db, job), commit=True)


# ============================ worker ============================
async def tick() -> int:
    ids = _claim()
    if not ids:
        return 0
    await asyncio.gather(*[run_one(j) for j in ids], return_exceptions=True)
    return len(ids)


async def _loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:
            print(f"[creative-tasks] worker tick 异常：{type(e).__name__}: {e}")
        await asyncio.sleep(WORKER_TICK)


def recover() -> int:
    """启动恢复：租约过期的 running 任务重新排队；有任务号的续查，没有的进待核实。"""
    db = SessionLocal()
    n = 0
    try:
        now = _now()
        for job in (db.query(GenerationJob)
                    .filter(GenerationJob.kind == "video",
                            GenerationJob.status == "running",
                            GenerationJob.lease_until.isnot(None),
                            GenerationJob.lease_until < now).all()):
            if job.stage == "submitting" and not job.provider_task_id:
                _fail(db, job, VideoPipelineError(
                    "SUBMIT_UNKNOWN",
                    "服务在提交回写前中断，无法确认供应商是否已受理（避免重复收费已停止自动重试）",
                    stage="submit"))
            else:
                job.status = "queued"
                job.lease_until = None
                job.next_poll_at = now
                job.updated_at = now
            n += 1
        db.commit()
    finally:
        db.close()
    return n


def start_worker() -> None:
    global _WORKER
    if _WORKER and not _WORKER.done():
        return
    n = recover()
    if n:
        print(f"[creative-tasks] 恢复 {n} 个中断的视频任务（有任务号的续查，结果不明的待核实）")
    _WORKER = asyncio.create_task(_loop())
    print(f"[creative-tasks] worker 已启动（并发上限 {VIDEO_CONCURRENCY}/配置，tick {WORKER_TICK}s）")


def stop_worker() -> None:
    global _WORKER
    if _WORKER and not _WORKER.done():
        _WORKER.cancel()
    _WORKER = None
