"""
媒体推广广告生成引擎（「素材创作 → 营销推广的媒体平台设置」专用）。

职责（严格遵循用户需求）：
1. 文案生成（generate_media_copy）：必须结合「落地页分析结论」(8 字段) 作为依据，调用已配置
   大模型产出平台结构化文案；生成后立即返回，前端展示并允许编辑；同时如实标注本次调用的模型。
2. 图片生成（generate_media_images）：以「用户勾选的创意文案组合 + 落地页分析结论 +
   风格/样式/颜色选项」为依据，调用文生图大模型产出背景，再叠加文案合成为可投放 PNG；
   无模型时用 Pillow 模板兜底，并如实标注图片实际调用的模型（或回退）。
   V4.38：文案组合按版位顺序轮换，每张图片回传所用组合，未勾选的文案不会出现在图片上。
   V4.40 / F07：任务矩阵可逐行指定 concept_index，同一概念的主标题、证据与 CTA 一起出图，
     不再由后端按版位取模机械配对；旧调用（不带 concept_index）仍按序轮换。
   V4.40 / F11：每批独立临时目录 + 供应商并发 / 超时限制 + 逐图状态（成功 / 回退 / 失败），
     批次可为 partial_success / failed，失败与回退都不计入「全部 AI 成功」。
   V4.40 / F08：每张图与导出元数据标记 ad_product / asset_role / os / spec_version。

复用既有能力：
- providers.get_llm_with_info / finalize_invocation / get_image / parse_json / UPLOAD_DIR / _active_config
- presets.build_directives / style_visual / palette_prompt / DIRECTION_MOOD / STYLE_TO_BG / DIRECTION_TO_BG / COLOR_TO_PALETTE
- imaging.render_ad_png
- text_utils.fit_text
- media_platforms.get_media_platform
"""
import os
import asyncio
import json
import time
import uuid
import urllib.request
import urllib.parse

from providers import (get_llm_with_info, finalize_invocation,
                       get_image, parse_json, UPLOAD_DIR, _active_config)
from presets import (build_directives, style_visual, palette_prompt,
                     DIRECTION_MOOD, STYLE_TO_BG, DIRECTION_TO_BG, COLOR_TO_PALETTE)
# V4.35：广告推广文案 / 推广图片的提示词改由「素材提示词」统一管理，保存即生效
from services import get_prompt
from prompt_catalog import (render_prompt, compose_copy_prompt, compose_image_prompt,
                            load_preset_overrides, MEDIA_IMAGE_SYS)
from imaging import render_ad_png, text_budget, TextOverflowError
from text_utils import fit_text, clip_report
from industry_profiles import (resolve_profile, is_complete_sentence, missing_protected,
                               protected_fragments)
from media_platforms import get_media_platform, SPEC_VERSION
from batch_workspace import BatchWorkspace

# V4.40 / F11：供应商级并发上限、单任务超时与本地渲染重试（不重试已计费的模型调用）。
MAX_CONCURRENT_IMAGE_TASKS = int(os.getenv("AD_MAX_IMAGE_CONCURRENCY", "4"))
IMAGE_TASK_TIMEOUT_SECONDS = int(os.getenv("AD_IMAGE_TASK_TIMEOUT", "200"))
MAX_RENDER_RETRIES = 1
_SUPPLIER_SEMS: dict[int, asyncio.Semaphore] = {}


def _supplier_semaphore() -> asyncio.Semaphore:
    """按事件循环维护全局信号量，限制跨批次的供应商并发（供应商限流）。"""
    key = id(asyncio.get_running_loop())
    sem = _SUPPLIER_SEMS.get(key)
    if sem is None:
        sem = asyncio.Semaphore(MAX_CONCURRENT_IMAGE_TASKS)
        _SUPPLIER_SEMS[key] = sem
    return sem


# ----------------------------- 文案字段结构（含 TikTok） -----------------------------
# 与 creative.COPY_SCHEMA 保持一致，并补齐 specs_data 缺失的 TikTok。
MEDIA_COPY_SCHEMA = {
    "Facebook": [
        {"key": "primary_text", "label": "主文案", "max": 125, "count": 1},
        {"key": "headline", "label": "标题", "max": 40, "count": 3},
        {"key": "description", "label": "描述", "max": 30, "count": 1},
        {"key": "cta", "label": "CTA 按钮", "max": 24, "count": 1},
    ],
    "Google": [
        {"key": "headline", "label": "RSA 标题", "max": 30, "count": 5},
        {"key": "description", "label": "RSA 描述", "max": 90, "count": 3},
    ],
    "Unity": [
        {"key": "headline", "label": "标题", "max": 30, "count": 1},
        {"key": "body", "label": "正文", "max": 50, "count": 1},
        {"key": "cta", "label": "CTA", "max": 20, "count": 1},
    ],
    "AppLovin": [
        {"key": "headline", "label": "标题", "max": 40, "count": 1},
        {"key": "body", "label": "正文", "max": 90, "count": 1},
        {"key": "cta", "label": "CTA", "max": 20, "count": 1},
    ],
    "Adsterra": [
        {"key": "title", "label": "标题", "max": 40, "count": 1},
        {"key": "description", "label": "描述", "max": 60, "count": 1},
        {"key": "cta", "label": "CTA", "max": 20, "count": 1},
    ],
    "Mintegral": [
        {"key": "headline", "label": "标题", "max": 40, "count": 1},
        {"key": "body", "label": "正文", "max": 90, "count": 1},
        {"key": "cta", "label": "CTA", "max": 20, "count": 1},
    ],
    "TikTok": [
        {"key": "headline", "label": "标题", "max": 40, "count": 1},
        {"key": "body", "label": "文案", "max": 100, "count": 1},
        {"key": "cta", "label": "CTA", "max": 20, "count": 1},
    ],
}

# V4.40 / F08：同一平台不同广告产品的文案字段不同。
# 说明书指出「Google 文案使用 RSA 字段，图片却混合展示横幅和应用广告位」：
# 这里允许按 ad_product 显式选择 schema，避免把 RSA 长描述当作 UAC 图片素材文案。
MEDIA_COPY_SCHEMA_BY_PRODUCT = {
    ("Google", "Google App Campaign (UAC)"): [
        {"key": "headline", "label": "UAC 标题", "max": 30, "count": 2},
        {"key": "description", "label": "UAC 描述", "max": 90, "count": 2},
    ],
}


def copy_schema_for(platform: str, ad_product: str = "") -> list:
    """按平台（+ 可选广告产品）取文案 schema；未知 ad_product 不影响旧行为。"""
    schema = MEDIA_COPY_SCHEMA_BY_PRODUCT.get((platform, ad_product))
    if schema:
        return schema
    return MEDIA_COPY_SCHEMA.get(platform) or MEDIA_COPY_SCHEMA["AppLovin"]


# FB CTA 枚举 → 人读文案（模型若返回枚举则还原）
FB_CTA_HUMAN = {
    "SHOP_NOW": "Shop Now", "LEARN_MORE": "Learn More", "DOWNLOAD": "Download",
    "INSTALL_MOBILE_APP": "Install App", "SIGN_UP": "Sign Up", "GET_OFFER": "Get Offer",
    "PLAY_GAME": "Play Game", "SUBSCRIBE": "Subscribe",
}

LANG_NAME = {"en": "English", "es": "Spanish", "pt": "Portuguese", "id": "Indonesian",
             "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic",
             "fr": "French", "de": "German"}


# ----------------------------- 工具 -----------------------------
def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            d = obj.model_dump()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            d = obj.dict()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _size_wh(size: str):
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1080


def _brand_of(analysis: dict) -> str:
    """V4.39 / F02：品牌只来自结构化数据 / 官方页面资料 / 用户明确确认。

    此前用 host 倒数第二段推导：`convert.ctypy.com` → `Ctypy`、
    `shop.example.co.uk` → `Co`。追踪域名与多级后缀都会让品牌错误，
    且域名是投放追踪信息，不是产品身份。无法确认时返回空串并由前端标注「待核实」。
    """
    return str((analysis or {}).get("brand") or "").strip()[:80]


# ----------------------------- 文案生成 -----------------------------
def _analysis_context(analysis: dict, platform: str, lang: str, db=None) -> str:
    """把落地页 8 字段分析结论拼成「生成依据」提示词（必须作为文案/图片的事实基础）。

    V4.35：结尾的指令部分改由「素材提示词 → 广告推广文案 · 分析结论注入」(media_context) 提供，
    可在页面编辑；db 为 None 时沿用内置兜底，保证任何调用点都不会因缺 db 而失败。
    """
    lines = []
    ind = (analysis.get("industry") or "").strip()
    typ = (analysis.get("type") or "").strip()
    aud = (analysis.get("audience") or "").strip()
    comp = analysis.get("competitors") or []
    adv = analysis.get("advantages") or []
    channels = analysis.get("channels") or []
    lang_name = (analysis.get("language") or "").strip()

    if typ:
        lines.append(f"网站类型: {typ}")
    if ind:
        lines.append(f"所属行业/领域: {ind}")
    if aud:
        lines.append(f"目标对象/人群: {aud}")
    if lang_name:
        lines.append(f"落地页语言: {lang_name}")
    if adv:
        lines.append("核心优势/卖点: " + "；".join(adv))
    if comp:
        lines.append("主要竞品: " + "；".join(comp))
    if channels:
        recs = []
        for c in channels:
            if isinstance(c, dict):
                p = c.get("platform") or ""
                r = c.get("reason") or ""
                if p:
                    recs.append(f"- {p}: {r}")
        if recs:
            lines.append("推广途径建议（来自落地页分析）:\n" + "\n".join(recs))
    # V4.39：行业画像参与文案生成，其它行业只改配置即可调整表达重点
    profile = resolve_profile(analysis, key=(analysis.get("industry_profile") or ""))
    lines.append(f"行业画像: {profile['label']}；价值维度: {'；'.join(profile['value_axes'])}；"
                 f"文案重点: {profile['copy_focus']}")
    facts = "\n".join(lines)
    if db is None:
        return (facts + f"\n请基于以上真实分析结论，为媒体平台【{platform}】"
                "撰写贴合其版位与受众调性的广告文案，不得编造页面未呈现的事实。")
    return render_prompt(get_prompt(db, "media_context"),
                         {"CONTEXT": facts, "PLATFORM": platform})


def _schema_instr(schema) -> str:
    parts = []
    for f in schema:
        if f["count"] > 1:
            parts.append(f"{f['key']}: 字符串数组，最多 {f['count']} 条，每条 ≤{f['max']} 字符")
        else:
            parts.append(f"{f['key']}: 字符串，≤{f['max']} 字符")
    return "；".join(parts)


def _limits_instr(lim: dict, schema) -> str:
    by_key = {f["key"]: f["max"] for f in schema}
    out = []
    # 优先用平台目录里明确的红线
    if lim.get("title_max"):
        out.append(f"标题≤{lim['title_max']}")
    if lim.get("description_max"):
        out.append(f"描述≤{lim['description_max']}")
    if lim.get("primary_text_max"):
        out.append(f"主文案≤{lim['primary_text_max']}")
    if lim.get("body_max"):
        out.append(f"正文≤{lim['body_max']}")
    # 补充 schema 中尚未覆盖的字段
    for k, mx in by_key.items():
        label = {"primary_text": "主文案", "headline": "标题", "description": "描述",
                 "body": "正文", "title": "标题", "cta": "CTA"}.get(k, k)
        if not any(label in o for o in out):
            out.append(f"{label}≤{mx}")
    return "；".join(out) or "遵守各字段字数上限"


def _build_fields_checked(parsed: dict, schema, profile: dict | None = None) -> dict:
    """把模型 JSON 映射到平台字段，**保留原始输出与裁剪状态**（V4.39 / F01）。

    此前 fit_text 的 clipped 标记被丢弃，_validate 只看长度，于是 "Book in minutes."
    被裁成 "Book in" 仍判合格。现在返回 fields / clips / raw_fields：
    clips 里含原文、裁剪结果、丢掉的部分与必须保留的语义片段，供语义压缩与阻断使用。
    """
    out: dict = {}
    clips: list[dict] = []
    raw: dict = {}
    for f in schema:
        key, mx, cnt = f["key"], f["max"], f["count"]
        if key == "cta":
            v = parsed.get("cta") or parsed.get("cta_button") or ""
            if isinstance(v, list):
                v = v[0] if v else ""
            v = str(v or "").strip()
            if v and v.upper() in FB_CTA_HUMAN:
                v = FB_CTA_HUMAN[v.upper()]
            raw[key] = v
            out["cta"] = v
            continue
        if cnt > 1:
            arr = parsed.get(key)
            if not isinstance(arr, list):
                arr = [arr] if arr else []
            raw[key] = list(arr)
            clipped = []
            for idx, x in enumerate(arr):
                s = str(x or "").strip()
                if not s:
                    continue
                rep = clip_report(s, mx)
                clipped.append(rep["result"])
                if rep["clipped"]:
                    clips.append({"field": key, "index": idx + 1, **rep,
                                  "protected": protected_fragments(rep["original"], profile)})
            out[key] = (clipped[:cnt] if clipped else
                        ([fit_text(str(parsed.get(key, "")), mx)[0]] if parsed.get(key) else []))
        else:
            v = parsed.get(key)
            if isinstance(v, list):
                v = v[0] if v else ""
            v = str(v or "").strip()
            raw[key] = v
            rep = clip_report(v, mx)
            out[key] = rep["result"]
            if rep["clipped"]:
                clips.append({"field": key, "index": 1, **rep,
                              "protected": protected_fragments(rep["original"], profile)})
    return {"fields": out, "clips": clips, "raw_fields": raw}


def _build_fields(parsed: dict, schema) -> dict:
    """兼容旧调用：只返回字段结构。"""
    return _build_fields_checked(parsed, schema)["fields"]


def _validate(fields: dict, schema, needs_revision: list | None = None) -> dict:
    problems = []
    for f in schema:
        key, mx, cnt = f["key"], f["max"], f["count"]
        v = fields.get(key)
        if not v:
            problems.append({"level": "error", "field": f["label"], "msg": "缺失"})
            continue
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if len(str(x)) > mx:
                problems.append({"level": "error", "field": f["label"],
                                 "msg": f"超 {mx} 字（当前 {len(str(x))}）"})
        if isinstance(v, list) and len(v) < cnt:
            problems.append({"level": "warn", "field": f["label"],
                             "msg": f"建议 {cnt} 条，当前 {len(v)} 条"})
    needs_revision = needs_revision or []
    for item in needs_revision:
        problems.append({"level": "error", "field": item.get("label") or item.get("field", ""),
                         "msg": "超长文案语义压缩未通过，需人工修改；不得输出残句"})
    issues = [{"level": p["level"], "code": p["field"], "message": p["msg"]} for p in problems]
    valid = not any(p["level"] == "error" for p in problems)
    return {"valid": valid, "ok": valid,
            "status": "needs_revision" if needs_revision else ("ok" if valid else "invalid"),
            "issues": issues, "problems": problems, "needs_revision": needs_revision}


# ----------------------------- 语义压缩（F01） -----------------------------
COMPRESS_MAX_ATTEMPTS = 2      # 单个字段最多重试 2 次
COMPRESS_MAX_CALLS = 6         # 单次文案生成最多 6 次压缩调用，控制成本


async def _semantic_compress(llm, field: str, original: str, limit: int,
                             lang: str, profile: dict, attempt: int) -> str:
    """请求模型把超长文案压缩成**完整短句**，限定事实与字符预算（说明书 T01 / T02）。"""
    must_keep = protected_fragments(original, profile)
    axes = "、".join(profile.get("value_axes") or []) or "页面已呈现的核心价值"
    sys_prompt = (
        "你是广告文案压缩器。只改写用户给出的原文，不新增任何事实、价格、优惠、评价或效果数据。"
        "必须输出一个语义完整的短句，不能是半截句，不能用省略号省略必要说明。"
        f"字符预算 ≤ {limit}（按字符计）。优先表达：{axes}。"
        "若原文含否定、限制、价格、期限、订阅/退款条件，必须原样保留其含义。"
        "只返回 JSON：{\"text\": \"压缩后的完整文案\"}。"
    )
    user_prompt = json.dumps({
        "field": field, "language": LANG_NAME.get(lang, "English"),
        "char_budget": limit, "attempt": attempt,
        "must_preserve": must_keep, "value_axes": profile.get("value_axes") or [],
        "original": original,
    }, ensure_ascii=False)
    resp = await llm.chat(sys_prompt, user_prompt)
    parsed = parse_json(resp) or {}
    if isinstance(parsed, dict) and parsed.get("text"):
        return str(parsed["text"]).strip()
    # 兼容模型直接返回一行纯文本
    return (resp or "").strip().strip('"').splitlines()[0].strip() if resp else ""


def _char_table(fields: dict, schema) -> list:
    rows = []
    for f in schema:
        v = fields.get(f["key"])
        if isinstance(v, list):
            for i, x in enumerate(v, 1):
                rows.append({"field": f"{f['label']} {i}", "text": str(x),
                             "len": len(str(x)), "max": f["max"], "over": len(str(x)) > f["max"]})
        elif v:
            rows.append({"field": f["label"], "text": str(v),
                         "len": len(str(v)), "max": f["max"], "over": len(str(v)) > f["max"]})
    return rows


async def generate_media_copy(db, analysis: dict, platform: str, lang: str = "en",
                              ad_product: str = "") -> dict:
    """基于落地页分析结论 + 选中平台，生成可编辑广告文案（V4.39 / F01 + F10，V4.40 / F08）。

    - 保留原始模型输出与每次裁剪的状态；
    - 超长文案请求有限次「语义压缩」，必须保留否定 / 价格条件 / 订阅限制；
    - 压缩仍失败则返回 needs_revision（valid=false），绝不把残句标为合格；
    - 模型展示与真实调用共用同一路由，回退标记在调用结束后刷新。
    """
    platform = platform or "Facebook"
    analysis = _as_dict(analysis)
    profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
    schema = copy_schema_for(platform, ad_product)
    spec = get_media_platform(platform) or {}
    lim = spec.get("copy_limits", {})
    labels = {f["key"]: f["label"] for f in schema}

    ctx = _analysis_context(analysis, platform, lang, db)
    sys_prompt = compose_copy_prompt(
        get_prompt(db, "media_copy_sys"),
        schema=_schema_instr(schema),
        limits=_limits_instr(lim, schema),
        language=LANG_NAME.get(lang, "English"),
        platform=platform,
    )

    llm, info = get_llm_with_info(db, "copy")
    try:
        resp = await llm.chat(sys_prompt, ctx)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        resp, parsed = "", {}
        info = finalize_invocation(info, llm, False)
    model_info = dict(info)
    model_info["role"] = "copy"

    built = _build_fields_checked(parsed, schema, profile)
    fields = built["fields"]
    revisions: list[dict] = []
    needs_revision: list[dict] = []
    compress_llm = None
    compress_calls = 0

    def _write_back(key: str, index: int, value: str):
        cur = fields.get(key)
        if isinstance(cur, list):
            while len(cur) < index:
                cur.append("")
            cur[index - 1] = value
        else:
            fields[key] = value

    for clip in built["clips"]:
        key, index = clip["field"], clip["index"]
        original, limit = clip["original"], clip["limit"]
        success = False
        for attempt in range(1, COMPRESS_MAX_ATTEMPTS + 1):
            if compress_calls >= COMPRESS_MAX_CALLS:
                break
            compress_calls += 1
            if compress_llm is None:
                compress_llm = get_llm_with_info(db, "copy")[0]
            try:
                cand = await _semantic_compress(compress_llm, key, original, limit,
                                                lang, profile, attempt)
            except Exception:
                cand = ""
            cand = str(cand or "").strip()
            lost = missing_protected(original, cand, profile)
            if (cand and len(cand) <= limit and is_complete_sentence(cand) and not lost):
                _write_back(key, index, cand)
                revisions.append({"field": key, "index": index, "status": "compressed",
                                  "before": original, "after": cand,
                                  "attempts": attempt, "protected_kept": clip["protected"]})
                success = True
                break
        if not success:
            # 保留完整原文（不输出残句），但明确阻断：不合格文案不能进入投放
            _write_back(key, index, original)
            needs_revision.append({"field": key, "label": labels.get(key, key),
                                   "index": index, "original": original,
                                   "limit": limit, "protected": clip["protected"],
                                   "reason": "语义压缩未能在字符预算内保留全部必要语义"})
            revisions.append({"field": key, "index": index, "status": "needs_revision",
                              "before": original, "after": original,
                              "attempts": COMPRESS_MAX_ATTEMPTS})

    validation = _validate(fields, schema, needs_revision)
    char_rows = _char_table(fields, schema)
    return {
        "platform": platform,
        "ad_product": ad_product or "",
        "lang": lang,
        "fields": fields,
        "schema": schema,
        "char_table": char_rows,
        "validation": validation,
        "model_info": model_info,
        "brand": _brand_of(analysis),
        "raw_fields": built["raw_fields"],
        "clips": built["clips"],
        "copy_revisions": revisions,
        "needs_revision": needs_revision,
        "industry_profile": profile["key"],
        "industry_profile_label": profile["label"],
        "compress_calls": compress_calls,
    }


# ----------------------------- 图片叠加 / 生成 -----------------------------
def _overlay_text(copy_fields: dict, platform: str, brand: str):
    """从编辑后的文案字段里取 标题/副标/CTA（用于图片叠加）。"""
    headline = copy_fields.get("headline") or copy_fields.get("title") or ""
    if isinstance(headline, list):
        headline = headline[0] if headline else ""
    sub = (copy_fields.get("description") or copy_fields.get("body")
           or copy_fields.get("primary_text") or "")
    if isinstance(sub, list):
        sub = sub[0] if sub else ""
    cta = copy_fields.get("cta") or ""
    if isinstance(cta, list):
        cta = cta[0] if cta else ""
    if isinstance(cta, str) and cta.upper() in FB_CTA_HUMAN:
        cta = FB_CTA_HUMAN[cta.upper()]
    return (headline or "").strip(), (sub or "").strip(), (cta or "").strip()


def build_overlay_text(headline: str, sub: str, cta: str, w: int, h: int,
                       profile: dict | None = None) -> dict:
    """V4.39 / F01：平台正文与图内文字分离，按版位像素预算检查。

    平台正文（primary_text / body / description）属于投放字段，不应整段压到图上；
    图内只放标题 + 短副标 + CTA。超预算时返回 overflow，由调用方阻止该版位出图，
    而不是用省略号或硬截断把必要说明删掉。
    """
    budget = text_budget(w, h)
    headline = (headline or "").strip()
    sub = (sub or "").strip()
    cta = (cta or "").strip()
    overflow = []
    if len(headline) > budget["headline_chars"]:
        overflow.append({"part": "headline", "chars": len(headline),
                         "budget": budget["headline_chars"]})
    if budget["sub_chars"] and len(sub) > budget["sub_chars"]:
        overflow.append({"part": "sub", "chars": len(sub),
                         "budget": budget["sub_chars"]})
    if len(cta) > budget["cta_chars"]:
        overflow.append({"part": "cta", "chars": len(cta),
                         "budget": budget["cta_chars"]})
    return {"headline": headline, "sub": sub, "cta": cta,
            "budget": budget, "overflow": overflow, "ok": not overflow}


def _media_image_prompt(analysis: dict, platform: str, directives: dict, design: dict, db=None) -> str:
    """结合落地页分析结论 + 创意方向/风格/配色，拼文生图背景提示词（不含文字）。

    V4.35：提示词模板改为「素材提示词 → 广告推广图片 · 文生图背景提示词」(media_image_sys)，
    可由总结库一键设为系统默认；db 为 None 时退回内置模板，保证任何调用点都不会失败。
    """
    ind = (analysis.get("industry") or "").strip()
    typ = (analysis.get("type") or "").strip()
    aud = (analysis.get("audience") or "").strip()
    adv = analysis.get("advantages") or []
    comp = analysis.get("competitors") or []

    dir_id = directives.get("direction_id") or ""
    mood = DIRECTION_MOOD.get(dir_id, "")
    style_keys = design.get("styles") or []
    style_desc = "; ".join(style_visual(s) for s in style_keys[:3]) or "modern advertising visual backdrop"
    pal = design.get("palette")

    # 结合落地页分析结论（需求要求：一定要按网站已有分析结论作为生成依据）
    ctx_bits = []
    if adv:
        ctx_bits.append("Product strengths: " + "; ".join(adv[:3]))
    if aud:
        ctx_bits.append(f"Target audience: {aud}")
    if comp:
        ctx_bits.append("Differentiate from competitors: " + ", ".join(comp[:3]))

    variables = {
        "INDUSTRY": ind or "market",
        "SITE_TYPE": typ or ind or "product",
        "AUDIENCE": aud,
        "STRENGTHS": "; ".join(adv[:3]),
        "COMPETITORS": ", ".join(comp[:3]),
        "PLATFORM": platform,
        "MOOD": ("Creative direction mood: %s." % mood) if mood else "",
        "STYLE": style_desc,
        "PALETTE": palette_prompt(pal) or "",
        "BRAND_CONTEXT": ("Brand context from landing page analysis: "
                          + " | ".join(ctx_bits) + ".") if ctx_bits else "",
    }
    template = get_prompt(db, "media_image_sys") if db is not None else MEDIA_IMAGE_SYS
    base = compose_image_prompt(template, variables)
    # V4.39：行业 / 品类局部调整真正进入画面约束。主干（分析 → 文案 → 背景 → 合成）
    # 对所有行业一致，这里只替换主视觉与表达重点；电商与订阅并非系统前提。
    profile = resolve_profile(analysis, key=(analysis.get("industry_profile") or ""))
    subject = (f"行业视觉约束（局部调整）: {profile['visual_subject']}。"
               f"表达重点: {'; '.join(profile['value_axes'])}。"
               "不得虚构商品外观、标签、价格、评价与效果数据。")
    return f"{base}\n{subject}"


def _cleanup_ai_bgs():
    """兼容旧调用名：只回收**超时遗留**的批次目录，不再按通配符删除其它批次的文件。

    正常批次由 `BatchWorkspace.cleanup()` 在 finally 中清理自身文件（F11）。
    """
    return BatchWorkspace.cleanup_stale(UPLOAD_DIR)


_LOGO_EXT = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg", ".webp": ".webp"}


def _resolve_logo_local(logo_url: str, workspace: BatchWorkspace | None = None):
    """把前端传来的 logo（已上传的 /files/... 或远程 URL）解析为本地文件路径。

    V4.40 / F11：远程下载的 Logo 写入**本批次目录**并登记到本批次文件清单；
    用户上传的 /files/... 是持久资产，不登记、不随批次清理。
    """
    if not logo_url:
        return None
    if logo_url.startswith("/files/"):
        name = logo_url[len("/files/"):]
        local = os.path.join(UPLOAD_DIR, name)
        return local if os.path.exists(local) else None
    if logo_url.startswith("http://") or logo_url.startswith("https://"):
        if workspace is None:
            return None
        try:
            ext = os.path.splitext(urllib.parse.urlparse(logo_url).path)[1].lower()
            ext = _LOGO_EXT.get(ext, ".png")
            rel = workspace.temp_name("mlogo", ext)
            dst = os.path.join(UPLOAD_DIR, rel)
            req = urllib.request.Request(
                logo_url, headers={"User-Agent": "Mozilla/5.0 (compatible; AdFactory/4.40)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
            workspace.register(dst)
            return dst
        except Exception:
            return None
    local = os.path.join(UPLOAD_DIR, os.path.basename(logo_url))
    return local if os.path.exists(local) else None


async def generate_media_images(db, analysis: dict, platform: str, lang: str,
                                copy_fields: dict, style_opts: dict, slots: list,
                                logo: str = "", copy_variants: list | None = None,
                                rules_meta: dict | None = None) -> dict:
    """基于「任务矩阵 + 创意文案组合 + 落地页分析结论 + 风格」生成推广图片素材。

    V4.38：copy_variants 为前端按勾选文案拼出的组合；不传时兼容旧行为。
    V4.40 / F07：slots 每行可指定 concept_index，同一概念的标题 / 证据 / CTA 一起出图。
    V4.40 / F08：每行带服务端解析的 ad_product / asset_role / os / spec_version，随图与导出标注。
    V4.40 / F11：批次独立临时目录、供应商并发 / 超时限制、逐图状态与失败隔离。
    返回：images / image_model / note / count / status / issues / skipped / task_results / rules。
    """
    platform = platform or "Facebook"
    analysis = _as_dict(analysis)
    style_opts = style_opts or {}
    rules_meta = dict(rules_meta or {})
    profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
    # 上线保留开关：strict_text=False 可临时回到旧的宽松排版（默认严格）
    strict_text = style_opts.get("strict_text", True) is not False
    creative_direction = style_opts.get("creative_direction") or ""
    content_style = style_opts.get("content_style") or ""
    color_scheme = style_opts.get("color_scheme") or ""
    spec = get_media_platform(platform) or {}
    spec_sizes = spec.get("image_sizes") or ["1080x1080"]

    directives = build_directives(creative_direction, content_style, color_scheme, lang=lang,
                                  overrides=load_preset_overrides(db))
    design = {}
    bg_key = None
    if content_style and content_style in STYLE_TO_BG:
        bg_key = STYLE_TO_BG[content_style]
    elif creative_direction and creative_direction in DIRECTION_TO_BG:
        bg_key = DIRECTION_TO_BG[creative_direction]
    if bg_key:
        design["styles"] = [bg_key]
    if color_scheme and color_scheme in COLOR_TO_PALETTE:
        design["palette"] = dict(COLOR_TO_PALETTE[color_scheme])

    brand = ((copy_fields or {}).get("brand")
             or (copy_variants[0].get("brand") if copy_variants and isinstance(copy_variants[0], dict) else "")
             or _brand_of(analysis))
    base_headline, base_sub, base_cta = _overlay_text(copy_fields or {}, platform, brand)

    # V4.38：把前端勾选的文案组合规范化；限制条数与长度，避免异常入参把渲染拖死。
    variants: list[dict] = []
    for raw in (copy_variants or [])[:40]:
        v = raw if isinstance(raw, dict) else {}
        cta = str(v.get("cta") or "").strip()[:120]
        if cta.upper() in FB_CTA_HUMAN:
            cta = FB_CTA_HUMAN[cta.upper()]
        variants.append({
            "headline": str(v.get("headline") or "").strip()[:1000],
            "sub": str(v.get("sub") or "").strip()[:1000],
            "cta": cta,
            "label": str(v.get("label") or "").strip()[:40],
            "concept_id": str(v.get("concept_id") or "").strip()[:40],
        })

    # V4.40 / F11：先回收上次超时遗留的批次目录，再为本批建独立工作区。
    stale = BatchWorkspace.cleanup_stale(UPLOAD_DIR)
    workspace = BatchWorkspace(UPLOAD_DIR)
    batch_id = workspace.batch_id
    batch_request_id = uuid.uuid4().hex[:12]
    started = time.monotonic()

    # 远程 Logo 下载进本批目录；用户上传的 /files/... 是持久资产，不随批次清理。
    logo_path = await asyncio.to_thread(_resolve_logo_local, logo or "", workspace)

    img = get_image(db)
    img_cfg = _active_config(db, "image")
    provider_name = (img_cfg.provider if img_cfg else "template")
    model_name = ((img_cfg.model if img_cfg else "") or "Pillow 品牌渐变模板")
    image_model = {
        "provider": provider_name,
        "model": model_name,
        "role": "image",
        "fallback": True,
        "config_id": (img_cfg.id if img_cfg else None),
        "request_id": batch_request_id,
        "source": "local",
        "error_type": "",
        "retries": 0,
    }

    try:

        # V4.40 / F07：任务矩阵逐行决定概念；后端不再按 idx % len 机械配对不同字段的文案。
        tasks: list[dict] = []
        skipped: list[dict] = []
        for idx, raw_slot in enumerate(slots or []):
            slot = raw_slot if isinstance(raw_slot, dict) else {}
            size = slot.get("size") or spec_sizes[0]
            placement = slot.get("placement") or ""
            w, h = slot.get("w"), slot.get("h")
            if not w or not h:
                w, h = _size_wh(size)
            bg_prompt = _media_image_prompt(analysis, platform, directives, design, db)

            ci = slot.get("concept_index")
            if variants:
                use_idx = ci if isinstance(ci, int) and 0 <= ci < len(variants) else idx % len(variants)
                v = variants[use_idx]
                headline, sub, cta = v["headline"], v["sub"], v["cta"]
                vlabel = v["label"] or f"组合 {use_idx + 1}"
                concept_id = v.get("concept_id") or f"C{use_idx + 1}"
            else:
                use_idx = None
                headline, sub, cta = base_headline, base_sub, base_cta
                vlabel, concept_id = "", ""
            meta = {
                "ad_product": slot.get("ad_product") or "未标注广告产品",
                "asset_role": slot.get("asset_role") or "unspecified",
                "os": slot.get("os") or "unknown",
                "placement_id": slot.get("placement_id") or "",
                "spec_version": slot.get("spec_version") or SPEC_VERSION,
                "concept_index": use_idx,
                "concept_id": concept_id,
            }
            # V4.39 / F01：出图前先按该版位的像素预算核对，超预算直接标记并跳过
            overlay = build_overlay_text(headline, sub, cta, w, h, profile)
            if strict_text and not overlay["ok"]:
                skipped.append({
                    "size": size, "placement": placement, "variant": vlabel,
                    "concept_id": concept_id, "status": "needs_revision",
                    "reason": "图内文案超出该版位可排版预算，已阻止生成；请缩短文案后重试",
                    "overflow": overlay["overflow"], "budget": overlay["budget"],
                    "batch_id": batch_id, **meta,
                })
                continue
            # V4.36：文件名带随机后缀，避免「重新生成」覆盖历史图片。
            ptag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in platform)[:20]
            fn = (f"media_{ptag}_{size}_{uuid.uuid4().hex[:10]}_"
                  f"{abs(hash((placement, size, headline, sub))) % 100000:05d}.png")
            out = os.path.join(UPLOAD_DIR, fn)
            tasks.append({"out": out, "w": w, "h": h, "bg_prompt": bg_prompt,
                          "fn": fn, "size": size, "placement": placement,
                          "logo_path": logo_path, "headline": headline, "sub": sub,
                          "cta": cta, "vlabel": vlabel, "meta": meta, "idx": idx})

        sem = _supplier_semaphore()

        async def _render_one(t: dict) -> dict:
            """一张图一个独立状态：成功 / 模板回退 / 失败，异常不外溢到整批。"""
            meta = t["meta"]
            common = {"size": t["size"], "placement": t["placement"],
                      "variant": t["vlabel"], "concept_id": meta["concept_id"],
                      "batch_id": batch_id, **meta}
            bg_path = None
            ai_ok = False
            provider_error = ""
            retries = 0
            request_id = uuid.uuid4().hex[:12]
            if img is not None:
                # 临时底图写进本批次目录，不与其他批次共享文件名空间。
                rel = workspace.temp_name("mabg")
                try:
                    async with sem:      # F11：供应商并发 / 速率限制
                        bg = await asyncio.wait_for(
                            img.generate(t["bg_prompt"], t["w"], t["h"], rel),
                            timeout=IMAGE_TASK_TIMEOUT_SECONDS)
                    if bg and os.path.isfile(bg):
                        bg_path, ai_ok = bg, True
                    else:
                        provider_error = "文生图供应商未返回可用底图"
                except asyncio.TimeoutError:
                    provider_error = f"文生图请求超时（>{IMAGE_TASK_TIMEOUT_SECONDS}s）"
                except Exception as e:
                    provider_error = f"文生图失败：{type(e).__name__}"
            else:
                provider_error = "未配置 image 用途的文生图模型"
            if not ai_ok and not provider_error:
                provider_error = "未获得 AI 底图"

            for attempt in range(MAX_RENDER_RETRIES + 1):
                try:
                    await asyncio.to_thread(
                        render_ad_png, t["out"], t["w"], t["h"],
                        t["headline"], t["sub"], t["cta"], (brand or "")[:40],
                        bg_path or None, t["logo_path"] or None, None, strict_text)
                    break
                except TextOverflowError as e:
                    return {"__skipped__": {
                        **common, "status": "needs_revision",
                        "reason": f"图内文案无法完整排版：{e}",
                        "budget": text_budget(t["w"], t["h"]),
                    }}
                except Exception as e:
                    if attempt >= MAX_RENDER_RETRIES:
                        return {"__failed__": {
                            **common, "status": "failed",
                            "reason": f"本地渲染失败：{type(e).__name__}: {str(e)[:120]}",
                            "retries": retries, "request_id": request_id,
                        }}
                    # 只重试本地渲染；已成功计费的模型调用绝不重复发起。
                    retries += 1
                    await asyncio.sleep(0)

            return {"__image__": {
                "url": t["out"], "file": t["fn"], "size": t["size"],
                "w": t["w"], "h": t["h"], "placement": t["placement"],
                "variant": t["vlabel"],
                "copy": {"headline": t["headline"], "sub": t["sub"], "cta": t["cta"]},
                "status": "ok" if ai_ok else "fallback",
                "ai_background": ai_ok,
                "fallback": not ai_ok,
                "fallback_reason": "" if ai_ok else provider_error,
                "model": {"provider": provider_name if ai_ok else "template",
                          "model": model_name if ai_ok else "Pillow 品牌渐变模板",
                          "config_id": (img_cfg.id if img_cfg and ai_ok else None),
                          "request_id": request_id},
                "retries": retries,
                "batch_id": batch_id,
                **meta,
            }}

        images: list[dict] = []
        if tasks:
            results = await asyncio.gather(*[_render_one(t) for t in tasks],
                                           return_exceptions=True)
            for t, r in zip(tasks, results):
                if isinstance(r, Exception):
                    skipped.append({
                        "size": t["size"], "placement": t["placement"],
                        "variant": t["vlabel"], "concept_id": t["meta"]["concept_id"],
                        "batch_id": batch_id, **t["meta"],
                        "status": "failed",
                        "reason": f"任务异常：{type(r).__name__}: {str(r)[:120]}",
                    })
                elif isinstance(r, dict) and "__skipped__" in r:
                    skipped.append(r["__skipped__"])
                elif isinstance(r, dict) and "__failed__" in r:
                    skipped.append(r["__failed__"])
                elif isinstance(r, dict) and "__image__" in r:
                    images.append(r["__image__"])
                else:
                    skipped.append({"size": t["size"], "placement": t["placement"],
                                    "status": "failed", "reason": "任务返回了无法识别的结果",
                                    "batch_id": batch_id, **t["meta"]})

        ai_count = sum(1 for x in images if x["ai_background"])
        fallback_count = len(images) - ai_count
        failed_count = sum(1 for x in skipped if x.get("status") == "failed")
        revision_count = sum(1 for x in skipped if x.get("status") == "needs_revision")
        status = "ok" if not skipped else ("partial_success" if images else "failed")
        image_model.update({
            "fallback": fallback_count > 0 or not images,
            "source": ("llm" if ai_count and not fallback_count else
                       "mock" if not ai_count else "mixed"),
            "mixed": ai_count > 0 and fallback_count > 0,
            "ai_success_count": ai_count,
            "template_fallback_count": fallback_count,
            "failed_count": failed_count,
            "needs_revision_count": revision_count,
            "batch_id": batch_id,
        })

        note_bits = [f"本批 {len(images)} 张成功（AI 底图 {ai_count} / 模板兜底 {fallback_count}）"]
        if variants:
            note_bits.append(f"共 {len(variants)} 组创意文案，按任务矩阵指定的概念叠加，同一概念的标题与证据保持一致")
        if image_model["mixed"]:
            note_bits.append("同批存在模板回退，已逐张标注，不按整批 AI 成功计")
        if failed_count:
            note_bits.append(f"{failed_count} 个任务失败，未计入合格素材；可仅重试失败项")
        if revision_count:
            note_bits.append(f"{revision_count} 个版位因图内文案超预算被阻止生成（needs_revision），未输出省略号残图")
        if status == "failed":
            note_bits.append("整批无可用素材，请检查文案与版位设置后重试")
        note = "；".join(note_bits) + "。"

        issues = [{
            "level": "error" if s.get("status") == "failed" else "warning",
            "status": s.get("status", ""),
            "size": s.get("size", ""), "placement": s.get("placement", ""),
            "concept_id": s.get("concept_id", ""),
            "ad_product": s.get("ad_product", ""),
            "message": s.get("reason", ""),
        } for s in skipped]
        task_results = [{
            "status": s.get("status", "failed"), "size": s.get("size", ""),
            "placement": s.get("placement", ""), "concept_id": s.get("concept_id", ""),
            "ad_product": s.get("ad_product", ""), "spec_version": s.get("spec_version", SPEC_VERSION),
            "file": "", "ai_background": False, "fallback": True,
            "error": s.get("reason", ""), "retries": s.get("retries", 0),
            "batch_id": batch_id,
        } for s in skipped] + [{
            "status": x["status"], "size": x["size"], "placement": x["placement"],
            "concept_id": x["concept_id"], "ad_product": x["ad_product"],
            "spec_version": x["spec_version"], "file": x["file"],
            "ai_background": x["ai_background"], "fallback": x["fallback"],
            "error": x["fallback_reason"], "retries": x["retries"],
            "batch_id": batch_id,
        } for x in images]

        return {
            "platform": platform,
            "images": images,
            "image_model": image_model,
            "note": note,
            "count": len(images),
            "copy_variant_count": len(variants),
            "status": status,
            "strict_text": strict_text,
            "issues": issues,
            "skipped": skipped,
            "task_results": task_results,
            "batch_id": batch_id,
            "spec_version": SPEC_VERSION,
            "rules": {**rules_meta,
                      "stale_cleanup": stale,
                      "supplier_concurrency": MAX_CONCURRENT_IMAGE_TASKS,
                      "task_timeout_seconds": IMAGE_TASK_TIMEOUT_SECONDS,
                      "elapsed_ms": int((time.monotonic() - started) * 1000)},
        }
    finally:
        # 只删本批次目录；其它并发批次的临时文件不受影响（说明书 T15）。
        workspace.cleanup()
