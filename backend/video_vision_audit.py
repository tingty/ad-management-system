"""V4.94 阶段三：成片视觉复核门（抽帧 → 画面文字识别 → 黄金词典比对）。

阶段一管住了"提交前不给模型写字的机会"，阶段二把品牌字样挪到播放层 DOM，
但模型仍可能在像素里偷画几个字。本模块是成片交付前的最后一道兜底：

- `extract_frames()`：用 imageio-ffmpeg 自带的 ffmpeg 从成片抽首 / 中 / 尾帧，
  只依赖 PIL 可解码的 JPEG 字节，不引入 cv2 / numpy 等重依赖；
- `recognize_frames()`：把抽帧图发给**真实**视觉模型逐字识别画面文字。
  绝不走 MockLLM / FallbackLLM —— 模拟结果没有审查价值；无视觉配置或调用失败时
  明确返回 `unavailable`，不冒充"已复核通过"；
- `audit_video_vision()`：按零文字 / 批准清单策略比对识别结果，任何画面文字
  或品牌错拼都形成 violation，由交付门把任务标成 needs_attention。

边界：不修改视频文件、不自动重生成；判违规时保留原片供下载核对，
真正的"品牌方确认"仍属外部验收，模拟测试不能替代。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from typing import Optional

VISION_AUDIT_VERSION = "1.0.0"
DEFAULT_FRAMES = 3
_FFMPEG_TIMEOUT = 30

_OCR_SYSTEM = (
    "你是严格的画面文字审查员。只输出图片中肉眼确实可见的印刷体 / 叠加文字，"
    "逐字照抄，不猜测、不翻译、不补上下文、不描述图形含义。"
    "只输出 JSON：{\"texts\":[\"画面中可见的文字\"]}；没有任何可读文字时输出 {\"texts\":[]}。"
    "不要输出解释或 Markdown。"
)
_OCR_USER = "逐字列出这张视频帧里可见的所有文字（品牌名、英文单词、数字、角标、字幕都算）。"


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return str(imageio_ffmpeg.get_ffmpeg_exe() or "")
    except Exception:
        return ""


def _sample_times(duration_sec: float, count: int) -> list[float]:
    try:
        d = float(duration_sec or 0)
    except (TypeError, ValueError):
        d = 0.0
    count = max(1, min(int(count or DEFAULT_FRAMES), 8))
    if d <= 1.0:
        return [0.0]
    raw = [0.5, d / 2, max(0.0, d - 0.6)][:count]
    # 时长较短时三个点可能重合，去重后仍至少保留首帧。
    out: list[float] = []
    for t in raw:
        t = round(max(0.0, min(t, max(0.0, d - 0.1))), 2)
        if t not in out:
            out.append(t)
    return out or [0.0]


def extract_frames(video_path: str, duration_sec: float = 0,
                   count: int = DEFAULT_FRAMES,
                   times: list[float] | None = None) -> tuple[list[bytes], dict]:
    """抽首 / 中 / 尾帧，返回 JPEG 字节列表；任何失败都返回可追溯原因。

    V4.147：times 可指定自定义采样时间点（逐镜 3–5 帧），上限 24 帧；不传则沿用
    旧的首/中/尾三点采样，既有调用完全不受影响。
    """
    exe = _ffmpeg_exe()
    if not exe or not video_path or not __import__("os").path.exists(video_path):
        return [], {"status": "unavailable", "reason": "ffmpeg 或成片文件不可用"}
    if times is not None:
        try:
            d = float(duration_sec or 0)
            pts = sorted({round(max(0.0, min(float(t), max(0.0, d - 0.05))), 2)
                          for t in list(times)[:24]})
        except (TypeError, ValueError):
            pts = _sample_times(duration_sec, count)
    else:
        pts = _sample_times(duration_sec, count)
    frames: list[bytes] = []
    errors: list[str] = []
    for t in pts:
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-ss", str(t),
               "-i", video_path, "-frames:v", "1", "-f", "image2pipe",
               "-vcodec", "mjpeg", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {str(e)[:80]}")
            continue
        if p.returncode != 0 or not p.stdout:
            errors.append((p.stderr or b"").decode("utf-8", "ignore")[-160:].strip() or "无输出")
            continue
        frames.append(p.stdout)
    if not frames:
        return [], {"status": "unavailable", "reason": "抽帧失败：" + "；".join(errors[:2])}
    return frames, {"status": "ok", "frames": len(frames), "times": pts[:len(frames)]}


def _parse_texts(raw: str) -> tuple[list[str], str]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\"texts\"\s*:\s*\[[\s\S]*?\]\s*\}", text)
        if not m:
            return [], "视觉模型未返回可解析的 JSON"
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return [], "视觉模型未返回可解析的 JSON"
    values = obj.get("texts") if isinstance(obj, dict) else None
    if not isinstance(values, (list, tuple)):
        return [], "视觉模型返回的 texts 不是数组"
    out: list[str] = []
    for v in values:
        s = re.sub(r"\s+", " ", str(v or "")).strip()
        if s and len(s) <= 200 and s not in out:
            out.append(s)
    return out, ""


async def recognize_frames(frames: list[bytes], model_cfg: Optional[dict]) -> dict:
    """用真实 OpenAI 兼容视觉接口逐帧识别文字；不配置 / 失败即 unavailable。"""
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    missing = [k for k in ("api_key", "base_url", "model") if not str(cfg.get(k) or "").strip()]
    if missing:
        return {"status": "unavailable", "reason": "未配置可用的视觉模型：" + "/".join(missing), "texts": []}
    try:
        from llm_catalog import _resolve_protocol
        if _resolve_protocol(str(cfg.get("provider") or "")) != "openai":
            return {"status": "unavailable",
                    "reason": "视觉复核仅支持 OpenAI 兼容协议（当前：" + str(cfg.get("provider") or "") + "）",
                    "texts": []}
    except Exception:
        return {"status": "unavailable", "reason": "视觉协议识别失败", "texts": []}

    content: list[dict] = [{"type": "text", "text": _OCR_USER}]
    for frame in frames:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")}})
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": _OCR_SYSTEM},
                     {"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 512,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(str(cfg["base_url"]).rstrip("/") + "/chat/completions",
                             headers={"Authorization": "Bearer " + str(cfg["api_key"]),
                                      "Content-Type": "application/json"},
                             json=payload)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        # 不回显 Key / URL，只给类型与短摘要（证据需可核对但不能泄露凭据）。
        return {"status": "unavailable", "reason": "视觉模型调用失败：" + type(e).__name__ + ": " + str(e)[:120],
                "texts": []}
    texts, err = _parse_texts(raw)
    if err:
        return {"status": "unavailable", "reason": err, "texts": []}
    return {"status": "ok", "texts": texts, "model": str(cfg["model"]), "frames_sent": len(frames)}


def _compare(texts: list[str], lexicon: Optional[dict], text_policy: str) -> list[dict]:
    entries = [str(x) for x in ((lexicon or {}).get("entries") or []) if str(x).strip()]
    violations: list[dict] = []
    for t in texts:
        if str(text_policy or "none").strip().lower() in ("", "none", "off", "false"):
            violations.append({"text": t, "type": "onscreen_text", "severity": "block",
                               "reason": "本次出片为零文字策略，画面不应出现任何文字"})
            continue
        # approved_only：只有黄金词典的逐字项允许上屏。
        exact = t in entries
        from brand_lexicon import enforce_onscreen
        chk = enforce_onscreen([t], lexicon)
        near = next((v.get("near_lexicon") for v in (chk.get("violations") or [])
                     if v.get("near_lexicon")), "")
        if not exact:
            violations.append({
                "text": t, "type": "brand_spelling_mismatch" if near else "unapproved_onscreen_text",
                "severity": "block",
                "reason": (f"画面文字疑似品牌名 / 单词错拼，应为「{near}」" if near else
                           "画面文字不在黄金词典批准清单中"),
            })
    return violations


async def audit_video_vision(video_path: str, lexicon: Optional[dict] = None,
                             text_policy: str = "none", model_cfg: Optional[dict] = None,
                             duration_sec: float = 0, count: int = DEFAULT_FRAMES) -> dict:
    """成片视觉复核：抽帧 → 真实视觉模型识别 → 词典比对。不修改输入文件。"""
    frames, ext = extract_frames(video_path, duration_sec, count)
    base = {"rules_version": VISION_AUDIT_VERSION, "text_policy": str(text_policy or "none"),
            "frames_checked": len(frames), "texts": [], "violations": []}
    if not frames:
        return {**base, "status": "unavailable", "reason": ext.get("reason") or "抽帧失败",
                "note": "未能抽帧复核；不冒充已通过，成片按未复核交付。"}
    rec = await recognize_frames(frames, model_cfg)
    if rec.get("status") != "ok":
        return {**base, "status": "unavailable", "reason": rec.get("reason") or "识别失败",
                "note": "未取得真实视觉识别结论；不冒充已通过，不因工具缺失误判成片。"}
    texts = [str(x) for x in (rec.get("texts") or []) if str(x).strip()]
    violations = _compare(texts, lexicon, text_policy)
    return {
        **base,
        "status": "violation" if violations else "ok",
        "texts": texts,
        "violations": violations,
        "model": rec.get("model") or "",
        "frames_sent": rec.get("frames_sent") or len(frames),
        "note": ("成片画面发现未经批准文字 / 疑似品牌错拼，已阻断标记待核实；原片保留可下载核对。"
                 if violations else "抽帧视觉复核通过：画面未发现文字。"),
    }


# ---------------------------------------------------------------------------
# V4.104 / 方案E：图片质量扩展检查（复用同一视觉模型通道，不走 Mock/Fallback）
# ---------------------------------------------------------------------------
_IMAGE_QUALITY_SYSTEM = (
    "你是广告素材质量审查员。根据画面判断以下四个维度，只输出严格 JSON，不要解释或 Markdown："
    "{\"product_presence\":{\"status\":\"ok|fail|unverified\",\"detail\":\"...\"},"
    "\"value_visibility\":{\"status\":\"ok|fail|unverified\",\"detail\":\"...\"},"
    "\"visual_conflict\":{\"status\":\"ok|fail|unverified\",\"detail\":\"...\"},"
    "\"ocr\":{\"status\":\"ok|fail|unverified\",\"detail\":\"...\"}}。"
    "product_presence=画面是否有清晰可辨的产品/主体；value_visibility=核心价值主张是否能被看见；"
    "visual_conflict=是否有明显视觉错误/拼接冲突/残缺；ocr=是否出现异常或错误文字。"
    "无法判断的维度填 unverified，不猜测。"
)
_IMAGE_QUALITY_USER = "审查这张推广图的四个质量维度，按系统要求的 JSON 结构输出。"
_IMAGE_QUALITY_DIMS = ("product_presence", "value_visibility", "visual_conflict", "ocr")


async def audit_image_quality(image_bytes: bytes, model_cfg: Optional[dict]) -> dict:
    """用真实视觉模型对单张推广图做四维质量检查。

    与 recognize_frames 同源：无配置 / 非 OpenAI 协议 / 调用失败一律 unavailable，
    绝不走 MockLLM/FallbackLLM，也不冒充已通过。调用方据此标 unverified。
    返回 {"status": "ok"|"unavailable", "checks": {...}, "reason": ...}。
    """
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    missing = [k for k in ("api_key", "base_url", "model") if not str(cfg.get(k) or "").strip()]
    if missing:
        return {"status": "unavailable", "checks": {},
                "reason": "未配置可用的视觉模型：" + "/".join(missing)}
    try:
        from llm_catalog import _resolve_protocol
        if _resolve_protocol(str(cfg.get("provider") or "")) != "openai":
            return {"status": "unavailable", "checks": {},
                    "reason": "视觉质检仅支持 OpenAI 兼容协议"}
    except Exception:
        return {"status": "unavailable", "checks": {}, "reason": "视觉协议识别失败"}

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _IMAGE_QUALITY_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": _IMAGE_QUALITY_USER},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")}},
            ]},
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(str(cfg["base_url"]).rstrip("/") + "/chat/completions",
                             headers={"Authorization": "Bearer " + str(cfg["api_key"]),
                                      "Content-Type": "application/json"},
                             json=payload)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"status": "unavailable", "checks": {},
                "reason": "视觉质检调用失败：" + type(e).__name__ + ": " + str(e)[:120]}
    try:
        cleaned = re.sub(r"^```json\s*|\s*```$", "", str(raw or "").strip(), flags=re.I)
        data = json.loads(cleaned)
    except Exception:
        return {"status": "unavailable", "checks": {}, "reason": "视觉质检返回不可解析 JSON"}
    checks: dict = {}
    for dim in _IMAGE_QUALITY_DIMS:
        row = data.get(dim) if isinstance(data, dict) else None
        st = str((row or {}).get("status") or "unverified") if isinstance(row, dict) else "unverified"
        if st not in ("ok", "fail", "unverified"):
            st = "unverified"
        checks[dim] = {"status": st, "detail": str((row or {}).get("detail") or "")[:200]}
    statuses = [v["status"] for v in checks.values()]
    status = "fail" if "fail" in statuses else ("ok" if all(s == "ok" for s in statuses) else "unverified")
    return {"status": status, "checks": checks, "model": str(cfg["model"])}
