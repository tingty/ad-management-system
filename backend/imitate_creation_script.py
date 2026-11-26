# -*- coding: utf-8 -*-
"""V4.148 · 模仿创作视频：创作脚本 C1–C8 + 确认闸门（不提交付费生成）。

职责：把已生成的分析脚本 A1–A10 与用户创作选项转成完整、系统、具象的创作脚本，
落 ``ImitateAnalysisScript.creation_json``；用户确认后冻结幂等键与成本预估，停在
creation_confirmed，交 V4.149 逐镜生成。本版绝不设置 provider_config_id /
provider_task_id / next_poll_at，worker 也绝不进入 _provider 提交分支。

真实模型红线：
- 复用系统统一 LLM 路由（copy 用途，必要时复用 analysis），**拒绝 Mock/Fallback**：
  调用后用 finalize_invocation 定稿，fallback 或 source!=llm 一律 unavailable。
- 端点执行严格模型门（copy 未测试通过 422）；worker 内二次校验，不臆造脚本。
- 商业信息只做「原文→改写后」对照并保持不逐字复制；承诺数字/绝对化用语阻断确认。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import ImitateAnalysisScript
from providers import get_llm_with_info, finalize_invocation

FRAMEWORK_VERSION = "imitate-creation/1.0"
C_KEYS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")
C_LABELS = {
    "C1": "目标规格", "C2": "结构方案", "C3": "逐镜生成指令", "C4": "风格方案",
    "C5": "商业信息方案", "C6": "字幕/话术方案", "C7": "合规标注", "C8": "生成参数",
}
COST_PER_SHOT_ESTIMATE = 0.45
COST_BASE_ESTIMATE = 0.08
ABSOLUTE_TERM_RE = re.compile(
    r"(最佳|最好|第一|唯一|全网|绝对|永久|彻底|保证|治愈|百分百|100%|顶尖|最强|史上最)",
    re.I,
)
PROMISE_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|％|倍|天|日|小时|个月|年|元|美元|USD|\$|€|£|人|次))", re.I)


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


def _s(v) -> str:
    return "" if v is None else str(v)


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _as_list(value) -> list:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _merge_dict(base: dict, value) -> dict:
    out = dict(base)
    if isinstance(value, dict):
        out.update({k: v for k, v in value.items() if k in base})
    return out


def _parse_script(raw: str) -> tuple[dict, str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(), flags=re.I)
    try:
        data = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return {}, "创作脚本不是可解析 JSON"
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}, "创作脚本不是可解析 JSON"
    if not isinstance(data, dict):
        return {}, "创作脚本不是 JSON 对象"
    return data, ""


# ---------------------------------------------------------------------------
# C1 目标规格：前端零硬编码，唯一来源是 media_spec_library
# ---------------------------------------------------------------------------
def video_spec_options() -> list[dict]:
    """返回视频投放规格选项（稳定 spec_id + 平台/产品/比例/时长区间/核验状态）。"""
    from media_spec_library import LIBRARY, VERIFY_LABEL
    out: list[dict] = []
    seen: set[str] = set()
    for e in LIBRARY:
        if e.media != "video" or e.spec_id in seen:
            continue
        seen.add(e.spec_id)
        out.append({
            "spec_id": e.spec_id,
            "platform": e.platform,
            "ad_product": e.ad_product,
            "asset_role": e.asset_role,
            "aspect_ratios": list(e.aspect_ratios or ()),
            "sizes": list(e.sizes or ()),
            "duration_min": e.duration_min,
            "duration_max": e.duration_max,
            "verification": e.verification,
            "verification_label": VERIFY_LABEL.get(e.verification, "未标注"),
            "source_url": e.source_url,
            "note": e.note,
        })
    return out


def resolve_target_spec(job) -> tuple[dict, str]:
    """解析任务冻结的目标规格；未登记/未选择时不猜规格。"""
    import media_spec_library as msl
    req = job.request_json or {}
    sid = str(req.get("target_spec_id") or "").strip()
    if sid:
        e = msl.entry_for_spec_id(sid)
        if not e or e.media != "video":
            return {}, f"目标规格 {sid} 未在视频规格库登记"
        d = e.as_dict()
        return {"spec_id": e.spec_id, "platform": e.platform, "ad_product": e.ad_product,
                "asset_role": e.asset_role, "target_aspect": (e.aspect_ratios or [""])[0],
                "target_size": (e.sizes or [""])[0] if e.sizes else None,
                "duration_min": e.duration_min, "duration_max": e.duration_max,
                "verification": e.verification, "verification_label": d.get("verification_label") or "",
                "source_url": e.source_url, "note": e.note,
                "library_version": d.get("library_version") or ""}, ""
    platform = str(req.get("target_platform") or "").strip()
    if not platform:
        return {}, "请先选择目标投放平台与版位规格"
    aspect = str(req.get("target_aspect_ratio") or req.get("aspect_ratio") or "").strip()
    row = msl.video_target(platform, aspect, req.get("target_duration"),
                           str(req.get("target_ad_product") or ""))
    candidates = msl.entries_for(platform, "video", str(req.get("target_ad_product") or ""))
    hit = next((x for x in candidates
                if row.get("ad_product") and x.ad_product == row["ad_product"]), None)
    row["spec_id"] = hit.spec_id if hit else ""
    return row, ""


# ---------------------------------------------------------------------------
# 严格模型门：copy 未测试通过拦截；copy 未配置且 analysis 测试通过时允许复用
# ---------------------------------------------------------------------------
def creation_model_gate(db: Session) -> list[dict]:
    import workshop as cw_workshop
    st = cw_workshop.model_status(db)
    by = {i.get("usage"): i for i in st.get("items", [])}
    copy = by.get("copy") or {"usage": "copy", "label": "文案模型", "ready": False,
                              "candidates": 0, "reason": "未配置"}
    ana = by.get("analysis") or {"usage": "analysis", "label": "分析模型", "ready": False,
                                "candidates": 0, "reason": "未配置"}
    if copy.get("ready"):
        return []
    # 只有「copy 完全没有配置」才允许复用已测试通过的 analysis；
    # 已配置但测试失败的配置不能被另一用途偷偷绕过。
    if int(copy.get("candidates") or 0) == 0 and ana.get("ready"):
        return []
    missing = [copy]
    if not ana.get("ready"):
        missing.append(ana)
    return missing


# ---------------------------------------------------------------------------
# C1–C8 归一化：模型只负责创作表达，规格/合规/幂等字段由代码冻结
# ---------------------------------------------------------------------------
def _base_shots(analysis: dict, fidelity: str) -> list[dict]:
    src = _as_list((analysis.get("A4") or {}).get("shots"))
    out: list[dict] = []
    for i, shot in enumerate(src or [{}], start=1):
        out.append({
            "index": shot.get("index") or i,
            "tc_start": shot.get("tc_start") or "",
            "tc_end": shot.get("tc_end") or "",
            "duration": shot.get("duration") or "",
            "visual_prompt": " ".join(str(shot.get(k) or "") for k in
                                      ("shot_size", "subject_action", "shooting", "props")).strip(),
            "negative_prompt": "画面零文字、零 logo、零水印、零价格标签",
            "shot_size": shot.get("shot_size") or "",
            "camera": shot.get("camera") or "",
            "movement_path": shot.get("movement_path") or "",
            "transition": shot.get("transition") or "",
            "first_frame_ref": "",
            "keep": True,
            "structure_role": "逐镜保留" if fidelity == "high" else (
                "保留钩子/CTA" if fidelity == "medium" and i in (1, len(src) or 1) else "叙事骨架"),
        })
    return out


def _commercial_items(analysis: dict, model_c5: dict, toggles: dict) -> list[dict]:
    a7 = analysis.get("A7") or {}
    occurrences = _as_list(a7.get("occurrences"))
    model_items = {str(i.get("type") or ""): i
                   for i in _as_list(model_c5.get("items"))}
    out: list[dict] = []
    for typ in ("brand", "copy", "sales", "promotion"):
        original = _s(a7.get(typ) or "")
        if not original:
            hit = next((o for o in occurrences if str(o.get("type") or "") == typ), None)
            original = _s(hit.get("text") or "") if hit else ""
        mi = model_items.get(typ) or {}
        retain = bool(toggles.get(typ, mi.get("retain", False)))
        rewritten = _s(mi.get("rewritten") or "")
        out.append({
            "type": typ,
            "original": original,
            "rewritten": rewritten if retain else "",
            "retain": retain,
            "burn_in": retain,  # C-M1：改写后文字由播放层/烧录层受控呈现，不由模型画字
            "not_verbatim": bool(original and rewritten and rewritten != original),
            "reason": _s(mi.get("reason") or "") or ("保留但已改写" if retain else "用户选择不保留"),
        })
    return out


def _cost_estimate(shots: list[dict], spec: dict) -> dict:
    count = max(1, len(shots))
    amount = round(COST_BASE_ESTIMATE + COST_PER_SHOT_ESTIMATE * count, 2)
    return {
        "currency": "USD",
        "amount": amount,
        "is_estimate": True,
        "shot_count": count,
        "basis": f"{count} 镜 × ${COST_PER_SHOT_ESTIMATE:.2f}/镜 + ${COST_BASE_ESTIMATE:.2f} 基础文本成本",
        "note": "工程预估，非供应商报价；实际以模型配置与供应商结算为准。",
        "spec_id": str(spec.get("spec_id") or ""),
    }


def _compliance_issues(script: dict, analysis: dict, spec: dict) -> list[str]:
    issues: list[str] = []
    c5 = script.get("C5") or {}
    for item in _as_list(c5.get("items")):
        if item.get("retain") and item.get("original") and item.get("rewritten") == item.get("original"):
            issues.append("VERBATIM_COMMERCIAL_TEXT:" + str(item.get("type") or ""))
    texts: list[str] = []
    for item in _as_list(c5.get("items")):
        if item.get("retain"):
            texts.append(_s(item.get("rewritten")))
    c6 = script.get("C6") or {}
    texts.append(_s(c6.get("voiceover_text")))
    for sub in _as_list(c6.get("subtitles")):
        texts.append(_s(sub.get("text")))
    joined = " ".join(t for t in texts if t)
    if ABSOLUTE_TERM_RE.search(joined):
        issues.append("ABSOLUTE_TERM_UNREMOVED")
    if PROMISE_NUMBER_RE.search(joined):
        issues.append("PROMISE_NUMBER_UNREMOVED")
    if spec.get("verification") == "C" or not spec.get("spec_id"):
        issues.append("TARGET_SPEC_UNREGISTERED")
    a9 = analysis.get("A9") or {}
    if a9.get("needs_evidence"):
        issues.append("EVIDENCE_REQUIRED")
    return issues


def normalize_creation(data: dict, *, analysis: dict, job, spec: dict,
                       meta: Optional[dict] = None) -> dict:
    """把模型输出 / 用户编辑统一归一化为 C1–C8 完整脚本。"""
    req = job.request_json or {}
    c2in = data.get("C2") or {}
    c3in = data.get("C3") or {}
    c4in = data.get("C4") or {}
    c5in = data.get("C5") or {}
    c6in = data.get("C6") or {}
    c7in = data.get("C7") or {}
    # 用户建任务时选择的结构保持度是硬约束；模型输出不能改写。
    # 用户后续在确认页调整时，revise_creation_script 会把新档位写回 job.request_json。
    fidelity = str(req.get("structure_fidelity") or c2in.get("fidelity") or "medium")[:16]
    if fidelity not in ("high", "medium", "low"):
        fidelity = "medium"
    shots = _as_list(c3in.get("shots"))
    if not shots:
        shots = _base_shots(analysis, fidelity)
    else:
        norm: list[dict] = []
        for i, s in enumerate(shots, start=1):
            norm.append(_merge_dict({
                "index": i, "tc_start": "", "tc_end": "", "duration": "",
                "visual_prompt": "", "negative_prompt": "画面零文字、零 logo、零水印、零价格标签",
                "shot_size": "", "camera": "", "movement_path": "", "transition": "",
                "first_frame_ref": "", "keep": True, "structure_role": "叙事骨架",
            }, s))
        norm = [s for s in norm if s.get("keep", True)]
        for i, s in enumerate(norm, start=1):
            s["index"] = i
        shots = norm
    a6 = analysis.get("A6") or {}
    toggles_in = c5in.get("toggles") or req.get("commercial_options") or {}
    if not isinstance(toggles_in, dict):
        toggles_in = {}
    toggles = {k: bool(toggles_in.get(k, False))
               for k in ("brand", "copy", "sales", "promotion")}
    items = _commercial_items(analysis, c5in, toggles)
    out = {
        "C1": _merge_dict({
            "spec_id": "", "platform": "", "ad_product": "", "asset_role": "",
            "target_aspect": "", "target_size": "", "duration_min": None,
            "duration_max": None, "verification": "", "verification_label": "",
            "source_url": "", "note": "", "library_version": "",
        }, spec),
        "C2": _merge_dict({
            "fidelity": fidelity,
            "hook": "", "cta": "", "retention_note": "",
            "shots": [{"index": s.get("index"), "duration": s.get("duration"),
                       "structure_role": s.get("structure_role")} for s in shots],
        }, c2in),
        "C3": {"shots": shots},
        "C4": _merge_dict({
            "primary": a6.get("primary") or "", "secondary": a6.get("secondary") or "",
            "accent": a6.get("accent") or "", "tone": a6.get("tone") or "",
            "light_type": a6.get("light_type") or "", "inherit_from_A6": True,
            "brand_color_correction": _s(c4in.get("brand_color_correction")),
            "style_note": _s(c4in.get("style_note")),
        }, c4in),
        "C5": {
            "toggles": toggles, "items": items,
            "not_verbatim_statement": "保留项均须改写，不逐字复制原片商业信息",
        },
        "C6": _merge_dict({
            "subtitles": [], "voiceover_text": "",
            "voiceover_note": "口播仅交付改写文案，人工配音；不引入 TTS/数字人",
            "subtitle_style": _s((analysis.get("A7") or {}).get("subtitle_style")),
        }, c6in),
        "C7": _merge_dict({
            "removed_claims": [], "absolute_terms": [], "evidence_refs": [],
            "promise_number_action": "承诺数字与绝对化用语默认剔除，需人工核实后方可补充",
            "blocking_issues": [],
        }, c7in),
        "C8": {
            "idempotency_key": _s((meta or {}).get("idempotency_key")),
            "estimated_cost": _cost_estimate(shots, spec),
            "model_usage": "copy",
            "shot_count": len(shots),
            "spec_id": str(spec.get("spec_id") or ""),
            "created_by": "imitate-creation/1.0",
        },
    }
    out["C2"]["fidelity"] = fidelity
    out["C1"] = _merge_dict(out["C1"], spec)  # 规格由代码冻结，模型不能改写
    out["C7"]["blocking_issues"] = _compliance_issues(out, analysis, spec)
    return {k: out[k] for k in C_KEYS}


def validate_for_confirm(script: dict) -> list[str]:
    issues: list[str] = []
    if not isinstance(script, dict):
        return ["SCRIPT_NOT_OBJECT"]
    missing = [k for k in C_KEYS if not isinstance(script.get(k), dict)]
    if missing:
        issues.append("MISSING_SECTIONS:" + ",".join(missing))
    if not _as_list((script.get("C3") or {}).get("shots")):
        issues.append("NO_SHOTS")
    if not ((script.get("C8") or {}).get("estimated_cost") or {}).get("amount"):
        issues.append("NO_COST_ESTIMATE")
    for x in ((script.get("C7") or {}).get("blocking_issues") or []):
        issues.append(str(x))
    return issues


# ---------------------------------------------------------------------------
# 真实文本模型：统一路由 + 严格拒绝 Mock/Fallback
# ---------------------------------------------------------------------------
_CREATION_SYSTEM = """你是专业广告视频的再创作策划。只依据提供的分析脚本 A1–A10、目标投放规格与用户选项，输出严格 JSON，不解释、不 Markdown、不编造原片没有的事实。
顶层键必须完整包含 C1..C8：
C1 {spec_id,platform,ad_product,target_aspect,target_size,duration_min,duration_max,verification}
C2 {fidelity,hook,cta,retention_note,shots:[{index,duration,structure_role}]}
C3 {shots:[{index,tc_start,tc_end,duration,visual_prompt,negative_prompt,shot_size,camera,movement_path,transition,first_frame_ref,keep}]}
C4 {primary,secondary,accent,tone,light_type,brand_color_correction,style_note}
C5 {toggles:{brand,copy,sales,promotion},items:[{type,original,rewritten,retain,reason}],not_verbatim_statement}
C6 {subtitles:[{text,duration_sec,style}],voiceover_text,voiceover_note,subtitle_style}
C7 {removed_claims,absolute_terms,evidence_refs,promise_number_action}
C8 {estimated_cost,model_usage,shot_count,spec_id}
硬要求：1) C1/C8 的规格与成本字段由系统代码冻结，模型只需回显；2) C3 逐镜必须具体可执行，visual_prompt 不写任何文字/logo/水印/价格；3) C5 保留项必须改写，不得与 original 相同，不新增未核实事实；4) A9 标记的承诺数字、绝对化用语、未核实声明一律不写进 C5/C6；5) C2.fidelity 必须等于用户选项；6) C6 口播只给改写文案，不做 TTS；7) 删镜用 keep=false，排序用 index。"""

_CREATION_USER_TMPL = """请基于以下证据生成完整创作脚本 C1–C8 的 JSON。

【分析脚本 A1–A10】{analysis}
【冻结目标规格 C1】{spec}
【用户创作选项】{options}
【结构保持度】{fidelity}

再次强调：模仿方法论，不复制原片品牌、具体文案、销售说辞与促销数字；保留项必须改写并标注不逐字复制。
"""


async def _summarize(system: str, user_text: str, llm_pair) -> tuple[dict, str, dict]:
    llm, info = llm_pair
    try:
        raw = await llm.chat(system, user_text)
    except Exception as e:
        return {}, "文本归纳调用失败：" + type(e).__name__ + ": " + str(e)[:120], info
    final = finalize_invocation(info, llm, parsed_ok=True)
    if final.get("fallback") or final.get("source") != "llm":
        return {}, "文本模型回退到 Mock/Fallback，拒绝冒充真实创作脚本", final
    data, reason = _parse_script(raw)
    if not data:
        return {}, reason, final
    return data, "", final


# ---------------------------------------------------------------------------
# 落库 / 读取 / 缓存
# ---------------------------------------------------------------------------
def creation_view(row: ImitateAnalysisScript) -> Optional[dict]:
    payload = row.creation_json or {}
    if not payload:
        return None
    return {
        "script_id": row.script_id,
        "job_id": row.job_id or "",
        "status": str(payload.get("status") or "ready"),
        "script_json": payload.get("script_json") or {},
        "meta_json": payload.get("meta_json") or {},
        "created_at": payload.get("generated_at") or (
            row.created_at.isoformat() if row.created_at else ""),
    }


def get_creation_script(db: Session, owner_id: int | None, script_id: str) -> Optional[dict]:
    q = db.query(ImitateAnalysisScript).filter(ImitateAnalysisScript.script_id == script_id)
    if owner_id is not None:
        q = q.filter(ImitateAnalysisScript.owner_id == owner_id)
    row = q.first()
    return creation_view(row) if row else None


def _write_creation(db: Session, row: ImitateAnalysisScript, *, script: dict, meta: dict,
                    status: str) -> dict:
    payload = {"status": status, "script_json": script, "meta_json": meta,
               "generated_at": meta.get("generated_at") or (
                   row.updated_at.isoformat() if row.updated_at else datetime.utcnow().isoformat() + "Z")}
    row.creation_json = payload
    row.updated_at = datetime.utcnow()
    db.commit()
    return creation_view(row) or {"script_id": row.script_id, "status": status,
                                  "script_json": script, "meta_json": meta}


def _analysis_row(db: Session, job, script_id: str) -> Optional[ImitateAnalysisScript]:
    q = db.query(ImitateAnalysisScript).filter(ImitateAnalysisScript.script_id == script_id)
    if getattr(job, "owner_id", None) is not None:
        q = q.filter(ImitateAnalysisScript.owner_id == job.owner_id)
    return q.first()


async def generate_and_store(db: Session, job, *, llm_pair=None) -> dict:
    """worker 编排：取分析脚本 → 冻结规格 → 真实 LLM 归纳 C1–C8 → 落库。"""
    req = job.request_json or {}
    sid = str(((job.result_json or {}).get("analysis_script_id")) or req.get("analysis_script_id") or "")
    if not sid:
        return {"status": "unavailable", "reason": "任务未挂载分析脚本，无法生成创作脚本"}
    row = _analysis_row(db, job, sid)
    if not row or not row.script_json:
        return {"status": "unavailable", "reason": "分析脚本不存在或无权访问"}
    analysis = row.script_json
    spec, spec_reason = resolve_target_spec(job)
    if not spec:
        return {"status": "unavailable", "reason": spec_reason or "目标规格不可用"}
    opts = dict(req.get("creation_options") or {})
    cache_key = _digest({"v": FRAMEWORK_VERSION, "analysis": analysis,
                         "spec": spec, "options": opts, "fidelity": req.get("structure_fidelity")})
    existing = row.creation_json or {}
    emeta = existing.get("meta_json") or {}
    if emeta.get("cache_key") == cache_key and existing.get("script_json"):
        return {**(creation_view(row) or {}), "status": "ok", "cached": True}
    if llm_pair is None:
        if creation_model_gate(db):
            return {"status": "unavailable", "reason": "文案模型未就绪或测试未通过，拒绝生成脚本"}
        try:
            llm_pair = get_llm_with_info(db, "copy", allow_reuse=True)
        except Exception as e:
            return {"status": "unavailable", "reason": "统一模型路由失败：" + type(e).__name__}
    user_text = _CREATION_USER_TMPL.format(
        analysis=json.dumps(analysis, ensure_ascii=False)[:9000],
        spec=json.dumps(spec, ensure_ascii=False),
        options=json.dumps(opts, ensure_ascii=False),
        fidelity=str(req.get("structure_fidelity") or "medium"),
    )
    data, reason, info = await _summarize(_CREATION_SYSTEM, user_text, llm_pair)
    if not data:
        return {"status": "unavailable", "reason": reason or "创作脚本无结果"}
    script = normalize_creation(data, analysis=analysis, job=job, spec=spec, meta=emeta)
    meta = {
        "framework_version": FRAMEWORK_VERSION,
        "cache_key": cache_key,
        "analysis_script_id": sid,
        "model": str(info.get("model") or ""),
        "provider": str(info.get("provider") or ""),
        "config_id": info.get("config_id"),
        "role": "copy",
        "resolved_from": str(info.get("resolved_from") or ""),
        "request_id": str(info.get("request_id") or ""),
        "fallback": False,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "target_spec_id": str(spec.get("spec_id") or ""),
    }
    out = _write_creation(db, row, script=script, meta=meta, status="ready")
    return {**out, "status": "ok", "cached": False}


def revise_creation_script(db: Session, job, *, patch: dict, note: str = "") -> dict:
    """用户编辑后重新归一化：规格仍由代码冻结，成本按新镜数重算。"""
    sid = str(((job.result_json or {}).get("creation_script_id")) or
              ((job.result_json or {}).get("analysis_script_id")) or "")
    row = _analysis_row(db, job, sid)
    if not row or not row.creation_json:
        return {"status": "unavailable", "reason": "创作脚本不存在或无权访问"}
    payload = row.creation_json
    script = dict(payload.get("script_json") or {})
    incoming = patch.get("script_json") if isinstance(patch, dict) and "script_json" in patch else patch
    if isinstance(incoming, dict):
        for k in C_KEYS:
            if isinstance(incoming.get(k), dict):
                script[k] = copy.deepcopy(incoming[k])
        c2_patch = incoming.get("C2")
        if isinstance(c2_patch, dict) and c2_patch.get("fidelity") in ("high", "medium", "low"):
            req = dict(job.request_json or {})
            req["structure_fidelity"] = c2_patch["fidelity"]
            job.request_json = req
    spec, spec_reason = resolve_target_spec(job)
    if not spec:
        return {"status": "unavailable", "reason": spec_reason or "目标规格不可用"}
    meta = dict(payload.get("meta_json") or {})
    if note:
        meta["last_edit_note"] = str(note)[:500]
    meta["revised_at"] = datetime.utcnow().isoformat() + "Z"
    # 修改后旧幂等键失效；V4.149 提交前必须重新确认生成新键。
    meta.pop("idempotency_key", None)
    script = normalize_creation(script, analysis=row.script_json or {}, job=job,
                                spec=spec, meta=meta)
    out = _write_creation(db, row, script=script, meta=meta, status="ready")
    return {**out, "status": "ok"}


def confirm_creation_script(db: Session, job, *, fee_ack: bool = False) -> dict:
    """确认闸门：冻结脚本与幂等键；本版绝不提交供应商、不设置付费字段。"""
    if not fee_ack:
        return {"status": "blocked", "reason": "请确认已知晓成本预估后再提交生成"}
    rid = (job.result_json or {}).get("creation_script_id") or (job.result_json or {}).get("analysis_script_id")
    row = _analysis_row(db, job, str(rid or ""))
    if not row or not row.creation_json:
        return {"status": "blocked", "reason": "创作脚本不存在或无权访问"}
    payload = row.creation_json
    script = payload.get("script_json") or {}
    issues = validate_for_confirm(script)
    if issues:
        return {"status": "blocked", "reason": "创作脚本未通过确认闸门：" + "、".join(issues[:5]),
                "issues": issues}
    meta = dict(payload.get("meta_json") or {})
    # 幂等键排除它自己，避免第一次确认写入 C8.idempotency_key 后第二次算出不同 key。
    key_script = copy.deepcopy(script)
    if isinstance(key_script.get("C8"), dict):
        key_script["C8"].pop("idempotency_key", None)
    key = _digest({"job_id": job.job_id, "script_id": row.script_id,
                   "script": key_script, "v": FRAMEWORK_VERSION})
    if meta.get("status") == "confirmed" and meta.get("idempotency_key") == key:
        return {"status": "ok", "idempotent": True, "idempotency_key": key,
                "cost_estimate": (script.get("C8") or {}).get("estimated_cost") or {}}
    meta["status"] = "confirmed"
    meta["idempotency_key"] = key
    meta["confirmed_at"] = datetime.utcnow().isoformat() + "Z"
    script = copy.deepcopy(script)
    script.setdefault("C8", {})["idempotency_key"] = key
    out = _write_creation(db, row, script=script, meta=meta, status="confirmed")
    return {**out, "status": "ok", "idempotent": False, "idempotency_key": key,
            "cost_estimate": (script.get("C8") or {}).get("estimated_cost") or {}}
