"""
AI 模型接入层（可配置多模型）。
- 未配置任何 Key 时，使用 Mock provider，保证 MVP 端到端可跑通。
- 在「设置页」配置 OpenAI 兼容协议的 api_key / base_url / model 后，自动切换为真实调用。
- 图像 provider 接入真实 DALL·E 风格接口失败时自动回退到占位图，避免阻断主流程。
"""
import os, json, re, httpx, base64, asyncio, itertools, uuid, time, shutil, subprocess, struct
from typing import Optional

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mock 可选延迟（毫秒）：用于演示进度条 / 验证任务取消，生产接真实模型时无影响
MOCK_DELAY = float(os.getenv("MOCK_DELAY_MS", "0")) / 1000.0


# ----------------------------- 抽象接口 -----------------------------
class LLMProvider:
    async def chat(self, system: str, user: str, **kw) -> str:
        raise NotImplementedError

class ImageProvider:
    # V4.42 / F06：每个具体供应商声明自己的能力目录键，供 plan_generation_size 选尺寸
    capability_key = "generic_image"

    async def generate(self, prompt: str, width: int, height: int, filename: str,
                       copy=None) -> str:
        """返回保存后的文件路径。

        V4.110：输入区参考图组件已删除，图片侧不再有「按参考图编辑」的分支；
        参考图只保留在视频「图生视频」链路。
        """
        raise NotImplementedError

    def capabilities(self, params: dict | None = None) -> dict:
        from image_capabilities import capability_of
        return capability_of(self.capability_key, params)

class VideoProvider:
    async def generate(self, prompt: str, platform: str, filename: str) -> dict:
        raise NotImplementedError


# ----------------------------- Mock -----------------------------
def _first_line(text):
    """取落地页首行中最靠前的名称段作为产品名，跳过提示脚手架行。"""
    fallback = "Unknown Product"
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("落地页") or line.startswith("请分析"):
            continue
        # 用中文/英文标点与空白切分，取第一段（通常是品牌名）
        head = re.split(r"[，,。;；:：、\s]", line)[0].strip()
        return (head or line)[:24], (text or "")
    return fallback, (text or "")

class MockLLM(LLMProvider):
    async def chat(self, system, user, **kw):
        if MOCK_DELAY:
            await asyncio.sleep(MOCK_DELAY)
        if "FRAMEWORK_JSON" in system:
            return _mock_framework(user)
        if "SITE_ANALYSIS_JSON" in system:
            return _mock_site_analysis(user)
        if "COPY_JSON" in system:
            return _mock_copy(user)
        if "KEYWORD_JSON" in system:
            return _mock_keywords(user)
        return "(mock) " + user[:200]

def _mock_framework(text):
    product, body = _first_line(text)
    is_app = any(k in body.lower() for k in ["app", "应用", "game", "游戏", "软件", "tool"])
    category = "App/工具" if is_app else "电商/服务"
    data = {
        "product": product,
        "category": category,
        "audience": "18-45 岁移动用户，关注效率与性价比，兴趣偏向科技/生活方式/娱乐",
        "geo": "T1（欧美）+ 拉美 + 东南亚；按产品成熟度分批投放",
        "languages": ["en", "es", "pt", "id"],
        "selling_points": ["核心功能突出", "性价比优势", "本地化适配", "用户口碑/评分高", "限时活动/优惠"],
        "platform_analysis": {
            "Meta": "兴趣/行为定向为主，强视觉+短文案，Reels 9:16 短视频更易起量",
            "Google": "UAC/搜索并重，搜索词覆盖品类词+竞品词，多尺寸图片素材齐备",
            "Unity": "游戏/工具类首选，Rewarded 视频 + 1080x1920 竖版",
            "AppLovin": "App 安装导向，创意利益点前置，程序化放量",
            "Moloco": "ML 竞价 RTB，受众扩展，转化导向短文案",
            "Adsterra": "多元广告位，CPM/CPA，直给利益点",
            "Mintegral": "移动 DSP + 可玩广告，互动引导强",
        },
    }
    return json.dumps(data, ensure_ascii=False)

def _metric_kind(v: str):
    """与 report._metric_detail 一致的轻量分类，仅用于 Mock 兜底时给指标标对类型。"""
    s = str(v)
    if s.startswith(("$", "¥", "€", "£")):
        return "price", "价格"
    if "%" in s or "％" in s or "percent" in s.lower():
        return "ratio", "比例 / 提升幅度"
    if re.search(r"\d\s?(?:x|倍)$", s, re.I):
        return "multiple", "倍数"
    if re.search(r"(?:M|B|K|万|亿|\+)$", s):
        return "scale", "用户量 / 规模"
    if s.lower().endswith("-star") or re.fullmatch(r"[0-5](?:\.\d)?", s):
        return "rating", "评分"
    return "other", "其他量化"


def _guess_product(text: str):
    """Mock 兜底：从正文首句主语猜产品名（如 'Calm is the #1 app…' -> 'Calm'）。

    仅在无真实模型、且本地未抽到产品名时启用，避免报告里出现 'Unknown Product'。
    只取首句主语，不编造任何信息。
    """
    if not text:
        return None
    first = re.split(r"[.\n!?]", text.strip(), 1)[0].strip()
    for pat in (r"^([A-Z][A-Za-z0-9'’&.\-]+)\s+(?:is|are|—|-)\b",
                r"^([A-Z][A-Za-z0-9'’&.\-]+)\s*[:：]"):
        m = re.match(pat, first)
        if m:
            return m.group(1)
    return None


def _mock_site_analysis(user):
    """无真实模型时，从提示词里的本地事实 JSON 派生一套自洽的 9 模块网站核心内容。

    关键：Mock 不编造，所有结论都来自提示词中真实抽取的事实（产品/品类/卖点/指标/人群/
    平台打法），保证端到端可跑通且内容能与页面正文对得上。
    """
    facts: dict = {}
    m = re.search(r"本地已抽取事实（JSON[^\n]*\n(.*?)\n\n请产出", user or "", re.S)
    if m:
        try:
            facts = json.loads(m.group(1).strip())
        except Exception:
            facts = {}
    product = facts.get("product") or "Unknown Product"
    category = facts.get("category") or "App/工具"
    dom = facts.get("domain") or "app"
    points = [str(x) for x in (facts.get("selling_points") or ["核心功能突出", "性价比优势", "用户口碑高"]) if x]
    metrics = [str(x) for x in (facts.get("metrics") or []) if x]
    audience = facts.get("audience") or "18-45 岁移动用户，关注效率与性价比"
    channel_src = facts.get("platform_analysis") or {}
    # Mock 兜底：本地没抽到产品名时，从正文首句主语猜一个（如 'Calm is the #1 app' -> 'Calm'）
    body = ""
    mb = re.search(r"正文:\n(.*?)\n\n### 本地已抽取事实", user or "", re.S)
    if mb:
        body = mb.group(1).strip()
    if not product or product == "Unknown Product":
        guessed = _guess_product(body)
        if guessed:
            product = guessed
    channel = {}
    for k, v in (channel_src or {}).items():
        channel[k] = {
            "tactics": v,
            "hook": "前 3 秒用核心卖点直击痛点",
            "selling_point": points[0] if points else "",
            "compliance_note": "避免绝对化与收益承诺表述",
        }
    return json.dumps({
        "positioning": {
            "product": product,
            "category": category,
            "category_key": dom,
            "one_liner": (re.split(r"[.\n!?]", body.strip(), 1)[0].strip()[:80]
                          if body.strip() else f"{product}：让日常任务更轻松"),
            "differentiators": points[:2],
        },
        "value": {
            "summary": f"围绕「{product}」提炼 {len(points)} 条核心价值主张，按信息密度排序。",
            "points": [{"point": p, "type": "benefit", "strength": "中", "evidence": "本地抽取"}
                       for p in points],
        },
        "proof": {
            "summary": (f"页面给出 {len(metrics)} 个量化指标。" if metrics
                        else "页面未给出可量化证明，这是当前最大的转化阻力。"),
            "metrics": [{"value": x, "kind": _metric_kind(x)[0], "label": _metric_kind(x)[1]} for x in metrics],
            "endorsements": [],
            "credibility": "需结合应用商店评分与用户量补充硬证据",
        },
        "audience": {
            "primary": audience,
            "demographics": "移动端为主，关注效率与性价比",
            "pain_points": ["手动处理重复任务，费时费力"],
            "secondary": "",
        },
        "page": {
            "sections": ["Hero", "卖点", "证据", "CTA"],
            "structure_note": "标准落地页结构，卖点分层表达清晰",
            "conversion_path": "落地页 → 了解卖点 → 主 CTA 转化",
            "primary_cta": "Get Started",
            "tone": "专业且亲切",
        },
        "channel": channel,
        "risk": {
            "items": [{"level": "warn", "item": "需规避绝对化表述",
                       "detail": "避免「最/第一/100%」等绝对化用词，多数平台会判违规。"}],
            "compliance": "按品类规避医疗宣称与收益承诺，未成年人定向需避开。",
        },
        "gaps": {
            "missing": (["应用商店评分/用户量硬证据"] if not metrics else []),
            "confidence": "中",
        },
        "next_steps": [
            "先以 2 个方向、每方向 2 个版位小预算测试 CTR，跑赢的再铺满版位。",
            "补齐应用商店评分与用户量证据，强化信任背书方向。",
        ],
    }, ensure_ascii=False)

_MOCK_COPY = {
    "en": {
        "titles": ["Save more on every order", "Compare prices in one tap", "Shop smarter, not harder"],
        "descriptions": ["All coupons in one app, works across stores.",
                         "Local deals and cashback, updated daily."],
        "ctas": ["Download now", "Get the app free", "Try it today"],
    },
    "es": {
        "titles": ["Ahorra en cada compra", "Compara precios al instante", "Compra más inteligente"],
        "descriptions": ["Todos los cupones en una app, válidos en varias tiendas.",
                         "Ofertas locales y reembolsos, actualizados a diario."],
        "ctas": ["Descargar gratis", "Probar ahora", "Instalar la app"],
    },
    "pt": {
        "titles": ["Economize em cada compra", "Compare preços na hora", "Compre com inteligência"],
        "descriptions": ["Todos os cupons em um app, válido em várias lojas.",
                         "Ofertas locais e cashback, atualizados diariamente."],
        "ctas": ["Baixar agora", "Testar grátis", "Instalar o app"],
    },
    "id": {
        "titles": ["Hemat di setiap belanja", "Bandingkan harga seketika", "Belanja lebih cerdas"],
        "descriptions": ["Semua kupon dalam satu aplikasi, berlaku di banyak toko.",
                         "Promo lokal dan cashback, diperbarui setiap hari."],
        "ctas": ["Unduh sekarang", "Coba gratis", "Pasang aplikasi"],
    },
}
_mock_seq = itertools.count()

def _mock_copy(user):
    """按语言出稿，遵守字数红线，并按调用序轮换措辞：保证每次重生成都有可见差异。"""
    lang = "en"
    for code in ("es", "pt", "id", "en"):
        if f"语言:{code}" in (user or ""):
            lang = code
            break
    base = _MOCK_COPY[lang]
    seed = next(_mock_seq) % 3
    titles = base["titles"][seed:] + base["titles"][:seed]
    descs = base["descriptions"][seed % 2:] + base["descriptions"][:seed % 2]
    cta = base["ctas"][seed]

    # 遵守 brief 中的字数红线（真实模型也可能超，校验会兜底；Mock 先自证合规）
    tm = re.search(r"标题≤(\d+)字", user or "")
    dm = re.search(r"描述≤(\d+)字", user or "")
    if tm:
        lim = int(tm.group(1))
        titles = [t[:lim] for t in titles]
    if dm:
        lim = int(dm.group(1))
        descs = [d[:lim] for d in descs]
    return json.dumps({"titles": titles, "descriptions": descs, "cta": cta[:25]},
                      ensure_ascii=False)

def _mock_keywords(user):
    """从 brief 抽产品名与语言，产出贴合产品的关键词组（而非通用占位）。"""
    pm = re.search(r"产品:([^｜\n]+)", user or "")
    product = (pm.group(1).strip() if pm else "Product")[:24]
    lang = "en"
    for code in ("es", "pt", "id", "en"):
        if f"语言:{code}" in (user or ""):
            lang = code
            break
    by_lang = {
        "en": {"broad": [f"{product} app", f"best coupon app", f"{product} deals"],
               "phrase": [f'"{product}" review', f'"{product}" free download'],
               "exact": [f"{product} official", f"download {product}"]},
        "es": {"broad": [f"app {product}", "cupones y descuentos", f"{product} ofertas"],
               "phrase": [f'"{product}" opiniones', f'"{product}" gratis'],
               "exact": [f"{product} oficial", f"descargar {product}"]},
        "pt": {"broad": [f"app {product}", "cupons e descontos", f"{product} ofertas"],
               "phrase": [f'"{product}" avaliação', f'"{product}" grátis'],
               "exact": [f"{product} oficial", f"baixar {product}"]},
        "id": {"broad": [f"aplikasi {product}", "kupon dan diskon", f"{product} promo"],
               "phrase": [f'"{product}" ulasan', f'"{product}" gratis'],
               "exact": [f"{product} resmi", f"unduh {product}"]},
    }
    return json.dumps(by_lang[lang], ensure_ascii=False)

class TemplateImage(ImageProvider):
    """默认出图：Pillow 合成真实 PNG（品牌渐变 + 标题/副标/CTA 排版），无需任何 API Key。"""
    capability_key = "template"

    async def generate(self, prompt, width, height, filename, copy=None):
        from imaging import render_ad_png
        path = os.path.join(UPLOAD_DIR, filename)
        cp = copy or {}
        await asyncio.to_thread(
            render_ad_png, path, width, height,
            cp.get("headline") or prompt, cp.get("sub") or "", cp.get("cta") or "",
            cp.get("brand") or "",
        )
        return path

# 兼容旧命名
MockImage = TemplateImage

class StoryboardVideo(VideoProvider):
    """无视频模型时的交付形态：可执行的分镜脚本 + 平台规格（导演/剪辑可直接照单制作）。"""
    async def generate(self, prompt, platform, filename, meta=None):
        meta = meta or {}
        lang = meta.get("lang") or "en"
        product = meta.get("product") or prompt
        hook = meta.get("headline") or product
        cta = meta.get("cta") or {"en": "Install now", "es": "Instalar ahora",
                                  "pt": "Instalar agora", "id": "Pasang sekarang"}.get(lang, "Install now")
        aspect = "9:16" if "1080x1920" in (meta.get("spec") or "") or platform in ("Unity", "Mintegral") else "1:1"
        shots = [
            {"t": "0-3s", "shot": "痛点开场", "visual": f"用户遇到问题的手持特写（{product} 使用场景）",
             "text": hook, "vo": f"{hook}"},
            {"t": "3-8s", "shot": "产品演示", "visual": "核心功能 2 步操作演示，屏幕录制 + 手指引导",
             "text": meta.get("sub") or "3 秒完成，效果立现", "vo": "One tap and it is done."},
            {"t": "8-12s", "shot": "社会证明", "visual": "评分 / 用户好评 / 数据角标",
             "text": "★★★★★ 4.8 · 100K+ users", "vo": "Loved by millions of users."},
            {"t": "12-15s", "shot": "CTA 收口", "visual": "产品 Logo + 下载按钮动画 + 端卡",
             "text": cta, "vo": cta},
        ]
        return {
            "provider": "storyboard",
            "platform": platform,
            "duration_sec": 15,
            "aspect": aspect,
            "resolution": "1080x1920" if aspect == "9:16" else "1080x1080",
            "format": "mp4 (H.264) / mov",
            "hook": hook,
            "cta": cta,
            "shots": shots,
            "deliverables": ["15s 主片", "6s 剪辑版（Feed）", "首帧封面图"],
            "note": "未配置视频模型，输出可执行分镜；在设置页配置 video 用途的模型后会自动调用真实生成。",
        }

# ------------------------- 视频响应解析：协议族白名单（V4.79 / F04） -------------------------
# 旧实现（≤V4.78）用 `_video_find_media` 递归找「第一个 http 字符串」，看似万能，实际会把
# 输入回显当成成片：阿里云百炼提交/查询响应形如
#   {"output": {"task_status": "PENDING", "task_id": "tk_x", "input": {"image": "https://…/p.jpg"}}}
# 递归会命中 input.image ——于是「图生视频」把用户上传的商品图落盘成 .mp4，界面显示成功却播不了。
# 现在改为「协议族 + 键名白名单」：只认厂商文档里出现的容器与字段，绝不从 input / parameters /
# request 等回显区取媒体，也绝不接受任意字符串。
_VIDEO_OK_STATES = {"succeeded", "success", "complete", "completed", "ready", "finished", "done"}
_VIDEO_FAIL_STATES = {"failed", "failure", "error", "cancelled", "canceled", "expired", "timeout"}
_VIDEO_MEDIA_URL_KEYS = ("video_url", "videoUrl", "url", "video_uri", "resource_url",
                         "download_url", "file_url", "play_url", "mp4_url")
_VIDEO_MEDIA_B64_KEYS = ("b64_json", "base64", "video_base64")


class VideoPipelineError(RuntimeError):
    """出片链路的**可分类**失败（V4.79 / F02–F05）。

    以前任何失败都被 `except` 吞掉并返回分镜脚本，界面于是显示「完成」——用户既不知道
    失败在哪一步，也不知道该做什么。现在失败带上 `error_code`，一个错误码只对应一个
    唯一正确的处置动作（见 `_VIDEO_ERROR_ACTIONS`），界面照此展示即可，不让用户猜。
    """

    def __init__(self, error_code: str, message: str, *, stage: str = "",
                 action: str = "", http_status: int = 0, task_id: str = "",
                 evidence: Optional[dict] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.stage = stage
        self.action = action or _VIDEO_ERROR_ACTIONS.get(error_code, "")
        self.http_status = http_status
        self.task_id = task_id
        self.evidence = dict(evidence or {})


#: 错误码 → 唯一可执行动作。界面只展示这一条，避免「重试 / 重新下载 / 去设置」三选一乱猜。
_VIDEO_ERROR_ACTIONS = {
    "CONFIG_MISSING": "到「系统设置 → 大模型配置」补齐这条视频配置的请求地址与模型版本。",
    "AUTH_FAILED": "到「大模型配置」更新该配置的 API Key，并确认部署机公网 IP 已加入厂商白名单。",
    "BAD_REQUEST": "到「大模型配置」核对模型版本与高级参数（协议契约），按服务端原文修正后重试。",
    "RATE_LIMITED": "厂商限流：等 1–2 分钟后重试（本次未出片，通常也未扣费）。",
    "PROVIDER_ERROR": "厂商侧 5xx，稍后重试；连续失败请核对厂商服务状态与部署机网络出口。",
    "CONTRACT_MISMATCH": "到「大模型配置」删除该配置后重选同一协议（会自动装配 endpoint / async_header / poll_path）。",
    "PROVIDER_REJECTED": "按失败原文调整提示词或参数后重试（涉及违规内容需改写描述）。",
    "POLL_UNREACHABLE": "检查部署机到厂商域名的网络连通性；任务可能已受理，可稍后按任务号继续查询。",
    "POLL_TIMEOUT": "任务仍在厂商侧渲染：稍后点「继续查询」按任务号回查，不要重新生成以免重复扣费。",
    "EMPTY_OUTPUT": "任务已完成但响应里没有成片地址：核对厂商返回结构后重新生成。",
    "DOWNLOAD_FAILED": "成片已生成但下载或校验失败：点「重新下载」即可，不要重新生成（避免重复扣费）。",
    "STORAGE_FAILED": "服务端写入失败：检查 uploads 目录磁盘空间与权限。",
    "CLAIM_UNSUPPORTED": "分镜文案含页面原文不支持的数字或限定丢失：回到分镜规划删掉该表述后重新出片（本次未提交厂商，不会扣费）。",
    "ASSET_MISSING": "图生视频缺少参考图：上传官方商品图 / 真实界面截图后再出片（本次未提交厂商，不会扣费）。",
}


def _video_evidence_snippet(obj, limit: int = 400) -> str:
    """证据摘要：把厂商原文留在证据链里，同时抹掉 Key / Token。"""
    try:
        s = json.dumps(obj, ensure_ascii=False) if isinstance(obj, (dict, list)) else str(obj)
    except Exception:
        s = repr(obj)
    s = re.sub(r"(?i)(api[-_]?key|authorization|access[-_]?token|secret)\"?\s*[:=]\s*\"?[^\",}\s]+",
               r"\1=***", s)
    s = re.sub(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9_-]+", r"\1***", s)
    return s[:limit]


def _video_pick_media_in(d) -> tuple:
    """从**一个**对象里按白名单键取媒体地址 / base64（不递归、不猜）。"""
    if not isinstance(d, dict):
        return "", ""
    url = b64 = ""
    for k in _VIDEO_MEDIA_URL_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            url = v
            break
    for k in _VIDEO_MEDIA_B64_KEYS:
        v = d.get(k)
        if isinstance(v, str) and len(v) > 64:
            b64 = v
            break
    return url, b64


def video_media_of(data, family: str = "") -> tuple:
    """按协议族白名单解析成片（V4.79 / F04）。

    - dashscope_maas：`output.video_url` / `output.video_urls[]` / `output.results[].url`
    - 通用网关 / OpenAI 风格：`data[].url`、`output|result|video` 容器、顶层媒体键
    只在这些位置找，**绝不下探 input / parameters / request 回显**。
    """
    if not isinstance(data, dict):
        return "", ""
    if family == "dashscope_maas":
        out = data.get("output") if isinstance(data.get("output"), dict) else {}
        u, b = _video_pick_media_in(out)
        if u or b:
            return u, b
        for k in ("video_urls", "urls"):
            v = out.get(k)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.startswith(("http://", "https://")):
                        return it, ""
        for k in ("results", "videos", "result"):
            v = out.get(k)
            for it in (v if isinstance(v, list) else [v]):
                u, b = _video_pick_media_in(it)
                if u or b:
                    return u, b
        return "", ""
    arr = data.get("data")
    if isinstance(arr, list):
        for it in arr:
            u, b = _video_pick_media_in(it)
            if u or b:
                return u, b
    for holder in ("output", "result", "video", "videos", "generation"):
        h = data.get(holder)
        if isinstance(h, dict):
            u, b = _video_pick_media_in(h)
            if u or b:
                return u, b
            for k in ("results", "videos", "data"):
                v = h.get(k)
                for it in (v if isinstance(v, list) else []):
                    u, b = _video_pick_media_in(it)
                    if u or b:
                        return u, b
        elif isinstance(h, list):
            for it in h:
                u, b = _video_pick_media_in(it)
                if u or b:
                    return u, b
    return _video_pick_media_in(data)


def _video_task_status(obj, family: str = "") -> str:
    """任务状态（V4.79）：只认标准键，不把任意字符串当状态。"""
    if not isinstance(obj, dict):
        return ""
    if family == "dashscope_maas":
        out = obj.get("output")
        if isinstance(out, dict) and isinstance(out.get("task_status"), str) and out["task_status"].strip():
            return out["task_status"].strip().lower()
    for k in ("task_status", "status", "state"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    for holder in ("output", "data", "result"):
        h = obj.get(holder)
        if isinstance(h, dict):
            st = _video_task_status(h, family)
            if st:
                return st
    return ""


def _video_find_msg(obj):
    if isinstance(obj, dict):
        for k in ("message", "error", "task_status_msg", "status_msg", "msg"):
            if k in obj and isinstance(obj[k], str) and obj[k]:
                return obj[k]
        for v in obj.values():
            m = _video_find_msg(v)
            if m:
                return m
    elif isinstance(obj, list):
        for it in obj:
            m = _video_find_msg(it)
            if m:
                return m
    return ""


_TASK_ID_KEYS = ("task_id", "taskId", "job_id", "generation_id", "id", "uuid")


def _video_find_task_id(obj, allow_request_id: bool = True):
    """从提交响应里找「可轮询」的任务标识（各厂商键名不一）。

    V4.75 修复（关键）：阿里云百炼 / DashScope 的提交响应形如
    `{"request_id": "...", "output": {"task_id": "...", "task_status": "PENDING"}}`，
    `task_id` 嵌在 `output`（或 `data`）里，顶层只有 `request_id`。
    旧实现把顶层键按顺序查找，`request_id` 排在候选里，于是误把「请求追踪号」
    当成任务号去轮询 `/api/v1/tasks/{request_id}`——永远查不到任务，轮询耗尽后
    静默回退分镜脚本。这正是「已配置视频大模型却生成不出视频」的根因。

    现在的顺序：先在被包裹的 output / data / result 里找任务号，再找顶层任务号，
    最后才把 request_id 当作部分网关的轮询键兜底。
    """
    if not isinstance(obj, dict):
        return None

    def _scan(d):
        if not isinstance(d, dict):
            return None
        for k in _TASK_ID_KEYS:
            v = d.get(k)
            if v:
                return str(v)
        # 再下探一层常见包裹（output.result / data.task）
        for wrap in ("result", "task", "video"):
            inner = d.get(wrap)
            if isinstance(inner, dict):
                for k in _TASK_ID_KEYS:
                    if inner.get(k):
                        return str(inner[k])
        return None

    # 1) 被包裹的任务对象优先（阿里云 output / 通用网关 data）
    for holder_key in ("output", "data", "result"):
        holder = obj.get(holder_key)
        if isinstance(holder, list) and holder:
            holder = holder[0]
        found = _scan(holder)
        if found:
            return found
    # 2) 顶层任务号
    found = _scan(obj)
    if found:
        return found
    # 3) 兜底：少量网关确实用 request_id 作为轮询键。
    #    但 dashscope 系（阿里云百炼）的 request_id 是请求追踪号，**不是**任务号——
    #    拿它去轮询必然查不到，旧版就是这么静默耗掉 6 分钟的。这类协议下不允许兜底。
    if allow_request_id and obj.get("request_id"):
        return str(obj["request_id"])
    return None


# ------------------------- 成片落盘校验（V4.79 / F05：三层校验） -------------------------
# 第一层 content-type / HTTP 状态；第二层容器 magic bytes + MP4 索引；第三层 ffprobe（若镜像内有）。
# 只要任一层不过就判失败 —— 以前下载异常直接 `return {"url": url}` 把外链当结果，
# 签名过期 / HTML 错误页都会落成「看起来成功但播不了」的坏文件。
_VIDEO_MIN_BYTES = 4096
_VIDEO_MAX_BYTES = 500 * 1024 * 1024


def _video_container(path: str) -> str:
    """按文件头识别视频容器（不依赖扩展名，也不轻信厂商 content-type）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except Exception:
        return ""
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if head[:3] == b"FLV":
        return "flv"
    if head[:3] == b"ID3":
        return "audio"
    if len(head) > 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "ts"
    return ""


def _mp4_has_moov(path: str) -> bool:
    """MP4 必须有 moov 索引才算完整（断点截断的 MP4 只有 ftyp + mdat，播放器打不开）。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if b"moov" in f.read(min(size, 4 * 1024 * 1024)):
                return True
            if size > 4 * 1024 * 1024:
                f.seek(max(0, size - 4 * 1024 * 1024))
                return b"moov" in f.read()
    except Exception:
        return False
    return False


def _ffprobe_video(path: str) -> dict:
    """可选第三层：镜像里有 ffprobe 就用它核轨道与时长；没有则跳过（不因缺工具判失败）。"""
    exe = shutil.which("ffprobe")
    if not exe:
        return {"available": False}
    try:
        p = subprocess.run(
            [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, timeout=20,
        )
        if p.returncode != 0:
            return {"available": True, "ok": False,
                    "reason": (p.stderr or b"").decode("utf-8", "ignore")[:200]}
        d = json.loads((p.stdout or b"{}").decode("utf-8", "ignore") or "{}")
        streams = [s for s in (d.get("streams") or []) if s.get("codec_type") == "video"]
        dur = float((d.get("format") or {}).get("duration") or 0)
        if not streams:
            return {"available": True, "ok": False, "reason": "没有视频轨道"}
        if dur <= 0:
            return {"available": True, "ok": False, "reason": "时长解析为 0"}
        return {"available": True, "ok": True, "duration": round(dur, 2),
                "width": streams[0].get("width"), "height": streams[0].get("height")}
    except Exception as e:
        return {"available": True, "ok": False, "reason": f"{type(e).__name__}: {e}"[:200]}


def _mp4_boxes(f, start: int, end: int):
    """遍历 [start, end) 区间内的 MP4 box，逐个 yield (type, payload_start, box_end)。不读 mdat 内容。"""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size = struct.unpack(">I", hdr[:4])[0]
        typ = hdr[4:8].decode("latin-1", "ignore")
        head = 8
        if size == 1:  # 64 位长度
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            head = 16
        elif size == 0:  # 直到文件尾
            size = end - pos
        if size < head:
            return
        yield typ, pos + head, pos + size
        pos += size


def _mp4_duration(path: str) -> float:
    """从 moov/mvhd 读出真实时长（秒）。无 ffprobe 时也能拿到实测值，零依赖、只读元数据。"""
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as f:
            for typ, p0, p1 in _mp4_boxes(f, 0, total):
                if typ != "moov":
                    continue
                for t2, q0, q1 in _mp4_boxes(f, p0, p1):
                    if t2 != "mvhd":
                        continue
                    f.seek(q0)
                    head = f.read(32)
                    if len(head) < 20:
                        return 0.0
                    ver = head[0]
                    if ver == 1:
                        if len(head) < 32:
                            return 0.0
                        scale = struct.unpack(">I", head[20:24])[0]
                        dur = struct.unpack(">Q", head[24:32])[0]
                    else:
                        scale = struct.unpack(">I", head[12:16])[0]
                        dur = struct.unpack(">I", head[16:20])[0]
                    if not scale or dur in (0, 0xFFFFFFFF):
                        return 0.0
                    return round(dur / scale, 2)
    except Exception:
        return 0.0
    return 0.0


_VIDEO_EXT_BY_CONTAINER = {"mp4": ".mp4", "webm": ".webm", "flv": ".flv", "ts": ".ts"}


def align_video_ext(path: str, container: str = "") -> str:
    """让扩展名与真实容器一致（厂商回 webm 却存成 .mp4 会被浏览器按 MIME 拒播）。"""
    cont = container or _video_container(path)
    want = _VIDEO_EXT_BY_CONTAINER.get(cont)
    if not want:
        return path
    root, cur = os.path.splitext(path)
    if cur.lower() == want:
        return path
    try:
        new = root + want
        if os.path.exists(new):
            return path
        os.replace(path, new)
        return new
    except Exception:
        return path


def verify_video_file(path: str) -> dict:
    """校验落盘文件是不是真能播的视频，返回结构化结论（不抛异常，便于把原因写进证据）。"""
    info: dict = {"ok": False, "path": path, "bytes": 0, "container": "", "reason": "", "ffprobe": {},
                  "duration": 0.0, "duration_source": ""}
    try:
        info["bytes"] = os.path.getsize(path)
    except Exception:
        info["reason"] = "文件不存在"
        return info
    if info["bytes"] < _VIDEO_MIN_BYTES:
        info["reason"] = f"文件仅 {info['bytes']} 字节，明显不是成片（可能下载到了错误页）"
        return info
    info["container"] = _video_container(path)
    if not info["container"]:
        try:
            with open(path, "rb") as f:
                sample = f.read(160).decode("utf-8", "ignore").strip()
        except Exception:
            sample = ""
        info["reason"] = f"不是可识别的视频容器（开头内容：{sample[:100]!r}）"
        return info
    if info["container"] == "audio":
        info["reason"] = "下载到的是音频（ID3），不是视频"
        return info
    if info["container"] == "mp4" and not _mp4_has_moov(path):
        info["reason"] = "MP4 缺少 moov 索引，文件不完整（常见于下载被中断）"
        return info
    probe = _ffprobe_video(path)
    info["ffprobe"] = probe
    if probe.get("available") and not probe.get("ok"):
        info["reason"] = "ffprobe 校验失败：" + str(probe.get("reason") or "")
        return info
    if probe.get("ok"):
        info["width"] = probe.get("width")
        info["height"] = probe.get("height")
        if probe.get("duration"):
            info["duration"] = probe.get("duration")
            info["duration_source"] = "ffprobe"
    # V4.80 / P1：没有 ffprobe 时直接读 moov/mvhd —— 时长必须来自真实文件，
    # 不能用「提示词里写的 15 秒」冒充交付时长（模型经常按要求只出 5s/10s 版本）。
    if not info["duration"] and info["container"] == "mp4":
        d = _mp4_duration(path)
        if d:
            info["duration"] = d
            info["duration_source"] = "mvhd"
    info["ok"] = True
    return info


async def download_video(url: str, out_path: str, evidence: Optional[dict] = None) -> dict:
    """下载成片并三层校验；失败抛 DOWNLOAD_FAILED（绝不把外链当结果返回）。"""
    ev = evidence if evidence is not None else {}
    tmp = out_path + ".part"
    status, ctype = 0, ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=600.0),
                                     follow_redirects=True) as c:
            async with c.stream("GET", url) as r:
                status = r.status_code
                ctype = (r.headers.get("content-type") or "").lower()
                if status >= 400:
                    body = (await r.aread())[:200]
                    raise VideoPipelineError(
                        "DOWNLOAD_FAILED", f"下载成片失败：HTTP {status}",
                        stage="download", http_status=status,
                        action="成片已在厂商侧生成但下载被拒（多为签名过期）：点「重新下载」重新获取地址。",
                        evidence={**ev, "download": {"http_status": status, "content_type": ctype,
                                                     "body": _video_evidence_snippet(body, 160)}},
                    )
                if "text/html" in ctype or "application/json" in ctype:
                    body = (await r.aread())[:300]
                    raise VideoPipelineError(
                        "DOWNLOAD_FAILED",
                        f"下载到的不是视频（content-type={ctype or '未知'}）：{_video_evidence_snippet(body, 160)}",
                        stage="download", http_status=status,
                        action="下载地址返回的是网页/JSON 而不是文件（多为签名过期或权限不足）：点「重新下载」。",
                        evidence={**ev, "download": {"http_status": status, "content_type": ctype,
                                                     "body": _video_evidence_snippet(body, 160)}},
                    )
                total = 0
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 20):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > _VIDEO_MAX_BYTES:
                            raise VideoPipelineError(
                                "DOWNLOAD_FAILED", "成片超过 500MB，已中止下载（避免占满磁盘）",
                                stage="download",
                                evidence={**ev, "download": {"http_status": status, "content_type": ctype,
                                                             "bytes": total}},
                            )
                        f.write(chunk)
        info = verify_video_file(tmp)
        if not info["ok"]:
            raise VideoPipelineError(
                "DOWNLOAD_FAILED", f"成片校验未通过：{info['reason']}",
                stage="download", http_status=status,
                evidence={**ev, "download": {"http_status": status, "content_type": ctype,
                                             "bytes": info.get("bytes"), "container": info.get("container"),
                                             "verify": info.get("reason")}},
            )
        os.replace(tmp, out_path)
        return {"http_status": status, "content_type": ctype, **{k: info.get(k) for k in
                ("bytes", "container", "duration", "duration_source", "width", "height")}}
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass



async def save_video_media(url: str, b64: str, filename: str, evidence: Optional[dict] = None) -> dict:
    """落盘成片（URL 与 base64 两条路径都必须过 `verify_video_file`）。

    V4.81 / P2：从 `ModelVideo._save_media` 提成模块函数 —— 后台 worker 续跑、单独重试下载
    与同步接口必须共用同一套落盘校验，否则「谁写文件谁定标准」会再次出现假成功。
    """
    ev = evidence if evidence is not None else {}
    out = os.path.join(UPLOAD_DIR, filename)
    if b64:
        payload = b64.split(",", 1)[1] if b64.startswith("data:") else b64
        try:
            raw = base64.b64decode(payload)
        except Exception as e:
            raise VideoPipelineError("DOWNLOAD_FAILED", f"成片 base64 解码失败：{e}",
                                     stage="download", evidence=ev)
        tmp = out + ".part"
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            info = verify_video_file(tmp)
            if not info["ok"]:
                raise VideoPipelineError("DOWNLOAD_FAILED", f"成片校验未通过：{info['reason']}",
                                         stage="download", evidence=ev)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        final = align_video_ext(out, info.get("container") or "")
        ev["download"] = {"source": "base64", "bytes": info.get("bytes"),
                          "container": info.get("container")}
        return {"file_path": final, "file_bytes": info.get("bytes"),
                "duration_sec": info.get("duration"),
                "duration_source": info.get("duration_source") or "", "evidence": ev}
    if not url:
        raise VideoPipelineError("EMPTY_OUTPUT", "既没有成片地址也没有 base64 内容",
                                 stage="download", evidence=ev)
    dl = await download_video(url, out, ev)
    final = align_video_ext(out, dl.get("container") or "")
    ev["download"] = {"source": "url", **dl}
    return {"file_path": final, "file_bytes": dl.get("bytes"),
            "duration_sec": dl.get("duration"),
            "duration_source": dl.get("duration_source") or "", "evidence": ev}
def _raise_http_error(code: int, raw: str, *, stage: str, evidence: dict, task_id: str = "") -> None:
    """把厂商 HTTP 状态翻译成可分类错误码（V4.79 / F02）。"""
    snippet = _video_evidence_snippet(raw, 300)
    if code in (401, 403):
        raise VideoPipelineError("AUTH_FAILED", f"鉴权失败（HTTP {code}）：{snippet}",
                                 stage=stage, http_status=code, task_id=task_id, evidence=evidence)
    if code == 429:
        raise VideoPipelineError("RATE_LIMITED", f"厂商限流（HTTP 429）：{snippet}",
                                 stage=stage, http_status=code, task_id=task_id, evidence=evidence)
    if code >= 500:
        raise VideoPipelineError("PROVIDER_ERROR", f"厂商侧错误（HTTP {code}）：{snippet}",
                                 stage=stage, http_status=code, task_id=task_id, evidence=evidence)
    raise VideoPipelineError("BAD_REQUEST", f"请求被拒（HTTP {code}）：{snippet}",
                             stage=stage, http_status=code, task_id=task_id, evidence=evidence)


def _evidence_poll(evidence: dict, n: int, http_status: int, obj, reason: str) -> None:
    """记录一次轮询（前 3 条 + 最近 5 条，避免证据无限增长）。"""
    rec: dict = {"n": n, "http_status": http_status}
    if obj is not None:
        rec["status"] = _video_task_status(obj, evidence.get("family", ""))
        rec["digest"] = _video_evidence_snippet(obj, 240)
    else:
        rec["error"] = (reason or "")[:200]
    polls = evidence.setdefault("polls", [])
    polls.append(rec)
    evidence["polls_total"] = len(polls)
    while len(polls) > 8:
        del polls[3]


class ModelVideo(VideoProvider):
    """可配置视频模型：POST {base_url}{endpoint|/video/generations}，兼容同步直出与异步任务两种形态。

    厂商差异（Runway / Pika / Luma / 302.ai / 可灵聚合网关等）通过 params.endpoint 对齐：
    - 同步网关（OpenAI / Sora 风格）直接返回视频 url / b64_json；
    - 异步厂商（主流）提交后返回 task_id，本类自动轮询任务状态并取片，
      轮询地址依次尝试 {base_url}/v1/video/generations/tasks/{id}、/{video/generations}/{id}、
      /tasks/{id}、{endpoint}/{id} 等常见形态。
    图生视频：body 带 image + mode=image_to_video。

    V4.79 行为变更（P0）：失败不再「吞掉并回退分镜」，而是抛 `VideoPipelineError`，
    带 error_code / 唯一处置动作 / 脱敏证据；成功必须落盘一个通过容器与轨道校验的本地文件。
    唯一保留的「非错误回退」是没有视频配置（由 routers 层决定走分镜）。

    扩展开关（写在模型配置的「参数(JSON)」里，均为字符串）：
    - endpoint：提交路径，默认 /video/generations；
    - body_shape="dashscope_maas"：改用阿里云百炼 MaaS 契约
      {model, input:{prompt}, parameters:{size,count}}（图生视频再补 input.image / parameters.mode）；
    - async_header="true"：提交时附加 X-DashScope-Async: enable 头（阿里云 MaaS 异步必需）；
    - poll_path：自定义轮询路径（如 /api/v1/tasks），优先于内置候选地址尝试；
    - poll_timeout_sec / poll_interval_sec：轮询总时长与间隔（默认 360s / 3s）。
    """
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.params = params or {}

    @property
    def family(self) -> str:
        return "dashscope_maas" if (self.params.get("body_shape") or "").strip() == "dashscope_maas" else "generic"

    def _poll_urls(self, task_id, endpoint):
        ep = endpoint or "/video/generations"
        # 厂商自定义轮询路径（如阿里云百炼 MaaS 的 /api/v1/tasks/{id}）：显式声明了契约
        # 就只查这一条，避免每轮额外打 5 个必然 404 的候选地址（长轮询下会撞限流）。
        poll_path = (self.params.get("poll_path") or "").strip()
        if poll_path:
            return [f"{self.base_url}{poll_path}/{task_id}"]
        return [
            f"{self.base_url}/v1/video/generations/tasks/{task_id}",
            f"{self.base_url}/video/generations/tasks/{task_id}",
            f"{self.base_url}/v1/video/generations/{task_id}",
            f"{self.base_url}{ep}/{task_id}",
            f"{self.base_url}/tasks/{task_id}",
        ]

    def _headers(self) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if str(self.params.get("async_header") or "").strip().lower() in ("true", "1", "yes"):
            headers["X-DashScope-Async"] = "enable"
        return headers

    def _body(self, prompt: str, meta: dict) -> dict:
        if self.family == "dashscope_maas":
            # 阿里云百炼 MaaS（wan3.0-video 等）契约：提交体为
            # {model, input:{prompt}, parameters:{size,count,duration}}，且需 X-DashScope-Async 头。
            # V4.83 / C05：此前只发 size/count，未传 duration，厂商按自身模板固定出 5s；
            # 用户选 15s 也只拿到 5.04s，页面仅提示警告仍标成功。现在把目标时长真正写进请求，
            # 并在交付门按实测时长判定（见 creative_tasks._duration_verdict）。
            aspect = meta.get("aspect", "9:16")
            size = meta.get("size") or ("1080*1920" if aspect == "9:16" else "1280*720")
            parameters: dict = {"size": size, "count": 1}
            duration = int(meta.get("duration") or 0)
            # 只有明确选了时长才发送；不传 0 给不支持该字段的旧模型。
            # send_duration=false 是给「该字段会 400」的厂商留的配置出口，默认发送以满足 15s 交付。
            if duration > 0 and str(self.params.get("send_duration", "true")).strip().lower() not in ("false", "0", "no"):
                parameters["duration"] = duration
            body = {
                "model": self.model,
                "input": {"prompt": prompt},
                "parameters": parameters,
            }
            if meta.get("image"):
                # wan3.0 官方图生视频用 input.media（type + media_url）；老端点仍接受 input.image。
                # 通过模型配置 media_input=true 显式切换，不猜入口、不把本地路径当公网 URL。
                if str(self.params.get("media_input", "false")).strip().lower() in ("true", "1", "yes"):
                    body["input"]["media"] = {
                        "type": "image_url",
                        "media_url": meta["image"],
                    }
                else:
                    body["input"]["image"] = meta["image"]
                body["parameters"]["mode"] = "image_to_video"
            return body
        body = {
            "model": self.model,
            "prompt": prompt,
            "duration": meta.get("duration", 15),
            "aspect_ratio": meta.get("aspect", "9:16"),
        }
        # 图生视频支持——把参考图作为 image 字段带入（厂商忽略即视为文生视频）
        if meta.get("image"):
            body["image"] = meta["image"]
            body["mode"] = meta.get("mode") or "image_to_video"
        return body

    async def _save_media(self, url, b64, filename, output_aspect, evidence):
        out = await save_video_media(url, b64, filename, evidence)
        out.update({"provider": "model", "model": self.model, "output_aspect": output_aspect})
        return out

    # ---- V4.81 / P2：分步执行（提交 / 查询一次 / 落盘），供持久化 worker 驱动 ----
    def plan_request(self, prompt, meta=None) -> dict:
        """冻结本次请求形态：同参数必得同结果，提交与后续每次查询都复用它。

        worker 重启后按这份「请求形态」重建请求，所以除 prompt 外全部入参都来自已冻结的
        任务快照，不允许在查询阶段读取会变化的实时状态。
        """
        meta = dict(meta or {})
        family = self.family
        if not self.base_url:
            raise VideoPipelineError("CONFIG_MISSING", "视频模型未配置请求地址（base_url）",
                                     stage="config", evidence={"family": family, "model": self.model})
        endpoint = (self.params.get("endpoint") or "/video/generations").strip()
        # 实际输出比例：部分厂商（如阿里云百炼 MaaS / wan3.0-video）忽略 size、固定输出
        # 9:16 竖屏。通过参数 output_aspect 显式声明固定比例（dashscope_maas 默认 9:16），
        # 生成链路据此把比例标注为 9:16，而非用户所选比例。
        forced = (self.params.get("output_aspect") or "").strip()
        if not forced and family == "dashscope_maas":
            forced = "9:16"
        out_aspect = forced or meta.get("aspect", "9:16")
        if forced:
            meta["aspect"] = forced
        # V4.85：X-DashScope-Async 只在「提交」时必需（触发异步任务），查询任务接口
        # （GET /api/v1/tasks/{id}）不应携带该头，部分网关会因此返回 400/403。
        # 冻结一份与提交头分离的「轮询头」，worker 重启续查复用同一份，不读实时配置。
        submit_headers = self._headers()
        poll_headers = {k: v for k, v in submit_headers.items()
                        if k.lower() != "x-dashscope-async"}
        return {
            "family": family, "endpoint": endpoint, "out_aspect": out_aspect, "meta": meta,
            "body": self._body(prompt, meta), "headers": submit_headers,
            "poll_headers": poll_headers,
            "poll_timeout": float(self.params.get("poll_timeout_sec") or 360),
            "poll_interval": max(0.2, float(self.params.get("poll_interval_sec") or 3)),
            "max_failures": max(1, int(self.params.get("poll_max_failures") or 6)),
        }

    async def submit_job(self, prompt, meta=None, evidence=None) -> dict:
        """只提交、不轮询。async 模式下返回的 task_id 必须能被调用方立即落库。"""
        request = self.plan_request(prompt, meta)
        ev = evidence if evidence is not None else {}
        ev.setdefault("polls", [])
        ev.update({"family": request["family"], "model": self.model,
                   "endpoint": request["endpoint"], "submit": {}, "download": {}})
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0, read=120.0)) as c:
            try:
                r = await c.post(self.base_url + request["endpoint"],
                                 headers=request["headers"], json=request["body"])
            except Exception as e:
                raise VideoPipelineError(
                    "PROVIDER_ERROR", f"提交请求失败：{type(e).__name__}: {e}", stage="submit",
                    evidence={**ev, "submit": {"error": f"{type(e).__name__}: {e}"[:200]}},
                )
            raw_text = ""
            try:
                raw_text = r.text or ""
            except Exception:
                pass
            ev["submit"] = {"endpoint": request["endpoint"], "http_status": r.status_code,
                            "snippet": _video_evidence_snippet(raw_text, 300)}
            if r.status_code >= 400:
                _raise_http_error(r.status_code, raw_text, stage="submit", evidence=ev)
            try:
                data = r.json()
            except Exception:
                raise VideoPipelineError(
                    "CONTRACT_MISMATCH",
                    f"提交响应不是合法 JSON（可能被网关替换成 HTML 错误页）：{_video_evidence_snippet(raw_text, 200)}",
                    stage="submit", http_status=r.status_code, evidence=ev,
                )
            rid = str(data.get("request_id") or data.get("requestId") or "")[:80]
            url, b64 = video_media_of(data, request["family"])
            if url or b64:
                ev["mode"] = "sync"
                return {"mode": "sync", "request": request, "media": {"url": url, "b64": b64},
                        "request_id": rid, "http_status": r.status_code, "evidence": ev}
            task_id = _video_find_task_id(data, allow_request_id=(request["family"] != "dashscope_maas"))
            if not task_id:
                raise VideoPipelineError(
                    "CONTRACT_MISMATCH",
                    "提交响应里既没有成片地址也没有任务号："
                    f"{_video_evidence_snippet(data, 240)}",
                    stage="submit", http_status=r.status_code, evidence=ev,
                )
            ev["mode"] = "async"
            ev["submit"]["task_id"] = task_id
            return {"mode": "async", "request": request, "task_id": task_id,
                    "request_id": rid, "http_status": r.status_code, "evidence": ev}

    async def poll_job(self, task_id, request, evidence=None) -> dict:
        """查询一次（不睡眠、不循环）。返回 state = pending / succeeded / failed / unreachable。

        401/403 仍然直接抛 AUTH_FAILED —— 这类错误重试没有意义，继续空转只会拖长用户等待。
        """
        ev = evidence if evidence is not None else {}
        ev.setdefault("polls", [])
        n = len(ev.get("polls") or []) + 1
        obj, poll_http, poll_url, last_reason = None, 0, "", ""
        # V4.85：查询任务只带「轮询头」，绝不携带提交用的 X-DashScope-Async。
        # 兼容 worker 重启后读到的旧任务快照（冻结时还没有 poll_headers 字段）：
        # 这里再做一次防御性剔除，保证任何来源的查询都不带异步头。
        poll_headers = request.get("poll_headers")
        if not poll_headers:
            poll_headers = {k: v for k, v in (request.get("headers") or {}).items()
                            if k.lower() != "x-dashscope-async"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0, read=60.0)) as c:
            for u in self._poll_urls(task_id, request["endpoint"]):
                try:
                    q = await c.get(u, headers=poll_headers)
                except Exception as e:
                    last_reason = f"查询请求异常：{type(e).__name__}"
                    continue
                poll_http, poll_url = q.status_code, u
                if q.status_code in (401, 403):
                    _raise_http_error(q.status_code, (q.text or "")[:300], stage="poll",
                                      evidence=ev, task_id=task_id)
                if q.status_code == 404:
                    last_reason = "轮询地址返回 404（多为 poll_path 与厂商契约不一致）"
                    continue
                if q.status_code == 429 or q.status_code >= 500:
                    last_reason = (f"厂商侧 {q.status_code}："
                                   f"{_video_evidence_snippet((q.text or '')[:200], 120)}")
                    break  # 限流 / 5xx：退避，不换地址重试
                if q.status_code >= 400:
                    last_reason = f"查询被拒 HTTP {q.status_code}"
                    continue
                try:
                    obj = q.json()
                except Exception:
                    last_reason = "查询响应不是 JSON（可能被网关替换成 HTML）"
                    continue
                break
        ev["poll_url"] = poll_url
        _evidence_poll(ev, n, poll_http, obj, last_reason)
        if obj is None:
            return {"state": "unreachable", "reason": last_reason, "http_status": poll_http,
                    "status": "", "evidence": ev}
        st = _video_task_status(obj, request["family"])
        if st in _VIDEO_OK_STATES:
            url, b64 = video_media_of(obj, request["family"])
            if not (url or b64):
                raise VideoPipelineError(
                    "EMPTY_OUTPUT", f"任务已完成（{st}）但响应里没有成片地址",
                    stage="poll", task_id=task_id, evidence=ev,
                )
            return {"state": "succeeded", "status": st, "media": {"url": url, "b64": b64},
                    "http_status": poll_http, "evidence": ev}
        if st in _VIDEO_FAIL_STATES:
            msg = (_video_find_msg(obj) or "")[:200] or f"任务状态 {st}"
            return {"state": "failed", "status": st, "message": msg,
                    "http_status": poll_http, "evidence": ev}
        return {"state": "pending", "status": st, "http_status": poll_http,
                "reason": last_reason, "evidence": ev}

    async def generate(self, prompt, platform, filename, meta=None):
        """同步合成入口（保留给 /cw-video/generate 与旧调用方）：提交 → 循环查询 → 落盘校验。"""
        evidence: dict = {"family": self.family, "model": self.model, "polls": []}
        sub = await self.submit_job(prompt, meta, evidence)
        request = sub["request"]
        if sub["mode"] == "sync":
            return await self._save_media(sub["media"]["url"], sub["media"]["b64"],
                                          filename, request["out_aspect"], evidence)
        task_id = sub["task_id"]
        deadline = time.time() + request["poll_timeout"]
        interval = base_interval = request["poll_interval"]
        failures = 0
        while time.time() < deadline:
            await asyncio.sleep(interval)
            r = await self.poll_job(task_id, request, evidence)
            if r["state"] == "succeeded":
                return await self._save_media(r["media"]["url"], r["media"]["b64"],
                                              filename, request["out_aspect"], evidence)
            if r["state"] == "failed":
                raise VideoPipelineError(
                    "PROVIDER_REJECTED",
                    f"厂商回报任务失败（{r['status']}）：{r.get('message') or ''}",
                    stage="poll", task_id=task_id, evidence=evidence,
                )
            if r["state"] == "unreachable":
                failures += 1
                if failures >= request["max_failures"]:
                    raise VideoPipelineError(
                        "POLL_UNREACHABLE", f"连续 {failures} 次查询失败：{r.get('reason') or ''}",
                        stage="poll", task_id=task_id, evidence=evidence,
                    )
                interval = min(interval * 1.6, 15.0)
                continue
            failures = 0
            interval = base_interval
        raise VideoPipelineError(
            "POLL_TIMEOUT",
            f"{int(request['poll_timeout'])} 秒内任务未完成（task_id={task_id}），厂商侧可能仍在渲染",
            stage="poll", task_id=task_id, evidence=evidence,
        )

class KlingVideo(VideoProvider):
    """可灵（Kling AI）原生异步视频：提交 text2video / image2video 任务 → 轮询取片 → 下载落盘。

    鉴权：Kling 官方 API 用 JWT（HS256），由 params.access_key + params.secret_key 签发；
    若未配置 access/secret，则退化为把 api_key 当 Bearer、base_url 当 /video/generations 网关
    （即复用 ModelVideo 的通用契约），保证「可灵」在聚合网关（如 302.ai）下也能直连。
    任意环节失败 → 回退 StoryboardVideo，绝不阻断主流程。
    """
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://api.klingai.com").rstrip("/")
        self.model = model or "kling-v1"
        self.params = params or {}

    # ---- JWT（不依赖 pyjwt，用标准库手动签 HS256）----
    @staticmethod
    def _jwt(access_key: str, secret_key: str) -> str:
        import hmac as _hmac, hashlib as _hl, base64 as _b64, time as _t, json as _json
        def b(d): return _b64.urlsafe_b64encode(d).rstrip(b"=")
        header = b(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        now = int(_t.time())
        payload = b(_json.dumps({"iss": access_key, "exp": now + 1800, "nbf": now - 5}).encode())
        signing_input = header + b"." + payload
        sig = _hmac.new(secret_key.encode(), signing_input, _hl.sha256).digest()
        return (signing_input + b"." + b(sig)).decode()

    def _headers(self):
        ak = self.params.get("access_key") or ""
        sk = self.params.get("secret_key") or ""
        if ak and sk:
            return {"Authorization": f"Bearer {self._jwt(ak, sk)}", "Content-Type": "application/json"}
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return {"Content-Type": "application/json"}

    def _resolve_image(self, ref):
        """把参考图转成可灵可消费形态：本地文件 → base64 data URI；URL 原样。"""
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref
        p = os.path.join(UPLOAD_DIR, os.path.basename(ref))
        if os.path.exists(p):
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f"data:image/{'jpeg' if mime == 'image/jpeg' else ext};base64,{b64}"
        return ref

    async def generate(self, prompt, platform, filename, meta=None):
        meta = meta or {}
        ak = self.params.get("access_key") or ""
        sk = self.params.get("secret_key") or ""
        # 没有可灵鉴权信息（也不在 /video/generations 网关模式）→ 明确的配置错误（不再静默回退分镜）
        if not (ak and sk) and not self.api_key:
            raise VideoPipelineError(
                "CONFIG_MISSING",
                "可灵未配置鉴权：请填写 access_key + secret_key（原生协议）或 api_key（聚合网关）",
                stage="config", evidence={"family": "kling", "model": self.model},
            )
        image_ref = meta.get("image")
        use_img = bool(image_ref)
        sub_path = "/v1/videos/image2video" if use_img else "/v1/videos/text2video"
        duration = int(meta.get("duration", 10)) if str(meta.get("duration", "")).isdigit() else 10
        duration = 10 if duration not in (5, 10) else duration  # 可灵仅支持 5/10 秒
        aspect = meta.get("aspect", "9:16")
        body = {
            "model": self.model,
            "prompt": prompt,
            "mode": self.params.get("mode") or "std",
            "duration": str(duration),
        }
        if not use_img:
            body["aspect_ratio"] = aspect
        if use_img:
            body["image"] = self._resolve_image(image_ref)
            if meta.get("image_fidelity") is not None:
                body["image_fidelity"] = meta.get("image_fidelity")
        ev: dict = {"family": "kling", "model": self.model, "submit": {}, "polls": [], "download": {}}
        if meta.get("duration") and str(meta.get("duration")).isdigit() and int(meta["duration"]) not in (5, 10):
            ev["duration_note"] = f"可灵仅支持 5/10 秒，已按 {duration} 秒提交（所选 {meta['duration']} 秒无法满足）"
        task_id = ""
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(self.base_url + sub_path, headers=self._headers(), json=body)
                ev["submit"] = {"endpoint": sub_path, "http_status": r.status_code,
                                "snippet": _video_evidence_snippet(r.text or "", 300)}
                if r.status_code >= 400:
                    _raise_http_error(r.status_code, r.text or "", stage="submit", evidence=ev)
                data = r.json()
                task_id = (data.get("data") or {}).get("task_id")
                if not task_id:
                    raise VideoPipelineError(
                        "CONTRACT_MISMATCH",
                        "可灵提交响应没有 task_id：" + _video_evidence_snippet(data, 200),
                        stage="submit", evidence=ev,
                    )
                ev["submit"]["task_id"] = task_id
                # 轮询（最多 ~6 分钟）
                for n in range(1, 121):
                    await asyncio.sleep(3)
                    q = await c.get(self.base_url + sub_path + "/" + task_id, headers=self._headers())
                    try:
                        qd = (q.json() or {}).get("data") or {}
                    except Exception:
                        _evidence_poll(ev, n, q.status_code, None, "查询响应不是 JSON")
                        continue
                    _evidence_poll(ev, n, q.status_code, qd, "")
                    status = qd.get("task_status")
                    if status == "succeed":
                        result = qd.get("task_result") or {}
                        videos = result.get("videos") or [
                            (w.get("resource") or {}).get("resource_url")
                            for w in (result.get("works") or [])
                        ]
                        url = None
                        if isinstance(videos, list) and videos:
                            if isinstance(videos[0], str):
                                url = videos[0]
                            elif isinstance(videos[0], dict):
                                url = videos[0].get("resource_url")
                        if not url:
                            raise VideoPipelineError(
                                "EMPTY_OUTPUT", f"可灵任务成功但没有成片地址：{_video_evidence_snippet(qd, 200)}",
                                stage="poll", task_id=task_id, evidence=ev,
                            )
                        # 成片下载同样走三层校验（不再直接把响应字节写成 .mp4）
                        out = os.path.join(UPLOAD_DIR, filename.rsplit(".", 1)[0] + ".mp4")
                        dl = await download_video(url, out, ev)
                        out = align_video_ext(out, dl.get("container") or "")
                        ev["download"] = {"source": "url", **dl}
                        return {"provider": "kling", "file_path": out, "model": self.model,
                                "output_aspect": aspect, "file_bytes": dl.get("bytes"),
                                "duration_sec": dl.get("duration"),
                                "duration_source": dl.get("duration_source") or "",
                                "evidence": ev,
                                "note": ev.get("duration_note") or ""}
                    if status == "failed":
                        raise VideoPipelineError(
                            "PROVIDER_REJECTED",
                            "可灵任务失败：" + (str(qd.get("task_status_msg") or "")[:200] or status),
                            stage="poll", task_id=task_id, evidence=ev,
                        )
                raise VideoPipelineError(
                    "POLL_TIMEOUT", f"可灵任务约 6 分钟内未完成（task_id={task_id}）",
                    stage="poll", task_id=task_id, evidence=ev,
                )
        except VideoPipelineError:
            raise
        except Exception as e:   # 网络层异常：分类上报，绝不静默换分镜冒充交付
            raise VideoPipelineError(
                "PROVIDER_ERROR", f"可灵调用失败：{type(e).__name__}: {e}",
                stage="poll" if task_id else "submit", task_id=task_id, evidence=ev,
            )


# ----------------------------- 真实 OpenAI 兼容 -----------------------------
class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    async def chat(self, system, user, **kw):
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                self.base_url + "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": self.params.get("temperature", 0.7),
                    # 9 模块结构化 JSON 输出较长，上限过小会被截断导致解析失败；这里设下限保护。
                    "max_tokens": max(int(self.params.get("max_tokens", 4096)), 3000),
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

class AnthropicLLM(LLMProvider):
    """Anthropic Claude：自有 /v1/messages 协议（x-api-key 头 + anthropic-version）。"""
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    async def chat(self, system, user, **kw):
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                self.base_url + "/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "max_tokens": max(int(self.params.get("max_tokens", 4096)), 256),
                    "temperature": self.params.get("temperature", 0.7),
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]


class GeminiLLM(LLMProvider):
    """Google Gemini：generateContent 协议（Key 以 ?key= 追加）。"""
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    async def chat(self, system, user, **kw):
        url = self.base_url + f"/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {
                        "maxOutputTokens": max(int(self.params.get("max_tokens", 4096)), 3000),
                        "temperature": self.params.get("temperature", 0.7),
                    },
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


def _classify_error(exc: Exception) -> str:
    """把供应商异常归类，供调用快照记录（不记录密钥、不记录响应正文）。"""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timed out" in text:
        return "timeout"
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return "auth"
    if "429" in text or "rate" in text:
        return "rate_limit"
    if "connect" in name or "network" in name:
        return "network"
    return "upstream"


class FallbackLLM(LLMProvider):
    """真实模型调用失败时自动回退 Mock，保证主流程不中断。

    used_fallback 记录本次调用是否真的走了兜底，供上层如实标注结果来源，
    避免「配了模型但实际用了 Mock」却被标记成 llm 的错误归因。
    V4.39 / F10：额外记录错误分类与异常类型名，由 finalize_invocation 在**调用之后**读取。
    """
    def __init__(self, real, fallback):
        self.real = real
        self.fallback = fallback
        self.used_fallback = False
        self.error_type = ""
        self.exception_type = ""
        self.retries = 0

    async def chat(self, system, user, **kw):
        try:
            out = await self.real.chat(system, user, **kw)
            self.used_fallback = False
            self.error_type = ""
            return out
        except Exception as e:
            self.used_fallback = True
            self.error_type = _classify_error(e)
            self.exception_type = type(e).__name__
            return await self.fallback.chat(system, user, **kw)

class OpenAIImage(ImageProvider):
    """文生图（DALL·E 兼容）：POST /images/generations，解码 b64 底图保存到 path。

    只负责"生成背景底图"，文案/版式叠加交给 render_creative 统一合成，
    这样文生图背景能与广告版式（评分卡/折扣角标/对比等）完美贴合。失败返回 None。
    """
    capability_key = "openai_image"

    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    @staticmethod
    def _nearest_size(width: int, height: int) -> str:
        ratio = width / max(1, height)
        if ratio > 1.2:
            return "1792x1024"
        if ratio < 0.83:
            return "1024x1792"
        return "1024x1024"

    async def generate(self, prompt, width, height, filename, copy=None):
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    self.base_url + "/images/generations",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "prompt": prompt, "n": 1,
                          "size": self._nearest_size(width, height), "response_format": "b64_json"},
                )
                r.raise_for_status()
                b64 = (r.json().get("data") or [{}])[0].get("b64_json")
                if not b64:
                    return None
                path = os.path.join(UPLOAD_DIR, filename)
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
                return path
        except Exception:
            return None


class GenericImageProvider(ImageProvider):
    """通用文生图：POST {base_url}{endpoint|/images/generations}，兼容多数厂商。

    endpoint 默认 /images/generations；Stable Diffusion 等可经 params.endpoint 指定
    （如 /sdapi/v1/txt2img）。返回解码后的背景底图路径；失败返回 None。
    """
    capability_key = "generic_image"

    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    @staticmethod
    def _decode(resp) -> Optional[bytes]:
        """从多种响应形态里抽取图像字节。"""
        if not isinstance(resp, dict):
            return None
        item = (resp.get("data") or [{}])[0] if isinstance(resp.get("data"), list) else {}
        if isinstance(item, dict) and item.get("b64_json"):
            try: return base64.b64decode(item["b64_json"])
            except Exception: pass
        if isinstance(item, dict) and item.get("url"):
            try: return httpx.get(item["url"], timeout=30).content
            except Exception: pass
        if isinstance(resp.get("images"), list) and resp["images"]:
            try: return base64.b64decode(resp["images"][0])
            except Exception: pass
        for k in ("output", "image", "images_b64"):
            v = resp.get(k)
            if isinstance(v, str):
                try: return base64.b64decode(v)
                except Exception: pass
        return None

    async def generate(self, prompt, width, height, filename, copy=None):
        endpoint = (self.params.get("endpoint") or "/images/generations").strip()
        url = self.base_url + endpoint
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "sdapi" in endpoint:
            body = {"prompt": prompt, "width": width, "height": height, "batch_size": 1, "n_iter": 1}
        else:
            body = {"model": self.model, "prompt": prompt, "size": f"{width}x{height}",
                    "n": 1, "response_format": "b64_json"}
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(url, headers=headers, json=body)
                r.raise_for_status()
                raw = self._decode(r.json())
                if not raw:
                    return None
                path = os.path.join(UPLOAD_DIR, filename)
                with open(path, "wb") as f:
                    f.write(raw)
                return path
        except Exception:
            return None


class DashScopeMaaSImageProvider(ImageProvider):
    """阿里云 MaaS 多模态生成（qwen-image 系列）。

    端点为「完整 URL」，形如 .../api/v1/services/aigc/multimodal-generation/generation，
    base_url 即整条地址，不再追加路径。
    请求体：{"model", "input":{"messages":[{"role":"user","content":[{"text":prompt}]}]},
             "parameters":{"size":"W*H","n":1}}
    响应：output.choices[0].message.content[0].image = 带签名的 OSS 临时 URL，需立即下载落盘。
    该端点仅支持同步调用（X-DashScope-Async 会被拒 403），超时设 180s。
    任意环节失败返回 None，由 Pillow 模板兜底，绝不阻断主流程。
    """
    capability_key = "dashscope_maas"

    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.params = params or {}
        # V4.42 / F06：记录本实例最近一次真实请求 / 返回尺寸，供逐图归档核对
        self.last_generation_meta: dict = {}

    @staticmethod
    def _snap(n: int) -> int:
        """兼容旧调用（单维度吸附到 1024 / 2048）。F06 后不再用两个 _snap 拼请求尺寸。"""
        return 2048 if n >= 1536 else 1024

    async def generate(self, prompt, width, height, filename, copy=None):
        from image_capabilities import plan_generation_size
        plan = plan_generation_size(self.capability_key, width, height, self.params)
        rw, rh = plan["request_size"]
        self.last_generation_meta = {**plan, "returned_size": None, "model": self.model}
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                r = await c.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                        # F06：宽高作为比例整体选择已声明的候选，不再各自 _snap 成方形
                        "parameters": {"size": f"{rw}*{rh}", "n": 1},
                    },
                )
                r.raise_for_status()
                data = r.json()
                img_url = (
                    data.get("output", {}).get("choices", [{}])[0]
                    .get("message", {}).get("content", [{}])[0].get("image")
                )
                if not img_url:
                    return None
                # 签名 URL 有效期短，立即下载落盘
                resp = await c.get(img_url)
                resp.raise_for_status()
                path = os.path.join(UPLOAD_DIR, filename)
                with open(path, "wb") as f:
                    f.write(resp.content)
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        self.last_generation_meta["returned_size"] = list(im.size)
                except Exception:
                    pass
                return path
        except Exception:
            return None


# ----------------------------- 工厂（按用途返回激活 provider） -----------------------------
def _usages_of(cfg) -> list:
    """兼容新旧两种存储：新配置存 usages(JSON 数组)，旧配置存 usage(单字符串)。

    V4.109：两列取**并集**，不再二选一。此前 `usages` 存在但为空数组（编辑时取消了
    全部勾选、或历史迁移写入 `[]`）会盖掉仍有内容的 `usage` 列，真实环境里表现为
    「明明配了图片模型，系统却按未配置处理」。
    """
    out: list[str] = []
    for v in (getattr(cfg, "usages", None), getattr(cfg, "usage", None)):
        if isinstance(v, list):
            out.extend(str(x) for x in v if x)
        elif v:
            out.append(str(v))
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def _usable(cfg) -> bool:
    """配置具备真实调用的最少三要素（缺任一项只能退回 Mock）。"""
    return bool(cfg.api_key and cfg.base_url and cfg.model)


# V4.78：视频模型「模态」识别。
# 仅凭「用途 = video」不足以判定一条配置能出片——文本配置（deepseek-chat / qwen-plus …）
# 一旦被误勾「视频模型」，出片就会拿它去打 /video/generations，必然失败并静默回退分镜，
# 用户看到的现象就是「创意工作台调用的视频模型变成了 deepseek」。这里用协议 + 厂商 key +
# 参数契约 + 模型名四路识别，把文本配置从视频候选里剔除。
_VIDEO_MODEL_HINT = re.compile(
    r"(video|cogvideo|veo|sora|runway|gen-?3|kling|keling|wanx|wan\d|pika|luma|vidu|"
    r"hailuo|seedance|jimeng|zhiying|pixverse|haiper|higgsfield|seaweed|midjourney-video)",
    re.I,
)


def is_video_capable(cfg) -> bool:
    """判断一条模型配置是否**具备视频出片能力**（V4.78）。"""
    from llm_catalog import _resolve_protocol, get_video_preset

    prov = str(getattr(cfg, "provider", "") or "")
    try:
        if _resolve_protocol(prov) == "generic-video":
            return True
    except Exception:
        pass
    try:
        if get_video_preset(prov):
            return True
    except Exception:
        pass
    low = prov.lower()
    if "video" in low or "keling" in low or "kling" in low:
        return True
    params = getattr(cfg, "params", None)
    if isinstance(params, dict):
        # 视频厂商契约参数存在，即视为视频端点（阿里云百炼 MaaS / 异步轮询型网关）
        if str(params.get("body_shape") or "").strip() == "dashscope_maas":
            return True
        if str(params.get("poll_path") or "").strip():
            return True
    return bool(_VIDEO_MODEL_HINT.search(str(getattr(cfg, "model", "") or "")))


def video_route_report(db) -> dict:
    """视频模型路由剖析（V4.78）：给出「实际选中谁、谁被跳过、为什么」。

    供 /cw-video/diagnose 与出片失败提示共用，避免用户只能看到一句
    「未配置视频模型」而无法判断到底命中了哪条配置。
    """
    from models import ModelConfig

    rows = db.query(ModelConfig).all()
    tagged = [c for c in rows if "video" in _usages_of(c)]
    capable, skipped = [], []
    for c in tagged:
        if is_video_capable(c):
            capable.append(c)
        else:
            reasons = []
            if not c.is_active:
                reasons.append("已停用")
            if not _usable(c):
                reasons.append("缺 API Key / 请求链接 / 模型版本")
            reasons.append("不是视频协议或视频模型（文本模型不能用于出片）")
            skipped.append({"cfg": c, "reason": "；".join(reasons)})
    return {"picked": _pick_config(rows, "video"), "tagged": tagged,
            "candidates": capable, "skipped": skipped}


def _pick_config(rows, usage):
    """挑选某用途实际生效的配置（V4.39 / F10 修复）。

    V4.34 的优先级保留：同用途多条时先看每日连通测试成功者，再看 id 最大者。
    **F10**：候选必须先过 `is_active`。此前 `last_test_ok=True` 的分支没有过滤停用项，
    导致「已停用但昨天测试成功」的配置仍会被系统自动调用（说明书 T13）。
    仅显式启用的配置才能进入候选；全部失败 / 未测试时保持旧行为。
    """
    candidates = [c for c in rows
                  if c.is_active and usage in _usages_of(c) and _usable(c)]
    # V4.78：video 用途必须再过一道模态校验。文本配置（deepseek / qwen-plus …）即使被
    # 误勾「视频模型」，也不能接管出片——否则会把 /chat/completions 的模型打到
    # /video/generations 上，失败后静默回退分镜，表现为「视频模型变成了 deepseek」。
    if usage == "video":
        candidates = [c for c in candidates if is_video_capable(c)]
    if not candidates:
        return None
    oks = [c for c in candidates if c.last_test_ok is True]
    pool = oks or candidates
    return max(pool, key=lambda c: c.id)


def effective_config_ids(db) -> set:
    """返回当前被系统功能实际采用的全部配置 id（供设置页标注「系统采用」）。"""
    from models import ModelConfig
    rows = db.query(ModelConfig).all()
    usages = set()
    for c in rows:
        usages.update(_usages_of(c))
    ids = set()
    for u in usages:
        c = _pick_config(rows, u)
        if c:
            ids.add(c.id)
    return ids


def _active_config(db, usage):
    # 延迟导入避免循环依赖
    from models import ModelConfig
    return _pick_config(db.query(ModelConfig).all(), usage)

def get_llm_with_info(db, usage="analysis") -> tuple[LLMProvider, dict]:
    """V4.39 / F10：统一路由入口，**只挑选一次配置**，同时返回调用快照。

    此前 services._resolve_model 自己按 is_active 挑一次，get_llm 又按 last_test_ok
    挑一次，页面展示的配置可能与实际调用的不同。现在展示与调用共用同一个 cfg。
    快照字段：provider / model / role / config_id / request_id / source / fallback /
    error_type / retries；不含 api_key、base_url 等敏感信息。
    """
    cfg = _active_config(db, usage)
    info = {
        "provider": (cfg.provider if cfg else ""),
        "model": ((cfg.model or "") if cfg else ""),
        "role": usage,
        "config_id": (cfg.id if cfg else None),
        "request_id": uuid.uuid4().hex[:12],
        "source": "mock" if not cfg else "llm",
        "fallback": not bool(cfg),
        "error_type": "",
        "retries": 0,
    }
    if not cfg:
        return MockLLM(), info
    try:
        from llm_catalog import _resolve_protocol
        protocol = _resolve_protocol(cfg.provider)
        if protocol == "anthropic":
            real = AnthropicLLM(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        elif protocol == "gemini":
            real = GeminiLLM(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        else:
            real = OpenAICompatibleLLM(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        return FallbackLLM(real, MockLLM()), info
    except Exception:
        info["fallback"] = True
        info["source"] = "mock"
        info["error_type"] = "init_error"
        return MockLLM(), info


def finalize_invocation(info: dict, llm: LLMProvider, parsed_ok: bool = True) -> dict:
    """V4.39 / F10：在 `chat()` **结束之后**刷新回退与来源标记。

    说明书已复现：used_fallback 在调用前读取永远是 False，Mock 返回可解析 JSON 时
    会被误标为 source=llm。这里统一按调用后的真实状态定稿。
    """
    info = dict(info or {})
    used = bool(getattr(llm, "used_fallback", False))
    if used:
        info["fallback"] = True
        info["source"] = "mock"
        info["error_type"] = getattr(llm, "error_type", "") or info.get("error_type", "")
    elif not info.get("provider"):
        info["fallback"] = True
        info["source"] = "mock"
    else:
        info["fallback"] = False
        info["source"] = "llm" if parsed_ok else "invalid_response"
    info["retries"] = int(getattr(llm, "retries", 0) or 0)
    return info


def resolve_analysis_llm(db) -> tuple[LLMProvider, dict]:
    """落地页分析专用：优先 analysis 模型，未配置时复用 copy 模型（V4.22 行为）。

    与 get_llm 共用同一套 _active_config 路由，避免「展示一套、调用另一套」。
    """
    usage = "analysis" if _active_config(db, "analysis") else (
        "copy" if _active_config(db, "copy") else "analysis")
    return get_llm_with_info(db, usage)


def get_llm(db, usage="analysis") -> LLMProvider:
    """兼容旧调用：只取 provider；需要归因的调用点改用 get_llm_with_info。"""
    return get_llm_with_info(db, usage)[0]

def get_image(db) -> Optional[ImageProvider]:
    """返回激活的文生图 Provider；未配置 Key/URL/Model 时返回 None（由 Pillow 模板兜底）。"""
    cfg = _active_config(db, "image")
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        try:
            from llm_catalog import _resolve_protocol
            proto = _resolve_protocol(cfg.provider)
            if proto == "openai-image":
                return OpenAIImage(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
            if proto == "dashscope-maas-image":
                return DashScopeMaaSImageProvider(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
            return GenericImageProvider(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        except Exception:
            pass
    return None

def video_provider_of_config(cfg) -> Optional[VideoProvider]:
    """V4.81 / P2：按「已落库的那条配置」构造视频 Provider。

    持久化任务必须用它而不是 `get_video(db)`：任务可能跑了 6 分钟，期间管理员切了默认
    配置；按配置 ID 复现才能保证「提交与查询打的是同一个厂商、同一个模型」。
    """
    if not (cfg and getattr(cfg, "api_key", None) and getattr(cfg, "base_url", None)
            and getattr(cfg, "model", None)):
        return None
    try:
        if (cfg.provider or "") == "keling":
            return KlingVideo(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        return ModelVideo(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
    except Exception:
        return None


def get_video(db) -> VideoProvider:
    """按「大模型配置」的 video 用途返回视频 Provider。
    - provider == 'keling' → 可灵原生异步 API（KlingVideo）
    - 其余 generic-video（Runway / Pika / Luma / 302.ai 等）→ 通用 /video/generations（ModelVideo）
    - 未配置 Key/URL/Model → 回退 StoryboardVideo（输出可执行分镜脚本）
    """
    cfg = _active_config(db, "video")
    prov = video_provider_of_config(cfg)
    if prov is not None:
        return prov
    return StoryboardVideo()


# ----------------------------- JSON 解析工具 -----------------------------
def parse_json(resp: str):
    """从模型回复中稳健提取 JSON。"""
    txt = resp.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
    try:
        return json.loads(txt)
    except Exception:
        pass
    s, e = txt.find("{"), txt.rfind("}")
    if s != -1 and e != -1:
        try:
            return json.loads(txt[s:e + 1])
        except Exception:
            pass
    return {}
