"""V4.46 / D4：主要媒体图片全覆盖计划（MediaCoveragePlan）+ 成本上界。

文档要求（D4「媒体与提示词」）：
- 「全规则图片」= 所选平台 + 广告产品 + 目标国家 / 系统下，规则目录已核验且该产品适用的
  **全部主要图片资产角色**，不是把各平台历史上所有尺寸穷举；
- required_tasks = selected_platforms × applicable_asset_roles × required_sizes × concept_strategy；
- 默认至少一个推荐概念覆盖全部主要图片角色；第二概念也完整适配其选定范围，
  不能用「轮换」伪装为每概念全覆盖；
- 超过单批 24 任务 / 40MP **拆为多个子批**，保持父计划完整，**不截断版位**；
- 预算不足时先缩减额外概念，再提示无法完成，不隐瞒缺口；
- 确认区展示总任务、预计模型调用、预计成本或上界、范围及未知项。

明确边界（文档 A11 / A12 / A14 / D4）：
- 只按**已选平台**生成覆盖，规则按广告产品区分（不把 Google RSA 混进 UAC）；
- 内部目录 `SPEC_VERIFIED_ON` 仍为空，覆盖报告明确标注「内部目录，投放前须官方核验」；
- 成本只是**上界估算**，不声称真实计费；预算上限由工作区默认值给出。
"""
from __future__ import annotations

import hashlib
import json

from media_platforms import (
    canonical_platform, MEDIA_PLATFORM_MAP, MEDIA_LIMITS, SPEC_VERSION,
    SPEC_VERIFIED_ON, SPEC_SOURCE, SPEC_DISCLAIMER, placement_rule,
)
from industry_profiles import resolve_profile
from claims import EvidenceSnapshot

# 单张图片模型调用的成本上界估算（USD）。仅用于确认区展示「预计成本上界」，
# 不代表真实计费；真实计费须由供应商账单核实（文档 A14）。
COST_PER_IMAGE_ESTIMATE = 0.05
# 每次文案生成（按概念）约折算为一次模型调用，用于「预计模型调用」估算。
COPY_CALL_PER_CONCEPT = 1


def _parse_size(size: str):
    parts = str(size).lower().replace("×", "x").split("x")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def build_coverage_plan(recommendation: dict, platforms: list[str] | None = None,
                        concepts: list[dict] | None = None,
                        workspace_defaults: dict | None = None) -> dict:
    """D4：根据策划结果与已选平台计算「全规则图片」覆盖计划。

    入参：
    - recommendation：来自 `creation_planner.build_recommendation` 的字典；
    - platforms：用户确认的平台（已通过 `validate_platform` 校验，不会含未知平台）；
    - concepts：结构化概念（决定概念数 × 角色覆盖）；
    - workspace_defaults：含 budget_cap / concept_count 等。

    返回 MediaCoveragePlan：tasks / sub_batches / cost_upper / report / coverage。
    """
    rec = recommendation if isinstance(recommendation, dict) else {}
    plats = [str(x).strip() for x in (platforms or rec.get("coverage_summary", {}).get("platforms") or []) if str(x or "").strip()][:8]
    defaults = dict(rec.get("workspace_defaults") or {})
    if isinstance(workspace_defaults, dict):
        defaults.update(workspace_defaults)
    concept_count = max(1, min(3, int(defaults.get("concept_count") or rec.get("workspace_defaults", {}).get("concept_count") or 1)))
    budget_cap = float(defaults.get("budget_cap") or 0)

    a = rec.get("analysis") if isinstance(rec.get("analysis"), dict) else {}
    profile = resolve_profile(a, key=a.get("industry_profile") or "")
    snap = EvidenceSnapshot.from_analysis(a)
    unsupported_platforms = [p for p in plats if not canonical_platform(p)]

    tasks: list[dict] = []
    concept_models = concepts if isinstance(concepts, list) and concepts else rec.get("structured_concepts") or []
    n_concepts = max(1, min(3, len(concept_models) or concept_count))

    for name in plats:
        key = canonical_platform(name)
        spec = MEDIA_PLATFORM_MAP.get(key)
        if not spec:
            continue
        for pl in spec.get("placements", []):
            if not pl.get("default"):
                continue
            # 取版位交付语义（asset_role / ad_product）——来自 PLACEMENT_RULES，不在平台列表里
            pr = placement_rule(key, pl["id"])
            role = pr.get("asset_role") or "unspecified"
            ad_product = pr.get("ad_product") or ""
            for size in pl.get("sizes", []):
                wh = _parse_size(size)
                if not wh:
                    continue
                w, h = wh
                # D4：每个概念都完整适配该版位（不是轮换伪装全覆盖）
                for ci in range(n_concepts):
                    tasks.append({
                        "platform": key,
                        "placement_id": pl["id"],
                        "placement_name": pl.get("name", ""),
                        "asset_role": role,
                        "ad_product": ad_product,
                        "size": size,
                        "concept_index": ci,
                        "concept_id": (concept_models[ci].get("concept_id") if ci < len(concept_models) else f"C{ci + 1:02d}"),
                        "w": w, "h": h,
                        "pixels": w * h,
                    })

    total_tasks = len(tasks)
    total_pixels = sum(t["pixels"] for t in tasks)
    # D4 / A12：超过单批 24 任务 / 40MP 自动拆子批，父计划完整，不截断版位。
    sub_batches = _split_batches(tasks)
    n_batches = len(sub_batches)
    truncated = total_tasks > MEDIA_LIMITS["max_slots"] and n_batches <= 1

    # 成本上界：每张图片一次模型调用 + 每概念一次文案调用。
    model_calls = total_tasks + n_concepts * COPY_CALL_PER_CONCEPT
    cost_upper = round(total_tasks * COST_PER_IMAGE_ESTIMATE + n_concepts * COPY_CALL_PER_CONCEPT * COST_PER_IMAGE_ESTIMATE, 4)
    over_budget = budget_cap > 0 and cost_upper > budget_cap
    # A14：预算不足 / 规则未核验 → 不得显示「完整可交付」，只解释缺口。
    deliverable_scope_ok = (not unsupported_platforms) and bool(SPEC_VERIFIED_ON)

    coverage = {
        "platforms": plats,
        "unsupported_platforms": unsupported_platforms,
        "asset_roles": sorted({t["asset_role"] for t in tasks}),
        "concept_count": n_concepts,
        "required_tasks": total_tasks,
        "total_pixels": total_pixels,
        "max_batch_slots": MEDIA_LIMITS["max_slots"],
        "max_batch_pixels": MEDIA_LIMITS["max_total_pixels"],
        "sub_batch_count": n_batches,
        "truncated": truncated,
        "spec_version": SPEC_VERSION,
        "spec_verified": bool(SPEC_VERIFIED_ON),
        "spec_source": SPEC_SOURCE,
        "spec_verified_on": SPEC_VERIFIED_ON or "（空：内部目录，未官方核验）",
        "disclaimer": SPEC_DISCLAIMER,
    }
    report = {
        "required": total_tasks,
        "passed_estimate": total_tasks,        # 执行前无法知道逐图结果，先记预计
        "needs_revision": 0,
        "failed": 0,
        "unsupported": len(unsupported_platforms),
        "unknown_spec": 0 if SPEC_VERIFIED_ON else total_tasks,  # 未核验规则的任务须显式标注
        "denominator_note": ("分母 = 必需且适用的任务；未知规则不能悄悄移出分母。"
                             if not SPEC_VERIFIED_ON else "分母 = 必需且适用的任务"),
    }
    est = {
        "model_calls_upper": model_calls,
        "cost_upper_usd": cost_upper,
        "budget_cap_usd": budget_cap,
        "over_budget": over_budget,
        "currency": "USD",
        "is_estimate": True,
        "note": ("成本仅为上界估算，不代表真实计费；真实计费须按供应商账单核实。"
                 if not over_budget else
                 "预计成本上界已超过工作区预算上限；不会静默生成，请调整概念数 / 平台或提高上限。"),
    }
    plan_hash = hashlib.sha256(json.dumps(
        {"p": plats, "c": n_concepts, "t": total_tasks, "b": budget_cap,
         "sv": SPEC_VERSION, "pv": profile.get("version")},
        ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    return {
        "schema_version": "1.0",
        "plan_hash": plan_hash,
        "tasks": tasks,
        "sub_batches": sub_batches,
        "coverage": coverage,
        "report": report,
        "cost_estimate": est,
        "deliverable_scope_ok": deliverable_scope_ok,
        "note": ("覆盖计划已按所选平台完整计算，超过单批限制的已拆子批，未截断任何版位。"
                 if not over_budget else
                 "预算不足：已停止生成，请调整范围后再确认。"),
    }


def _split_batches(tasks: list[dict]) -> list[list[dict]]:
    """D4 / A12：贪心拆批，每批任务数 ≤ 24 且累计像素 ≤ 40MP；父计划保留全部任务。"""
    max_slots = MEDIA_LIMITS["max_slots"]
    max_pixels = MEDIA_LIMITS["max_total_pixels"]
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_px = 0
    for t in tasks:
        if len(cur) >= max_slots or cur_px + t["pixels"] > max_pixels:
            if cur:
                batches.append(cur)
            cur, cur_px = [], 0
        cur.append(t)
        cur_px += t["pixels"]
    if cur:
        batches.append(cur)
    return batches


def merge_manifest(plan: dict, job_results: list[dict]) -> dict:
    """D6 / A20：把多个生成任务结果打包为素材清单 manifest。

    列出 media / concept / role / 缺失报告；未通过质检的任务明确计入 failed / needs_revision，
    不谎报「全部完成」。
    """
    plan_tasks = plan.get("tasks") or []
    items: list[dict] = []
    missing: list[dict] = []
    by_key: dict[str, int] = {}
    for jr in job_results:
        for im in (jr.get("images") or []):
            if isinstance(im, dict):
                items.append({
                    "file": im.get("file", ""),
                    "url": im.get("url", ""),
                    "placement": im.get("placement", ""),
                    "size": im.get("size", ""),
                    "concept_id": im.get("concept_id", ""),
                    "status": im.get("status", "ok"),
                })
        for tr in (jr.get("task_results") or []):
            if isinstance(tr, dict) and tr.get("status") in ("failed", "needs_revision"):
                missing.append({"task_index": tr.get("task_index"),
                                "reason": tr.get("reason") or tr.get("error"),
                                "status": tr.get("status")})

    return {
        "item_count": len(items),
        "items": items,
        "plan_required_tasks": len(plan_tasks),
        "missing_report": missing,
        "complete": len(missing) == 0 and len(items) == len(plan_tasks),
        "incomplete_reason": ("" if not missing else
                              f"{len(missing)} 项未通过质检或生成失败；供应商失败纯背景模板不计合格商品图（A15）。"),
    }
