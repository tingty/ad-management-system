# -*- coding: utf-8 -*-
"""V4.145 / V4.146 · 模仿创作视频。

V4.145：任务事实视图（只读列出 imitate_video 任务，owner 隔离）。
V4.146：源视频获取 —— 直链服务端代下载（SSRF 逐跳校验 + 200MB 流式落盘）+ 本地上传
复用 + ffmpeg 元数据（画幅/分辨率/帧率/音轨）+ 原片预览 + 任务创建（登记源视频快照）。

★ 费用红线：本模块绝不调用大模型、绝不提交视频生成。新建任务只写 GenerationJob
（kind='imitate_video'、stage='source_acquiring'、provider_config_id=None、
next_poll_at=None），worker 不会进入 submitting 分支。分析/创作/出片由 V4.147–V4.149 交付。

任务事实唯一来源：generation_jobs（kind='imitate_video'），复用 creative_tasks 租约
worker；本模块不维护任何进程内任务字典。
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import uuid

from sqlalchemy.orm import Session

from models import CreativeAssetSource, GenerationJob, User
from creative_tasks import VIDEO_KINDS

# 模仿创作视频在 generation_jobs.kind 中的取值
KIND = "imitate_video"
SOURCE_ACQUIRING = "source_acquiring"

# 落盘目录与静态前缀（与 routers.py / providers.py 同源）
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
FILES_PREFIX = "/files/"


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# 元数据：用 imageio-ffmpeg 自带的 ffmpeg 解析（容器无 ffprobe，不依赖系统安装）
# ---------------------------------------------------------------------------
def probe_source_video(path: str) -> dict:
    """解析源视频元数据：时长/分辨率/画幅比/帧率/音轨有无。

    只用 imageio_ffmpeg 提供的 ffmpeg 二进制（无需 ffprobe）：执行 ``ffmpeg -i``
    解析 stderr 的 Duration / Stream 行。拿不到的字段留空字符串，不猜测（规格 §11.3）。
    """
    out: dict = {
        "duration_sec": None, "width": None, "height": None,
        "aspect_ratio": "", "fps": "", "has_audio": False, "codec": "", "raw": "",
    }
    try:
        import subprocess
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run([exe, "-hide_banner", "-i", path],
                              capture_output=True, text=True, timeout=30)
        text = proc.stderr or ""
        out["raw"] = text[:2000]
    except Exception:
        return out
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        try:
            out["duration_sec"] = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                                   + float(m.group(3)))
        except (ValueError, TypeError):
            pass
    vline = ""
    for line in text.splitlines():
        if "Stream #" in line and "Video:" in line:
            vline = line
            break
    if vline:
        m = re.search(r"(\d{2,5})x(\d{2,5})", vline)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            out["width"], out["height"] = w, h
            g = math.gcd(w, h)
            if g:
                out["aspect_ratio"] = f"{w // g}:{h // g}"
        m = re.search(r"([\d.]+)\s*fps", vline)
        if m:
            out["fps"] = m.group(1)
        m = re.search(r"Video:\s*([A-Za-z0-9_-]+)", vline)
        if m:
            out["codec"] = m.group(1)
    out["has_audio"] = any("Stream #" in line and "Audio:" in line
                           for line in text.splitlines())
    return out


def file_sha256(path: str) -> str:
    """源视频 sha256（分块读，避免大文件一次性入内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 源视频登记（任务级快照写 GenerationJob.request_json；原件级复用 creative_asset_sources）
# ---------------------------------------------------------------------------
def _register_source(db: Session, user: User, *, path: str, source: str,
                     source_url: str, name: str, verdict: dict, meta: dict) -> dict:
    """把已落盘的源视频登记为 CreativeAssetSource（幂等：同 sha256 复用）。

    返回供 request_json / 预览使用的快照 dict。不改 /assets/upload-video 共享端点，
    避免影响现有素材库流程；登记失败不影响任务创建（降级为仅 request_json 快照）。
    """
    fname = os.path.basename(path)
    digest = ""
    try:
        digest = file_sha256(path)
    except Exception:
        pass
    snap = {
        "name": name or fname,
        "source": source,                       # url / upload
        "source_url": source_url or "",
        "file": FILES_PREFIX + fname,
        "file_path": path,
        "file_hash": digest,
        "container": verdict.get("container") or "",
        "bytes": verdict.get("bytes") or 0,
        "duration_sec": meta.get("duration_sec") or verdict.get("duration") or None,
        "width": meta.get("width") or verdict.get("width") or None,
        "height": meta.get("height") or verdict.get("height") or None,
        "aspect_ratio": meta.get("aspect_ratio") or "",
        "fps": meta.get("fps") or "",
        "has_audio": bool(meta.get("has_audio")),
        "codec": meta.get("codec") or "",
        "probe_available": bool(meta.get("duration_sec") or meta.get("width")),
    }
    # 只登记为「原件」，不参与素材库模板归并；同 hash 复用，避免重复落库。
    try:
        if digest and getattr(user, "id", None) is not None:
            existing = (db.query(CreativeAssetSource)
                        .filter(CreativeAssetSource.owner_id == user.id,
                                CreativeAssetSource.file_hash == digest)
                        .first())
            if not existing:
                db.add(CreativeAssetSource(
                    owner_id=user.id,
                    owner_name=getattr(user, "username", "") or "",
                    title=(name or fname)[:255],
                    source_type="url" if source == "url" else "video",
                    file=snap["file"],
                    source_url=(source_url or "")[:1024] or None,
                    media_kind="video",
                    width=snap["width"], height=snap["height"],
                    duration_sec=snap["duration_sec"],
                    file_hash=digest, status="imported",
                ))
                db.commit()
    except Exception:
        db.rollback()
    return snap


def create_task(db: Session, user: User, *, source_snapshot: dict,
                options: dict | None = None, rights_ack: bool = False) -> dict:
    """新建 imitate_video 任务：只写任务事实 + 源视频快照，不触发任何模型调用。

    费用安全：stage 停在 source_acquiring，provider_config_id / next_poll_at 均不设置，
    worker 不会领取（_claim 要求 next_poll_at 到期），更不会进入 submitting 分支。
    V4.147 把任务推进到分析阶段时才设置 next_poll_at。
    """
    opt = options or {}
    owner = getattr(user, "id", None)
    job_id = _uid("imv_")
    snap = dict(source_snapshot or {})
    req = {
        **snap,
        "name": snap.get("name") or "模仿创作视频",
        "rights_ack": bool(rights_ack),      # 权利声明留痕（规格 §11.2）
        "target_platform": (opt.get("target_platform") or "")[:64],
        "target_duration": opt.get("target_duration") or "",
        "structure_fidelity": (opt.get("structure_fidelity") or "medium")[:16],
        "language": (opt.get("language") or "")[:32],
    }
    job = GenerationJob(
        job_id=job_id,
        kind=KIND,
        status="queued",
        stage=SOURCE_ACQUIRING,
        owner_id=owner,
        owner_name=getattr(user, "username", "") or "",
        request_json=req,
        progress=0,
        attempts=0,
        # 明确不设 provider_config_id / provider_task_id / next_poll_at
    )
    db.add(job)
    db.commit()
    return {"job_id": job_id, "status": job.status, "stage": job.stage}


# ---------------------------------------------------------------------------
# 任务事实视图
# ---------------------------------------------------------------------------
def _task_view(j: GenerationJob) -> dict:
    req = j.request_json or {}
    res = j.result_json or {}
    return {
        "job_id": j.job_id,
        "name": req.get("name") or req.get("source_name") or "",
        "status": j.status or "",
        "stage": j.stage or "",
        "source": req.get("source") or req.get("source_url") or "",
        "source_url": req.get("source_url") or "",
        "source_file": req.get("file") or "",
        "aspect_ratio": req.get("aspect_ratio") or "",
        "duration_sec": req.get("duration_sec"),
        "rights_ack": bool(req.get("rights_ack")),
        "analysis_script_id": res.get("analysis_script_id") or "",
        "analysis_cached": bool(res.get("analysis_cached")),
        "error_message": j.error_message or "",
        "created_at": j.created_at.isoformat() if j.created_at else "",
    }


def list_tasks(db: Session, user: User) -> list[dict]:
    """列出当前账号的模仿创作视频任务（只读，按创建时间倒序，owner 隔离）。"""
    q = (db.query(GenerationJob)
         .filter(GenerationJob.kind == KIND)
         .order_by(GenerationJob.created_at.desc()))
    if getattr(user, "id", None) is not None:
        q = q.filter(GenerationJob.owner_id == user.id)
    return [_task_view(j) for j in q.limit(200).all()]


def get_task(db: Session, user: User, job_id: str) -> GenerationJob | None:
    """owner 隔离取单个 imitate_video 任务（找不到返回 None，调用层翻 404）。"""
    q = db.query(GenerationJob).filter(GenerationJob.job_id == job_id,
                                       GenerationJob.kind == KIND)
    if getattr(user, "id", None) is not None:
        q = q.filter(GenerationJob.owner_id == user.id)
    return q.first()


def worker_kinds() -> tuple[str, ...]:
    """暴露给测试 / 运维：worker 当前接管的视频类 kind 集合。"""
    return VIDEO_KINDS
