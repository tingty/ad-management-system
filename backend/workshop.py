"""V4.108 素材工作坊：落地页 → 文案 + 图片的一站式简化创作（独立一级模块）。

与「创意工作台」的差别只在入口与呈现：工作坊不暴露路线规划、brief 确认、版位矩阵，
输入一个链接或一句产品描述就能拿到可预览、可下载的素材；底层的分析、文案、出图
仍复用同一套链路与同一份素材标准库，不另写第二套生成逻辑。

三条硬约束
----------
1. **只用已验证模型**：只采用「大模型配置」里该用途当前生效、且连通性测试通过的配置。
   未配置 / 未测试通过 / 配置不完整，一律在调用前阻断（needs_input），
   绝不用 Mock 或本地模板冒充交付物。
2. **回退如实标注**：文本模型回退 Mock、图片回退 Pillow 模板时，结果带 `fallback` 标记，
   不把兜底内容当成「AI 生成」交付。
3. **尺寸只来自标准库**：本模块不硬编码任何像素，尺寸、比例与核验级别全部取自
   `media_spec_library`，与素材标准库页面、生成链路同源。
"""
from __future__ import annotations

import math
import re
from typing import Iterable

#: 一次创作最多出几张图（控制费用与等待时间）
MAX_IMAGES = 6

#: 用途 → 中文短名（前端只显示这些，不展示模型细节以外的说明）
USAGE_LABEL = {"analysis": "分析模型", "copy": "文案模型", "image": "图片模型"}

#: 首页只取「主素材」类规则，忽略 logo 位、上传式横幅等次要规则，
#: 避免把 6 个 banner 尺寸一次性堆到界面上。
_MAIN_ROLES = ("image_main", "story_vertical", "carousel_image",
               "image_landscape", "image_square")

#: 平台展示顺序：主流大媒体在前，其余按标准库出现顺序
_PLATFORM_ORDER = ("Meta", "Google", "TikTok", "Unity", "AppLovin",
                   "Mintegral", "Moloco", "Adsterra")

_URL_RE = re.compile(r"^https?://\S+$", re.I)


# ---------------------------------------------------------------- 输入解析

def split_input(raw: str) -> tuple[str, str]:
    """把输入拆成（链接, 文本）。

    只把「整行就是一个 http(s) 链接」当链接，其余一律当产品描述——
    避免把「链接 + 一段说明」误当成纯 URL 丢掉用户写的内容。
    """
    s = (raw or "").strip()
    if not s:
        return "", ""
    return (s, "") if _URL_RE.match(s) else ("", s)


# ---------------------------------------------------------------- 模型闸门

def _cfg_view(cfg, usage: str, reason: str = "") -> dict:
    return {
        "usage": usage,
        "label": USAGE_LABEL.get(usage, usage),
        "ready": not reason,
        "reason": reason,
        "name": (getattr(cfg, "name", "") or "") if cfg else "",
        "provider": (getattr(cfg, "provider", "") or "") if cfg else "",
        "model": (getattr(cfg, "model", "") or "") if cfg else "",
        "config_id": getattr(cfg, "id", None) if cfg else None,
        "last_test_at": (cfg.last_test_at.isoformat() if cfg and cfg.last_test_at else None),
    }


def _rows_serving(db, usage: str) -> list:
    """所有「勾了这个用途」的配置行（含停用 / 不完整的），仅用于给出准确原因。"""
    from models import ModelConfig
    from providers import _usages_of

    return [c for c in db.query(ModelConfig).all() if usage in _usages_of(c)]


def _reason_of(db, usage: str, cfg) -> str:
    """未就绪的**具体**原因：区分「没配」「配了但停用」「配了但要素不全」「没测过」「测了没过」。

    V4.109：原来只有一句「未配置」，真实环境里「已经配了图片模型、只是没点过测试」
    会被误读成系统看不到这条配置。排查时最需要的正是这几句差别。
    """
    from providers import _usable

    if cfg is None:
        rows = _rows_serving(db, usage)
        if not rows:
            return "未配置"
        active = [c for c in rows if c.is_active]
        if not active:
            return "已配置但已停用"
        if not any(_usable(c) for c in active):
            return "配置不完整（缺少 Key / 地址 / 模型）"
        if all(c.last_test_ok is False for c in active):
            return "最近一次连通测试未通过"
        return "尚未测试通过"
    if not _usable(cfg):
        return "配置不完整（缺少 Key / 地址 / 模型）"
    if cfg.last_test_ok is not True:
        return "最近一次连通测试未通过" if cfg.last_test_ok is False else "尚未测试通过"
    return ""


def model_status(db) -> dict:
    """三种用途当前生效配置的「可用 / 未就绪」状态。

    `ready` 只有在「配置存在 + 三要素完整 + 最近一次连通测试成功」时才是 True；
    未测试（last_test_ok is None）同样按未就绪处理——工作坊不拿没验证过的模型跑真实费用。
    未就绪时 `reason` 必须具体到「停用 / 要素不全 / 未测试 / 测试失败」，便于在真实
    环境里一眼定位是配置问题还是测试问题；`candidates` 给出该用途被勾选的配置条数。
    """
    from providers import _active_config, get_image

    items = []
    for usage in ("analysis", "copy", "image"):
        cfg = _active_config(db, usage)
        reason = _reason_of(db, usage, cfg)
        if not reason and usage == "image" and get_image(db) is None:
            reason = "图片模型不可用（协议未识别）"
        item = _cfg_view(cfg, usage, reason)
        item["candidates"] = len(_rows_serving(db, usage))
        items.append(item)
    missing = [i["label"] for i in items if not i["ready"]]
    return {"items": items, "ready": not missing, "missing": missing}


def missing_models(db, usages: Iterable[str]) -> list[dict]:
    """返回指定用途里未就绪的条目（空列表 = 全部可用）。"""
    want = set(usages)
    st = model_status(db)
    return [i for i in st["items"] if i["usage"] in want and not i["ready"]]


def workbench_model_status(db) -> dict:
    """V4.113：创意工作台的模型就绪视图（以「实际会调用哪条配置」为准）。

    工作坊是硬门：只认「显式配置 + 最近测试通过」，因为不拿没验证过的模型跑真实费用。
    创意工作台是既有链路：`providers._pick_config` 在「全部未测试 / 测试失败」时仍会
    选中配置并真实调用，所以这里的 ready 必须与实际调用口径一致，否则会出现
    「页面提示模型未就绪、点生成却成功了」的状态矛盾。`last_test_ok` 不为 True 时
    不判未就绪，只用 note 如实提示，便于用户自行决定是否重新测试。

    另外允许「文案模型缺失时复用分析模型」（两者都是 chat 能力），复用如实标成
    `reused_from` + `note`，与 `get_llm_with_info(allow_reuse=True)` 行为一致。
    """
    from providers import _active_config, get_image

    st = model_status(db)
    by = {i["usage"]: i for i in st["items"]}
    for usage in ("analysis", "copy", "image"):
        item = by.get(usage)
        if not item or item["ready"]:
            continue
        cfg = _active_config(db, usage)
        if cfg is None:
            continue
        if usage == "image" and get_image(db) is None:
            continue  # 协议未识别，确实不可用（与 model_status 口径保持一致）
        note = ("最近一次连通测试未通过，建议重新测试" if cfg.last_test_ok is False
                else "尚未测试连通性（系统仍按此配置调用）")
        by[usage] = dict(item, ready=True, reason="", note=note,
                         last_test_ok=cfg.last_test_ok)
    ana, copy, image = by.get("analysis"), by.get("copy"), by.get("image")
    if copy and not copy["ready"] and ana and ana["ready"]:
        copy = dict(copy, ready=True, reason="", reused_from="analysis",
                    note="未单独配置文案模型，将复用分析模型 %s/%s"
                         % (ana.get("provider") or "—", ana.get("model") or "—"))
    items = [i for i in (ana, copy, image) if i]
    missing = [i["label"] for i in items if not i["ready"]]
    return {"items": items, "ready": not missing, "missing": missing}


# ---------------------------------------------------------------- 规格选项

def _wh(size: str) -> tuple[int, int]:
    try:
        w, h = str(size).lower().replace("×", "x").split("x")
        return int(w), int(h)
    except Exception:
        return 0, 0


def aspect_of(size: str) -> str:
    """1080x1350 → 4:5（按最大公约数算，不猜「近似比例」）。"""
    w, h = _wh(size)
    if not w or not h:
        return ""
    g = math.gcd(w, h)
    return f"{w // g}:{h // g}"


def size_label(size: str) -> str:
    w, h = _wh(size)
    return f"{aspect_of(size)} · {w}×{h}" if w and h else str(size)


def _acceptable(platform: str, size: str, spec_id: str) -> bool:
    """这个「平台 + 尺寸 + spec_id」组合能否通过出图执行期的媒体规则。

    V4.111：工作坊把尺寸交给 `generation_jobs` 后，`run_job` 会用
    `media_platforms.validate_task_matrix()` 再校验一次。此前 `platform_options()`
    只查素材标准库，导致库里登记、但旧规则目录未收录的尺寸（如 Google 1200x1200、
    TikTok 640x640）被摆到界面上，用户选了就必然在出图阶段被判「不在允许清单」，
    任务失败而页面拿不到任何原因——表现就是「选了尺寸却生成不出图片」。

    这里直接**调用执行期同一个校验函数**，不做第二套规则：能选的必然能出图。
    """
    from media_platforms import validate_task_matrix, MediaRuleError

    try:
        validate_task_matrix(platform, [{"size": size, "spec_id": spec_id}])
        return True
    except MediaRuleError:
        return False


def platform_options() -> list[dict]:
    """按标准库列出「平台 → 可选尺寸」，每个尺寸带 spec_id / 比例 / 核验级别。

    V4.111：只保留能通过执行期媒体规则的尺寸（同一套规则函数判定），
    避免界面可选、任务必败。
    """
    from media_spec_library import all_entries, image_targets

    seen: list[str] = []
    for e in all_entries():
        if e.media == "image" and e.platform not in seen:
            seen.append(e.platform)
    ordered = [p for p in _PLATFORM_ORDER if p in seen]
    ordered += [p for p in seen if p not in ordered]

    out = []
    for p in ordered:
        rows, sizes, used = [], [], set()
        for t in image_targets(p):
            if t.get("asset_role") not in _MAIN_ROLES:
                continue
            for s in (t.get("sizes") or []):
                if s in used:
                    continue
                if not _acceptable(p, s, t.get("spec_id") or ""):
                    continue
                used.add(s)
                sizes.append({
                    "size": s,
                    "aspect": aspect_of(s),
                    "label": size_label(s),
                    "spec_id": t.get("spec_id") or "",
                    "ad_product": t.get("ad_product") or "",
                    "verification": t.get("verification") or "",
                })
        if sizes:
            out.append({"platform": p, "sizes": sizes})
    return out


def resolve_targets(rows: Iterable[dict]) -> tuple[list[dict], list[str]]:
    """把前端选的 {platform, sizes[]} 解析成受控任务清单（服务端重新查标准库）。

    只接受本库登记过的「平台 + 尺寸」组合；未知组合直接报错，不静默换尺寸。
    返回 (targets, errors)，targets 附带 spec_id / 比例 / 核验级别供展示与出图共用。
    """
    options = {o["platform"]: {s["size"]: s for s in o["sizes"]} for o in platform_options()}
    targets, errors, seen = [], [], set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        p = str(row.get("platform") or "").strip()
        if p not in options:
            errors.append(f"未登记的平台：{p or '(空)'}")
            continue
        for raw in (row.get("sizes") or []):
            size = str(raw or "").strip()
            if not size:
                continue
            hit = options[p].get(size)
            if not hit:
                errors.append(f"{p} 未登记尺寸 {size}")
                continue
            key = (p, size)
            if key in seen:
                continue
            seen.add(key)
            targets.append({**hit, "platform": p})
    return targets, errors


def group_targets(targets: Iterable[dict]) -> dict[str, list[dict]]:
    """按平台分组并保留选择顺序（出图按平台各建一个任务）。"""
    grouped: dict[str, list[dict]] = {}
    for t in targets or []:
        grouped.setdefault(str(t.get("platform") or ""), []).append(t)
    return grouped


# ---------------------------------------------------------------- 文案整形

def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value or "").strip()


def copy_view(platform: str, result: dict) -> dict:
    """把平台文案结果整形成界面可直接渲染的「标签 → 值」，并如实标注是否回退。"""
    result = result if isinstance(result, dict) else {}
    schema = result.get("schema") or []
    fields = result.get("fields") or {}
    rows = []
    for f in schema:
        key = str(f.get("key") or "")
        if not key:
            continue
        raw = fields.get(key)
        values = [str(x).strip() for x in (raw if isinstance(raw, list) else [raw])
                  if str(x or "").strip()]
        if values:
            rows.append({"key": key, "label": f.get("label") or key,
                         "max": f.get("max") or 0, "values": values})
    mi = result.get("model_info") or {}
    blocked = result.get("blocked") if isinstance(result.get("blocked"), dict) else None
    fallback = bool(mi.get("fallback")) or str(mi.get("source") or "") in ("mock", "local")
    review = int((result.get("validation") or {}).get("problem_count") or 0) if isinstance(
        result.get("validation"), dict) else 0
    if blocked:
        # V4.113：模型侧真实原因（鉴权 / 限流 / 超时 / 非 JSON）原样透出，
        # 不再统一成「文案模型未返回有效结果」。
        status, reason = "failed", str(blocked.get("message") or "文案模型未返回有效结果")
    elif fallback:
        status, reason = "failed", "文案模型未返回有效结果，已阻止使用本地模拟内容"
    elif review:
        status, reason = "review", "部分字段需要复核（长度 / 证据）"
    else:
        status, reason = "ok", ""
    text = "\n".join(f"{r['label']}：" + " ｜ ".join(r["values"]) for r in rows)
    return {
        "platform": platform,
        "status": status,
        "reason": reason,
        "rows": rows,
        "text": text,
        "model": {
            "provider": mi.get("provider") or "",
            "model": mi.get("model") or "",
            "config_id": mi.get("config_id"),
        },
    }


def landing_payload(analysis: dict) -> dict:
    """把工作坊的统一分析整形成 `LandingAnalysis` 可接受的入参。

    V4.112：类型收敛统一走 `analysis_contract.normalize_analysis()`（文本 / 字符串数组 /
    channels 一次修完），这里只保留「按字段白名单裁剪」——boxes / snapshot 等前端展示用
    的大字段不进任务负载。此前就地修 channels 的做法已收敛掉，避免两套口径。
    """
    from schemas import LandingAnalysis
    from analysis_contract import normalize_analysis

    data = normalize_analysis(analysis if isinstance(analysis, dict) else {})
    return {k: v for k, v in data.items() if k in LandingAnalysis.model_fields}


def overlay_variant(result: dict, analysis: dict) -> dict:
    """出图叠加用的短文案：只取第一行标题 / 正文 / CTA（长文本由版式预算决定是否放得下）。"""
    fields = (result or {}).get("fields") or {}
    return {
        "headline": _first(fields.get("headline") or fields.get("title")),
        "sub": _first(fields.get("primary_text") or fields.get("description")
                      or fields.get("body")),
        "cta": _first(fields.get("cta")),
        "brand": str((result or {}).get("brand") or (analysis or {}).get("brand") or ""),
        "label": str((result or {}).get("platform") or ""),
    }


def image_view(im: dict) -> dict:
    """单张图的结果整形：尺寸说明、比例、是否模板兜底，一并给出。"""
    im = im if isinstance(im, dict) else {}
    size = str(im.get("size") or "")
    ai_ok = bool(im.get("ai_background")) and str(im.get("status")) == "ok"
    return {
        "url": im.get("url") or "",
        "file": im.get("file") or "",
        "size": size,
        "aspect": aspect_of(size),
        "label": size_label(size),
        "placement": im.get("placement") or "",
        "status": "ok" if ai_ok else str(im.get("status") or "fallback"),
        "fallback": not ai_ok,
        "fallback_reason": str(im.get("fallback_reason") or ""),
        "width": im.get("w") or _wh(size)[0],
        "height": im.get("h") or _wh(size)[1],
    }
