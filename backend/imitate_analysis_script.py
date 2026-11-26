# -*- coding: utf-8 -*-
"""V4.147 · 模仿创作视频：分析脚本 A1–A10（真实视觉模型，绝不 Mock/Fallback）。

职责：把参考视频解构为完整、系统、具象的分析脚本，落 ``imitate_analysis_script.script_json``。

真实模型红线：
- 视觉调用自建 httpx（仿 asset_deconstruct.deconstruct_image），**不经过**
  get_llm_with_info / MockLLM / FallbackLLM；配置缺失 / 协议不符 / 调用失败 /
  返回不可解析一律返回 status=unavailable + reason，绝不臆造、绝不冒充已分析。
- 分析前由端点做 ``missing_models(db, ["analysis"])`` 422 硬门（worker 内转
  needs_attention），口径与素材工作坊一致。
- 只调用 analysis 用途视觉模型；不碰视频提交（submit_job / get_video），不进 submitting 分支。

证据来源：抽帧（video_vision_audit.extract_frames）+ 真实视觉 OCR + 现有 6 维解构
（asset_video_deconstruct.deconstruct_video）+ Pillow 全局取色 + VLM 逐镜归纳 A1–A10。
同 owner + file_hash 命中 analyzed 记录直接复用，不重复调用模型、不产生 token 费用。
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import ImitateAnalysisScript
from creative_tasks import _now, _vision_model_cfg

FRAMEWORK_VERSION = "imitate-analysis/1.0"
A_KEYS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10")


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# A6 全局取色：Pillow quantize，输出十六进制主色/辅色/点缀色估值（不做 VLM 臆测）
# ---------------------------------------------------------------------------
def dominant_colors(jpeg_bytes: bytes, top_n: int = 6) -> dict:
    """从抽帧图提取主色（十六进制 + 占比），供 A6 色彩光影使用。"""
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
        im.thumbnail((96, 96))
        q = im.quantize(colors=max(4, top_n + 2), method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette() or []
        hist = q.histogram()
        total = sum(hist) or 1
        pairs = []
        for idx, cnt in enumerate(hist):
            if cnt <= 0 or idx * 3 + 2 >= len(pal):
                continue
            r, g, b = pal[idx * 3], pal[idx * 3 + 1], pal[idx * 3 + 2]
            pairs.append((cnt / total, f"#{r:02X}{g:02X}{b:02X}"))
        pairs.sort(reverse=True)
        top = pairs[:max(1, top_n)]
        return {"status": "ok", "colors": [
            {"hex": h, "ratio": round(r, 4)} for r, h in top]}
    except Exception as e:
        return {"status": "unavailable", "reason": "取色失败：" + type(e).__name__, "colors": []}


# ---------------------------------------------------------------------------
# A1–A10 结构化 prompt：要求严格 JSON、不编造、颜色用 #RRGGBB 估值
# ---------------------------------------------------------------------------
_ANALYSIS_SYSTEM = """你是专业广告投放视频的解构分析师。只依据提供的抽帧画面、OCR 文字、6 维摘要、元数据与取色结果，按固定维度逐镜拆解，输出严格 JSON，不解释、不 Markdown、不编造看不到的事实。
JSON 顶层键必须完整包含 A1..A10（缺项用空字符串/空数组/"unverified" 占位），结构如下：
A1 全局规格：{duration, aspect_ratio, resolution, fps, audio, container, style_one_line}
A2 叙事骨架：{hook_first3s, emotion_curve, selling_points_order, cta_timing, cta_form, info_density}
A3 内容布局：{zones:[{frame,subject_zone,text_zone,logo_zone,blank_zone}], safe_area, text_hold_sec}
A4 逐镜镜头表：{shots:[{index,tc_start,tc_end,duration,shot_size,camera,shooting,movement_path,subject_action,props,transition}]}
A5 运动轨迹：{per_shot:[{index,subject_path,camera_path,element_speed}]}
A6 色彩光影：{primary,secondary,accent,color_temp,saturation,contrast,tone,light_type,light_direction,light_change}（颜色必须是 #RRGGBB 估值，参考输入取色结果）
A7 商业信息：{brand, copy, sales, promotion, occurrences:[{type,text,tc,position}], subtitle_style, voiceover_transcript, speech_rate}
A8 音频：{bgm_style, beat_points, sfx_points, voice_pause_stress}
A9 合规标记：{promise_numbers:[], absolute_terms:[], unverified_claims:[], needs_evidence:[]}
A10 可模仿结论：{why_effective:[3-5 条字符串]}
要求：A4/A5 尽量逐镜具象到时码与运镜；看不到的一律标 unverified，A9 只做标记不输出承诺性数字本身。"""

_ANALYSIS_USER_TMPL = """请分析这条参考视频并输出 A1..A10 的完整 JSON。

【元数据】{meta}
【全局取色】{colors}
【真实 OCR 文字】{ocr}
【现有 6 维解构摘要】{dims}
【抽帧图像】共 {n} 帧，按时码顺序：{times}
（以下按顺序附带每帧图像，请结合画面归纳；只描述可见事实。）
"""


def _parse_script(raw: str) -> tuple[dict, str]:
    """去代码围栏 → json.loads → 正则兜底；失败返回 ( {}, reason )。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(), flags=re.I)
    try:
        data = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return {}, "归纳结果不可解析 JSON"
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}, "归纳结果不可解析 JSON"
    if not isinstance(data, dict):
        return {}, "归纳结果不是 JSON 对象"
    return data, ""


def _normalize_script(data: dict) -> dict:
    """按 A1–A10 白名单归一，缺项补默认结构，保证脚本字段完整可编辑。"""
    defaults = {
        "A1": {"duration": "", "aspect_ratio": "", "resolution": "", "fps": "",
               "audio": "", "container": "", "style_one_line": ""},
        "A2": {"hook_first3s": "", "emotion_curve": "", "selling_points_order": "",
               "cta_timing": "", "cta_form": "", "info_density": ""},
        "A3": {"zones": [], "safe_area": "", "text_hold_sec": ""},
        "A4": {"shots": []},
        "A5": {"per_shot": []},
        "A6": {"primary": "", "secondary": "", "accent": "", "color_temp": "",
               "saturation": "", "contrast": "", "tone": "", "light_type": "",
               "light_direction": "", "light_change": ""},
        "A7": {"brand": "", "copy": "", "sales": "", "promotion": "",
               "occurrences": [], "subtitle_style": "", "voiceover_transcript": "",
               "speech_rate": ""},
        "A8": {"bgm_style": "", "beat_points": [], "sfx_points": [],
               "voice_pause_stress": ""},
        "A9": {"promise_numbers": [], "absolute_terms": [], "unverified_claims": [],
               "needs_evidence": []},
        "A10": {"why_effective": []},
    }
    out = {}
    for k in A_KEYS:
        v = data.get(k)
        if isinstance(v, dict):
            merged = dict(defaults[k])
            merged.update({kk: vv for kk, vv in v.items() if kk in defaults[k]})
            out[k] = merged
        else:
            out[k] = dict(defaults[k])
    return out


# ---------------------------------------------------------------------------
# 缓存：同 owner + file_hash + analyzed 命中即复用（换模型不误用旧脚本）
# ---------------------------------------------------------------------------
def cached_script(db: Session, owner_id: int | None, file_hash: str,
                  model: str = "") -> Optional[dict]:
    if not file_hash:
        return None
    q = (db.query(ImitateAnalysisScript)
         .filter(ImitateAnalysisScript.file_hash == file_hash,
                 ImitateAnalysisScript.status == "analyzed"))
    if owner_id is not None:
        q = q.filter(ImitateAnalysisScript.owner_id == owner_id)
    row = q.order_by(ImitateAnalysisScript.created_at.desc()).first()
    if not row:
        return None
    meta = row.meta_json or {}
    if model and meta.get("model") and meta.get("model") != model:
        return None  # 换过模型，旧脚本不可信
    return {"script_id": row.script_id, "script_json": row.script_json,
            "meta_json": meta, "cached": True}


def _store(db: Session, *, owner, file_hash: str, script: dict, meta: dict) -> dict:
    sid = _uid("ias_")
    row = ImitateAnalysisScript(
        script_id=sid,
        owner_id=getattr(owner, "id", None),
        owner_name=getattr(owner, "username", "") or "",
        file_hash=file_hash,
        status="analyzed",
        source_url=(meta.get("source_url") or "")[:1000] or None,
        job_id=meta.get("job_id"),
        script_json=script,
        meta_json=meta,
    )
    db.add(row)
    db.commit()
    return {"script_id": sid, "script_json": script, "meta_json": meta, "cached": False}


# ---------------------------------------------------------------------------
# 真实视觉归纳（自建 httpx，绝不 Mock/Fallback）
# ---------------------------------------------------------------------------
async def _summarize(frames: list[bytes], user_text: str, model_cfg: dict) -> tuple[dict, str]:
    """把抽帧 + 证据文本送 analysis 视觉模型归纳 A1–A10；返回 (data, reason)。"""
    missing = [k for k in ("api_key", "base_url", "model")
               if not str(model_cfg.get(k) or "").strip()]
    if missing:
        return {}, "视觉模型三要素缺失：" + "/".join(missing)
    try:
        from llm_catalog import _resolve_protocol
        if _resolve_protocol(str(model_cfg.get("provider") or "")) != "openai":
            return {}, "分析仅支持 OpenAI 兼容协议的视觉模型"
    except Exception as e:
        return {}, "视觉协议识别失败：" + type(e).__name__
    content = [{"type": "text", "text": user_text}]
    for fr in frames:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(fr).decode("ascii")}})
    payload = {
        "model": model_cfg["model"],
        "messages": [{"role": "system", "content": _ANALYSIS_SYSTEM},
                     {"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 4096,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, read=180.0)) as c:
            r = await c.post(str(model_cfg["base_url"]).rstrip("/") + "/chat/completions",
                             headers={"Authorization": "Bearer " + str(model_cfg["api_key"]),
                                      "Content-Type": "application/json"}, json=payload)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {}, "视觉归纳调用失败：" + type(e).__name__ + ": " + str(e)[:120]
    return _parse_script(raw)


# ---------------------------------------------------------------------------
# 主编排：抽帧 → 取色 → OCR + 6 维摘要 → VLM 归纳 → 归一化 → 写表
# ---------------------------------------------------------------------------
async def analyze_and_store(db: Session, job, *, model_cfg: Optional[dict] = None) -> dict:
    """对一条 imitate_video 任务执行真实分析并落库。

    返回 {"status": "ok"|"unavailable", ...}；失败带 reason，绝不返回假脚本。
    model_cfg 可注入以便测试；生产由 _vision_model_cfg(db) 取 analysis 真实配置。
    """
    req = job.request_json or {}
    file_path = str(req.get("file_path") or "")
    file_hash = str(req.get("file_hash") or "")
    if not file_path or not os.path.isfile(file_path):
        return {"status": "unavailable", "reason": "源视频文件不存在或已被清理"}
    owner = type("Owner", (), {"id": getattr(job, "owner_id", None),
                               "username": getattr(job, "owner_name", "") or ""})()

    cfg = model_cfg if isinstance(model_cfg, dict) else _vision_model_cfg(db)
    model = str((cfg or {}).get("model") or "")

    # 缓存复用：同 hash 命中 analyzed 直接返回，不调用模型、不产生 token
    hit = cached_script(db, getattr(job, "owner_id", None), file_hash, model)
    if hit:
        return {"status": "ok", **hit}

    if not cfg:
        return {"status": "unavailable", "reason": "analysis 视觉模型未配置或不可用"}

    duration = float(req.get("duration_sec") or 0)
    # 逐镜采样：按时长均匀取 6 个点（<=24 上限），比首/中/尾更利于 A4/A5 逐镜具象
    n = 6 if duration > 6 else max(2, int(duration) if duration > 0 else 3)
    times = [round(duration * i / max(1, n - 1), 2) for i in range(n)] if duration > 0 else []
    try:
        import video_vision_audit as vva
        frames, finfo = vva.extract_frames(file_path, duration, count=n, times=times or None)
    except Exception as e:
        return {"status": "unavailable", "reason": "抽帧失败：" + type(e).__name__}
    if not frames:
        return {"status": "unavailable", "reason": "抽帧失败：" + str(finfo.get("reason") or "")[:120]}

    colors = dominant_colors(frames[0])
    ocr_texts: list[str] = []
    dims_summary = ""
    try:
        ocr = await vva.recognize_frames(frames, cfg)
        if isinstance(ocr, dict) and ocr.get("status") == "ok":
            ocr_texts = [str(t) for t in (ocr.get("texts") or []) if t]
    except Exception:
        pass  # OCR 不可用不阻断分析，仅少一路证据
    try:
        import asset_video_deconstruct as avd
        dec = await avd.deconstruct_video(frames, cfg, duration_sec=duration,
                                          times=finfo.get("times") or times)
        dims = dec.get("dims_json") or {}
        dims_summary = json.dumps({"video": dims.get("video", {}),
                                   "visual": dims.get("visual", {}),
                                   "info": dims.get("info", {})},
                                  ensure_ascii=False)[:2500]
    except Exception:
        pass  # 6 维摘要不可用不阻断主归纳

    meta_text = json.dumps({
        "duration_sec": duration, "aspect_ratio": req.get("aspect_ratio") or "",
        "resolution": f"{req.get('width') or '?'}x{req.get('height') or '?'}",
        "fps": req.get("fps") or "", "has_audio": bool(req.get("has_audio")),
        "container": req.get("container") or "",
    }, ensure_ascii=False)
    user_text = _ANALYSIS_USER_TMPL.format(
        meta=meta_text,
        colors=json.dumps(colors, ensure_ascii=False),
        ocr=" / ".join(ocr_texts) or "（无）",
        dims=dims_summary or "（无）",
        n=len(frames),
        times=finfo.get("times") or times,
    )
    data, reason = await _summarize(frames, user_text, cfg)
    if not data:
        return {"status": "unavailable", "reason": reason or "视觉归纳无结果"}

    script = _normalize_script(data)
    # A6 颜色若模型未给十六进制，用真实取色结果兜底（不臆造）
    if colors.get("status") == "ok" and colors.get("colors"):
        c = colors["colors"]
        a6 = script["A6"]
        if not re.match(r"^#[0-9A-Fa-f]{6}$", str(a6.get("primary") or "")):
            a6["primary"] = c[0]["hex"]
        if len(c) > 1 and not re.match(r"^#[0-9A-Fa-f]{6}$", str(a6.get("secondary") or "")):
            a6["secondary"] = c[1]["hex"]
        if len(c) > 2 and not re.match(r"^#[0-9A-Fa-f]{6}$", str(a6.get("accent") or "")):
            a6["accent"] = c[2]["hex"]

    meta = {
        "framework_version": FRAMEWORK_VERSION,
        "model": model,
        "provider": str(cfg.get("provider") or ""),
        "role": "analysis",
        "fallback": False,
        "file_hash": file_hash,
        "job_id": getattr(job, "job_id", None),
        "source_url": req.get("source_url") or "",
        "frames": len(frames),
        "times": finfo.get("times") or times,
        "colors": colors,
        "ocr_status": "ok" if ocr_texts else "unavailable",
        "analyzed_at": datetime.utcnow().isoformat() + "Z",
    }
    return {"status": "ok", **_store(db, owner=owner, file_hash=file_hash,
                                    script=script, meta=meta)}


def get_analysis_script(db: Session, owner_id: int | None, script_id: str) -> Optional[dict]:
    """按 script_id + owner 隔离读取已落库的分析脚本。"""
    q = db.query(ImitateAnalysisScript).filter(ImitateAnalysisScript.script_id == script_id)
    if owner_id is not None:
        q = q.filter(ImitateAnalysisScript.owner_id == owner_id)
    row = q.first()
    if not row:
        return None
    return {"script_id": row.script_id, "job_id": row.job_id, "status": row.status,
            "script_json": row.script_json, "meta_json": row.meta_json,
            "created_at": row.created_at.isoformat() if row.created_at else ""}
