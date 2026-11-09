"""
素材创作平台 · 共用服务层（V4.37 精简版）。

仅保留仍被使用的三块能力：
  1) 系统提示词注册表 / 默认值同步（PROMPT_REGISTRY、get_prompt、sync_prompt_defaults）；
  2) 落地页抓取与页面结构解析（fetch_page、parse_page_meta、extract_logo）；
  3) 「素材创作」落地页 8 字段大模型推理（analyze_landing_concise）。

原「素材管理」（创作工作台 / 批量生成 / 素材库 / 规格库）专用的
Campaign / Material / Angle 生产链路、报告、优化、批量任务等已整体移除。
"""
import asyncio
import html as html_lib
import re
from urllib.parse import urljoin, urlparse

import httpx

from models import ModelConfig, PromptConfig
from providers import get_llm, parse_json
from prompt_catalog import PROMPT_META, EXTRA_PROMPTS, preset_prompt_entries

# V4.37：旧的 5 条系统级提示词（网站核心内容分析 / 创意方向 / 文案 / 视频分镜 / 图片设计）
# 只服务于已删除的「创作工作台 / 批量生成」，故从注册表移除。
PROMPT_REGISTRY: list = []
# 这些 key 的库内自定义内容随模块一起归档清理，避免「素材提示词」里出现失效条目。
REMOVED_PROMPT_KEYS = ("site_analysis", "angle", "copy", "video", "image")

# ----------------------------- 素材创作（落地页分析）：8 字段 LLM 推理提示词框架 -----------------------------
# 5 段提示词在运行时拼接为「系统提示词」一次调用大模型，输出 8 个必要字段。
# 每段可单独在「素材提示词」中编辑；category 用于在提示词库里分门别类展示。
# 注意：本框架不依赖 MARKER 标记（解析走稳健 JSON 提取），编辑时无需保留特定结尾标记。
LANDING_MODULE = "素材创作（落地页分析）"

SYS_LANDING_FRAMEWORK = (
    "你是海外效果广告投放策略师。给定落地页 URL 与正文，请基于页面真实内容，用大模型推理能力提炼该网站的关键信息。\n"
    "任务：输出以下 8 个字段的结构化 JSON（只输出 JSON，不要任何解释文字）：\n"
    "{\n"
    '  "language": "网站主要语言（如 中文 / English / Español）",\n'
    '  "industry": "从网站主营信息推断出的行业（如 在线教育 / 跨境电商 / SaaS 工具 / 移动游戏）",\n'
    '  "type": "网站属性/类型（如 电商网站 / 技术服务 / 公益平台 / 政府网站 / 旅游服务 / 家政服务 / 营销·广告平台 / SaaS 工具 / 其他）",\n'
    '  "audience": "目标对象：面向哪些人群 / 企业 / 渠道 / 地区",\n'
    '  "competitors": ["全球排名 top 3 的主要竞品名称"],\n'
    '  "advantages": ["核心优势/卖点，提炼而非功能罗列，最多 5 条"],\n'
    '  "channels": [{"platform": "推荐用于用户增长的媒体平台", "reason": "推荐理由 / 数据依据"}]\n'
    "}\n"
    "硬性约束：\n"
    "1. 所有结论必须来自给定正文与页面结构，禁止编造；缺信息时对应字段填空字符串或空数组，不要补通用套话。\n"
    "2. type 与 industry 要区分：industry 是所处行业，type 是『这个网站是什么』（它的本质属性）。\n"
    "3. competitors 最多 3 个、advantages 最多 5 条、channels 最多 5 个；不足则少给，不要硬凑。\n"
    "4. channels 的 reason 必须具体（结合受众 / 产品形态 / 行业惯例或数据依据），避免『流量大』这类空话。"
)

SYS_LANDING_BASIC = (
    "请重点核对以下字段的提取准确性：\n"
    "- language：以页面正文与 <html lang> 的实际语言为准，不要被个别英文术语误导；多语站点取主语言。\n"
    "- industry：依据网站『在做什么业务、服务谁』来定，而不是页面装饰。页面有教程/博客不代表就是教育行业——要看它实际售卖/提供的核心服务。\n"
    "- type：判定网站本质属性，从「电商网站 / 技术服务 / 公益平台 / 政府网站 / 旅游服务 / 家政服务 / 媒体平台 / SaaS 工具 / 其他」中选最贴切者；"
    "若网站用于帮助广告主获客、对接渠道与流量、提供广告/营销/变现/代理服务，应判为「营销·广告平台」相关类型，不要因页面含教程或案例就误判。\n"
    "- audience：明确对象是谁（终端消费者 / 企业客户 / 渠道代理 / 流量主），以及主要覆盖地区。"
)

SYS_LANDING_COMPETITORS = (
    "competitors：列出该网站在『全球市场』上最主要的 3 个竞品（按知名度 / 市场份额 / 直接替代关系取 top 3），仅给名称数组。\n"
    "若网站为 niche / 新兴产品导致难以判定，给出最相近的 3 个替代方案名称；实在无参考则给空数组。不要编造不存在的竞品。"
)

SYS_LANDING_ADVANTAGES = (
    "advantages：从该网站的真实卖点中提炼『核心优势 / 差异化价值』，而不是罗列功能清单。\n"
    "每条是一句可独立成立的价值陈述（如『覆盖 200+ 国家的一件代发网络』『AI 自动生成投放创意，节省 70% 素材制作时间』）。\n"
    "聚焦技术特质、服务承诺、资源壁垒、性价比等真正构成竞争力的点；默认最多 5 条，不足则少给，不要硬凑。"
)

SYS_LANDING_CHANNELS = (
    "channels：推荐该网站用于『获取用户增长』的媒体 / 广告平台，最多 5 个。\n"
    "每个对象含 platform（平台名，如 Google / Meta / TikTok / 行业垂直媒体 / 应用商店 ASO）与 reason（为什么适合它的推荐理由，"
    "可结合受众、产品形态、行业惯例或数据依据，如『目标用户为 Z 世代，TikTok 短视频种草转化高』）。"
)

LANDING_PROMPTS = [
    {
        "key": "landing_framework",
        "name": "落地页分析 · 分析总框架",
        "module": LANDING_MODULE,
        "category": "分析框架",
        "description": "落地页分析的顶层指令：明确任务、输出 JSON 结构与硬性约束。其余提示词分别细化各字段的提取规则。",
        "content": SYS_LANDING_FRAMEWORK,
    },
    {
        "key": "landing_basic",
        "name": "落地页分析 · 基础识别",
        "module": LANDING_MODULE,
        "category": "基础识别",
        "description": "细化 language / industry / type / audience 四个字段的提取规则与判定要点（行业与类型区分、本质属性判定）。",
        "content": SYS_LANDING_BASIC,
    },
    {
        "key": "landing_competitors",
        "name": "落地页分析 · 竞品识别",
        "module": LANDING_MODULE,
        "category": "竞争分析",
        "description": "细化 competitors 字段：全球排名 top 3 竞品，含判定口径，禁止编造。",
        "content": SYS_LANDING_COMPETITORS,
    },
    {
        "key": "landing_advantages",
        "name": "落地页分析 · 优势提炼",
        "module": LANDING_MODULE,
        "category": "价值提炼",
        "description": "细化 advantages 字段：提炼核心优势，非功能罗列，默认 ≤5 条。",
        "content": SYS_LANDING_ADVANTAGES,
    },
    {
        "key": "landing_channels",
        "name": "落地页分析 · 推广途径",
        "module": LANDING_MODULE,
        "category": "增长推广",
        "description": "细化 channels 字段：推荐用于用户增长的媒体平台，每个含平台名 + 推荐理由/数据依据，默认 ≤5 个。",
        "content": SYS_LANDING_CHANNELS,
    },
]

# 把落地页分析提示词并入注册表（提示词管理 / 素材提示词 单一数据源）
PROMPT_REGISTRY = PROMPT_REGISTRY + LANDING_PROMPTS

# V4.35「素材提示词」全量目录：
#   1) 既有 10 条系统提示词补齐「功能类型 / 使用类型」标签（prompt_catalog.PROMPT_META）；
#   2) 合入从 media_ad.py 抽出的 3 条广告推广文案 / 图片提示词（此前硬编码、不可管理）；
#   3) 合入三大预设库 D/S/C 共 62 条提示词片段（此前页面完全看不到，编辑后可回写生效）。
# 这样「素材创作」涉及的全部提示词都在同一注册表里，「素材提示词」页一次展示、统一编辑。
from prompt_catalog import PROMPT_META, EXTRA_PROMPTS, preset_prompt_entries


def _normalize_prompt_registry(items: list) -> list:
    out = []
    for item in items:
        d = dict(item)
        meta = PROMPT_META.get(d["key"], {})
        for field in ("func_type", "usage_type", "category"):
            if not d.get(field) and meta.get(field):
                d[field] = meta[field]
        d.setdefault("func_type", "production")
        d.setdefault("usage_type", "system")
        d.setdefault("category", "未分类")
        out.append(d)
    return out


PROMPT_REGISTRY = _normalize_prompt_registry(
    PROMPT_REGISTRY + EXTRA_PROMPTS + preset_prompt_entries()
)

_PROMPT_FALLBACK = {p["key"]: p["content"] for p in PROMPT_REGISTRY}

# 旧版默认提示词快照，只用于升级迁移：库里内容仍是这段未改动的默认值时刷新为新版，
# 用户自己编辑过的内容（已不等于快照）绝不覆盖。
_PROMPT_LEGACY: dict = {}   # 已下线模块的旧默认快照，无需再迁移

def get_prompt(db, key: str) -> str:
    """读取当前生效的提示词：DB 中启用版本优先，未配置/停用/读取失败回退内置默认。"""
    try:
        row = db.query(PromptConfig).filter_by(key=key, is_active=True).first()
        if row and (row.content or "").strip():
            return row.content
    except Exception:
        pass
    return _PROMPT_FALLBACK.get(key, "")


def sync_prompt_defaults(db) -> list:
    """把提示词默认值升级到当前版本：元信息（名称/模块/说明）始终跟随代码版本；
    正文只在库里仍是旧默认快照时刷新，用户自己改过的不动。返回被更新的 key 列表。
    """
    touched = []
    for item in PROMPT_REGISTRY:
        row = db.query(PromptConfig).filter_by(key=item["key"]).first()
        if not row:
            continue
        changed = False
        meta = (item["name"], item["module"], item["description"], item.get("category"),
                item.get("func_type"), item.get("usage_type"))
        if (row.name, row.module, row.description, row.category,
                row.func_type, row.usage_type) != meta:
            row.name, row.module, row.description = item["name"], item["module"], item["description"]
            row.category = item.get("category")
            row.func_type = item.get("func_type")
            row.usage_type = item.get("usage_type")
            changed = True
        legacy = (_PROMPT_LEGACY.get(item["key"]) or "").strip()
        if legacy and (row.content or "").strip() == legacy:
            row.content = item["content"]
            changed = True
        if changed:
            touched.append(item["key"])
    if touched:
        db.commit()
    return touched



# ----------------------------- 落地页抓取与页面结构解析 -----------------------------

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


def extract_logo(html: str, base_url: str = "") -> str:
    """从落地页 HTML 中启发式提取品牌 / 公司 logo 的绝对 URL。

    优先级：含 'logo' 关键字的 <img> > apple-touch-icon > og:image > favicon。
    内联 data: URI 与无法解析的相对路径均跳过。返回空串表示未抓到。
    """
    if not html:
        return ""

    def _abs(u: str) -> str:
        u = (u or "").strip()
        if not u or u.startswith("data:"):
            return ""
        if u.startswith("//"):
            scheme = (urlparse(base_url).scheme or "https")
            return f"{scheme}:{u}"
        if u.startswith("http://") or u.startswith("https://"):
            return u
        if base_url:
            try:
                return urljoin(base_url, u)
            except Exception:
                return ""
        return ""

    # 1) 含 logo 关键字的 <img>（class / id / alt / title / src）
    for m in re.finditer(r"(?is)<img\b([^>]*)>", html):
        attrs = m.group(1)
        if (re.search(r"(?i)(class|id|alt|title)\s*=\s*[\"'][^\"']*logo[^\"']*[\"']", attrs)
                or re.search(r"(?i)\bsrc\s*=\s*[\"'][^\"']*logo[^\"']*[\"']", attrs)):
            src = re.search(r"(?i)\bsrc\s*=\s*[\"']([^\"']+)[\"']", attrs)
            if src:
                a = _abs(src.group(1))
                if a:
                    return a

    # 2) apple-touch-icon
    m = re.search(r"(?i)<link\b[^>]*rel=[\"'][^\"']*apple-touch-icon[^\"']*[\"'][^>]*>", html)
    if m:
        href = re.search(r"(?i)\bhref\s*=\s*[\"']([^\"']+)[\"']", m.group(0))
        if href:
            a = _abs(href.group(1))
            if a:
                return a

    # 3) og:image
    m = re.search(r"(?i)<meta\b[^>]*property=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)[\"']", html)
    if not m:
        m = re.search(r"(?i)<meta\b[^>]*content=[\"']([^\"']+)[\"'][^>]*property=[\"']og:image[\"']", html)
    if m:
        a = _abs(m.group(1))
        if a:
            return a

    # 4) favicon / icon
    for rel in ("icon", "shortcut icon"):
        m = re.search(r"(?i)<link\b[^>]*rel=[\"'][^\"']*" + re.escape(rel) + r"[^\"']*[\"'][^>]*>", html)
        if m:
            href = re.search(r"(?i)\bhref\s*=\s*[\"']([^\"']+)[\"']", m.group(0))
            if href:
                a = _abs(href.group(1))
                if a:
                    return a
    return ""


async def fetch_page(url: str) -> dict:
    """抓一次落地页，返回正文 + 页面结构。

    抓取失败不抛异常：网络问题不该变成 500，交由上层在报告里明确写"没抓到"。
    """
    empty = {"text": "", "chars": 0, "status": 0, "fetched": False,
             "title": "", "description": "", "lang": "", "h1": [], "h2": [],
             "ctas": [], "images": 0, "has_video": False, "final_url": url, "html": ""}
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
    return {**empty, **meta, "text": body, "chars": len(body), "status": status, "fetched": True, "html": html}


async def fetch_page_text(url: str) -> str:
    """兼容旧调用：只要正文。"""
    return (await fetch_page(url))["text"]


# ----------------------------- 素材创作：落地页分析（8 字段 LLM 推理） -----------------------------

LANDING_KEYS = ["landing_framework", "landing_basic", "landing_competitors", "landing_advantages", "landing_channels"]


def get_landing_prompt(db) -> str:
    """拼接 5 段提示词为一份系统提示词（按注册顺序）。每段都可单独在「素材提示词」编辑。"""
    parts = [get_prompt(db, k) for k in LANDING_KEYS]
    return "\n\n".join([p for p in parts if p]).strip()


def build_landing_prompt(url: str, text: str, page: dict) -> str:
    """构造落地页分析的用户提示词：URL（展示）+ 页面结构 + 正文。"""
    meta_bits = []
    if page:
        if page.get("title"):
            meta_bits.append(f"标题: {page.get('title')}")
        if page.get("h1"):
            meta_bits.append(f"H1: {page.get('h1')}")
        if page.get("h2"):
            meta_bits.append(f"H2: {page.get('h2')}")
        if page.get("ctas"):
            meta_bits.append(f"CTA: {page.get('ctas')}")
        if page.get("description"):
            meta_bits.append(f"META描述: {page.get('description')}")
    meta_str = "；".join(meta_bits) if meta_bits else "无"
    return (
        f"落地页 URL: {url or '无'}\n"
        f"页面结构: {meta_str}\n"
        f"正文:\n{(text or '')[:4000]}\n\n"
        "请基于以上页面真实内容，输出 8 字段 JSON。"
    )


def _resolve_model(db):
    """返回 (llm, info)。info 记录实际调用的模型与用途，前端据此展示"用了哪个模型"。

    优先用「分析」模型；若未单独配置分析模型，但已配置「文案」文本模型，则复用「文案」模型
    （V4.22 模式：避免只配了一个大模型却让落地页分析默默走 Mock）。
    """
    candidates = []
    for c in db.query(ModelConfig).filter_by(is_active=True).all():
        us = c.usages if c.usages is not None else [c.usage]
        if "analysis" in us and c.api_key and c.base_url and c.model:
            candidates.append((c, "analysis"))
        elif "copy" in us and c.api_key and c.base_url and c.model:
            candidates.append((c, "copy"))
    cfg, usage = None, None
    for want in ("analysis", "copy"):
        best = None
        for c, role in candidates:
            if role == want and (best is None or c.id > best.id):
                best = c
        if best:
            cfg, usage = best, want
            break
    llm = get_llm(db, usage or "analysis")   # 带 Mock 兜底
    info = {"provider": "", "model": "", "role": usage or "analysis", "fallback": True}
    if cfg:
        info["provider"] = cfg.provider
        info["model"] = cfg.model or ""
        info["fallback"] = bool(getattr(llm, "used_fallback", False))
    return llm, info


def _normalize_landing(raw: dict, url: str) -> dict:
    """把模型原始输出规整为 8 字段结构（裁剪长度、保证类型）。"""
    raw = raw if isinstance(raw, dict) else {}

    def as_str(v):
        return (str(v).strip() if v is not None else "")

    def as_str_list(v, limit):
        out = []
        if isinstance(v, list):
            for x in v:
                s = as_str(x)
                if s:
                    out.append(s)
                if len(out) >= limit:
                    break
        return out

    chs = []
    for c in (raw.get("channels") or []):
        if isinstance(c, dict):
            p = as_str(c.get("platform"))
            r = as_str(c.get("reason"))
            if p:
                chs.append({"platform": p, "reason": r})
        elif isinstance(c, str):
            s = as_str(c)
            if s:
                chs.append({"platform": s, "reason": ""})
        if len(chs) >= 5:
            break

    return {
        "url": url or as_str(raw.get("url")),
        "language": as_str(raw.get("language")),
        "industry": as_str(raw.get("industry")),
        "type": as_str(raw.get("type")),
        "audience": as_str(raw.get("audience")),
        "competitors": as_str_list(raw.get("competitors"), 3),
        "advantages": as_str_list(raw.get("advantages"), 5),
        "channels": chs,
    }


def _local_landing(url: str, page: dict) -> dict:
    """无模型 / 模型失败时的本地兜底：只做最小识别（语言），其余留空，明确表示未用大模型推理。

    用户要求必须用大模型推理，因此兜底结果必须如实标注 source=local，前端提示需配置大模型。
    """
    lang = (page or {}).get("lang") or ""
    return {
        "url": url, "language": lang, "industry": "", "type": "", "audience": "",
        "competitors": [], "advantages": [], "channels": [],
    }


async def analyze_landing_concise(db, url, text, page=None) -> dict:
    """素材创作：落地页分析。抓取（无正文时）→ 拼接提示词 → 调用已配置大模型推理 → 规整 8 字段。

    返回 dict 含 8 字段 + model_info + source。source=llm 表示真用了大模型；local 表示走了兜底。
    """
    url = (url or "").strip()
    text = (text or "").strip()
    if page is None and url and not text:
        page = await fetch_page(url)
    page = page or {}
    if not text and page.get("text"):
        text = page["text"]

    # 启发式提取品牌 logo（即使走本地兜底也尽量给出，供后续图片合成复用）
    logo = extract_logo(page.get("html") or "", url)

    sys_prompt = get_landing_prompt(db)
    user_prompt = build_landing_prompt(url, text, page)
    llm, info = _resolve_model(db)

    # 没有任何可用的真实模型配置：直接走本地兜底，明确标注
    if not info["provider"]:
        return {**_local_landing(url, page), "model_info": info, "source": "local", "logo": logo}

    try:
        resp = await llm.chat(sys_prompt, user_prompt)
        raw = parse_json(resp)
        if isinstance(raw, dict) and (
            raw.get("industry") or raw.get("type") or raw.get("audience")
            or raw.get("language") or raw.get("advantages") or raw.get("channels")
        ):
            data = _normalize_landing(raw, url)
            return {**data, "model_info": info, "source": "mock" if info["fallback"] else "llm", "logo": logo}
        print(f"[landing] 模型返回无法解析为 8 字段 JSON（len={len(resp)}），回退本地构造")
    except Exception as e:
        print("[landing] llm failed:", str(e)[:140])
    # 模型调用 / 解析失败：本地兜底，但保留已识别到的模型信息进行追溯
    return {**_local_landing(url, page), "model_info": info, "source": "local", "logo": logo}
