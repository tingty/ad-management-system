"""
创意方向引擎 + 平台字段级文案。

核心变化：素材的最小单位从「平台×语言×类型」变成「创意方向 Angle」。
每个方向有独立的洞察、钩子逻辑、视觉方案和适配平台，同一产品跑 6 个方向，
产出的是 6 套可对比、可测试的创意，而不是同一句话换 8 个尺寸。

文案按平台真实字段结构输出（FB 三段式 / Google RSA 多标题），
超长时按词边界裁剪而不是硬切，避免出现 "…upda" 这种不能投放的文案。
"""
import json
import re

from insight import detect_lang

# ----------------------------- 平台文案字段结构 -----------------------------
FB_CTA = ["SHOP_NOW", "LEARN_MORE", "DOWNLOAD", "INSTALL_MOBILE_APP", "SIGN_UP",
          "GET_OFFER", "PLAY_GAME", "SUBSCRIBE"]

COPY_SCHEMA = {
    "Facebook": [
        {"key": "primary_text", "label": "主文案", "max": 125, "count": 1, "multiline": True},
        {"key": "headline", "label": "标题", "max": 40, "count": 3},
        {"key": "description", "label": "描述", "max": 30, "count": 1},
        {"key": "cta", "label": "CTA 按钮", "max": 24, "count": 1, "enum": FB_CTA},
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
    "Moloco": [
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
}

# ----------------------------- 文案安全裁剪 -----------------------------
def fit_text(text: str, limit: int) -> tuple[str, bool]:
    """按词边界裁到 limit 内。返回 (结果, 是否发生了裁剪)。

    广告文案里出现 "…upda" 这种半截词等于废稿，所以宁可丢词也不切断词。
    中文按字符裁，但会避开标点切分点。
    """
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text, False
    if re.search(r"[\u4e00-\u9fa5]", text):
        cut = text[:limit]
        # 尽量在标点或空格处收尾
        for i in range(len(cut) - 1, max(0, len(cut) - 8), -1):
            if cut[i] in "，。、；：,.;: ":
                return cut[:i].strip(), True
        return cut.rstrip("，。、；： "), True
    words = text.split()
    out = ""
    for w in words:
        cand = f"{out} {w}".strip()
        if len(cand) <= limit:
            out = cand
        else:
            break
    if not out:                       # 单个词就超限：只能硬切
        return text[:limit].rstrip(), True
    return out.rstrip(" ,.;:—-"), True


def _clip_list(items, limit):
    out, cut = [], False
    for it in items:
        c, k = fit_text(it, limit)
        cut = cut or k
        if c and c not in out:
            out.append(c)
    return out, cut


# ----------------------------- 创意方向定义 -----------------------------
# hooks/bodies 中的占位符：
#   {p} 产品名  {b} 卖点（仅当文案语言与原文语言一致时才注入，避免中英夹杂）
ANGLE_LIBRARY = [
    {
        "key": "pain", "name": "痛点直击", "template": "compare",
        "insight": "先让用户看见现状的麻烦，再给出一步到位的解法，转化靠「对比落差」",
        "visual": "左右分屏：左侧手动操作的混乱，右侧产品内一步完成的结果",
        "hook_type": "冲突 / 损失厌恶",
        "kpi": "CTR / 转化率", "platform_fit": ["Facebook", "Unity", "AppLovin"],
        "hooks": {
            "en": ["Still doing it the hard way?", "There is a faster way", "Stop wasting time on this"],
            "es": ["¿Todavía lo haces a mano?", "Hay una forma más rápida", "Deja de perder tiempo"],
            "pt": ["Ainda faz do jeito difícil?", "Existe um jeito mais rápido", "Pare de perder tempo"],
            "id": ["Masih pakai cara lama?", "Ada cara yang lebih cepat", "Berhenti buang waktu"],
        },
        "bodies": {
            "en": ["{p} takes over the part you keep repeating.", "What used to take minutes now takes one tap."],
            "es": ["{p} se encarga de la parte que repites.", "Lo que tardaba minutos ahora es un toque."],
            "pt": ["{p} assume a parte que você repete.", "O que levava minutos agora é um toque."],
            "id": ["{p} mengambil bagian yang kamu ulang.", "Yang tadinya lama kini sekali ketuk."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "左半屏：手动重复操作的混乱快剪", "copy": "{pa}"},
            {"t": "1-3s", "visual": "右半屏：{p} 内一步完成的结果", "copy": "一步搞定"},
            {"t": "3-5s", "visual": "结果对比 + CTA", "copy": "现在就试"},
        ],
    },
    {
        "key": "benefit", "name": "利益直给", "template": "stat",
        "insight": "把最硬的利益点放在第一视觉层级，适合冷启动快速判断素材方向",
        "visual": "超大数字或核心承诺居中，下方一句解释 + CTA",
        "hook_type": "利益直给",
        "kpi": "CTR / IPM", "platform_fit": ["Facebook", "Google", "Moloco", "Adsterra"],
        "hooks": {
            "en": ["{b}", "{p}, without the extra steps", "The shorter way to the same result"],
            "es": ["{b}", "{p}, sin pasos extra", "El camino corto al mismo resultado"],
            "pt": ["{b}", "{p}, sem etapas extras", "O caminho curto para o mesmo resultado"],
            "id": ["{b}", "{p}, tanpa langkah tambahan", "Jalan singkat ke hasil yang sama"],
        },
        "bodies": {
            "en": ["Everything in one place, ready when you need it.", "No setup, no learning curve."],
            "es": ["Todo en un solo lugar, listo cuando lo necesitas.", "Sin configuración ni curva de aprendizaje."],
            "pt": ["Tudo em um só lugar, pronto quando você precisa.", "Sem configuração e sem curva de aprendizado."],
            "id": ["Semua di satu tempat, siap saat dibutuhkan.", "Tanpa setup, tanpa belajar dulu."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "超大数字 / 核心承诺居中", "copy": "{b}"},
            {"t": "1-3s", "visual": "下方一句解释 + 产品界面", "copy": "一切在一个地方"},
            {"t": "3-5s", "visual": "CTA 按钮", "copy": "了解更多"},
        ],
    },
    {
        "key": "proof", "name": "社会证明", "template": "rating",
        "insight": "用评分、用户量、榜单降低决策风险，适合已积累口碑的产品放量",
        "visual": "星级评分卡 + 用户量角标，产品界面作为背景虚化",
        "hook_type": "社会认同",
        "kpi": "CVR", "platform_fit": ["Facebook", "Google", "Mintegral", "Moloco"],
        "hooks": {
            "en": ["Rated by real users", "People keep coming back", "Why users stay"],
            "es": ["Valorada por usuarios reales", "La gente vuelve", "Por qué se quedan"],
            "pt": ["Avaliado por usuários reais", "As pessoas voltam", "Por que ficam"],
            "id": ["Dinilai pengguna asli", "Banyak yang kembali", "Kenapa mereka bertahan"],
        },
        "bodies": {
            "en": ["{p} is used every day by people with the same problem.", "Reviews say the same thing: it just works."],
            "es": ["{p} se usa a diario por gente con el mismo problema.", "Las reseñas dicen lo mismo: funciona."],
            "pt": ["{p} é usado todo dia por quem tinha o mesmo problema.", "As avaliações dizem o mesmo: funciona."],
            "id": ["{p} dipakai tiap hari oleh orang dengan masalah serupa.", "Ulasan bilang sama: memang works."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "星级评分卡 + 用户量角标", "copy": "真实用户怎么评"},
            {"t": "1-3s", "visual": "用户评价滚动 + 界面虚化", "copy": "每天都在用"},
            {"t": "3-5s", "visual": "CTA", "copy": "看看为什么"},
        ],
    },
    {
        "key": "curiosity", "name": "悬念好奇", "template": "bigtype",
        "insight": "不给结论只给线索，压低理解成本同时抬高点击动机，适合信息流首测",
        "visual": "纯字体版式，一句反常识主张 + 强调色块，无产品截图",
        "hook_type": "悬念",
        "kpi": "CTR", "platform_fit": ["Facebook", "Adsterra", "Moloco"],
        "hooks": {
            "en": ["The part nobody mentions", "This is why it feels slow", "You are paying for the wrong thing"],
            "es": ["La parte que nadie menciona", "Por esto se siente lento", "Estás pagando por lo incorrecto"],
            "pt": ["A parte que ninguém menciona", "É por isso que parece lento", "Você paga pela coisa errada"],
            "id": ["Bagian yang tak dibahas", "Ini sebabnya terasa lambat", "Kamu bayar untuk hal yang salah"],
        },
        "bodies": {
            "en": ["{p} shows what is actually happening, in one screen.", "Look closer before you decide."],
            "es": ["{p} muestra lo que pasa de verdad, en una pantalla.", "Mira bien antes de decidir."],
            "pt": ["{p} mostra o que realmente acontece, em uma tela.", "Olhe de perto antes de decidir."],
            "id": ["{p} menunjukkan yang sebenarnya, satu layar.", "Lihat lebih dekat sebelum memutuskan."],
        },
        "storyboard": [
            {"t": "0-2s", "visual": "纯字体版式 + 反常识主张", "copy": "没人告诉你的那部分"},
            {"t": "2-4s", "visual": "一屏揭示真相的界面", "copy": "{p} 一屏看懂"},
            {"t": "4-5s", "visual": "CTA", "copy": "点开看看"},
        ],
    },
    {
        "key": "ugc", "name": "真实体验", "template": "ugc",
        "insight": "第一人称视角 + 手持界面，绕过广告防御心理，适合再营销与相似人群",
        "visual": "手机框内真实界面，顶部状态栏与底部字幕条，模拟用户录制",
        "hook_type": "真实感 / 身份认同",
        "kpi": "CTR / 完播率", "platform_fit": ["Facebook", "Mintegral", "AppLovin"],
        "hooks": {
            "en": ["I tried it for a week", "My honest take", "Nobody asked, but here it is"],
            "es": ["Lo probé una semana", "Mi opinión honesta", "Nadie lo pidió, pero aquí está"],
            "pt": ["Testei por uma semana", "Minha opinião honesta", "Ninguém pediu, mas aqui está"],
            "id": ["Saya coba seminggu", "Pendapat jujur saya", "Tidak ada yang minta, tapi ini"],
        },
        "bodies": {
            "en": ["Three uses in, and I stopped going back to the old way.", "{p} did the boring part for me."],
            "es": ["Tres usos y ya no volví al método anterior.", "{p} hizo la parte aburrida por mí."],
            "pt": ["Três usos e não voltei ao método antigo.", "{p} fez a parte chata por mim."],
            "id": ["Tiga kali pakai, tak kembali ke cara lama.", "{p} mengerjakan bagian membosankan."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "手机框内真实界面录屏", "copy": "我用了 X 天"},
            {"t": "1-3s", "visual": "手持录制第一视角口播", "copy": "说真的，回不去了"},
            {"t": "3-5s", "visual": "CTA", "copy": "自己试试"},
        ],
    },
    {
        "key": "promo", "name": "限时促动", "template": "promo",
        "insight": "用时间与门槛制造行动理由，适合冲量窗口与新用户首单",
        "visual": "圆形折扣角标 + 倒计时条，产品名与 CTA 抢眼",
        "hook_type": "损失厌恶 / 紧迫",
        "kpi": "CVR / ROAS", "platform_fit": ["Facebook", "Google", "Adsterra", "Unity"],
        "hooks": {
            "en": ["Ends soon", "Only for new users", "This week only"],
            "es": ["Termina pronto", "Solo nuevos usuarios", "Solo esta semana"],
            "pt": ["Termina em breve", "Só para novos usuários", "Só esta semana"],
            "id": ["Segera berakhir", "Hanya pengguna baru", "Hanya minggu ini"],
        },
        "bodies": {
            "en": ["Start with {p} today, decide later.", "The offer is live now, no code needed."],
            "es": ["Empieza con {p} hoy, decide después.", "La oferta está activa, sin código."],
            "pt": ["Comece com {p} hoje, decida depois.", "A oferta está no ar, sem código."],
            "id": ["Mulai {p} hari ini, putuskan nanti.", "Promo aktif sekarang, tanpa kode."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "圆形折扣角标 + 倒计时条", "copy": "本周专属"},
            {"t": "1-3s", "visual": "产品名 + 利益点快剪", "copy": "现在开始，以后再说"},
            {"t": "3-5s", "visual": "CTA", "copy": "领取优惠"},
        ],
    },
    {
        "key": "scenario", "name": "场景代入", "template": "scenario",
        "insight": "把用户放进具体使用场景，用「我以前 / 我以后」的叙事制造代入感与前后落差",
        "visual": "第一视角场景还原：左旧场景（手忙脚乱）右新场景（从容完成）",
        "hook_type": "场景代入 / 共情",
        "kpi": "CTR / 完播率", "platform_fit": ["Facebook", "TikTok", "Mintegral", "AppLovin"],
        "hooks": {
            "en": ["When you only have 3 minutes…", "Picture the 9pm version of you", "The moment it finally clicked"],
            "es": ["Cuando solo tienes 3 minutos…", "Tu yo de las 9pm", "El día que por fin encajó"],
            "pt": ["Quando você só tem 3 minutos…", "Você às 21h", "O dia que finalmente fez sentido"],
            "id": ["Saat kamu cuma punya 3 menit…", "Kamu jam 9 malam", "Saat akhirnya pas"],
        },
        "bodies": {
            "en": ["Before {p}, this took all night. Now it takes one tap.", "The 9pm you would thank the 9am you."],
            "es": ["Antes de {p}, esto era una noche entera. Ahora un toque.", "Tu yo de las 9pm te lo agradecería."],
            "pt": ["Antes do {p}, era uma noite inteira. Agora um toque.", "Você das 21h agradeceria."],
            "id": ["Sebelum {p}, ini semalaman. Kini satu ketuk.", "Kamu jam 9 malam akan berterima kasih."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "第一视角：{p} 出现前的狼狈场景", "copy": "你被旧方式困住的那一刻"},
            {"t": "1-3s", "visual": "切换新场景：{p} 一步解决", "copy": "现在只要一步"},
            {"t": "3-5s", "visual": "从容结果 + CTA", "copy": "亲自试试"},
        ],
    },
    {
        "key": "comparison", "name": "对比测评", "template": "compare",
        "insight": "用横向对比 / 评测视角建立客观可信，把「为什么选我」交给数据说话",
        "visual": "三方对比表 / 评分雷达图，本产品高亮，关键指标打勾",
        "hook_type": "对比 / 客观可信",
        "kpi": "CVR / 信任度", "platform_fit": ["Facebook", "Google", "Mintegral", "Moloco"],
        "hooks": {
            "en": ["We tested 3, here's the verdict", "Not all are built the same", "The numbers don't lie"],
            "es": ["Probamos 3, esta es la conclusión", "No todas se construyen igual", "Los números no mienten"],
            "pt": ["Testamos 3, veja o veredito", "Nem todas são iguais", "Os números não mentem"],
            "id": ["Kami uji 3, ini kesimpulannya", "Tidak semua sama", "Angka tidak bohong"],
        },
        "bodies": {
            "en": ["{p} scored {m} where others stalled.", "Side by side, the difference is the detail."],
            "es": ["{p} logró {m} donde otras se estancaron.", "Cara a cara, la diferencia está en el detalle."],
            "pt": ["{p} chegou a {m} onde outras travaram.", "Lado a lado, a diferença está no detalhe."],
            "id": ["{p} capai {m} saat lain mentok.", "Bersebelahan, bedanya ada di detail."],
        },
        "storyboard": [
            {"t": "0-1s", "visual": "三方并排对比，抛出问题", "copy": "我们测了 3 款"},
            {"t": "1-3s", "visual": "本产品高亮 + 关键指标 {m} 打勾", "copy": "结论很清晰"},
            {"t": "3-5s", "visual": "CTA", "copy": "看看对比"},
        ],
    },
]
ANGLE_MAP = {a["key"]: a for a in ANGLE_LIBRARY}
SUPPORTED_LANGS = ["en", "es", "pt", "id"]


def _lang(lang: str) -> str:
    return lang if lang in SUPPORTED_LANGS else "en"


def _fmt(tpl: str, product: str, benefit: str, metric: str = "", pain: str = "") -> str:
    s = (tpl or "")
    s = s.replace("{p}", product).replace("{b}", benefit)
    s = s.replace("{m}", metric).replace("{pa}", pain)
    s = re.sub(r"\{[a-z_]+\}", "", s)  # 清理残留占位符，避免泄漏 {xxx}
    return s.strip()


# ----------------------------- 文案生成 -----------------------------
# 短描述专用（FB description 只有 30 字符、Unity body 50 字符）。
# 直接用长正文裁到 30 会变成半句话，读起来像没写完，所以按方向单独备短句。
SHORTS = {
    ("pain", "en"): ["One tap instead of ten", "Skip the manual steps"],
    ("pain", "es"): ["Un toque y listo", "Sin pasos manuales"],
    ("pain", "pt"): ["Um toque e pronto", "Sem passos manuais"],
    ("pain", "id"): ["Sekali ketuk saja", "Tanpa langkah manual"],
    ("benefit", "en"): ["One place for everything", "Fewer steps, same result"],
    ("benefit", "es"): ["Todo en un solo lugar", "Menos pasos, mismo resultado"],
    ("benefit", "pt"): ["Tudo em um só lugar", "Menos passos, mesmo resultado"],
    ("benefit", "id"): ["Semua di satu tempat", "Lebih sedikit langkah"],
    ("proof", "en"): ["Rated by real users", "Users who stay"],
    ("proof", "es"): ["Valorada por usuarios", "Usuarios que vuelven"],
    ("proof", "pt"): ["Avaliado por usuários", "Usuários que voltam"],
    ("proof", "id"): ["Dinilai pengguna asli", "Pengguna yang kembali"],
    ("curiosity", "en"): ["Nobody tells you this", "Look closer"],
    ("curiosity", "es"): ["Nadie te lo dice", "Mira de cerca"],
    ("curiosity", "pt"): ["Ninguém te conta", "Olhe de perto"],
    ("curiosity", "id"): ["Tak ada yang bilang", "Lihat lebih dekat"],
    ("ugc", "en"): ["I tried it myself", "Honest, 7 days in"],
    ("ugc", "es"): ["Lo probé yo mismo", "Honesto, 7 días"],
    ("ugc", "pt"): ["Testei eu mesmo", "Honesto, 7 dias"],
    ("ugc", "id"): ["Saya coba sendiri", "Jujur, 7 hari"],
    ("promo", "en"): ["Ends this week", "New users only"],
    ("promo", "es"): ["Termina esta semana", "Solo nuevos usuarios"],
    ("promo", "pt"): ["Termina esta semana", "Só novos usuários"],
    ("promo", "id"): ["Berakhir minggu ini", "Hanya pengguna baru"],
    ("scenario", "en"): ["Your 9pm self would thank you", "Only 3 minutes? Covered"],
    ("scenario", "es"): ["Tu yo de las 9pm lo agradecería", "¿Solo 3 minutos? Listo"],
    ("scenario", "pt"): ["Você das 21h agradeceria", "Só 3 minutos? Resolvido"],
    ("scenario", "id"): ["Kamu jam 9 malam berterima kasih", "Cuma 3 menit? Beres"],
    ("comparison", "en"): ["We tested 3, here's why", "The numbers don't lie"],
    ("comparison", "es"): ["Probamos 3, esta es la razón", "Los números no mienten"],
    ("comparison", "pt"): ["Testamos 3, veja por quê", "Os números não mentem"],
    ("comparison", "id"): ["Kami uji 3, ini alasannya", "Angka tidak bohong"],
}


def build_copy_kit(fw, angle: dict, lang: str, benefit: str = "") -> dict:
    """生成一个方向的文案素材包：headlines / bodies / cta / storyboard，已按语言本地化。

    - benefit 只在「原文语言 == 目标语言」时注入，避免中英夹杂；
    - 自动从 fw.site_analysis 抽取量化指标({m})与痛点({pa})注入，让创意精准表达价值与用户兴趣；
    - 未传入 benefit 时，从 site_analysis 的价值点自动补一个（语言一致才补）；
    - storyboard 的文案同样经占位符替换，产出可直接拍的分镜。
    """
    lg = _lang(lang)
    product = fw.product or "the app"
    sa = getattr(fw, "site_analysis", None) or {}
    if isinstance(sa, str):
        try:
            sa = json.loads(sa)
        except Exception:
            sa = {}
    sa = sa if isinstance(sa, dict) else {}
    val_points = ((sa.get("value") or {}).get("points") or []) if isinstance(sa.get("value"), dict) else []
    proof_metrics = ((sa.get("proof") or {}).get("metrics") or []) if isinstance(sa.get("proof"), dict) else []
    pains = ((sa.get("audience") or {}).get("pain_points") or []) if isinstance(sa.get("audience"), dict) else []

    # benefit：优先用传入；否则从价值点补（仅语言一致）
    b = (benefit or "").strip()
    if not b and val_points:
        cand = val_points[0].get("point") if isinstance(val_points[0], dict) else str(val_points[0])
        if cand and detect_lang(cand) == lg:
            b = cand[:34]

    # metric：量化指标语言无关，始终注入（数字即证据）
    metric = ""
    if proof_metrics:
        m0 = proof_metrics[0].get("value") if isinstance(proof_metrics[0], dict) else str(proof_metrics[0])
        metric = (m0 or "").strip()
    if not metric and (fw.metrics or []):
        metric = str((fw.metrics or [])[0])

    # pain：仅语言一致时注入
    pain = ""
    if pains:
        p0 = pains[0] if isinstance(pains[0], str) else str(pains[0])
        if p0 and detect_lang(p0) == lg:
            pain = p0

    raw_hooks = angle["hooks"][lg]
    if b:
        hooks = [_fmt(h, product, b, metric, pain) for h in raw_hooks]
    else:
        hooks = [_fmt(h, product, "", metric, pain) for h in raw_hooks if "{b}" not in h] or [f"{product} in one tap"]
    bodies = [_fmt(x, product, b, metric, pain) for x in angle["bodies"][lg]]
    storyboard = [
        {"t": s.get("t"),
         "visual": _fmt(s.get("visual", ""), product, b, metric, pain),
         "copy": _fmt(s.get("copy", ""), product, b, metric, pain)}
        for s in (angle.get("storyboard") or [])
    ]
    cta_by_angle = {
        "pain": {"en": "Download", "es": "Descargar", "pt": "Baixar", "id": "Unduh"},
        "benefit": {"en": "Learn more", "es": "Ver más", "pt": "Saiba mais", "id": "Lihat"},
        "proof": {"en": "See why", "es": "Ver por qué", "pt": "Ver por quê", "id": "Lihat"},
        "curiosity": {"en": "Open", "es": "Abrir", "pt": "Abrir", "id": "Buka"},
        "ugc": {"en": "Try it", "es": "Probar", "pt": "Testar", "id": "Coba"},
        "promo": {"en": "Get offer", "es": "Ver oferta", "pt": "Ver oferta", "id": "Ambil promo"},
        "scenario": {"en": "Try it", "es": "Probar", "pt": "Testar", "id": "Coba"},
        "comparison": {"en": "See why", "es": "Ver por qué", "pt": "Ver por quê", "id": "Lihat"},
    }
    return {"headlines": hooks, "bodies": bodies,
            "shorts": SHORTS.get((angle["key"], lg), bodies[:1]),
            "cta": cta_by_angle[angle["key"]][lg],
            "storyboard": storyboard}


def map_to_platform(kit: dict, platform: str, product: str) -> dict:
    """把素材包映射成平台字段结构，超限按词边界裁剪。"""
    schema = COPY_SCHEMA.get(platform) or COPY_SCHEMA["AppLovin"]
    out, issues = {}, []
    for field in schema:
        key, mx = field["key"], field["max"]
        if key == "cta":
            val = kit.get("cta") or "Learn more"
            if field.get("enum") and val not in field["enum"]:
                # FB 只接受枚举值，做一次语义映射
                val = {"Download": "DOWNLOAD", "Learn more": "LEARN_MORE",
                       "Get offer": "GET_OFFER", "See why": "LEARN_MORE",
                       "Open": "LEARN_MORE", "Try it": "DOWNLOAD"}.get(val, "LEARN_MORE")
            out[key] = val
            continue
        if key in ("headline", "title"):
            # 候选池里先筛「本来就放得下」的，避免把 "without the extra steps" 裁成
            # "without the extra" 这种半句话；实在不够再用裁剪兜底。
            pool = list(kit["headlines"]) + list(kit.get("shorts") or [])
            pool += [f"{product} official", f"Try {product} free",
                     f"{product} in one tap", f"Get {product}"]
            fits, seen = [], set()
            for x in pool:
                if len(x) <= mx and x.lower() not in seen:
                    fits.append(x); seen.add(x.lower())
            vals = fits[: field["count"]]
            cut = False
            if len(vals) < field["count"]:
                rest = [x for x in pool if x.lower() not in seen]
                extra, cut = _clip_list(rest, mx)
                for x in extra:
                    if x.lower() not in seen and len(vals) < field["count"]:
                        vals.append(x); seen.add(x.lower())
        elif key == "description":
            # 短描述字段（FB 30 字符）用短句库；Google RSA 的 90 字符用正文，信息量才够
            pool = kit["bodies"] if mx >= 60 else (kit.get("shorts") or kit["bodies"])
            used = {x.lower() for x in (out.get("headline") or [])} if isinstance(out.get("headline"), list) else set()
            pool = [x for x in pool if x.lower() not in used] or pool
            vals, cut = _clip_list(pool[: field["count"]], mx)
        elif key == "primary_text":
            vals, cut = _clip_list(kit["bodies"][:1], mx)
        elif key == "body":
            vals, cut = _clip_list(kit["bodies"][:1], mx)
        else:
            vals, cut = _clip_list(kit["bodies"][:1], mx)
        out[key] = vals[0] if field["count"] == 1 else vals
        if cut:
            issues.append({"field": key, "issue": "已按词边界裁剪以符合字数上限"})
    return {"fields": out, "issues": issues}


def copy_text(fields: dict, platform: str) -> str:
    """人读版本，用于列表展示与纯文本导出。"""
    schema = COPY_SCHEMA.get(platform) or []
    lines = []
    for f in schema:
        v = fields.get(f["key"])
        if not v:
            continue
        if isinstance(v, list):
            for i, x in enumerate(v, 1):
                lines.append(f"{f['label']} {i}: {x}")
        else:
            lines.append(f"{f['label']}: {v}")
    return "\n".join(lines)


# ----------------------------- 同质化检测 -----------------------------
def _tokens(text) -> set:
    if isinstance(text, list):
        text = " ".join(map(str, text))
    text = str(text or "").lower()
    if re.search(r"[\u4e00-\u9fa5]", text):
        return set(text)
    return {w for w in re.findall(r"[a-z0-9']+", text) if len(w) > 2}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def flag_duplicates(items: list[dict]) -> None:
    """同一平台/语言下，方向之间文案重合度过高时打标，避免拿同质素材去跑量。"""
    for i, cur in enumerate(items):
        for prev in items[:i]:
            if cur["platform"] != prev["platform"] or cur["language"] != prev["language"]:
                continue
            s = similarity(cur["text"], prev["text"])
            if s >= 0.75:
                cur.setdefault("warnings", []).append(
                    f"与该平台「{prev['angle_name']}」方向文案重合 {int(s * 100)}%，建议二选一")
                break


# ----------------------------- 质量校验 -----------------------------
def validate_copy(fields: dict, platform: str, issues: list | None = None) -> dict:
    schema = COPY_SCHEMA.get(platform) or []
    problems = []
    for f in schema:
        v = fields.get(f["key"])
        if not v:
            problems.append({"level": "error", "field": f["label"], "msg": "缺失"})
            continue
        vals = v if isinstance(v, list) else [v]
        for x in vals:
            if len(x) > f["max"]:
                problems.append({"level": "error", "field": f["label"],
                                 "msg": f"超 {f['max']} 字（当前 {len(x)}）"})
        if isinstance(v, list) and len(v) < f["count"]:
            problems.append({"level": "warn", "field": f["label"],
                             "msg": f"建议 {f['count']} 条，当前 {len(v)} 条"})
    for it in (issues or []):
        problems.append({"level": "warn", "field": it["field"], "msg": it["issue"]})
    # 同时给出 V2 的 issues 结构，保持前端/导出兼容
    compat = [{"level": p["level"], "code": p["field"], "message": p["msg"]} for p in problems]
    return {"valid": not any(p["level"] == "error" for p in problems),
            "ok": not any(p["level"] == "error" for p in problems),
            "issues": compat, "problems": problems}


def char_table(fields: dict, platform: str) -> list[dict]:
    """前端字段级字数表：投放人员需要一眼看到每条文案还剩多少字符。"""
    schema = COPY_SCHEMA.get(platform) or []
    rows = []
    for f in schema:
        v = fields.get(f["key"])
        if isinstance(v, list):
            for i, x in enumerate(v, 1):
                rows.append({"field": f"{f['label']} {i}", "text": x,
                             "len": len(x), "max": f["max"], "over": len(x) > f["max"]})
        elif v:
            rows.append({"field": f["label"], "text": str(v),
                         "len": len(str(v)), "max": f["max"], "over": len(str(v)) > f["max"]})
    return rows


# ----------------------------- 关键词（搜索类平台） -----------------------------
DOMAIN_NOUN = {
    "commerce": "shopping app", "game": "puzzle game", "fitness": "fitness app",
    "finance": "budget app", "travel": "travel app", "photo_ai": "photo editor",
    "education": "learning app", "app": "app",
}
ANGLE_KW_MODIFIER = {
    "pain": {"en": "alternative", "es": "alternativa", "pt": "alternativa", "id": "alternatif"},
    "benefit": {"en": "discount", "es": "descuento", "pt": "desconto", "id": "diskon"},
    "proof": {"en": "review", "es": "opiniones", "pt": "avaliação", "id": "ulasan"},
    "curiosity": {"en": "how to", "es": "cómo", "pt": "como", "id": "cara"},
    "ugc": {"en": "honest review", "es": "opinión real", "pt": "opinião real", "id": "review jujur"},
    "promo": {"en": "offer", "es": "oferta", "pt": "oferta", "id": "promo"},
    "scenario": {"en": "how to", "es": "cómo", "pt": "como", "id": "cara"},
    "comparison": {"en": "vs", "es": "frente a", "pt": "versus", "id": "bandingkan"},
}


def build_keywords(fw, angle_key: str, lang: str) -> dict:
    """按方向出三组匹配类型的关键词；搜索类平台（Google / Adsterra）可直接导入。"""
    lg = _lang(lang)
    p = fw.product or "app"
    noun = DOMAIN_NOUN.get(getattr(fw, "domain", None) or "app", "app")
    mod = ANGLE_KW_MODIFIER.get(angle_key, ANGLE_KW_MODIFIER["benefit"]).get(lg, "review")
    download = {"en": "download", "es": "descargar", "pt": "baixar", "id": "unduh"}[lg]
    free = {"en": "free", "es": "gratis", "pt": "grátis", "id": "gratis"}[lg]
    return {
        "broad": [f"{p}", f"{p} {noun}", f"best {noun}", f"{mod} {noun}"],
        "phrase": [f'"{p}" {download}', f'"{p}" {free}', f'best {noun} {free}'],
        "exact": [f"{p} {noun}", f"{download} {p}", f"{p} {free}"],
    }


def keyword_text(kw: dict) -> str:
    out = []
    for k in ("broad", "phrase", "exact"):
        if kw.get(k):
            out.append(f"[{k}] " + " | ".join(kw[k]))
    return "\n".join(out)
