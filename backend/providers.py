"""
AI 模型接入层（可配置多模型）。
- 未配置任何 Key 时，使用 Mock provider，保证 MVP 端到端可跑通。
- 在「设置页」配置 OpenAI 兼容协议的 api_key / base_url / model 后，自动切换为真实调用。
- 图像 provider 接入真实 DALL·E 风格接口失败时自动回退到占位图，避免阻断主流程。
"""
import os, json, re, httpx, base64, asyncio, itertools
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
    async def generate(self, prompt: str, width: int, height: int, filename: str) -> str:
        """返回保存后的文件路径。"""
        raise NotImplementedError

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
            "Facebook": "兴趣/行为定向为主，强视觉+短文案，Reels 9:16 短视频更易起量",
            "Google": "UAC/搜索并重，搜索词覆盖品类词+竞品词，多尺寸图片素材齐备",
            "Unity": "游戏/工具类首选，Rewarded 视频 + 1080x1920 竖版",
            "AppLovin": "App 安装导向，创意利益点前置，程序化放量",
            "Moloco": "ML 竞价 RTB，受众扩展，转化导向短文案",
            "Adsterra": "多元广告位，CPM/CPA，直给利益点",
            "Mintegral": "移动 DSP + 可玩广告，互动引导强",
        },
    }
    return json.dumps(data, ensure_ascii=False)

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

class ModelVideo(VideoProvider):
    """可配置视频模型：POST {base_url}/video/generations，支持 url 或 b64_json 返回。

    不同厂商（Runway / 可灵 / Pika）协议差异大，这里约定一个最小通用契约；
    调用失败或无返回时自动回退分镜脚本，绝不阻断主流程。
    """
    def __init__(self, api_key, base_url, model, params=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.params = params or {}

    async def generate(self, prompt, platform, filename, meta=None):
        meta = meta or {}
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                r = await c.post(
                    self.base_url + "/video/generations",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "prompt": prompt,
                          "duration": meta.get("duration", 15),
                          "aspect_ratio": meta.get("aspect", "9:16")},
                )
                r.raise_for_status()
                data = r.json()
                item = (data.get("data") or [{}])[0]
                if item.get("b64_json"):
                    path = os.path.join(UPLOAD_DIR, filename.rsplit(".", 1)[0] + ".mp4")
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(item["b64_json"]))
                    return {"provider": "model", "file_path": path, "model": self.model}
                if item.get("url"):
                    return {"provider": "model", "url": item["url"], "model": self.model}
        except Exception as e:
            sb = await StoryboardVideo().generate(prompt, platform, filename, meta)
            sb["note"] = f"视频模型调用失败（{str(e)[:80]}），已回退分镜脚本。"
            return sb
        return await StoryboardVideo().generate(prompt, platform, filename, meta)


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
                    "max_tokens": self.params.get("max_tokens", 1500),
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

class FallbackLLM(LLMProvider):
    """真实模型调用失败时自动回退 Mock，保证主流程不中断。"""
    def __init__(self, real, fallback):
        self.real = real
        self.fallback = fallback

    async def chat(self, system, user, **kw):
        try:
            return await self.real.chat(system, user, **kw)
        except Exception:
            return await self.fallback.chat(system, user, **kw)

class OpenAIImage(ImageProvider):
    """AI 底图 + 文案合成。

    images/generations 仅支持有限尺寸（1024x1024 / 1792x1024 / 1024x1792），
    因此按目标比例请求最接近的尺寸，再由 Pillow 裁剪到目标尺寸并叠加文案。
    任一步失败都回退到纯模板合成，保证一定有可交付图片。
    """
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
        from imaging import render_ad_png
        cp = copy or {}
        bg_path = None
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
                if b64:
                    bg_path = os.path.join(UPLOAD_DIR, "_bg_" + filename.rsplit(".", 1)[0] + ".png")
                    with open(bg_path, "wb") as f:
                        f.write(base64.b64decode(b64))
        except Exception:
            bg_path = None   # 回退纯模板

        path = os.path.join(UPLOAD_DIR, filename)
        await asyncio.to_thread(
            render_ad_png, path, width, height,
            cp.get("headline") or prompt, cp.get("sub") or "", cp.get("cta") or "",
            cp.get("brand") or "", bg_path,
        )
        try:
            if bg_path and os.path.exists(bg_path):
                os.remove(bg_path)   # 中间底图不落库，避免 uploads 膨胀
        except Exception:
            pass
        return path


# ----------------------------- 工厂（按用途返回激活 provider） -----------------------------
def _active_config(db, usage):
    # 延迟导入避免循环依赖
    from models import ModelConfig
    return db.query(ModelConfig).filter_by(usage=usage, is_active=True).first()

def get_llm(db, usage="analysis") -> LLMProvider:
    cfg = _active_config(db, usage)
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        try:
            real = OpenAICompatibleLLM(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
            return FallbackLLM(real, MockLLM())
        except Exception:
            pass
    return MockLLM()

def get_image(db) -> ImageProvider:
    cfg = _active_config(db, "image")
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        try:
            return OpenAIImage(cfg.api_key, cfg.base_url, cfg.model, cfg.params)
        except Exception:
            pass
    return TemplateImage()

def get_video(db) -> VideoProvider:
    cfg = _active_config(db, "video")
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        try:
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
