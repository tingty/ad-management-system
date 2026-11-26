# -*- coding: utf-8 -*-
"""V4.145 · 模仿创作视频（骨架，不产生费用）。

职责：为「模仿创作视频」一级模块提供任务事实视图。本版只读列出生效的
imitate_video 任务（owner 隔离），不创建任务、不调用大模型、不提交视频生成。
源视频获取 / 分析脚本 / 创作脚本 / 出片依次由 V4.146–V4.149 交付。

任务事实唯一来源：generation_jobs（kind='imitate_video'），复用 creative_tasks
租约 worker；本模块不维护任何进程内任务字典。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from models import GenerationJob, User
from creative_tasks import VIDEO_KINDS

# 模仿创作视频在 generation_jobs.kind 中的取值
KIND = "imitate_video"


def list_tasks(db: Session, user: User) -> list[dict]:
    """列出当前账号的模仿创作视频任务（只读，按创建时间倒序）。

    owner 隔离口径与现有 creative_tasks 任务列表一致：按 owner_id 过滤。
    """
    q = (db.query(GenerationJob)
         .filter(GenerationJob.kind == KIND)
         .order_by(GenerationJob.created_at.desc()))
    if getattr(user, "id", None) is not None:
        q = q.filter(GenerationJob.owner_id == user.id)
    rows = q.limit(200).all()
    out = []
    for j in rows:
        req = j.request_json or {}
        out.append({
            "job_id": j.job_id,
            "name": req.get("name") or req.get("source_name") or "",
            "status": j.status or "",
            "stage": j.stage or "",
            "source": req.get("source") or req.get("source_url") or "",
            "created_at": j.created_at.isoformat() if j.created_at else "",
        })
    return out


def worker_kinds() -> tuple[str, ...]:
    """暴露给测试 / 运维：worker 当前接管的视频类 kind 集合。"""
    return VIDEO_KINDS
