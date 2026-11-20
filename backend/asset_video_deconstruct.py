"""V4.121 素材创意模板库 · 视频解构引擎（framework_version: asset-video-deconstruct/1.0）。

在 V4.118 图片解构之上，把一条导入的推广视频解构成结构化 JSON，
**复用同一套 12 类分类字典、归并键与 golden 完整度口径**（asset_merge 直接消费），
并新增视频专属四个维度：分镜 / 钩子 / 字幕 / 节奏。

设计红线（沿用项目一贯的诚实交付原则）：

1. **复用真实视觉通道**：逐帧调用 asset_deconstruct.deconstruct_image（同源真实视觉模型，
   绝不 Mock / Fallback）；字幕用 video_vision_audit.recognize_frames 的真实 OCR。
   任一通道不可用都如实标注，不臆造分镜 / 字幕内容。
2. **完整度口径不变**：completeness 仍按 asset-deconstruct/1.0 的 12 项计分，
   保证图片 / 视频的 golden 选择在同一把尺子上可比；视频专属维度单独展示，
   有 caveat 说明"基于抽帧推断"，不冒充逐帧精算。
3. **框架版本化**：VIDEO_FRAMEWORK_VERSION 固定，供归并白名单与回归防漂移。
4. **抽帧来源唯一**：抽帧统一走 video_vision_audit.extract_frames()（imageio-ffmpeg
   自带 ffmpeg，无系统依赖），不在本模块重复实现。

第 1–2 步（视频上传 / 归档 / 封面帧）由 /assets/upload-video + 前端导入完成；
本模块接手解构与分类建议，沉淀模板仍由 V4.119 的 asset_merge 完成。
"""
from __future__ import annotations

from typing import Optional

import asset_deconstruct as ad

FRAMEWORK_VERSION = "asset-video-deconstruct/1.0"

# 视频专属维度（在 dims_json["video"] 下，全部用 {value, confidence, caveat?} 的
# 统一 cell 结构，前端 DimBlock 可直接渲染，无需特殊分支）。
VIDEO_DIM_KEYS = (
    "shot_sequence", "hook_moment", "subtitle_strategy", "rhythm",
    "frame_count", "duration_sec",
)


def _unavailable(reason: str, model_info: Optional[dict] = None) -> dict:
    out = ad._unavailable(reason)
    out["framework_version"] = FRAMEWORK_VERSION
    if model_info:
        out["model_info"] = model_info
    return out


def _cell(value, confidence: float, caveat: str = "") -> dict:
    cell = {"value": value, "confidence": round(max(0.0, min(1.0, float(confidence or 0))), 4)}
    if caveat:
        cell["caveat"] = caveat
    return cell


def _values(dims: dict, section: str, key: str):
    cell = (dims.get(section) or {}).get(key) if isinstance(dims.get(section), dict) else None
    return ad._value_of(cell)


def _confidence(dims: dict, section: str, key: str) -> float:
    cell = (dims.get(section) or {}).get(key) if isinstance(dims.get(section), dict) else None
    return ad._conf_of(cell)


def _dedup(values) -> list:
    out: list = []
    for v in values or []:
        s = str(v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _merge_benefits(results: list[dict]) -> list:
    merged: list = []
    for r in results:
        for b in _values(r["dims_json"], "info", "benefits") or []:
            if isinstance(b, str) and b.strip():
                merged.append(b.strip())
    return _dedup(merged)[:12]


def _merge_list(results: list[dict], key: str, allowed) -> list:
    """跨帧合并 purpose / hook（AI 建议 + 人工确认两类来源都算）。"""
    merged: list = []
    for r in results:
        for src in _category_sources(r.get("category_json")):
            merged.extend(src.get(key) or [])
    return [x for x in _dedup(merged) if x in allowed]


def _category_sources(category_json: dict) -> list:
    """AI 建议 + 人工确认都可能已存在，归并时两者都视为有效来源。"""
    if not isinstance(category_json, dict):
        return []
    out = [category_json]
    if isinstance(category_json.get("confirmed"), dict):
        out.append(category_json["confirmed"])
    if isinstance(category_json.get("ai_suggestion"), dict):
        out.append(category_json["ai_suggestion"])
    return out


def _pick_primary(results: list[dict]) -> str:
    """优先取已归一到 12 类、置信度最高的主分类，避免未归一建议污染归并键。"""
    candidates = []
    for r in results:
        cell = (r["dims_json"].get("category") or {}).get("primary") or {}
        val = ad._value_of(cell)
        if val in ad.PRIMARY_CATEGORIES:
            candidates.append((_conf_of_cell(cell), str(val)))
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1] if candidates else ""


def _conf_of_cell(cell) -> float:
    return ad._conf_of(cell)


def _build_shots(results: list[dict], times: list) -> str:
    """分镜序列：每帧一条，按抽样时间排列；只描述可见构图与主体位置。"""
    lines = []
    for i, r in enumerate(results):
        t = times[i] if i < len(times) else i
        composition = _values(r["dims_json"], "layout", "composition") or "未识别构图"
        subject = _values(r["dims_json"], "layout", "subject_position") or ""
        lines.append(f"分镜{i + 1}（约{float(t):.1f}s）：{composition}" + (f"；主体{subject}" if subject else ""))
    return " | ".join(lines)[:600]


def _build_hook(results: list[dict]) -> str:
    """钩子：取置信度最高的钩子类型，附首帧标题角色，均来自真实视觉解构。"""
    best = None
    for r in results:
        cell = (r["dims_json"].get("effect") or {}).get("hook_type") or {}
        val = ad._value_of(cell)
        if val and (best is None or _conf_of_cell(cell) > best[0]):
            best = (_conf_of_cell(cell), str(val))
    first_headline = _values(results[0]["dims_json"], "info", "headline_role") if results else ""
    parts = []
    if best:
        parts.append(f"钩子类型：{best[1]}")
    if first_headline:
        parts.append(f"首帧信息角色：{first_headline}")
    return "；".join(parts)[:300]


def _build_subtitles(ocr: dict) -> tuple[str, float, str]:
    """字幕 / 画面文字：只来自真实 OCR；不可用时留空并给 caveat，绝不臆造。"""
    if str(ocr.get("status") or "") != "ok":
        reason = str(ocr.get("reason") or "字幕识别不可用")
        return "", 0.0, f"字幕识别不可用：{reason}（未臆造字幕内容）"
    texts = [str(x).strip() for x in (ocr.get("texts") or []) if str(x).strip()]
    if not texts:
        return "画面未识别到可读文字（含字幕）", 0.8, "OCR 识别结果，含画面文字与字幕，需人工确认"
    return " / ".join(_dedup(texts))[:500], 0.75, "OCR 逐字识别结果（含画面文字与字幕），需人工确认是否字幕"


def _build_rhythm(results: list[dict], duration_sec: float, times: list) -> str:
    """节奏：基于抽样时间与构图切换的客观推断，明确非逐帧精算。"""
    compositions = _dedup([_values(r["dims_json"], "layout", "composition") for r in results])
    sample_count = len(results)
    d = round(float(duration_sec or 0), 2)
    if d > 0:
        avg = d / max(1, sample_count)
        base = f"时长约 {d}s，抽 {sample_count} 帧（平均间隔约 {avg:.1f}s），构图变化 {max(0, len(compositions) - 1)} 次"
    else:
        base = f"时长未知，抽 {sample_count} 帧，构图变化 {max(0, len(compositions) - 1)} 次"
    return base[:300]


async def deconstruct_video(frames: list[bytes], model_cfg: Optional[dict],
                            duration_sec: float = 0,
                            times: Optional[list] = None,
                            ocr: Optional[dict] = None) -> dict:
    """用真实视觉模型解构一条视频的抽样帧；任何不可用都诚实标注，不臆造。

    frames 来自 video_vision_audit.extract_frames()；model_cfg 来自
    creative_tasks._vision_model_cfg(db)（真实配置）。逐帧复用图片解构引擎，
    聚合为一条视频分析记录；category_json / 完整度口径与图片一致，可直接归并。
    ocr 可选：来自 recognize_frames 的真实画面文字识别；None 表示未做识别。
    """
    frame_list = [f for f in (frames or []) if isinstance(f, (bytes, bytearray)) and f]
    if not frame_list:
        return _unavailable("视频抽帧失败或无可用帧，无法解构")
    times = list(times or [])

    # 逐帧真实视觉解构（同源模型 / 同源协议，绝不 Mock）。
    per_frame = []
    for frame in frame_list:
        per_frame.append(await ad.deconstruct_image(bytes(frame), model_cfg))
    usable = [r for r in per_frame if r.get("status") in ("analyzed", "low_confidence")
              and r.get("completeness", 0) > 0]
    if not usable:
        reason = next((r.get("reason") for r in per_frame if r.get("reason")), "视觉模型未返回有效解构")
        return _unavailable("视频各帧解构均不可用：" + str(reason)[:120],
                            per_frame[0].get("model_info"))

    # 主干取完整度最高的帧；其余帧只做信息补充，不稀释主干判断。
    main = max(usable, key=lambda r: (float(r.get("completeness") or 0),
                                      float(r.get("confidence") or 0)))
    dims = {k: dict(v) if isinstance(v, dict) else v for k, v in main["dims_json"].items()}
    if isinstance(dims.get("info"), dict):
        merged = _merge_benefits(usable)
        if merged:
            dims["info"]["benefits"] = {"value": merged,
                                        "confidence": max(
                                            _confidence(dims, "info", "benefits"), 0.6)}

    # 分类：主分类取已归一且置信度最高者；purpose / hook 跨帧合并去重。
    category_json = dict(main.get("category_json") or {})
    primary = _pick_primary(usable)
    if primary and primary in ad.PRIMARY_CATEGORIES:
        category_json["primary"] = primary
    purposes = _merge_list(usable, "purposes", ad.PURPOSES)
    hooks = _merge_list(usable, "hooks", ad.HOOK_TYPES)
    if purposes:
        category_json["purposes"] = purposes
    if hooks:
        category_json["hooks"] = hooks
    category_json["taxonomy_version"] = "asset-category/1.0"
    # dims.category 与 category_json 保持同源，保证归并键读取一致。
    if isinstance(dims.get("category"), dict):
        dims["category"]["primary"] = {"value": category_json.get("primary") or "",
                                       "confidence": _confidence(dims, "category", "primary"),
                                       "in_taxonomy": category_json.get("primary") in ad.PRIMARY_CATEGORIES}
        dims["category"]["purpose"] = {"value": purposes,
                                       "confidence": _confidence(dims, "category", "purpose")}
        dims["category"]["hook"] = {"value": hooks,
                                    "confidence": _confidence(dims, "category", "hook")}

    # 视频专属维度（统一 cell 结构；caveat 明示抽样推断 / OCR 来源）。
    subtitle_text, subtitle_conf, subtitle_caveat = _build_subtitles(ocr or {})
    shot_conf = sum(_confidence(r["dims_json"], "layout", "composition") for r in usable) / len(usable)
    hook_conf = sum(_confidence(r["dims_json"], "effect", "hook_type") for r in usable) / len(usable)
    dims["video"] = {
        "shot_sequence": _cell(_build_shots(usable, times), shot_conf,
                               "基于抽样的分镜推断，非逐帧精算"),
        "hook_moment": _cell(_build_hook(usable), hook_conf, "基于抽样帧的钩子推断"),
        "subtitle_strategy": _cell(subtitle_text, subtitle_conf, subtitle_caveat),
        "rhythm": _cell(_build_rhythm(usable, duration_sec, times), 0.6,
                        "基于抽样的节奏推断，非逐帧精算"),
        "frame_count": _cell(len(frame_list), 1.0),
        "duration_sec": _cell(round(float(duration_sec or 0), 2), 1.0),
    }
    if len(usable) < len(frame_list):
        dims["video"]["shot_sequence"]["caveat"] += f"；仅 {len(usable)}/{len(frame_list)} 帧解构成功"

    completeness, confidence = ad.compute_completeness(dims)
    status = "analyzed" if completeness >= 0.5 else "low_confidence"
    model_info = dict(main.get("model_info") or {})
    model_info.update({"frames_sent": len(frame_list), "frames_usable": len(usable),
                       "subtitle_ocr": str((ocr or {}).get("status") or "skipped")})
    return {
        "framework_version": FRAMEWORK_VERSION,
        "dims_json": dims,
        "category_json": category_json,
        "template_guess": main.get("template_guess") or {},
        "completeness": completeness,
        "confidence": confidence,
        "status": status,
        "model_info": model_info,
    }
