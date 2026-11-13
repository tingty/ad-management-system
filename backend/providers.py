"""
AI 模型接入层（可配置多模型）。
- 未配置任何 Key 时，使用 Mock provider，保证 MVP 端到端可跑通。
- 在「设置页」配置 OpenAI 兼容协议的 api_key / base_url / model 后，自动切换为真实调用。
- 图像 provider 接入真实 DALL·E 风格接口失败时自动回退到占位图，避免阻断主流程。
"""
import os, json, re, httpx, base64, asyncio, itertools, uuid
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

    async def generate(self, prompt: str, width: int, height: int, filename: str) -> str:
        """返回保存后的文件路径。"""
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

# ------------------------- 通用视频响应解析辅助（适配多厂商异步/同步形态） -------------------------
_VIDEO_URL_KEYS = ("url", "video_url", "resource_url", "videoUrl", "video")
_VIDEO_B64_KEYS = ("b64_json", "base64")


def _video_find_media(obj, _u=None, _b=None):
    """递归在响应 JSON 中找首个视频 URL 与首个 b64_json（通用体，适配 OpenAI / Runway / Pika / Luma 等）。"""
    if _u and _b:
        return _u, _b
    if isinstance(obj, str):
        if _u is None and obj.startswith("http"):
            return obj, _b
        if _b is None and obj.startswith("data:"):
            return _u, obj
        return _u, _b
    if isinstance(obj, dict):
        for k in _VIDEO_URL_KEYS:
            if _u is None and k in obj and isinstance(obj[k], str) and obj[k].startswith("http"):
                _u = obj[k]
        for k in _VIDEO_B64_KEYS:
            if _b is None and k in obj and isinstance(obj[k], str) and obj[k]:
                _b = obj[k]
        if _u is None or _b is None:
            for v in obj.values():
                _u, _b = _video_find_media(v, _u, _b)
    elif isinstance(obj, list):
        for it in obj:
            if _u is None or _b is None:
                _u, _b = _video_find_media(it, _u, _b)
    return _u, _b


def _video_find_status(obj):
    if isinstance(obj, dict):
        for k in ("status", "task_status", "state"):
            if k in obj and isinstance(obj[k], str):
                return obj[k].lower()
        for v in obj.values():
            s = _video_find_status(v)
            if s:
                return s
    elif isinstance(obj, list):
        for it in obj:
            s = _video_find_status(it)
            if s:
                return s
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


def _video_find_task_id(obj):
    """从提交响应里找任务标识（各厂商键名不一：id/task_id/uuid/job_id/generation_id/request_id）。"""
    if isinstance(obj, dict):
        for k in ("id", "task_id", "taskId", "uuid", "job_id", "generation_id", "request_id"):
            if obj.get(k):
                return str(obj[k])
        data = obj.get("data")
        if isinstance(data, dict):
            for k in ("id", "task_id", "taskId", "uuid"):
                if data.get(k):
                    return str(data[k])
        if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get("id"):
            return str(data[0]["id"])
    return None


class ModelVideo(VideoProvider):
    """可配置视频模型：POST {base_url}{endpoint|/video/generations}，兼容同步直出与异步任务两种形态。

    厂商差异（Runway / Pika / Luma / 302.ai / 可灵聚合网关等）通过 params.endpoint 对齐：
    - 同步网关（OpenAI / Sora 风格）直接返回视频 url / b64_json；
    - 异步厂商（主流）提交后返回 task_id，本类自动轮询任务状态并取片，
      轮询地址依次尝试 {base_url}/v1/video/generations/tasks/{id}、/{video/generations}/{id}、
      /tasks/{id}、{endpoint}/{id} 等常见形态，状态/URL 字段做通用递归匹配。
    图生视频：body 带 image + mode=image_to_video。
    任何环节失败或无视频产出 → 回退分镜脚本，绝不阻断主流程。
    """
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.params = params or {}

    def _poll_urls(self, task_id, endpoint):
        ep = endpoint or "/video/generations"
        return [
            f"{self.base_url}/v1/video/generations/tasks/{task_id}",
            f"{self.base_url}/video/generations/tasks/{task_id}",
            f"{self.base_url}/v1/video/generations/{task_id}",
            f"{self.base_url}{ep}/{task_id}",
            f"{self.base_url}/tasks/{task_id}",
        ]

    async def _finalize(self, url, b64, filename):
        if b64:
            out = os.path.join(UPLOAD_DIR, filename.rsplit(".", 1)[0] + ".mp4")
            with open(out, "wb") as f:
                f.write(base64.b64decode(b64))
            return {"provider": "model", "file_path": out, "model": self.model}
        if url:
            try:
                async with httpx.AsyncClient(timeout=600) as cc:
                    d = await cc.get(url)
                    d.raise_for_status()
                    out = os.path.join(UPLOAD_DIR, filename)
                    with open(out, "wb") as f:
                        f.write(d.content)
                return {"provider": "model", "file_path": out, "model": self.model}
            except Exception:
                return {"provider": "model", "url": url, "model": self.model}
        sb = await StoryboardVideo().generate("", "", filename, {})
        sb["note"] = "视频任务已完成但未解析到成片地址，已回退分镜脚本。"
        return sb

    async def generate(self, prompt, platform, filename, meta=None):
        meta = meta or {}
        if not self.base_url:
            sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
            sb["note"] = "视频模型未配置 base_url，已回退分镜脚本。"
            return sb
        endpoint = (self.params.get("endpoint") or "/video/generations").strip()
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
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=600.0)) as c:
                r = await c.post(self.base_url + endpoint, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                # 1) 同步直出
                url, b64 = _video_find_media(data)
                if url or b64:
                    return await self._finalize(url, b64, filename)
                # 2) 异步任务：轮询取片
                task_id = _video_find_task_id(data)
                if task_id:
                    for _ in range(120):  # 最多 ~6 分钟
                        await asyncio.sleep(3)
                        for u in self._poll_urls(task_id, endpoint):
                            try:
                                q = await c.get(u, headers=headers)
                            except Exception:
                                continue
                            if q.status_code >= 400:
                                continue
                            try:
                                obj = q.json()
                            except Exception:
                                continue
                            st = _video_find_status(obj)
                            if st in ("succeeded", "success", "complete", "completed", "ready", "finished"):
                                fu, fb = _video_find_media(obj)
                                if fu or fb:
                                    return await self._finalize(fu, fb, filename)
                                raise RuntimeError("视频任务完成但未找到成片地址")
                            if st in ("failed", "error", "cancelled", "canceled"):
                                raise RuntimeError("视频任务失败：" + str(_video_find_msg(obj))[:120])
        except Exception as e:
            sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
            sb["note"] = f"视频模型调用失败（{str(e)[:80]}），已回退分镜脚本。"
            return sb
        sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
        sb["note"] = "视频模型未返回可消费视频或任务标识，已回退分镜脚本。"
        return sb


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
        # 没有可灵鉴权信息（也不在 /video/generations 网关模式）→ 直接回退分镜
        if not (ak and sk) and not self.api_key:
            sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
            sb["note"] = "未配置可灵鉴权（access_key/secret_key 或 api_key），已回退分镜脚本。"
            return sb
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
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(self.base_url + sub_path, headers=self._headers(), json=body)
                r.raise_for_status()
                data = r.json()
                task_id = (data.get("data") or {}).get("task_id")
                if not task_id:
                    raise RuntimeError("可灵未返回 task_id：" + str(data)[:120])
                # 轮询（最多 ~6 分钟）
                for _ in range(120):
                    await asyncio.sleep(3)
                    q = await c.get(self.base_url + sub_path + "/" + task_id, headers=self._headers())
                    qd = q.json().get("data") or {}
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
                            raise RuntimeError("可灵成片 URL 缺失")
                        out = os.path.join(UPLOAD_DIR, filename.rsplit(".", 1)[0] + ".mp4")
                        dl = await c.get(url)
                        dl.raise_for_status()
                        with open(out, "wb") as f:
                            f.write(dl.content)
                        return {"provider": "kling", "file_path": out, "model": self.model}
                    if status == "failed":
                        raise RuntimeError("可灵任务失败：" + str(qd.get("task_status_msg") or "")[:120])
                raise RuntimeError("可灵任务轮询超时")
        except Exception as e:
            sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
            sb["note"] = f"可灵调用失败（{str(e)[:80]}），已回退分镜脚本。"
            return sb


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
    """兼容新旧两种存储：新配置存 usages(JSON 数组)，旧配置存 usage(单字符串)。"""
    u = cfg.usages if cfg.usages is not None else cfg.usage
    if isinstance(u, list):
        return [str(x) for x in u if x]
    if u:
        return [str(u)]
    return []

def _usable(cfg) -> bool:
    """配置具备真实调用的最少三要素（缺任一项只能退回 Mock）。"""
    return bool(cfg.api_key and cfg.base_url and cfg.model)


def _pick_config(rows, usage):
    """挑选某用途实际生效的配置（V4.39 / F10 修复）。

    V4.34 的优先级保留：同用途多条时先看每日连通测试成功者，再看 id 最大者。
    **F10**：候选必须先过 `is_active`。此前 `last_test_ok=True` 的分支没有过滤停用项，
    导致「已停用但昨天测试成功」的配置仍会被系统自动调用（说明书 T13）。
    仅显式启用的配置才能进入候选；全部失败 / 未测试时保持旧行为。
    """
    candidates = [c for c in rows
                  if c.is_active and usage in _usages_of(c) and _usable(c)]
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

def get_video(db) -> VideoProvider:
    """按「大模型配置」的 video 用途返回视频 Provider。
    - provider == 'keling' → 可灵原生异步 API（KlingVideo）
    - 其余 generic-video（Runway / Pika / Luma / 302.ai 等）→ 通用 /video/generations（ModelVideo）
    - 未配置 Key/URL/Model → 回退 StoryboardVideo（输出可执行分镜脚本）
    """
    cfg = _active_config(db, "video")
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        try:
            if (cfg.provider or "") == "keling":
                return KlingVideo(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
            return ModelVideo(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        except Exception:
            pass
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
