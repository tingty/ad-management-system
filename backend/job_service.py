"""V4.42 / F12：服务端持久生成任务、幂等、分项重试与自动归档。

说明书 F12 的原始问题：状态只在浏览器内存 / localStorage，生成接口是等待结果的长请求，
图片完成后还要浏览器另发请求归档；刷新或关闭页面就无法恢复；历史追加 `uniq[-80:]`
静默截掉早期素材引用。

本模块把「生成 + 归档」整体搬到服务端：

- `create_job()`：立即落库并返回 `job_id`；同一个 `idempotency_key` 只创建一个任务；
- `spawn_job()`：用 `asyncio.create_task` 在后台执行，申请方 HTTP 请求已返回，
  浏览器断开 / 刷新不影响任务；
- `run_job()`：独立 `SessionLocal()`，串起规则校验 → `generate_media_images` →
  写 `CreativeAsset` 不可变记录 → 更新历史会话（展示缓存）→ 定稿状态；
- `retry_failed()`：只用失败子任务重建请求，成功项不重复调用模型、不重复归档；
- `list_assets()`：按 `history_id` / `job_id` 分页查询，**超过 80 张仍可读到早期素材**。

事实边界：任务状态与资产记录持久化在数据库，但进程被强制杀死时正在运行的内存任务
不会自动续跑（记录会停在 `running`，由启动时 `recover_interrupted()` 标为 `failed` 并写明原因）；
这里不宣称跨进程队列或分布式事务。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import SessionLocal
from models import GenerationJob, CreativeAsset, CreationHistory, utcnow
from schemas import MediaImageRequest
from media_platforms import (validate_task_matrix, MediaRuleError, SPEC_VERSION)
from industry_profiles import resolve_profile
from media_ad import generate_media_images
from creation_history import history_to_dict

TERMINAL = {"succeeded", "partial_success", "failed", "canceled"}
DISPLAY_CACHE_LIMIT = 80       # images_json 只是展示缓存，完整资产在 creative_assets
_RUNNING: dict[str, asyncio.Task] = {}


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


def job_to_dict(job: GenerationJob, include_result: bool = True) -> dict:
    def _iso(v):
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)
    out = {
        "job_id": job.job_id,
        "idempotency_key": job.idempotency_key,
        "kind": job.kind,
        "status": job.status,
        "owner_id": job.owner_id,
        "owner_name": job.owner_name or "",
        "history_id": job.history_id,
        "retry_of": job.retry_of,
        "progress": int(job.progress or 0),
        "attempts": int(job.attempts or 0),
        "cancel_requested": bool(job.cancel_requested),
        "error": job.error or "",
        "result": job.result_json if include_result else None,
        "subtasks": job.subtasks_json or [],
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "finished_at": _iso(job.finished_at),
        "terminal": job.status in TERMINAL,
    }
    return out


def asset_to_dict(a: CreativeAsset) -> dict:
    return {
        "asset_id": a.asset_id, "job_id": a.job_id, "history_id": a.history_id,
        "file": a.file, "url": f"/files/{a.file}",
        "size": a.size or "", "placement": a.placement or "",
        "concept_id": a.concept_id or "", "spec_version": a.spec_version or "",
        "status": a.status, "meta": a.meta_json or {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def create_job(db: Session, payload: dict, user, *,
               idempotency_key: str = "", kind: str = "images") -> tuple[GenerationJob, bool]:
    """幂等创建：同 key 返回已有任务（created=False），绝不重复出图 / 归档。"""
    key = (idempotency_key or "").strip()[:200]
    if key:
        old = db.query(GenerationJob).filter_by(idempotency_key=key).first()
        if old:
            return old, False
    req = payload.get("images_request") if isinstance(payload.get("images_request"), dict) else payload
    # 入参在进入后台任务之前就按 Pydantic 校验一遍，避免把坏请求排进队列
    parsed = MediaImageRequest(**req)
    archive = payload.get("archive") if isinstance(payload.get("archive"), dict) else {}
    hid = archive.get("history_id")
    job = GenerationJob(
        job_id=_uid("job_"),
        idempotency_key=key or _uid("idem_"),
        kind=kind, status="queued",
        owner_id=getattr(user, "id", None),
        owner_name=(getattr(user, "display_name", None) or getattr(user, "username", "") or ""),
        history_id=hid if isinstance(hid, int) else None,
        request_json={"images_request": parsed.model_dump(), "archive": archive},
        subtasks_json=[], progress=0, attempts=0,
        created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job, True


def spawn_job(job_id: str) -> None:
    """把任务挂到当前事件循环；保存引用避免被 GC 中途回收。"""
    if job_id in _RUNNING and not _RUNNING[job_id].done():
        return
    task = asyncio.create_task(run_job(job_id))
    _RUNNING[job_id] = task
    task.add_done_callback(lambda _t, jid=job_id: _RUNNING.pop(jid, None))


def recover_interrupted() -> int:
    """进程重启后把停在 running / queued 的任务标为失败，不假装它还在跑。"""
    db = SessionLocal()
    try:
        rows = db.query(GenerationJob).filter(GenerationJob.status.in_(["running", "queued"])).all()
        for r in rows:
            r.status = "failed"
            r.error = "服务进程在任务执行期间重启；该任务未自动续跑，请用分项重试重新提交失败项"
            r.finished_at = utcnow()
            r.updated_at = utcnow()
        db.commit()
        return len(rows)
    finally:
        db.close()


async def _set_status(job_id: str, **fields) -> None:
    def _work():
        db = SessionLocal()
        try:
            row = db.query(GenerationJob).filter_by(job_id=job_id).first()
            if not row:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = utcnow()
            db.commit()
        finally:
            db.close()
    await asyncio.to_thread(_work)


def _is_canceled(job_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.query(GenerationJob).filter_by(job_id=job_id).first()
        return bool(row and row.cancel_requested)
    finally:
        db.close()


def archive_result(db: Session, job: GenerationJob, result: dict) -> dict:
    """服务端归档：逐张写不可变资产记录 + 更新历史会话展示缓存。

    浏览器不再参与归档，因此「生成完但页面已关闭」不会丢素材。
    """
    archived, duplicates, errors = [], [], []
    for im in (result.get("images") or []):
        if not isinstance(im, dict):
            continue
        fn = str(im.get("file") or "").strip()
        if not fn:
            continue
        exists = db.query(CreativeAsset).filter_by(file=fn).first()
        if exists:
            duplicates.append(fn)
            continue
        try:
            db.add(CreativeAsset(
                asset_id=_uid("asset_"), job_id=job.job_id,
                history_id=job.history_id, owner_id=job.owner_id,
                file=fn, size=str(im.get("size") or ""),
                placement=str(im.get("placement") or ""),
                concept_id=str(im.get("concept_id") or ""),
                spec_version=str(im.get("spec_version") or SPEC_VERSION),
                status=str(im.get("status") or "ok"),
                meta_json=im, created_at=utcnow(),
            ))
            archived.append(fn)
        except Exception as e:
            errors.append(f"{fn}: {type(e).__name__}")

    history_update = {}
    if job.history_id:
        row = db.query(CreationHistory).filter_by(id=job.history_id).first()
        if row:
            req = job.request_json or {}
            arch = (req.get("archive") or {})
            old = row.images_json if isinstance(row.images_json, list) else []
            fresh = [{**im, "url": im.get("file")} for im in (result.get("images") or [])
                     if isinstance(im, dict)]
            merged, seen = [], set()
            for im in list(old) + fresh:
                key = str(im.get("file") or im.get("url") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                item = dict(im)
                item["file"] = str(item.get("file") or item.get("url") or "").split("/")[-1]
                merged.append(item)
            if "copy" in arch:
                row.copy_json = arch["copy"]
                row.has_copy = bool(arch["copy"])
            if "style_opts" in arch or result.get("creative_config"):
                # F04 配置快照在服务端生成后才产生，这里补进历史，保证「当时实际生效」
                # 的配置与逐图一致，且不被后续预设修改覆盖。
                so = dict(arch.get("style_opts") or {})
                if result.get("creative_config"):
                    so["creative_config"] = result["creative_config"]
                row.style_opts_json = so
            if "platform" in arch:
                row.platform = str(arch["platform"] or "")
            if "lang" in arch:
                row.lang = str(arch["lang"] or "")
            row.image_model_json = result.get("image_model") or None
            row.note = str(result.get("note") or "")
            # images_json 只是最近 80 张的展示缓存；完整不可变记录在 creative_assets
            row.images_json = merged[-DISPLAY_CACHE_LIMIT:]
            row.image_count = len(merged)
            row.updated_at = utcnow()
            history_update = {"history_id": row.id, "total_assets": len(merged),
                              "display_cache": len(row.images_json)}
    db.commit()
    return {"archived": archived, "duplicates": duplicates, "errors": errors,
            "history_update": history_update,
            "retention_policy": ("CreativeAsset 为不可变记录，不自动删除、不截断；"
                                 "images_json 仅为最近 80 张展示缓存，完整清单按 history_id 分页查询")}


async def run_job(job_id: str) -> None:
    """后台执行：规则校验 → 生成 → 服务端归档 → 定稿。任何异常都落库为 failed。"""
    await _set_status(job_id, status="running", progress=5)
    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter_by(job_id=job_id).first()
        if not job:
            return
        if job.cancel_requested:
            await _set_status(job_id, status="canceled", progress=100,
                              error="任务在开始前已取消", finished_at=utcnow())
            return
        req = job.request_json or {}
        parsed = MediaImageRequest(**(req.get("images_request") or {}))
        slots = [s.model_dump() for s in parsed.slots]
        variants = [v.model_dump() for v in parsed.copy_variants]
        analysis = parsed.analysis.model_dump()
        profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
        try:
            checked = validate_task_matrix(
                parsed.platform, slots, total_pixels=parsed.total_pixels,
                variant_count=len(variants), profile=profile)
        except MediaRuleError as e:
            await _set_status(job_id, status="failed", progress=100,
                              error="媒体规则校验未通过：" + "；".join(e.errors),
                              finished_at=utcnow())
            return
        if parsed.spec_version and parsed.spec_version != SPEC_VERSION:
            await _set_status(job_id, status="failed", progress=100,
                              error=f"媒体规则版本不一致：客户端 {parsed.spec_version}，服务端 {SPEC_VERSION}",
                              finished_at=utcnow())
            return
        if await asyncio.to_thread(_is_canceled, job_id):
            await _set_status(job_id, status="canceled", progress=100,
                              error="任务在调用模型前已取消", finished_at=utcnow())
            return
        await _set_status(job_id, progress=20, attempts=GenerationJob.attempts + 1)
        result = await generate_media_images(
            db, analysis, checked["meta"]["platform"], parsed.lang,
            parsed.copy_fields, parsed.style_opts, checked["slots"],
            parsed.logo or "", copy_variants=variants, rules_meta=checked["meta"])
        canceled = await asyncio.to_thread(_is_canceled, job_id)
        # 每张图带上任务 ID，归档 / 导出可回溯到具体服务端任务
        for im in (result.get("images") or []):
            if isinstance(im, dict):
                im["job_id"] = job_id
        archive = archive_result(db, job, result)
        result = {**result, "job_id": job_id, "archive": archive}
        status = ("canceled" if canceled else
                  "failed" if result.get("status") == "failed" else
                  "partial_success" if result.get("status") == "partial_success" else
                  "succeeded")
        subtasks = result.get("task_results") or []
        await _set_status(
            job_id, status=status, progress=100, result_json=result,
            subtasks_json=subtasks,
            error=("任务已取消；已生成部分仍完成归档，不丢素材" if canceled else ""),
            finished_at=utcnow())
    except Exception as e:
        await _set_status(job_id, status="failed", progress=100,
                          error=f"{type(e).__name__}: {str(e)[:300]}",
                          finished_at=utcnow())
    finally:
        db.close()


def cancel_job(db: Session, job: GenerationJob) -> dict:
    """取消：终态任务不可取消；运行中的任务在检查点停止，状态真实可见。"""
    if job.status in TERMINAL:
        return {"ok": False, "job_id": job.job_id, "status": job.status,
                "message": "任务已结束，无需取消"}
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "canceled"
        job.error = "任务在排队时已取消"
        job.finished_at = utcnow()
    job.updated_at = utcnow()
    db.commit()
    return {"ok": True, "job_id": job.job_id, "status": job.status,
            "message": "已请求取消；运行中的任务会在检查点停止并保留已生成素材"}


def retry_failed(db: Session, origin: GenerationJob, user) -> tuple[GenerationJob | None, str]:
    """仅重试 `status=failed` 的子任务；成功项不重复调用模型、不重复归档。"""
    if origin.status not in TERMINAL:
        return None, "原任务尚未结束，暂不能重试"
    results = origin.result_json or {}
    failed = [x for x in (results.get("task_results") or [])
              if isinstance(x, dict) and x.get("status") == "failed"]
    if not failed:
        return None, "原任务没有可重试的失败项（needs_revision 需先人工修改文案）"
    req = (origin.request_json or {}).get("images_request") or {}
    slots = list(req.get("slots") or [])
    picked, used = [], set()
    for f in failed:
        ti = f.get("task_index")
        if isinstance(ti, int) and 0 <= ti < len(slots) and ti not in used:
            used.add(ti)
            picked.append(slots[ti])
    if not picked:
        return None, "无法把失败项匹配回原任务矩阵，已阻止整批重跑（避免重复收费）"
    new_req = {**req, "slots": picked, "total_pixels": None}
    archive = (origin.request_json or {}).get("archive") or {}
    n = db.query(GenerationJob).filter_by(retry_of=origin.job_id).count() + 1
    payload = {"images_request": new_req, "archive": archive}
    job, created = create_job(db, payload, user,
                              idempotency_key=f"{origin.job_id}:retry:{n}")
    if created:
        job.retry_of = origin.job_id
        db.commit()
        db.refresh(job)
    return job, f"已按 {len(picked)} 个失败项创建重试任务（成功项不重复生成）"


def list_assets(db: Session, *, history_id: int | None = None,
                job_id: str = "", limit: int = 50, offset: int = 0) -> dict:
    """分页读取不可变资产；T16 要求超过 80 张仍能查到早期素材。"""
    q = db.query(CreativeAsset)
    if history_id is not None:
        q = q.filter(CreativeAsset.history_id == history_id)
    if job_id:
        q = q.filter(CreativeAsset.job_id == job_id)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    total = q.count()
    rows = q.order_by(CreativeAsset.id.asc()).offset(off).limit(lim).all()
    return {"items": [asset_to_dict(r) for r in rows], "total": total,
            "limit": lim, "offset": off,
            "retention_policy": "不可变记录，不自动截断；删除历史记录时按显式策略同步清理"}
