"""
媒体推广广告生成引擎（「素材创作 → 营销推广的媒体平台设置」专用）。

职责（严格遵循用户需求）：
1. 文案生成（generate_media_copy）：必须结合「落地页分析结论」(8 字段) 作为依据，调用已配置
   大模型产出平台结构化文案；生成后立即返回，前端展示并允许编辑；同时如实标注本次调用的模型。
2. 图片生成（generate_media_images）：以「编辑后的文案 + 落地页分析结论 + 风格/样式/颜色选项」
   为依据，调用文生图大模型产出背景，再叠加文案合成为可投放 PNG；无模型时用 Pillow 模板兜底，
   并如实标注图片实际调用的模型（或回退）。

复用既有能力：
- providers.get_llm / get_image / parse_json / UPLOAD_DIR / _active_config
- presets.build_directives / style_visual / palette_prompt / DIRECTION_MOOD / STYLE_TO_BG / DIRECTION_TO_BG / COLOR_TO_PALETTE
- imaging.render_ad_png
- creative.fit_text
- media_platforms.get_media_platform
"""
import os
import asyncio
import uuid
import urllib.request
import urllib.parse
from typing import Optional

from providers import get_llm, get_image, parse_json, UPLOAD_DIR, _active_config
from presets import (build_directives, style_visual, palette_prompt,
                     DIRECTION_MOOD, STYLE_TO_BG, DIRECTION_TO_BG, COLOR_TO_PALETTE)
# V4.35：广告推广文案 / 推广图片的提示词改由「素材提示词」统一管理，保存即生效
from services import get_prompt
from prompt_catalog import (render_prompt, compose_copy_prompt, compose_image_prompt,
                            load_preset_overrides, MEDIA_IMAGE_SYS)
from imaging import render_ad_png
from text_utils import fit_text
from media_platforms import get_media_platform


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
    """从 URL 域名推导品牌名（首字母大写），失败回退空串。"""
    url = (analysis.get("url") or "").strip()
    if url:
        m = re_host(url)
        if m:
            name = m.split(".")[-2] if "." in m else m
            return name.capitalize()
    ind = (analysis.get("industry") or "").strip()
    return ind.split("/")[0].strip().capitalize() if ind else ""


def re_host(url: str):
    import re
    m = re.search(r"https?://([^/\s?#]+)", url)
    return m.group(1) if m else None


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


def _build_fields(parsed: dict, schema) -> dict:
    """把模型 JSON 映射到平台字段结构，逐字段按词边界裁剪到上限。"""
    out = {}
    for f in schema:
        key, mx, cnt = f["key"], f["max"], f["count"]
        if key == "cta":
            v = parsed.get("cta") or parsed.get("cta_button") or ""
            if isinstance(v, list):
                v = v[0] if v else ""
            v = (str(v or "").strip())
            if v and v.upper() in FB_CTA_HUMAN:
                v = FB_CTA_HUMAN[v.upper()]
            out["cta"] = v
            continue
        if cnt > 1:
            arr = parsed.get(key)
            if not isinstance(arr, list):
                arr = [arr] if arr else []
            clipped = []
            for x in arr:
                s = str(x or "").strip()
                if not s:
                    continue
                c, _ = fit_text(s, mx)
                clipped.append(c)
            out[key] = clipped[:cnt] if clipped else ([fit_text(str(parsed.get(key, "")), mx)[0]] if parsed.get(key) else [])
        else:
            v = parsed.get(key)
            if isinstance(v, list):
                v = v[0] if v else ""
            v = str(v or "").strip()
            v, _ = fit_text(v, mx)
            out[key] = v
    return out


def _validate(fields: dict, schema) -> dict:
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
    issues = [{"level": p["level"], "code": p["field"], "message": p["msg"]} for p in problems]
    return {"valid": not any(p["level"] == "error" for p in problems),
            "ok": not any(p["level"] == "error" for p in problems),
            "issues": issues, "problems": problems}


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


async def generate_media_copy(db, analysis: dict, platform: str, lang: str = "en") -> dict:
    """基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案，并标注本次模型。

    返回：fields(结构化文案) / schema / char_table / validation / model_info / brand。
    """
    platform = platform or "Facebook"
    analysis = _as_dict(analysis)
    schema = MEDIA_COPY_SCHEMA.get(platform) or MEDIA_COPY_SCHEMA["AppLovin"]
    spec = get_media_platform(platform) or {}
    lim = spec.get("copy_limits", {})

    # V4.35：主提示词来自「素材提示词」目录（可由总结库一键设为系统默认）；
    # 字段结构 / 字数红线 / 语言等动态约束由 compose_copy_prompt 注入，模板缺失时自动追加输出契约。
    ctx = _analysis_context(analysis, platform, lang, db)
    sys_prompt = compose_copy_prompt(
        get_prompt(db, "media_copy_sys"),
        schema=_schema_instr(schema),
        limits=_limits_instr(lim, schema),
        language=LANG_NAME.get(lang, "English"),
        platform=platform,
    )
    user_prompt = ctx

    llm = get_llm(db, "copy")
    try:
        resp = await llm.chat(sys_prompt, user_prompt)
    except Exception:
        resp = ""
    used_fallback = bool(getattr(llm, "used_fallback", False))
    cfg = _active_config(db, "copy")
    model_info = {
        "provider": (cfg.provider if cfg else "mock"),
        "model": (cfg.model or "") if cfg else "",
        "role": "copy",
        "fallback": (True if not cfg else used_fallback),
    }

    parsed = parse_json(resp) or {}
    fields = _build_fields(parsed, schema)
    validation = _validate(fields, schema)
    char_rows = _char_table(fields, schema)
    brand = _brand_of(analysis)

    return {
        "platform": platform,
        "lang": lang,
        "fields": fields,
        "schema": schema,
        "char_table": char_rows,
        "validation": validation,
        "model_info": model_info,
        "brand": brand,
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
    return compose_image_prompt(template, variables)


def _cleanup_ai_bgs():
    try:
        import glob
        for f in glob.glob(os.path.join(UPLOAD_DIR, "_mabg_*.png")):
            try:
                os.remove(f)
            except Exception:
                pass
        for f in glob.glob(os.path.join(UPLOAD_DIR, "_mlogo_*.png")):
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


_LOGO_EXT = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg", ".webp": ".webp"}


def _resolve_logo_local(logo_url: str):
    """把前端传来的 logo（已上传的 /files/... 或远程抓取到的 http(s) URL）解析为本地文件路径。

    远程 URL 会下载到 UPLOAD_DIR 并缓存为 _mlogo_*.xxx；无法解析/下载则返回 None（不走 logo）。
    """
    if not logo_url:
        return None
    if logo_url.startswith("/files/"):
        name = logo_url[len("/files/"):]
        local = os.path.join(UPLOAD_DIR, name)
        return local if os.path.exists(local) else None
    if logo_url.startswith("http://") or logo_url.startswith("https://"):
        try:
            ext = os.path.splitext(urllib.parse.urlparse(logo_url).path)[1].lower()
            ext = _LOGO_EXT.get(ext, ".png")
            fn = f"_mlogo_{uuid.uuid4().hex}{ext}"
            dst = os.path.join(UPLOAD_DIR, fn)
            req = urllib.request.Request(
                logo_url, headers={"User-Agent": "Mozilla/5.0 (compatible; AdFactory/3.2)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
            return dst
        except Exception:
            return None
    local = os.path.join(UPLOAD_DIR, os.path.basename(logo_url))
    return local if os.path.exists(local) else None


async def generate_media_images(db, analysis: dict, platform: str, lang: str,
                                copy_fields: dict, style_opts: dict, slots: list,
                                logo: str = "") -> dict:
    """基于「编辑后的文案 + 落地页分析结论 + 风格/样式/颜色」生成推广图片素材。

    - 文生图大模型已配置 → 按创意方向/风格/配色生成 AI 背景，再叠加文案合成 PNG；
    - 未配置 → Pillow 品牌渐变模板兜底，并如实标注回退。
    返回：images(含 url/file/size/placement) / image_model(本次调用模型) / note / count。
    """
    platform = platform or "Facebook"
    analysis = _as_dict(analysis)
    style_opts = style_opts or {}
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

    brand = (copy_fields or {}).get("brand") or _brand_of(analysis)
    headline, sub, cta = _overlay_text(copy_fields or {}, platform, brand)
    # 把 logo（上传的 /files/... 或远程抓取 URL）解析为本地可合成路径
    logo_path = await asyncio.to_thread(_resolve_logo_local, logo or "")

    img = get_image(db)
    img_cfg = _active_config(db, "image")
    ai_used = False
    image_model = {
        "provider": (img_cfg.provider if img_cfg else "template"),
        "model": (img_cfg.model if img_cfg else "Pillow 品牌渐变模板"),
        "fallback": (True if not img_cfg else False),
    }

    # 版位任务
    tasks = []
    for slot in (slots or []):
        size = slot.get("size") or spec_sizes[0]
        placement = slot.get("placement") or ""
        w, h = _size_wh(size)
        bg_prompt = _media_image_prompt(analysis, platform, directives, design, db)
        # V4.36：文件名带随机后缀。此前同名文案会生成完全相同的文件名，用户点「重新生成」
        # 会直接覆盖上一次的 PNG，导致「素材历史」里旧会话的图片被无声替换、无法再下载。
        ptag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in platform)[:20]
        fn = (f"media_{ptag}_{size}_{uuid.uuid4().hex[:10]}_"
              f"{abs(hash((placement, size, headline, sub))) % 100000:05d}.png")
        out = os.path.join(UPLOAD_DIR, fn)
        tasks.append((out, w, h, bg_prompt, fn, size, placement, logo_path))

    async def _render_one(out, w, h, bg_prompt, fn, size, placement, logo_path):
        nonlocal ai_used
        bg_path = None
        if img is not None:
            try:
                bg = await img.generate(bg_prompt, w, h, f"_mabg_{fn}")
                if bg:
                    bg_path = bg
                    ai_used = True
            except Exception:
                bg_path = None
        await asyncio.to_thread(
            render_ad_png, out, w, h,
            (headline or "")[:200], (sub or "")[:200], (cta or "")[:60], (brand or "")[:40],
            bg_path or None, logo_path or None,
        )
        return {"url": out, "file": fn, "size": size, "w": w, "h": h, "placement": placement}

    images = []
    if tasks:
        results = await asyncio.gather(*[_render_one(*t) for t in tasks], return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            images.append(r)

    if img is not None and not ai_used:
        image_model["fallback"] = True
        image_model["provider"] = img_cfg.provider if img_cfg else "template"
        image_model["model"] = (img_cfg.model if img_cfg else "") or "Pillow 品牌渐变模板"

    note = ""
    if image_model["fallback"]:
        note = ("未检测到可用文生图模型（或未配置 image 用途的 Key），已使用 Pillow 品牌渐变模板兜底生成图片；"
                "在「设置」中配置 image 用途的大模型后即可生成 AI 背景图。")
    else:
        note = f"图片背景由文生图大模型生成：{image_model['provider']} / {image_model['model']}。"

    _cleanup_ai_bgs()

    return {
        "platform": platform,
        "images": images,
        "image_model": image_model,
        "note": note,
        "count": len(images),
    }
