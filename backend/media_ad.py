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
- creative_config.resolve_creative_config（文案与图片共用同一份预设解析结果）
- imaging.render_ad_png（按版式 / 品牌 token / Logo 安全区合成）
- text_utils.fit_text
- media_platforms.get_media_platform
"""
import os
import asyncio
import inspect
import json
import time
import uuid
import urllib.request
import urllib.parse

from providers import (get_llm_with_info, finalize_invocation,
                       get_image, parse_json, UPLOAD_DIR, _active_config)
from presets import style_visual, palette_prompt, DIRECTION_MOOD
# V4.35：广告推广文案 / 推广图片的提示词改由「素材提示词」统一管理，保存即生效
from services import get_prompt
# V4.44 / N01：证据→承诺强引用与生成后限定校验
from claims import EvidenceSnapshot, claim_contract, audit_copy_fields
from prompt_catalog import (render_prompt, compose_copy_prompt, compose_image_prompt,
                            load_preset_overrides, MEDIA_IMAGE_SYS)
from imaging import render_ad_png, text_budget, TextOverflowError
from text_utils import fit_text, clip_report
from industry_profiles import (resolve_profile, is_complete_sentence, missing_protected,
                               protected_fragments)
from media_platforms import get_media_platform, SPEC_VERSION
from batch_workspace import BatchWorkspace
# V4.42 / F06：供应商尺寸能力目录、按比例构图与主体保护
from image_capabilities import (plan_generation_size, composition_goal,
                                capability_of, plan_composition)
# V4.41 / F03 + F04：统一创意配置、创意概念与视觉简报
from creative_config import (resolve_creative_config, strategy_block, visual_text_block,
                             build_concept, build_visual_brief, choose_layout,
                             brief_prompt_block, prompt_hash, config_snapshot,
                             CREATIVE_CONFIG_VERSION)

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
    "Meta": [
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
    # V4.44 / N04：Moloco 图片 / 原生角色的文案字段（内部整理，待官方复核）
    "Moloco": [
        {"key": "headline", "label": "标题", "max": 40, "count": 1},
        {"key": "body", "label": "正文", "max": 90, "count": 1},
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
def _evidence_context(analysis: dict) -> str:
    """V4.44 / N01：把 facts / evidence_chain / 限定契约真正送进文案模型。

    V4.43 的 `_analysis_context` 只传 8 字段摘要，证据字段停留在接口结果里，
    模型看不到「哪条承诺该引用哪个编号」，短句因此丢掉 `up to / 最多 / 护理模式`。
    """
    a = analysis if isinstance(analysis, dict) else {}
    snap = EvidenceSnapshot.from_analysis(a)
    if not snap.available:
        return ("【证据状态】本次没有可定位的原文证据快照（旧历史 / 抓取失败）。"
                "禁止输出任何含数字、价格、效果、试用、退货或订阅条件的承诺；"
                "只写页面已明示的中性描述，缺资料须标注为未确认。")
    bits = [f"【不可变证据快照】{snap.snapshot_id}，可引用编号 "
            + "、".join(sorted(snap.valid_ids)[:24])]
    for label, key in (("已验证事实 facts", "facts"), ("营销假设 assumptions", "assumptions"),
                       ("资料缺口 gaps", "gaps")):
        rows = [str(x).strip() for x in (a.get(key) or []) if str(x or "").strip()][:12]
        if rows:
            bits.append(f"{label}：" + "；".join(rows))
    chain = []
    for row in (a.get("evidence_chain") or [])[:16]:
        if isinstance(row, dict):
            claim = str(row.get("claim") or "").strip()[:160]
            ids = "、".join(str(x) for x in (row.get("evidence_ids") or []) if x)
            if claim:
                chain.append(f"- {claim}｜引用 {ids or '（无）'}"
                             + ("｜已剔除无效引用" if row.get("rejected") else ""))
    if chain:
        bits.append("【事实 → 证据映射（只允许引用下列已存在编号）】\n" + "\n".join(chain))
    invalid = [str(x) for x in (a.get("evidence_invalid_ids") or []) if x]
    if invalid:
        bits.append("【已被拒绝的证据编号】" + "、".join(invalid[:24])
                    + "；这些编号不存在或无法定位原文，禁止在文案里沿用其承诺。")
    bits.append(claim_contract(snap))
    return "\n".join(bits)


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
    # V4.44 / N01：证据链与限定契约进入文案依据，不再停留在接口返回里
    lines.append(_evidence_context(analysis))
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
                              ad_product: str = "", style_opts: dict | None = None,
                              creative_config: dict | None = None) -> dict:
    """基于落地页分析结论 + 选中平台，生成可编辑广告文案（V4.39 / F01 + F10，V4.40 / F08）。

    - 保留原始模型输出与每次裁剪的状态；
    - 超长文案请求有限次「语义压缩」，必须保留否定 / 价格条件 / 订阅限制；
    - 压缩仍失败则返回 needs_revision（valid=false），绝不把残句标为合格；
    - 模型展示与真实调用共用同一路由，回退标记在调用结束后刷新。
    - V4.41 / F04：注入 `ResolvedCreativeConfig.strategy` 的编辑后预设文本；
      纯视觉字段（调色板 / 版式 / 背景键）不会进入文案提示词。
    """
    platform = platform or "Meta"
    analysis = _as_dict(analysis)
    profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
    schema = copy_schema_for(platform, ad_product)
    spec = get_media_platform(platform) or {}
    lim = spec.get("copy_limits", {})
    labels = {f["key"]: f["label"] for f in schema}
    config = creative_config or resolve_creative_config(
        style_opts, lang=lang, overrides=load_preset_overrides(db))

    ctx = _analysis_context(analysis, platform, lang, db)
    sys_prompt = compose_copy_prompt(
        get_prompt(db, "media_copy_sys"),
        schema=_schema_instr(schema),
        limits=_limits_instr(lim, schema),
        language=LANG_NAME.get(lang, "English"),
        platform=platform,
        creative=strategy_block(config),
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

    # V4.44 / N01：生成后统一校验证据引用与限定保护，与文案是否超长、是否压缩无关
    claim_audit = audit_copy_fields(fields, analysis)
    for v in (claim_audit.get("violations") or []):
        needs_revision.append({
            "field": v.get("field", ""), "label": labels.get(v.get("field", ""), v.get("field", "")),
            "index": v.get("index") if isinstance(v.get("index"), int) else 0,
            "original": v.get("text", ""), "limit": 0,
            "protected": v.get("missing") or v.get("invalid_ids") or [],
            "reason": "证据 / 承诺校验未通过：" + str(v.get("reason") or ""),
            "type": v.get("type"),
        })
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
        # V4.44 / N01：可追溯的证据→承诺审计（可定位原文 ≠ 商业真实性已审核）
        "claim_audit": claim_audit,
        "industry_profile": profile["key"],
        "industry_profile_label": profile["label"],
        "compress_calls": compress_calls,
        # F04：文案任务归档「当时实际使用的配置」，后续改预设不会覆盖这份快照
        "creative_config": config_snapshot(config),
        "creative_prompt_hash": prompt_hash(sys_prompt),
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
                       profile: dict | None = None, layout: str = "",
                       logo_path: str | None = None) -> dict:
    """V4.39 / F01：平台正文与图内文字分离，按版位像素预算检查。

    平台正文（primary_text / body / description）属于投放字段，不应整段压到图上；
    图内只放标题 + 短副标 + CTA。超预算时返回 overflow，由调用方阻止该版位出图，
    而不是用省略号或硬截断把必要说明删掉。
    V4.41 / F05：预算按所选版式与 Logo 预留框计算，与渲染层使用同一规格。
    """
    budget = text_budget(w, h, layout=layout, logo_path=logo_path)
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


def _media_image_prompt(analysis: dict, platform: str, config: dict,
                        brief: dict | None = None, db=None) -> str:
    """V4.41 / F03 + F04：按「概念 → 视觉简报 → 提示词」顺序逐任务构建背景提示词。

    与 V4.40 的根本差别：本函数**收标题 / 证据 / 概念 / 版式**，且只在文案组合
    选定后调用；不同概念得到不同的主体、动作、证据与构图（说明书 T05）。
    同时把编辑过的全部预设文本原样写入提示词（T06 的唯一标记必须出现）。
    """
    ind = (analysis.get("industry") or "").strip()
    typ = (analysis.get("type") or "").strip()
    aud = (analysis.get("audience") or "").strip()
    adv = analysis.get("advantages") or []
    comp = analysis.get("competitors") or []
    cfg = config or {}
    visual = cfg.get("visual") or {}

    dir_id = (cfg.get("preset_ids") or {}).get("direction") or ""
    mood = DIRECTION_MOOD.get(dir_id, "")
    style_keys = visual.get("styles") or []
    style_desc = "; ".join(style_visual(s) for s in style_keys[:3]) or "modern advertising visual backdrop"
    pal = visual.get("palette") or {}

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

    # V4.39：行业 / 品类局部调整。主干对所有行业一致，只替换主视觉与表达重点。
    profile = resolve_profile(analysis, key=(analysis.get("industry_profile") or ""))
    subject = (f"行业视觉约束（局部调整）: {profile['visual_subject']}。"
               f"表达重点: {'; '.join(profile['value_axes'])}。")

    blocks = [base, subject]
    preset_text = visual_text_block(cfg)
    if preset_text:
        # F04：direction_text / style_text / color_text / design_prompt 原样进供应商请求
        blocks.append("[ResolvedCreativeConfig / F04] " + preset_text)
    if brief:
        # F03：先确定概念再写画面；同一 concept_key 跨尺寸保持承诺一致
        blocks.append(brief_prompt_block(brief))
    needs = [b for b in blocks if b and b.strip()]
    return "\n".join(needs)


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
                                rules_meta: dict | None = None,
                                overlay_mode: str = "text_button") -> dict:
    """基于「任务矩阵 + 创意文案组合 + 落地页分析结论 + 风格」生成推广图片素材。

    V4.38：copy_variants 为前端按勾选文案拼出的组合；不传时兼容旧行为。
    V4.40 / F07：slots 每行可指定 concept_index，同一概念的标题 / 证据 / CTA 一起出图。
    V4.40 / F08：每行带服务端解析的 ad_product / asset_role / os / spec_version，随图与导出标注。
    V4.40 / F11：批次独立临时目录、供应商并发 / 超时限制、逐图状态与失败隔离。
    V4.41 / F03 + F04 + F05：共用一份 ResolvedCreativeConfig；先选概念再做 VisualBrief
      与背景提示词；按版式 / 品牌 token / Logo 安全区逐张合成。
    返回：images / image_model / note / count / status / issues / skipped / task_results /
          rules / creative_config。
    """
    platform = platform or "Meta"
    analysis = _as_dict(analysis)
    style_opts = dict(style_opts or {})
    rules_meta = dict(rules_meta or {})
    profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
    # 上线保留开关：strict_text=False 可临时回到旧的宽松排版（默认严格）
    strict_text = style_opts.get("strict_text", True) is not False
    spec = get_media_platform(platform) or {}
    spec_sizes = spec.get("image_sizes") or ["1080x1080"]

    # F04：唯一一份解析结果。删除此前的 STYLE_TO_BG / COLOR_TO_PALETTE 重复映射，
    # 编辑过的预设文本、调色板与版式都从这里进入文案与画面。
    config = resolve_creative_config(style_opts, lang=lang,
                                     overrides=load_preset_overrides(db))
    cfg_snapshot = config_snapshot(config)
    palette = dict(config["visual"].get("palette") or {})
    dim_ratio = float(config["visual"].get("dim_ratio") or 0.28)

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

    # F03：商品参考图 / 真实 UI。供应商声明支持参考编辑时把原图传给它；
    # 否则退回本地合成，并在归档明确写出能力限制，不假装做了 AI 参考编辑。
    ref_rel = str(style_opts.get("reference_image") or "").strip()
    product_path = None
    if ref_rel.startswith("/files/"):
        candidate = os.path.join(UPLOAD_DIR, os.path.basename(ref_rel[len("/files/"):]))
        if os.path.isfile(candidate):
            product_path = candidate
    try:
        sig = inspect.signature(img.generate) if img is not None else None
        provider_supports_ref = bool(sig and "reference_image" in sig.parameters)
    except (TypeError, ValueError):
        provider_supports_ref = False
    if product_path and provider_supports_ref:
        reference_mode, capability_note = "provider_reference", ""
    elif product_path:
        reference_mode = "local_composite"
        capability_note = ("当前文生图供应商未声明参考编辑能力，已把用户提供的真实商品图"
                           "本地合成到主体区；这不是 AI 参考编辑，商品细节不再生成。")
    else:
        reference_mode = "none"
        capability_note = ("未提供商品参考图；画面只使用落地页事实与行业视觉约束，"
                           "不得虚构商品外观、标签、规格与评价。")

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
        cap_key = getattr(img, "capability_key", "template") if img is not None else "template"
        tasks: list[dict] = []
        skipped: list[dict] = []
        for idx, raw_slot in enumerate(slots or []):
            slot = raw_slot if isinstance(raw_slot, dict) else {}
            size = slot.get("size") or spec_sizes[0]
            placement = slot.get("placement") or ""
            w, h = slot.get("w"), slot.get("h")
            if not w or not h:
                w, h = _size_wh(size)

            # V4.41 / F03：顺序修正 —— 先选文案概念，再构造视觉简报与背景提示词。
            # V4.40 是先算 bg_prompt 再选文案，导致所有概念共用同一画面描述。
            ci = slot.get("concept_index")
            if variants:
                use_idx = ci if isinstance(ci, int) and 0 <= ci < len(variants) else idx % len(variants)
                v = variants[use_idx]
                headline, sub, cta = v["headline"], v["sub"], v["cta"]
                vlabel = v["label"] or f"组合 {use_idx + 1}"
                concept = build_concept(v, use_idx, analysis, profile)
            else:
                use_idx = None
                headline, sub, cta = base_headline, base_sub, base_cta
                concept = build_concept({"headline": headline, "sub": sub, "cta": cta},
                                        idx, analysis, profile)
                vlabel = ""
            concept_id = concept["concept_id"]
            layout = choose_layout(concept, config, w, h)
            brief = build_visual_brief(concept, analysis, profile, config, w, h,
                                       placement=placement,
                                       ad_product=slot.get("ad_product") or "")
            brief["reference_mode"] = reference_mode
            brief["capability_note"] = capability_note
            if reference_mode == "local_composite" and layout == "banner":
                # 小横幅没有可用的主体区，不假称已叠加商品图
                brief["capability_note"] = (capability_note +
                                            " 本版位为小横幅，无可用主体区，未叠加商品图。")
            # V4.42 / F06：宽高作为一个比例整体选供应商已声明的尺寸；
            # 同时把「主体放在安全区、给文字留白」的构图目标写进文生图提示词。
            cap_key = getattr(img, "capability_key", "template") if img is not None else "template"
            cap_params = (img_cfg.params if img_cfg else None) or {}
            gen_plan = plan_generation_size(cap_key, w, h, cap_params)
            bg_prompt = (_media_image_prompt(analysis, platform, config, brief, db)
                         + "\nComposition goal: " + composition_goal(w, h, layout))
            phash = prompt_hash(bg_prompt)

            meta = {
                "ad_product": slot.get("ad_product") or "未标注广告产品",
                "asset_role": slot.get("asset_role") or "unspecified",
                "os": slot.get("os") or "unknown",
                "placement_id": slot.get("placement_id") or "",
                "spec_version": slot.get("spec_version") or SPEC_VERSION,
                "concept_index": use_idx,
                "concept_id": concept_id,
                "concept_key": concept["concept_key"],
                "layout": layout,
                "prompt_hash": phash,
                "creative_config_id": config["config_id"],
                "request_size": gen_plan["request_size"],
                "target_size": [w, h],
                "size_capability": {
                    "provider": gen_plan["provider"],
                    "needs_outpaint": gen_plan["needs_outpaint"],
                    "ratio_delta": gen_plan["ratio_delta"],
                    "size_verified_on": gen_plan["size_verified_on"],
                    "capability_note": gen_plan["capability_note"],
                },
            }
            # V4.39 / F01：出图前先按该版式 + Logo 预留框核对像素预算
            overlay = build_overlay_text(headline, sub, cta, w, h, profile,
                                         layout=layout, logo_path=logo_path)
            if strict_text and not overlay["ok"]:
                skipped.append({
                    "size": size, "placement": placement, "variant": vlabel,
                    "concept_id": concept_id, "status": "needs_revision",
                    "reason": "图内文案超出该版位可排版预算，已阻止生成；请缩短文案后重试",
                    "overflow": overlay["overflow"], "budget": overlay["budget"],
                    "batch_id": batch_id, "task_index": idx, **meta,
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
                          "cta": cta, "vlabel": vlabel, "meta": meta, "idx": idx,
                          "brief": brief, "layout": layout, "palette": palette,
                          "dim_ratio": dim_ratio, "prompt_hash": phash})

        sem = _supplier_semaphore()

        async def _render_one(t: dict) -> dict:
            """一张图一个独立状态：成功 / 模板回退 / 失败，异常不外溢到整批。"""
            meta = t["meta"]
            b = t["brief"]
            brief_view = {k: b.get(k, "") for k in (
                "concept_id", "concept_key", "layout", "subject", "action",
                "setting", "core_promise", "evidence", "reference_mode",
                "capability_note")}
            common = {"size": t["size"], "placement": t["placement"],
                      "variant": t["vlabel"], "concept_id": meta["concept_id"],
                      "batch_id": batch_id, **meta,
                      "visual_brief": brief_view,
                      "creative_config": cfg_snapshot}
            bg_path = None
            ai_ok = False
            provider_error = ""
            retries = 0
            request_id = uuid.uuid4().hex[:12]
            # V4.42 / F06：渲染层把真实裁切参数回填到这里，随图归档
            trace: dict = {}
            if img is not None:
                # 临时底图写进本批次目录，不与其他批次共享文件名空间。
                rel = workspace.temp_name("mabg")
                try:
                    async with sem:      # F11：供应商并发 / 速率限制
                        gen = img.generate
                        if reference_mode == "provider_reference" and product_path:
                            call = gen(t["bg_prompt"], t["w"], t["h"], rel,
                                       reference_image=product_path)
                        else:
                            call = gen(t["bg_prompt"], t["w"], t["h"], rel)
                        bg = await asyncio.wait_for(call, timeout=IMAGE_TASK_TIMEOUT_SECONDS)
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

            returned_size = None
            if bg_path:
                try:
                    from PIL import Image
                    with Image.open(bg_path) as _probe:
                        returned_size = list(_probe.size)
                except Exception:
                    pass

            for attempt in range(MAX_RENDER_RETRIES + 1):
                try:
                    await asyncio.to_thread(
                        render_ad_png, t["out"], t["w"], t["h"],
                        t["headline"], t["sub"], t["cta"], (brand or "")[:40],
                        bg_path or None, t["logo_path"] or None, None, strict_text,
                        t["palette"], t["layout"],
                        product_path if reference_mode == "local_composite" else None,
                        t["dim_ratio"], False, None, trace, overlay_mode)
                    break
                except TextOverflowError as e:
                    return {"__skipped__": {
                        **common, "status": "needs_revision",
                        "reason": f"图内文案无法完整排版：{e}",
                        "budget": text_budget(t["w"], t["h"], layout=t["layout"],
                                              logo_path=t["logo_path"]),
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
                "task_index": t["idx"],
                # F04：每张图绑定当时的概念、配置快照与最终提示词哈希
                "visual_brief": brief_view,
                "creative_config": cfg_snapshot,
                # F06：请求尺寸 / 实际返回尺寸 / 真实裁切参数，逐图可核对（T08）
                "returned_size": returned_size,
                "composition": trace.get("composition") or {
                    "mode": "gradient", "crop": None, "protected": True,
                    "requested_size": [t["w"], t["h"]], "returned_size": returned_size,
                },
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
        note_bits.append(f"每张图按概念生成独立视觉简报，配置 {config['config_id']}（{CREATIVE_CONFIG_VERSION}）已随图归档")
        if reference_mode != "none":
            note_bits.append(f"商品参考图模式 {reference_mode}：{capability_note}")
        if image_model["mixed"]:
            note_bits.append("同批存在模板回退，已逐张标注，不按整批 AI 成功计")
        if failed_count:
            note_bits.append(f"{failed_count} 个任务失败，未计入合格素材；可仅重试失败项")
        if revision_count:
            note_bits.append(f"{revision_count} 个版位因图内文案超预算被阻止生成（needs_revision），未输出省略号残图")
        if status == "failed":
            note_bits.append("整批无可用素材，请检查文案与版位设置后重试")
        outpaint_count = sum(1 for x in images
                             if (x.get("composition") or {}).get("mode") == "outpaint")
        if outpaint_count:
            note_bits.append(f"{outpaint_count} 张因比例差 / 极端版位改用扩图保留完整主体，未执行居中裁切")
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
            "batch_id": batch_id, "task_index": s.get("task_index"),
            "layout": s.get("layout", ""), "prompt_hash": s.get("prompt_hash", ""),
            "creative_config_id": s.get("creative_config_id", ""),
        } for s in skipped] + [{
            "status": x["status"], "size": x["size"], "placement": x["placement"],
            "concept_id": x["concept_id"], "ad_product": x["ad_product"],
            "spec_version": x["spec_version"], "file": x["file"],
            "ai_background": x["ai_background"], "fallback": x["fallback"],
            "error": x["fallback_reason"], "retries": x["retries"],
            "batch_id": batch_id, "task_index": x.get("task_index"),
            "layout": x.get("layout", ""), "prompt_hash": x.get("prompt_hash", ""),
            "creative_config_id": x.get("creative_config_id", ""),
            "request_size": x.get("request_size"), "returned_size": x.get("returned_size"),
            "composition_mode": (x.get("composition") or {}).get("mode", ""),
            "crop": (x.get("composition") or {}).get("crop"),
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
            # F04：整批的配置快照，供「素材历史」写入；后续修改预设不会覆盖它
            "creative_config": {**cfg_snapshot,
                                "scope": config["scope"],
                                "strategy_text_hash": prompt_hash(
                                    visual_text_block(config)),
                                "reference_mode": reference_mode},
            "reference_mode": reference_mode,
            "capability_note": capability_note,
            # F06：整批的构图与尺寸能力汇总，导出与逐图字段互为佐证
            "composition": {
                "provider": cap_key if tasks else "template",
                "modes": sorted({(x.get("composition") or {}).get("mode", "") for x in images}),
                "outpaint_count": outpaint_count,
                "protected_count": sum(1 for x in images
                                       if (x.get("composition") or {}).get("protected")),
                "size_capabilities": capability_of(
                    cap_key if tasks else "template",
                    (img_cfg.params if img_cfg else None) or {}),
                "note": "尺寸能力以官方文档与受控测试为准；未核验比例由渲染端扩图 / 主体保护处理",
            },
            "rules": {**rules_meta,
                      "stale_cleanup": stale,
                      "supplier_concurrency": MAX_CONCURRENT_IMAGE_TASKS,
                      "task_timeout_seconds": IMAGE_TASK_TIMEOUT_SECONDS,
                      "elapsed_ms": int((time.monotonic() - started) * 1000)},
        }
    finally:
        # 只删本批次目录；其它并发批次的临时文件不受影响（说明书 T15）。
        workspace.cleanup()
