"""V4.46 / D5：自动创作的持久计划服务（编排 + 版本冻结 + 质检 + 归档）。

文档要求（D5「服务端编排」）：
- 多阶段持久任务：created → analyzing → needs_input / recommendation_ready →
  platform_confirmed → planning → generating → validating → succeeded / partial_success / failed / canceled；
- 子任务预登记、持久计划与恢复、按工作区隔离幂等键 + 规范化 payload_hash（同键不同内容 409）；
- 超过执行限制拆子批、不截断；取消后停止派发新子任务，并对已完成项归档，不暗示立即停已计费调用；
- 质检与归档：供应商失败得到的纯背景模板 → draft / needs_revision，不计合格商品图（A15）；
  打包 manifest 含 media / concept / role / 缺失报告（A20）。

设计：不另造生成系统。计划只持有「分析 / 推荐 / 覆盖 / 确认令牌 / 关联任务 / 归档 manifest」，
真正的出图仍通过既有 `GenerationJob` 执行；本模块负责把分散的任务结果汇总、质检与归档。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid

from sqlalchemy.orm import Session

from models import CreationPlan, GenerationJob, utcnow
from creation_planner import build_recommendation
from media_coverage import build_coverage_plan, merge_manifest
from media_platforms import validate_platform, MediaRuleError, SPEC_VERIFIED_ON


def _uid(prefix: str = "plan_") -> str:
    return prefix + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# 纯逻辑（可独立单测，不依赖数据库 / 模型）
# ---------------------------------------------------------------------------
def build_plan_doc(analysis: dict, platforms: list[str], workspace_defaults: dict | None = None) -> dict:
    """D2 + D4：组合「确定性策划」与「全覆盖计划」为一份计划文档（执行前）。"""
    rec = build_recommendation(analysis, platforms, workspace_defaults=workspace_defaults or {})
    coverage = build_coverage_plan(rec, platforms, rec.get("structured_concepts"), rec.get("workspace_defaults"))
    return {
        "recommendation": rec,
        "coverage": coverage,
        "plan_id": rec.get("plan_id"),
        "plan_version": rec.get("plan_version"),
        "status": rec.get("status"),
        "delivery_grade": rec.get("delivery_grade"),
        "spec_verified": bool(SPEC_VERIFIED_ON),
    }


def qa_generation_result(result: dict, plan_doc: dict) -> dict:
    """D5 / A15：对生成结果做逐图质检。

    供应商失败（task_results.status=failed）且图像为空、或图像被标记为纯渐变模板的，
    一律计 draft / needs_revision，不得当作合格商品图。返回质检结论与可交付裁决。
    """
    result = result if isinstance(result, dict) else {}
    plan_doc = plan_doc if isinstance(plan_doc, dict) else {}
    findings: list[dict] = []
    images = result.get("images") or []
    task_results = result.get("task_results") or []

    passed = 0
    needs_revision = 0
    failed = 0
    for tr in task_results:
        if not isinstance(tr, dict):
            continue
        st = tr.get("status")
        idx = tr.get("task_index")
        if st == "ok":
            passed += 1
        elif st == "failed":
            failed += 1
            findings.append({
                "task_index": idx, "status": "needs_revision",
                "reason": "供应商生成失败：纯背景 / 无主体，不计合格商品图（A15）",
            })
        elif st == "needs_revision":
            needs_revision += 1
            findings.append({"task_index": idx, "status": "needs_revision",
                             "reason": tr.get("reason") or "未通过逐图质检"})

    # 兜底：图像自身带 status=draft / needs_revision 标记（由生成链路标注）
    for im in images:
        if isinstance(im, dict) and im.get("status") in ("draft", "needs_revision"):
            findings.append({
                "task_index": im.get("task_index"),
                "status": im["status"],
                "reason": "图像被标注为草案 / 需返修（如纯渐变模板、过小不可读文案、商品外观不一致）",
            })

    required = (plan_doc.get("coverage") or {}).get("report", {}).get("required") or len(images) or len(task_results)
    all_pass = (failed == 0 and needs_revision == 0 and len(images) > 0)
    # A14 / N03：规格未核验 / 缺商品图 → 即使图都生成了，也只能是草案，不能显示完整可交付。
    deliverable = all_pass and bool(SPEC_VERIFIED_ON) \
        and plan_doc.get("delivery_grade") != "draft"
    grade = "draft" if (not deliverable) else "standard"
    return {
        "passed": passed, "needs_revision": needs_revision, "failed": failed,
        "findings": findings,
        "required": required,
        "deliverable": deliverable,
        "delivery_grade": grade,
        "note": ("真实商品图不得由纯文生图自由重画；合成背景也须避免出现第二个虚构商品。"
                 if grade == "draft" else "全部必需图片通过质检且规则已核验，可显示完整可交付。"),
    }


def build_manifest(plan_doc: dict, job_results: list[dict]) -> dict:
    """D6 / A20：汇总多个生成任务结果为素材清单 manifest。"""
    coverage = (plan_doc or {}).get("coverage") or {}
    m = merge_manifest(coverage, job_results)
    qa = qa_generation_result(
        {"images": [im for jr in job_results for im in (jr.get("images") or [])],
         "task_results": [tr for jr in job_results for tr in (jr.get("task_results") or [])]},
        plan_doc)
    return {**m, "qa": qa, "spec_verified": bool(SPEC_VERIFIED_ON)}


# ---------------------------------------------------------------------------
# 状态机辅助
# ---------------------------------------------------------------------------
STAGES = ["created", "analyzing", "needs_input", "recommendation_ready",
          "platform_confirmed", "planning", "generating", "validating",
          "succeeded", "partial_success", "failed", "canceled"]
TERMINAL = {"succeeded", "partial_success", "failed", "canceled"}


def next_stage(current: str, event: str) -> str:
    """最小的合法状态转移；非法转移返回当前阶段（不静默前进）。"""
    table = {
        ("created", "analyze"): "analyzing",
        ("analyzing", "ok"): "recommendation_ready",
        ("analyzing", "blocked"): "needs_input",
        ("recommendation_ready", "confirm"): "platform_confirmed",
        ("platform_confirmed", "plan"): "planning",
        ("planning", "generate"): "generating",
        ("generating", "validate"): "validating",
        ("validating", "ok"): "succeeded",
        ("validating", "partial"): "partial_success",
        ("validating", "fail"): "failed",
    }
    nxt = table.get((current, event))
    return nxt if nxt else current


# ---------------------------------------------------------------------------
# DB CRUD（持久计划）
# ---------------------------------------------------------------------------
def create_plan(db: Session, analysis: dict, platforms: list[str],
                workspace_defaults: dict | None, user) -> CreationPlan:
    """D5：创建持久计划，落库分析 / 推荐 / 覆盖快照，返回 CreationPlan 行。"""
    plats = [str(x).strip() for x in (platforms or []) if str(x or "").strip()][:8]
    try:
        for p in plats:
            validate_platform(p)
    except MediaRuleError as e:
        raise e
    doc = build_plan_doc(analysis, plats, workspace_defaults)
    rec = doc["recommendation"]
    # 幂等：plan_id 由分析 + 平台 + 默认值确定性派生，相同输入应返回同一计划，
    # 避免重复提交命中唯一约束（前端重试 / 刷新后重新确认）。
    plan_id = doc["plan_id"] or _uid()
    existing = db.query(CreationPlan).filter_by(plan_id=plan_id).first()
    if existing:
        existing.updated_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    plan = CreationPlan(
        plan_id=plan_id,
        plan_version=doc["plan_version"] or "pv1",
        mode="auto", stage="recommendation_ready" if rec.get("status") != "needs_input" else "needs_input",
        status=rec.get("status", "draft"),
        analysis_json=analysis,
        recommendation_json=rec,
        coverage_json=doc["coverage"],
        owner_id=getattr(user, "id", None),
        owner_name=(getattr(user, "display_name", None) or getattr(user, "username", "") or ""),
        job_ids=[],
        created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def set_coverage(db: Session, plan_id: str, platforms: list[str], user) -> CreationPlan:
    """D4 / A11：用户确认平台后重算覆盖计划（只按已选范围）。"""
    plan = db.query(CreationPlan).filter_by(plan_id=plan_id).first()
    if not plan:
        raise KeyError("plan_not_found")
    plats = [str(x).strip() for x in (platforms or []) if str(x or "").strip()][:8]
    for p in plats:
        validate_platform(p)
    doc = build_plan_doc(plan.analysis_json or {}, plats, (plan.recommendation_json or {}).get("workspace_defaults"))
    plan.coverage_json = doc["coverage"]
    plan.updated_at = utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def confirm_plan(db: Session, plan_id: str, fee_authorized_usd: float, user) -> CreationPlan:
    """D5 / A13 / A14：冻结版本、范围与费用授权，生成 approval_token。

    确认后，任何产品事实 / 目标地区变化都会使下游推荐、提示词、覆盖与确认令牌失效
    （前端通过 plan_version 比对实现）；本次把费用授权写入计划，作为出图上限依据。
    """
    plan = db.query(CreationPlan).filter_by(plan_id=plan_id).first()
    if not plan:
        raise KeyError("plan_not_found")
    if plan.stage in TERMINAL:
        raise ValueError("计划已结束，不能再次确认")
    coverage = plan.coverage_json or {}
    cost_upper = (coverage.get("cost_estimate") or {}).get("cost_upper_usd") or 0
    if fee_authorized_usd <= 0:
        raise ValueError("未授权费用上限，不能确认生成（A14）")
    if cost_upper > 0 and fee_authorized_usd < cost_upper:
        raise ValueError(f"费用授权 {fee_authorized_usd} 低于预计成本上界 {cost_upper}（A14：不隐瞒缺口）")
    token = secrets.token_hex(16)
    plan.approval_token = token
    plan.fee_authorized = True
    plan.stage = "platform_confirmed"
    plan.plan_version = (plan.recommendation_json or {}).get("plan_version") or plan.plan_version
    plan.updated_at = utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def attach_job(db: Session, plan_id: str, job_id: str) -> CreationPlan:
    plan = db.query(CreationPlan).filter_by(plan_id=plan_id).first()
    if not plan:
        raise KeyError("plan_not_found")
    jobs = list(plan.job_ids or [])
    if job_id not in jobs:
        jobs.append(job_id)
    plan.job_ids = jobs
    plan.stage = "generating"
    plan.updated_at = utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def finalize(db: Session, plan_id: str, job_results: list[dict]) -> CreationPlan:
    """D5 / D6：汇总任务结果 → 质检 → 归档 manifest；更新阶段与状态。"""
    plan = db.query(CreationPlan).filter_by(plan_id=plan_id).first()
    if not plan:
        raise KeyError("plan_not_found")
    doc = {"recommendation": plan.recommendation_json, "coverage": plan.coverage_json,
           "delivery_grade": (plan.recommendation_json or {}).get("delivery_grade", "draft")}
    manifest = build_manifest(doc, job_results)
    plan.manifest_json = manifest
    plan.stage = "validating"
    if manifest.get("qa", {}).get("deliverable"):
        plan.status = "succeeded" if manifest.get("complete") else "partial_success"
    else:
        plan.status = "partial_success" if manifest.get("item_count") else "failed"
    plan.updated_at = utcnow()
    db.commit()
    db.refresh(plan)
    return plan


def get_plan(db: Session, plan_id: str) -> CreationPlan | None:
    return db.query(CreationPlan).filter_by(plan_id=plan_id).first()


def validate_plan_reference(db: Session, plan_id: str | None, plan_version: str | None,
                           analysis_snapshot_id: str) -> CreationPlan:
    """D5：校验生成请求携带的计划引用，拒绝改写事实绕过计划。

    - plan 必须存在且已确认（有 approval_token）；
    - 给定 plan_version 与冻结版本不一致 → 409（A13 下游失效）；
    - 请求的分析原文 snapshot_id 与计划不一致 → 422（禁止改写事实绕过计划）。
    返回已验证的计划行。
    """
    if not plan_id:
        raise ValueError("plan_id_required")
    plan = get_plan(db, plan_id)
    if not plan:
        raise KeyError("plan_not_found")
    if plan_version and plan.plan_version and plan_version != plan.plan_version:
        raise ValueError("plan_version_mismatch")
    if not plan.approval_token:
        raise ValueError("plan_not_confirmed")
    base_snap = (plan.analysis_json or {}).get("evidence_snapshot_id") or ""
    if base_snap and analysis_snapshot_id and base_snap != analysis_snapshot_id:
        raise ValueError("fact_rewrite_blocked")
    return plan



def plan_to_dict(plan: CreationPlan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "mode": plan.mode,
        "stage": plan.stage,
        "status": plan.status,
        "recommendation": plan.recommendation_json,
        "coverage": plan.coverage_json,
        "approval_token": plan.approval_token,
        "fee_authorized": bool(plan.fee_authorized),
        "job_ids": plan.job_ids or [],
        "manifest": plan.manifest_json,
        "owner_id": plan.owner_id,
        "owner_name": plan.owner_name or "",
        "history_id": plan.history_id,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
