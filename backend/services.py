"""
业务逻辑 V3：洞察 → 创意方向 → 按方向生产素材（图/文案/视频关键帧）。

与 V2 的差别：
- 分析层用本地抽取（insight.py）兜底，配置了模型再用模型润色，不再输出写死的通用卖点；
- 生产以「创意方向」为单位，同一方向跨版位重新排版，而不是同一张图换尺寸；
- 文案按平台字段结构输出并对齐字数，超长按词边界裁剪，最后做同质化检查。
"""
import asyncio
import html as html_lib
import json
import os
import re

import httpx

from models import Framework, Campaign, Material, PlatformSpec, Angle, ModelConfig
from providers import get_llm, get_image, get_video, parse_json
from insight import analyze_local, detect_lang
from creative import (ANGLE_LIBRARY, ANGLE_MAP, COPY_SCHEMA, build_copy_kit, map_to_platform,
                      copy_text, validate_copy, char_table, flag_duplicates, fit_text,
                      build_keywords, keyword_text)
from render import render_creative, render_keyframe
from validation import build_validation

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
IMAGE_MAX_SIZES = int(os.getenv("IMAGE_SIZES_PER_PLATFORM", "4"))
VIDEO_KEYFRAMES = 4

SYS_FRAMEWORK = (
    "你是海外效果广告投放策略师。基于给出的事实（产品、指标、卖点、品类），"
    "输出严格 JSON：product, category, audience, geo, languages(列表), selling_points(3-5条，必须来自给定事实，不得编造), "
    "platform_analysis(对象：平台名 -> 该品类在该平台的素材打法)。只输出 JSON。MARKER:FRAMEWORK_JSON"
)
SYS_ANGLE = (
    "你是效果广告创意总监。基于产品事实，给出 6 个互不重复的创意方向。严格 JSON："
    '{"angles":[{"key":"pain|benefit|proof|curiosity|ugc|promo","name":"中文名","insight":"为什么这个角度对这个产品有效",'
    '"hook":"该方向最短的一句钩子文案（目标语言）","visual":"画面具体长什么样","kpi":"主要影响指标"}]}。只输出 JSON。MARKER:ANGLE_JSON'
)
SYS_COPY = (
    "你是效果广告文案。严格按创意方向与语言撰写，不使用夸大或无法证实的数字。"
    "输出严格 JSON：{\"headlines\":[3条短标题],\"bodies\":[2条正文],\"cta\":\"按钮文案\"}。"
    "每条都必须能独立成立，且不超过给定字数上限。只输出 JSON。MARKER:COPY_JSON"
)


def has_real(db, usage="analysis") -> bool:
    cfg = db.query(ModelConfig).filter_by(usage=usage, is_active=True).first()
    return bool(cfg and cfg.api_key and cfg.base_url and cfg.model)


def _spec_for(db, platform):
    return db.query(PlatformSpec).filter_by(platform=platform).first()


def _size_wh(size: str):
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1080


def variant_label(version: int) -> str:
    return chr(64 + version) if 1 <= version <= 26 else f"V{version}"


# ----------------------------- 分析 -----------------------------
# 页面上的按钮/链接文案：判断这个落地页让用户"做什么"，是分析报告里转化路径的依据
CTA_TEXT_RE = re.compile(
    r"^(?:learn more|see more|read more|see how|shop now|buy now|order now|download(?: now)?|"
    r"install(?: now)?|try (?:it )?free|try [\w' .]{0,24}for free|get started|get offer|"
    r"sign ?up|start (?:free|now|trial)|subscribe|play (?:now|free)|book (?:now|a demo)|"
    r"了解更多|立即下载|立即体验|免费试用|立即购买|查看详情|开始使用|注册|预约)", re.I)

_PAGE_META_KEYS = ("title", "description", "lang", "h1", "h2", "ctas", "images", "has_video")


def _tag_text(inner: str) -> str:
    txt = re.sub(r"(?s)<[^>]+>", " ", inner or "")
    return re.sub(r"\s+", " ", html_lib.unescape(txt)).strip()


def parse_page_meta(html: str, final_url: str = "") -> dict:
    """从 HTML 里取"页面结构"，而不是只取正文。

    投放人员看落地页先看三件事：主标题在说什么、卖点怎么分层、按钮让用户做什么。
    这三件事在纯文本里会丢失，所以单独解析出来放进分析报告。
    """
    if not html:
        return {"title": "", "description": "", "lang": "", "h1": [], "h2": [],
                "ctas": [], "images": 0, "has_video": False, "final_url": final_url}

    def _first(pattern: str) -> str:
        m = re.search(pattern, html, re.I | re.S)
        return _tag_text(m.group(1)) if m else ""

    title = _first(r"<title[^>]*>(.*?)</title>")
    description = (_first(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)')
                   or _first(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)'))
    lang = ""
    m = re.search(r"<html[^>]+lang=[\"']([\w\-]+)", html, re.I)
    if m:
        lang = m.group(1).lower()

    def _heads(tag: str, limit: int) -> list[str]:
        out = []
        for inner in re.findall(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", html)[:limit * 2]:
            t = _tag_text(inner)
            if 2 <= len(t) <= 140 and t not in out:
                out.append(t)
            if len(out) >= limit:
                break
        return out

    ctas = []
    for inner in re.findall(r"(?is)<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", html):
        t = _tag_text(inner)
        if 2 <= len(t) <= 40 and CTA_TEXT_RE.match(t) and t.lower() not in [c.lower() for c in ctas]:
            ctas.append(t)
        if len(ctas) >= 6:
            break

    return {
        "title": title[:180], "description": description[:300], "lang": lang,
        "h1": _heads("h1", 3), "h2": _heads("h2", 8), "ctas": ctas,
        "images": len(re.findall(r"(?i)<img\b", html)),
        "has_video": bool(re.search(r"(?i)<video\b|youtube\.com/embed|player\.vimeo\.com", html)),
        "final_url": final_url,
    }


async def fetch_page(url: str) -> dict:
    """抓一次落地页，返回正文 + 页面结构。

    抓取失败不抛异常：网络问题不该变成 500，交由上层在报告里明确写"没抓到"。
    """
    empty = {"text": "", "chars": 0, "status": 0, "fetched": False,
             "title": "", "description": "", "lang": "", "h1": [], "h2": [],
             "ctas": [], "images": 0, "has_video": False, "final_url": url}
    if not url:
        return empty
    html, status = "", 0
    for attempt in range(2):          # 网关偶发 502，重试一次比直接失败更划算
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (compatible; AdFactory/3.2)"}) as cli:
                r = await cli.get(url)
                status = r.status_code
                if r.status_code < 400:
                    html = r.text
                    break
                print("[fetch] http", r.status_code, url)
        except Exception as e:
            print("[fetch] failed:", url, str(e)[:120])
        await asyncio.sleep(0.8)
    if not html:
        return {**empty, "status": status}

    meta = parse_page_meta(html, url)
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h[1-6]|section|header|footer|td)>", "\n", cleaned)
    text = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    text = html_lib.unescape(text)
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    body = "\n".join([l for l in lines if l])
    return {**empty, **meta, "text": body, "chars": len(body), "status": status, "fetched": True}


async def fetch_page_text(url: str) -> str:
    """兼容旧调用：只要正文。"""
    return (await fetch_page(url))["text"]


async def analyze_landing_page(db, url, text, page=None) -> Framework:
    """抓取（无正文时）→ 本地抽取 → 可选模型润色 → 落库。

    page 是 fetch_page 的结果，分析报告要用它的页面结构；不传则内部抓一次。
    """
    from models import LandingPage
    if page is None and url and not (text or "").strip():
        page = await fetch_page(url)
    page = page or {}
    # 正文优先用调用方给的；只给了 page（前端已经抓过）时，必须从 page 里取回来，
    # 否则 analyze_local 拿到空串，卖点会退化成"请粘贴正文"。
    if not (text or "").strip() and page.get("text"):
        text = page["text"]

    page_slim = {k: v for k, v in page.items() if k != "text"} if page else {}
    lp = LandingPage(url=url, raw_text=text, parsed_json={"page": page_slim} if page_slim else None)
    db.add(lp); db.commit(); db.refresh(lp)

    facts = analyze_local(text or "", url or "")     # 永远先做本地抽取
    data = dict(facts)
    if has_real(db, "analysis"):
        llm = get_llm(db, "analysis")
        prompt = (
            f"落地页 URL: {url or '无'}\n"
            f"页面结构: 标题={page.get('title') or '无'}；H1={page.get('h1') or '无'}；"
            f"H2={page.get('h2') or '无'}；CTA={page.get('ctas') or '无'}\n"
            f"正文:\n{(text or '')[:4000]}\n\n"
            f"本地已抽取的事实（以此为准，不要编造）：\n"
            f"产品: {facts['product']}\n品类: {facts['category']}\n"
            f"卖点: {facts['selling_points']}\n指标: {facts['metrics']}\n"
            "请产出推广框架 JSON。"
        )
        try:
            refined = parse_json(await llm.chat(SYS_FRAMEWORK, prompt))
            if refined.get("selling_points"):
                data.update({k: refined[k] for k in
                             ("product", "category", "audience", "geo", "languages",
                              "selling_points", "platform_analysis") if refined.get(k)})
                data["analyzer"] = "llm+local"
        except Exception:
            pass

    evidence = dict(data.get("evidence") or {})
    if page:
        # 页面结构单独存一份：报告需要，前端"抽取依据"也能看到
        evidence["page"] = {k: page.get(k) for k in _PAGE_META_KEYS + ("chars", "status", "fetched", "final_url")}

    fw = Framework(
        landing_page_id=lp.id,
        product=data.get("product"),
        category=data.get("category"),
        audience=data.get("audience"),
        geo=data.get("geo"),
        languages=data.get("languages"),
        selling_points=data.get("selling_points"),
        platform_analysis=data.get("platform_analysis"),
        raw_json=evidence,
        domain=data.get("domain"),
        metrics=data.get("metrics"),
        brand_color=data.get("brand_color"),
        assets=data.get("assets"),
        analyzer=data.get("analyzer", "local"),
    )
    db.add(fw); db.commit(); db.refresh(fw)
    lp.parsed_json = {**data, "page": page_slim} if page_slim else data
    db.commit()
    return fw


# ----------------------------- 创意方向 -----------------------------
def local_angles(fw, lang="en") -> list[dict]:
    """本地生成 6 个方向：钩子来自方向模板，落到产品名与首个卖点上。"""
    raw = fit_text((fw.selling_points or [fw.product])[0], 34)[0]
    benefit = raw if detect_lang(raw) == lang else ""
    out = []
    for i, a in enumerate(ANGLE_LIBRARY):
        kit = build_copy_kit(fw, a, lang, benefit)
        out.append({
            "key": a["key"], "name": a["name"], "insight": a["insight"],
            "visual": a["visual"], "template": a["template"], "kpi": a["kpi"],
            "platform_fit": a["platform_fit"], "hook": kit["headlines"][0], "sort": i,
        })
    return out


async def plan_angles(db, fw, platforms=None, extra=None, lang=None) -> list[Angle]:
    """生成并落库创意方向（同框架重复调用会覆盖上一版）。"""
    lang = lang or (fw.languages or ["en"])[0]
    angles = local_angles(fw, lang if lang in ("en", "es", "pt", "id") else "en")

    if has_real(db, "copy"):
        llm = get_llm(db, "copy")
        prompt = (
            f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
            f"卖点: {fw.selling_points}\n可量化指标: {fw.metrics}\n目标语言: {lang}\n"
            f"投放平台: {platforms or '未知'}\n额外要求: {extra or '无'}\n"
            "给出 6 个创意方向，key 只能用 pain/benefit/proof/curiosity/ugc/promo。"
        )
        try:
            resp = parse_json(await llm.chat(SYS_ANGLE, prompt))
            got = {x.get("key"): x for x in (resp.get("angles") or []) if x.get("key") in ANGLE_MAP}
            for a in angles:
                g = got.get(a["key"])
                if g:
                    a["hook"] = (g.get("hook") or a["hook"])[:80]
                    a["insight"] = (g.get("insight") or a["insight"])[:200]
                    a["visual"] = (g.get("visual") or a["visual"])[:200]
        except Exception:
            pass

    db.query(Angle).filter_by(framework_id=fw.id).delete()
    rows = []
    for a in angles:
        row = Angle(framework_id=fw.id, **a)
        db.add(row); rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


# ----------------------------- 文案 -----------------------------
async def _angle_copy(db, fw, angle_key, lang, extra):
    """返回 (fields, issues)。有真实模型时先用模型写，再统一走字数对齐。"""
    angle = ANGLE_MAP.get(angle_key) or ANGLE_LIBRARY[0]
    raw_benefit = fit_text((fw.selling_points or [fw.product])[0], 34)[0]
    # 卖点只在语言一致时直接复用，否则会产出中英夹杂的标题
    benefit = raw_benefit if detect_lang(raw_benefit) == lang else ""
    kit = build_copy_kit(fw, angle, lang, benefit)

    if has_real(db, "copy"):
        llm = get_llm(db, "copy")
        prompt = (
            f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
            f"已验证卖点: {fw.selling_points}\n可用指标: {fw.metrics}\n"
            f"创意方向: {angle['name']} —— {angle['insight']}\n"
            f"语言: {lang}\n额外要求: {extra or '无'}\n"
            "headlines 每条 ≤40 字符，bodies 每条 ≤90 字符。"
        )
        try:
            resp = parse_json(await llm.chat(SYS_COPY, prompt))
            if resp.get("headlines"):
                kit = {
                    "headlines": [str(x) for x in resp["headlines"]][:3],
                    "bodies": [str(x) for x in (resp.get("bodies") or [])][:2] or kit["bodies"],
                    "cta": resp.get("cta") or kit["cta"],
                }
        except Exception:
            pass
    return kit


def _render_spec(fw, angle_key, fields, lang, template, metric=None):
    angle = ANGLE_MAP.get(angle_key) or ANGLE_LIBRARY[0]
    headline = fields.get("headline") or fields.get("title") or fw.product
    if isinstance(headline, list):
        headline = headline[0]
    sub = fields.get("primary_text") or fields.get("body") or fields.get("description") or ""
    if isinstance(sub, list):
        sub = sub[0]
    cta = fields.get("cta") or ""
    if cta in ("LEARN_MORE", "SHOP_NOW", "DOWNLOAD", "INSTALL_MOBILE_APP", "SIGN_UP",
               "GET_OFFER", "PLAY_GAME", "SUBSCRIBE"):
        cta = {"LEARN_MORE": "Learn more", "SHOP_NOW": "Shop now", "DOWNLOAD": "Download",
               "INSTALL_MOBILE_APP": "Install", "SIGN_UP": "Sign up",
               "GET_OFFER": "Get offer", "PLAY_GAME": "Play now", "SUBSCRIBE": "Subscribe"}[cta]
    m = metric or (fw.metrics or [""])[0]
    rating_value, rating_label = _rating_from_metrics(fw.metrics)
    if m and (_num_tokens(m) & _num_tokens(headline or "")):
        # "2M" 与 "Over 2 million" 是同一个数字：字符串不相等，但画面上是重复的
        m = ""
    return {
        "template": template, "headline": headline, "sub": sub, "cta": cta,
        "brand": fw.product, "brand_color": fw.brand_color, "metric": m,
        "product_img": (fw.assets or {}).get("product"),
        "before_label": "BEFORE", "after_label": "AFTER",
        "rating_value": rating_value, "rating_label": rating_label,
    }


def _num_tokens(text: str) -> set:
    """把 "2M" / "2 million" / "2,000,000" 归一成同一个数量，用于判重。"""
    out = set()
    for mt in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|m|b|k)?", text or "", re.I):
        try:
            v = float(mt.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (mt.group(2) or "").lower()
        v *= {"million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9,
              "thousand": 1e3, "k": 1e3}.get(unit, 1)
        out.add(v)
    return out


def _rating_from_metrics(metrics) -> tuple[str, str]:
    """评分卡的分数只能取自原文（"5-star"/"4.8"），取不到就只放星级不放数字。"""
    metrics = list(metrics or [])
    for m in metrics:
        if m.lower().endswith("-star"):
            # 不要拼 "5★"：Arial 没有 U+2605，会渲染成方框；星级本身已经画在图上了
            return m[:-5], "star reviews"
    for m in metrics:
        if re.fullmatch(r"[0-5](?:\.\d)?", m):
            return m, "user rating"
    for m in metrics:
        if re.fullmatch(r"\d[\d.,]*[KMB]?", m):
            return m, "reviews"
    return "", "user rating"


# ----------------------------- 生产 -----------------------------
async def produce_campaign(db, fw, campaign, angle_keys, platforms, types, langs,
                           extra=None, sizes_per_platform=None,
                           video_mode="all") -> list[Material]:
    keys = [k for k in (angle_keys or []) if k in ANGLE_MAP] or ["benefit"]
    # 版位数量可配：默认 4，最少 1、最多 8（超过平台实际版位数时后面的循环自然截断）
    max_sizes = max(1, min(int(sizes_per_platform or IMAGE_MAX_SIZES), 8))
    video_keys = keys if video_mode == "all" else (keys[:1] if video_mode == "first" else [])
    mats, copy_index = [], []

    # 1) 先把文案算出来（模型调用串行，避免限流），再并行出图
    copy_jobs = []
    for key in keys:
        for platform in platforms:
            for lang in langs:
                copy_jobs.append((key, platform, lang))

    rendered = []
    for key, platform, lang in copy_jobs:
        kit = await _angle_copy(db, fw, key, lang, extra)
        mapped = map_to_platform(kit, platform, fw.product)
        fields = mapped["fields"]
        validation = validate_copy(fields, platform, mapped["issues"])
        if key == "promo":
            # 本地模板不知道这个产品当下有没有活动，"限时/本周截止"这类表述必须人工核对
            validation.setdefault("problems", []).append(
                {"level": "warn", "field": "活动真实性",
                 "msg": "促销方向默认带时效表述，投放前请确认活动真实存在"})
        mats.append(Material(
            campaign_id=campaign.id, type="copy", platform=platform, language=lang,
            angle_key=key, version=1, variant="A", prompt_log=extra,
            content={"fields": fields, "char_table": char_table(fields, platform),
                     "schema": COPY_SCHEMA.get(platform, [])},
            text_content=copy_text(fields, platform), validation=validation))
        if "keyword" in types:
            kw = build_keywords(fw, key, lang)
            mats.append(Material(
                campaign_id=campaign.id, type="keyword", platform=platform, language=lang,
                angle_key=key, version=1, variant="A", prompt_log=extra,
                content=kw, text_content=keyword_text(kw),
                validation=build_validation("keyword", kw)))

        # Google 的 description 是列表，这里统一取第一条做同质化比对
        raw_text = (fields.get("primary_text") or fields.get("body")
                    or fields.get("description") or "")
        if isinstance(raw_text, list):
            raw_text = raw_text[0] if raw_text else ""
        copy_index.append({"platform": platform, "language": lang,
                           "angle_name": ANGLE_MAP[key]["name"],
                           "text": str(raw_text), "angle_key": key, "warnings": []})

        if "image" in types:
            spec = _spec_for(db, platform)
            all_sizes = list(spec.image_sizes if spec else ["1080x1080"])
            data = _render_spec(fw, key, fields, lang, ANGLE_MAP[key]["template"])
            for size in all_sizes[:max_sizes]:
                w, h = _size_wh(size)
                fn = f"{campaign.id}_{platform}_{key}_{lang}_{w}x{h}_v1.png"
                rendered.append({"kind": "image", "angle": key, "platform": platform,
                                 "lang": lang, "size": size, "w": w, "h": h,
                                 "allowed": all_sizes,
                                 "out": os.path.join(UPLOAD_DIR, fn), "data": data})

    # 2) 并行出图（Pillow 是同步的，放线程池）
    results = await asyncio.gather(*[
        asyncio.to_thread(render_creative, item["out"], item["w"], item["h"], item["data"])
        for item in rendered
    ], return_exceptions=True)

    for item, res in zip(rendered, results):
        if isinstance(res, Exception):
            print("[render] failed:", item["out"], res)
            continue
        mats.append(Material(
            campaign_id=campaign.id, type="image", platform=item["platform"],
            language=item["lang"], angle_key=item["angle"], version=1, variant="A",
            spec_json={"size": item["size"], "template": item["data"]["template"],
                       "angle": item["angle"], "w": item["w"], "h": item["h"]},
            file_path=item["out"], prompt_log=extra,
            validation=build_validation("image", None,
                                        {"size": item["size"], "all_sizes": item["allowed"]})))

    # 3) 视频关键帧（每个方向一条 15s 分镜，4 张关键帧 + 首帧封面），并行渲染
    if "video" in types and video_keys:
        vtasks = []
        for key in video_keys:
            for platform in platforms:
                lang = langs[0]
                spec = _spec_for(db, platform)
                vw, vh = (1080, 1920) if "1080x1920" in (spec.image_sizes if spec else []) else (1080, 1080)
                src = next((m for m in mats if m.type == "copy" and m.angle_key == key
                            and m.platform == platform and m.language == lang), None)
                fields = (src.content or {}).get("fields", {}) if src else {}
                if not fields:
                    continue
                data = _render_spec(fw, key, fields, lang, ANGLE_MAP[key]["template"])
                vtasks.append(_make_video(db, campaign, fw, key, platform, lang, data, vw, vh, extra))
        for v in await asyncio.gather(*vtasks, return_exceptions=True):
            if isinstance(v, Material):
                mats.append(v)

    for m in mats:
        m.variant = m.variant or "A"
    db.add_all(mats)
    db.commit()
    for m in mats:
        db.refresh(m)

    flag_duplicates(copy_index)
    _apply_dup_warnings(mats, copy_index)
    db.commit()
    return mats


def _apply_dup_warnings(mats, copy_index):
    by_id = {}
    for m in mats:
        if m.type == "copy":
            by_id[(m.angle_key, m.platform, m.language)] = m
    for item in copy_index:
        if not item["warnings"]:
            continue
        m = by_id.get((item["angle_key"], item["platform"], item["language"]))
        if m and isinstance(m.validation, dict):
            m.validation.setdefault("problems", []).extend(
                [{"level": "warn", "field": "创意方向", "msg": w} for w in item["warnings"]])


async def _make_video(db, campaign, fw, key, platform, lang, data, vw, vh, extra):
    from providers import StoryboardVideo
    # 每一镜换一套版式，关键帧连起来能读出镜头推进，而不是同一张图复制四遍
    scenes = [
        ("痛点开场", "0-3s", "先给出问题现场，让用户认领", data.get("template")),
        ("产品演示", "3-8s", "核心动作演示，两步内看到结果", "ugc"),
        ("结果证明", "8-12s", "结果与口碑，降低决策风险", "rating"),
        ("CTA 收口", "12-15s", "品牌 + 行动指令，端卡", "bigtype"),
    ]
    kf_dir = os.path.join(UPLOAD_DIR, f"{campaign.id}_{platform}_{key}_{lang}_kf")
    os.makedirs(kf_dir, exist_ok=True)
    frames = []
    for i, (scene, tc, note, tpl) in enumerate(scenes[:VIDEO_KEYFRAMES], 1):
        d = dict(data)
        d["template"] = tpl or data.get("template")
        d["caption"] = note
        if i == len(scenes):
            d["headline"] = data.get("cta") or data.get("headline")
            d["cta"] = ""
        elif d["template"] == "rating":
            d["sub"] = data.get("sub") or ""
        out = os.path.join(kf_dir, f"kf{i}.png")
        await asyncio.to_thread(render_keyframe, out, vw, vh, d, i, VIDEO_KEYFRAMES, tc, scene)
        frames.append({"index": i, "scene": scene, "timecode": tc, "note": note,
                       "file": out, "ref": f"{campaign.id}_{platform}_{key}_{lang}_kf/kf{i}.png"})
    cover = os.path.join(UPLOAD_DIR, f"{campaign.id}_{platform}_{key}_{lang}_cover.png")
    await asyncio.to_thread(render_creative, cover, vw, vh, data)

    story = await StoryboardVideo().generate(
        f"{fw.product} · {platform} · {lang}", platform, "x.mp4",
        meta={"product": fw.product, "lang": lang, "headline": data.get("headline"),
              "sub": data.get("sub"), "cta": data.get("cta"),
              "aspect": "9:16" if vh > vw else "1:1", "duration": 15,
              "spec": (spec.video_spec if (spec := _spec_for(db, platform)) else "")})
    story["keyframes"] = frames
    story["cover"] = cover
    story["note"] = ("未配置视频模型：已产出 4 张关键帧 + 首帧封面 + 逐镜脚本，"
                     "剪辑可直接照此成片；配置视频模型后自动替换为真视频。")
    return Material(
        campaign_id=campaign.id, type="video", platform=platform, language=lang,
        angle_key=key, version=1, variant="A", content=story, file_path=cover,
        prompt_log=extra, validation=build_validation("video", story))


# ----------------------------- 重生成 -----------------------------
async def regenerate_material(db, material, extra):
    from sqlalchemy import func
    fw = db.query(Framework).join(Campaign).filter(Campaign.id == material.campaign_id).first()
    maxv = db.query(func.max(Material.version)).filter(
        Material.campaign_id == material.campaign_id, Material.type == material.type,
        Material.platform == material.platform, Material.language == material.language,
        Material.angle_key == material.angle_key).scalar() or 0
    version = int(maxv) + 1
    key = material.angle_key or "benefit"
    new = Material(campaign_id=material.campaign_id, type=material.type,
                   platform=material.platform, language=material.language or "en",
                   angle_key=key, version=version, variant=variant_label(version),
                   prompt_log=extra)

    if material.type in ("copy", "keyword"):
        if material.type == "keyword":
            from creative import COPY_SCHEMA  # noqa: F401
        fields_kit = await _angle_copy(db, fw, key, material.language or "en", extra)
        mapped = map_to_platform(fields_kit, material.platform, fw.product)
        new.content = {"fields": mapped["fields"],
                       "char_table": char_table(mapped["fields"], material.platform),
                       "schema": COPY_SCHEMA.get(material.platform, [])}
        new.text_content = copy_text(mapped["fields"], material.platform)
        new.validation = validate_copy(mapped["fields"], material.platform, mapped["issues"])
    elif material.type == "image":
        sj = material.spec_json or {}
        w, h = _size_wh(sj.get("size") or "1080x1080")
        fn = f"{material.campaign_id}_{material.platform}_{key}_{material.language}_{w}x{h}_v{version}.png"
        fw_like = fw or Framework(product="Ad", selling_points=["Ad"])
        kit = await _angle_copy(db, fw_like, key, material.language or "en", extra)
        fields = map_to_platform(kit, material.platform, fw_like.product)["fields"]
        data = _render_spec(fw_like, key, fields, material.language or "en", ANGLE_MAP[key]["template"])
        await asyncio.to_thread(render_creative, os.path.join(UPLOAD_DIR, fn), w, h, data)
        new.file_path = os.path.join(UPLOAD_DIR, fn)
        new.spec_json = {**sj, "version": version}
        new.validation = build_validation("image", None, new.spec_json)
    elif material.type == "video":
        fw_like = fw or Framework(product="Ad", selling_points=["Ad"])
        kit = await _angle_copy(db, fw_like, key, material.language or "en", extra)
        fields = map_to_platform(kit, material.platform, fw_like.product)["fields"]
        data = _render_spec(fw_like, key, fields, material.language or "en", ANGLE_MAP[key]["template"])
        vobj = await _make_video(db, type("C", (), {"id": material.campaign_id})(), fw_like,
                                 key, material.platform, material.language or "en", data, 1080, 1920, extra)
        new.content = vobj.content
        new.file_path = vobj.file_path
        new.validation = vobj.validation
    db.add(new); db.commit(); db.refresh(new)
    return new


# ----------------------------- 素材优化 -----------------------------
async def optimize_campaign(db, campaign, instruction, scope="all", angle_keys=None) -> dict:
    """按优化要求重出素材：先算新文案，再用同一份文案重渲染图片，保证图文一致。

    版本号递增而不是覆盖：投放人员要能对比"改之前 / 改之后"，也便于回滚。
    """
    from optimize import apply_rules, parse_instruction
    fw = db.query(Framework).filter_by(id=campaign.framework_id).first()
    if not fw:
        raise ValueError("推广框架不存在")

    rules = parse_instruction(instruction)
    mats = db.query(Material).filter_by(campaign_id=campaign.id).all()
    wanted = {k for k in (angle_keys or []) if k}
    if not mats:
        raise ValueError("该批次还没有素材，请先生成素材再优化")

    base, maxv, size_ver, base_tpl = {}, {}, {}, {}
    # 版式/配色要沿最新版本继承：拿"第一张遇到的图"会导致每轮优化都退回 v1 的版式，
    # 上一轮刚换的 bigtype 和蓝色就这么被悄悄丢掉了。
    tpl_ver, last_color, last_metric = {}, {}, {}
    for m in mats:
        angle = m.angle_key or "benefit"
        if wanted and angle not in wanted:
            continue
        lang = m.language or "en"
        v = m.version or 1
        if m.type == "copy":
            k = (angle, m.platform, lang)
            if k not in base or v > (base[k].version or 1):
                base[k] = m
        mk = (m.type, angle, m.platform, lang)
        maxv[mk] = max(maxv.get(mk, 0), v)
        if m.type == "image":
            sj = m.spec_json or {}
            sk = (angle, m.platform, lang, sj.get("size") or "1080x1080")
            if sk not in size_ver or v > (size_ver[sk].version or 1):
                size_ver[sk] = m
            tk = (angle, m.platform, lang)
            if v >= tpl_ver.get(tk, 0):
                tpl_ver[tk] = v
                base_tpl[tk] = sj.get("template") or ""
                last_color[tk] = sj.get("brand_color") or ""
                # None = 这版没记录过，渲染时不要覆盖；"" = 上一轮主动清掉了量级，要沿用
                last_metric[tk] = (sj["metric"], sj.get("rating_value") or "") if "metric" in sj else None

    if not base:
        raise ValueError("没有可优化的文案素材（当前批次可能只出了图片或视频）")

    created, do_copy, do_image = 0, scope in ("all", "copy", "image"), scope in ("all", "image")
    merged, warnings, notes, noop = {}, [], [], []
    seen = {}

    for (angle, platform, lang), copy_mat in base.items():
        raw_fields = (copy_mat.content or {}).get("fields") or {}
        if not isinstance(raw_fields, dict) or not raw_fields:
            continue
        res = apply_rules(raw_fields, rules, platform, lang, angle, fw.product or "",
                          base_tpl.get((angle, platform, lang)) or
                          (ANGLE_MAP.get(angle) or {}).get("template", "bigtype"),
                          fw.metrics)
        fields = res["fields"]

        for item in res["applied"]:
            slot = merged.setdefault(item["rule"], {
                "rule": item["rule"], "label": item["label"], "note": item["note"],
                "changes": [], "hit": 0})
            slot["hit"] += 1
            for c in item["changes"]:
                key = (c["field"], c["before"], c["after"])
                bucket = seen.setdefault(item["rule"], set())
                if key in bucket or len(slot["changes"]) >= 6:
                    continue
                bucket.add(key)
                slot["changes"].append(c)
        for w in res["warnings"]:
            if w not in warnings:
                warnings.append(w)

        # 这轮规则对这份素材到底改了什么？文案没变、版式配色也没变，
        # 就不该再出版本——否则 v2 只是 v1 的复印件，交付时会顶掉真正的最新版。
        same_copy = fields == raw_fields
        group_imgs = [img for (ag, pf, lg, _sz), img in size_ver.items()
                      if (ag, pf, lg) == (angle, platform, lang)]
        look_changed = (
            bool(res["brand_color"])
            or res["template"] != (base_tpl.get((angle, platform, lang)) or res["template"])
            # 去数字规则即使文案本来没数字，也要看图上是否杵着量级
            or (any(r["key"] == "no_numbers" for r in rules)
                and any((img.spec_json or {}).get("metric") for img in group_imgs))
        )
        if same_copy and not look_changed:
            noop.append(f"{angle}·{platform}/{lang}")
            continue

        # 1) 新文案版本
        if do_copy and not same_copy:
            cv = maxv.get(("copy", angle, platform, lang), 1) + 1
            mapped_issues = [{"field": k, "issue": "优化时按字数上限裁剪"}
                             for k in fields if isinstance(fields.get(k), str)
                             and len(fields[k]) >= _field_max(platform, k)]
            db.add(Material(
                campaign_id=campaign.id, type="copy", platform=platform, language=lang,
                angle_key=angle, version=cv, variant=variant_label(cv), prompt_log=instruction,
                content={"fields": fields, "char_table": char_table(fields, platform),
                         "schema": COPY_SCHEMA.get(platform, []), "optimized": True},
                text_content=copy_text(fields, platform),
                validation=validate_copy(fields, platform, mapped_issues)))
            maxv[("copy", angle, platform, lang)] = cv
            created += 1

        # 2) 图片：同组每个尺寸各出一张新版本，版式/配色按规则结果。
        # 同一组的多个尺寸共用一个版本号，前端按版本切换时图文才对得上。
        if do_image and (not same_copy or look_changed):
            iv, made = maxv.get(("image", angle, platform, lang), 1) + 1, 0
            for (ag, pf, lg, size), img in size_ver.items():
                if (ag, pf, lg) != (angle, platform, lang):
                    continue
                w, h = _size_wh(size)
                spec = _render_spec(fw, angle, fields, lang, res["template"])
                lm = last_metric.get((angle, platform, lang))
                if lm is not None:
                    # 上一版主动去掉的量级/评分要沿用，否则每轮都从产品数据里重新捞回来
                    spec["metric"], spec["rating_value"] = lm
                if any(r["key"] == "no_numbers" for r in rules):
                    # 文案去了数字，图上还杵着 "2M" 就自相矛盾了
                    spec["metric"] = ""
                    spec["rating_value"] = ""
                if res["brand_color"]:
                    spec["brand_color"] = res["brand_color"]
                elif last_color.get((angle, platform, lang)):
                    # 本轮没要求改色，就沿用上一版的主色
                    spec["brand_color"] = last_color[(angle, platform, lang)]
                fn = f"{campaign.id}_{platform}_{angle}_{lang}_{w}x{h}_v{iv}.png"
                out = os.path.join(UPLOAD_DIR, fn)
                try:
                    await asyncio.to_thread(render_creative, out, w, h, spec)
                except Exception as e:      # 单张失败不该让整批优化回滚
                    print("[optimize] render failed", out, e)
                    notes.append(f"{platform} {size} 渲染失败，已跳过")
                    continue
                db.add(Material(
                    campaign_id=campaign.id, type="image", platform=platform, language=lang,
                    angle_key=angle, version=iv, variant=variant_label(iv),
                    file_path=out, prompt_log=instruction,
                    spec_json={**(img.spec_json or {}), "size": size, "w": w, "h": h,
                               # 版式/配色/量级都以本次实际渲染的 spec 为准落库，
                               # 否则下一轮优化从旧 spec 读不到新颜色，蓝色会被"忘掉"
                               "template": spec.get("template"),
                               "brand_color": spec.get("brand_color"),
                               "metric": spec.get("metric"),
                               "rating_value": spec.get("rating_value"),
                               "optimized": True, "angle": angle},
                    validation=build_validation("image", None,
                                                {"size": size,
                                                 "all_sizes": (img.spec_json or {}).get("all_sizes")
                                                 or _spec_sizes(db, platform)})))
                created += 1
                made += 1
            if made:
                maxv[("image", angle, platform, lang)] = iv

    if noop:
        head = "、".join(noop[:3]) + (" 等" if len(noop) > 3 else "")
        notes.append(f"{len(noop)} 组素材本轮无改动、保持原版本（{head}）：这些文案已在平台字数上限内，"
                     f"规则模式不做会破坏语义的硬裁")
    if campaign.materials and any(m.type == "video" for m in mats):
        notes.append("视频分镜未重生成：本轮只更新文案与图片。如需同步分镜，请重新生成视频。")
    if scope == "image":
        notes.append("仅重渲染图片：文案版本也一并更新，避免图上文字与投放文案不一致。")

    db.commit()
    version = max((v for v in maxv.values()), default=1)
    return {"created": created, "version": version,
            "applied": list(merged.values()), "warnings": warnings, "notes": notes,
            "rules": rules}


def _field_max(platform: str, key: str) -> int:
    for f in COPY_SCHEMA.get(platform) or []:
        if f["key"] == key:
            return f["max"]
    return 999


def _spec_sizes(db, platform):
    spec = _spec_for(db, platform)
    return list(spec.image_sizes if spec else [])


# ----------------------------- 兼容旧调用（批量任务） -----------------------------
async def generate_campaign_materials(db, fw, campaign, platforms, types, langs, extra):
    types = [t for t in types if t in ("image", "video", "copy", "keyword")]
    if not types:
        types = ["image", "copy"]
    return await produce_campaign(db, fw, campaign, ["benefit", "proof"], platforms,
                                  types, langs, extra, sizes_per_platform=2)
