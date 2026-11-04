"""
推广产品分析报告：把落地页抓取 + 本地抽取的结果，整理成投放人员能直接用的结构化报告。

为什么单独一个模块：
- 旧版 `facts` 只是几个字段平铺，投放看不出"这个产品能不能投、该怎么投"；
- 报告需要"结论 + 依据 + 缺口"，且每条结论都要能回到原文，不能是通用套话。

报告分七段：产品与定位 / 核心价值主张 / 信任与量化背书 / 目标人群 /
落地页结构与转化路径 / 各平台投放读法 / 风险与信息缺口，最后给下一步动作。
"""
import re
from datetime import datetime

from insight import CJK_RE, PLATFORM_NOTES, detect_domain, normalize_text

# 差异化表述：出现这些词，说明页面在跟别的东西作对比
DIFF_HINTS = ["unlike", "compared", "instead of", "rather than", "only ", "no need",
              "without", "more than", "than ", "独家", "唯一", "不同于", "相比", "无需",
              "不用", "省去", "告别", "替代"]
BENEFIT_WORDS = ["free", "unlimited", "instant", "auto", "offline", "no ads", "built-in",
                 "免费", "不限", "自动", "离线", "无广告", "内置", "一键", "实时"]
PRICE_RE = re.compile(r"[$¥€£]\s?\d|\d+\s?(?:天|日|days?)\s?(?:free|免费)|免费试用|free trial", re.I)
# 「免费」常常不带数字（Try Calm for Free / 免费试用 / $0），PRICE_RE 抓不到。
# 这里只认明确的免费结构，避免把 "free from anxiety" 这类「摆脱焦虑」误判成价格。
FREE_RE = re.compile(
    r"for\s+free|free\s+trial|free\s+plan|try\s+[\w\s&'’\-]{0,24}?free\b"
    r"|start\s+[\w\s]{0,20}?free\b|no\s+cost|no\s+charge|免费(?:试用|体验|版)?|试用|0\s*元|\$\s?0\b|¥\s?0\b", re.I)

# 品类 → 平台合规红线。这些是真实会被拒登的点，不是免责声明。
COMPLIANCE_BY_DOMAIN = {
    "fitness": [
        ("健康类宣称", "「治愈 / 治疗 / 替代药物」类表述属于医疗宣称，Meta 与 Google 健康政策会拒登；"
                       "睡眠、焦虑、减压只能说「帮助放松」，不能说「治好失眠」。"),
        ("效果承诺", "减重/增肌类不要写具体公斤数或天数承诺，改用「每天 10 分钟」这类过程描述。"),
        ("免责声明", "涉及身心健康的素材建议加一句「不构成医疗建议」，尤其是搜索侧落地页。"),
    ],
    "finance": [
        ("收益承诺", "不得出现「稳赚 / 保本 / 年化 X%」等收益承诺，金融类广告需主体资质与地区备案。"),
        ("隐私数据", "收集财务数据时素材里不要出现真实账户截图，容易被判为误导。"),
    ],
    "game": [
        ("诱导表述", "避免「破解 / 免费内购 / 无限金币」类表述，会触发平台虚假宣传判定。"),
        ("未成年人", "素材与受众设置需避开未成年人定向，部分市场还有额外的游戏分级要求。"),
    ],
    "commerce": [
        ("折扣时效", "折扣、倒计时、库存数字必须与真实活动一致；虚构倒计时是电商素材最常见的拒登原因。"),
        ("价格一致性", "素材价格需与落地页一致，落地页改价后要同步重出素材。"),
    ],
    "education": [
        ("结果承诺", "「包过 / 30 天流利」类结果承诺在多数市场属于夸大宣传，改为课时与学习方式描述。"),
    ],
    "app": [
        ("数据可查", "用户量、评分、榜单排名需与落地页/应用商店一致，投放期间要能被抽查到。"),
        ("权限说明", "涉及相册、通讯录等权限时，素材不要暗示「必须授权才能用」。"),
    ],
}

PLATFORM_ROLE = {
    "Facebook": "冷启动与放量主力，创意决定 CPM；Reels/Stories 竖版优先",
    "Google": "承接主动搜索需求，RSA 靠标题组合覆盖词；PMax 吃多尺寸图",
    "Unity": "游戏与激励场景，Rewarded 换量，前 5 秒必须出核心循环",
    "AppLovin": "算法放量，素材生命周期短，需要高频上新",
    "Moloco": "RTB 高意向人群，事件优化为主，素材偏功能演示",
    "Adsterra": "原生/横幅流量便宜，素材走「问题—方案」软文结构",
    "Mintegral": "可玩与互动素材强项，适合演示型产品",
}


def _metric_detail(m: str) -> dict:
    """给每个数字加上"这是什么"，否则 2M / 74% / 5-star 混在一起没有意义。"""
    s = (m or "").strip()
    low = s.lower()
    if low.endswith("-star") or re.fullmatch(r"[0-5](?:\.\d)?", s):
        return {"value": s, "kind": "rating", "label": "评分"}
    if s.startswith(("$", "¥", "€", "£")):
        return {"value": s, "kind": "price", "label": "价格"}
    if "%" in s or "％" in s or "percent" in low:
        return {"value": s, "kind": "ratio", "label": "比例 / 提升幅度"}
    if re.search(r"\d\s?(?:x|倍)$", s, re.I):
        return {"value": s, "kind": "multiple", "label": "倍数"}
    if re.search(r"(?:M|B|K|万|亿|\+)$", s):
        return {"value": s, "kind": "scale", "label": "用户量 / 规模"}
    return {"value": s, "kind": "other", "label": "其他量化"}


def _prop_type(point: str) -> str:
    low = point.lower()
    if re.search(r"\d", point):
        return "metric"
    if any(w in low for w in ("review", "rated", "rating", "users", "customers", "million",
                              "用户", "好评", "评分", "榜单", "推荐")):
        return "proof"
    return "benefit"


def _prop_strength(point: str, ptype: str) -> str:
    n = len(point)
    has_num = bool(re.search(r"\d", point))
    if ptype == "proof" and has_num:
        return "强"
    if has_num and n <= 46:
        return "强"
    if has_num or any(w in point.lower() for w in BENEFIT_WORDS):
        return "中"
    if n > 60:
        return "弱"
    return "中"


def _diff_sentences(text: str, limit: int = 3) -> list[str]:
    """从正文里找"跟别人不一样"的表述；找不到就返回空，不编造。"""
    out = []
    for line in normalize_text(text).splitlines():
        low = line.lower()
        if len(line) < 12 or len(line) > 160:
            continue
        if any(h in low for h in DIFF_HINTS):
            s = re.split(r"(?<=[。！？!?])", line)[0].strip(" -—·")
            if 10 <= len(s) <= 120 and s not in out:
                out.append(s)
        if len(out) >= limit:
            break
    return out


def _confidence(chars, points, metrics, audience_src, h1, h2, ctas, fetched):
    score, reasons = 28, []
    if fetched and chars >= 8000:
        score += 20; reasons.append(f"正文抓取 {chars:,} 字，信息量充足")
    elif fetched and chars >= 3000:
        score += 14; reasons.append(f"正文抓取 {chars:,} 字")
    elif fetched and chars > 0:
        score += 6; reasons.append(f"正文只抓到 {chars} 字，信息偏少")
    else:
        reasons.append("未抓到正文，结论主要来自 URL 与用户输入")
    if len(points) >= 4:
        score += 15; reasons.append(f"抽到 {len(points)} 条可回溯的卖点")
    elif len(points) >= 2:
        score += 9; reasons.append(f"抽到 {len(points)} 条卖点，够起步")
    else:
        reasons.append("可用卖点不足 2 条，创意会很单薄")
    if len(metrics) >= 2:
        score += 15; reasons.append(f"识别到 {len(metrics)} 个可量化指标")
    elif len(metrics) == 1:
        score += 8; reasons.append("只有 1 个量化指标")
    else:
        reasons.append("没有可量化指标，数字型素材缺主体")
    if audience_src == "原文":
        score += 10; reasons.append("人群描述来自原文")
    if h1:
        score += 5
    if len(h2) >= 3:
        score += 7; reasons.append(f"页面有 {len(h2)} 个卖点小标题，结构清晰")
    if ctas:
        score += 5; reasons.append(f"识别到转化按钮（{ctas[0]}）")
    score = max(20, min(95, score))
    label = "高" if score >= 75 else ("较高" if score >= 60 else ("中" if score >= 45 else "低"))
    return score, label, reasons


def _gaps(fw, page, chars, fetched) -> list[dict]:
    out = []
    points = fw.selling_points or []
    metrics = fw.metrics or []
    audience = fw.audience or ""
    text = " ".join(points)

    if not fetched or chars == 0:
        out.append({"level": "error", "item": "没有抓到落地页正文",
                    "impact": "产品名与卖点只能靠 URL 推断，报告结论不可直接使用；"
                              "建议手动粘贴正文，或确认链接是否需要登录/JS 渲染。"})
    elif chars < 800:
        out.append({"level": "warn", "item": f"正文只有 {chars} 字",
                    "impact": "卖点与人群抽取会偏少，建议补充功能介绍与目标人群描述后重新分析。"})
    if len(metrics) == 0:
        out.append({"level": "warn", "item": "未识别到可量化指标",
                    "impact": "数字主体版式（stat）没有可用数字，proof 方向会退化成纯字体版式。"})
    if not any(m.lower().endswith("-star") or re.fullmatch(r"[0-5](?:\.\d)?", m) for m in metrics):
        out.append({"level": "info", "item": "未识别到评分 / 评价数",
                    "impact": "社会证明方向缺硬证据，建议从应用商店补充评分与评价量。"})
    if audience and ("按品类默认" in audience or "未写明人群" in audience):
        out.append({"level": "warn", "item": "人群是按品类推断的，不是原文写的",
                    "impact": "定向建议仅作参考，正式投放前请用自有数据或一方人群验证。"})
    page_text = " ".join([page.get("title") or "", page.get("description") or ""]
                         + list(page.get("h1") or []) + list(page.get("h2") or [])
                         + list(page.get("ctas") or []))
    if (not PRICE_RE.search(text + " " + page_text)
            and not FREE_RE.search(text + " " + page_text)
            and not any(_metric_detail(m)["kind"] == "price" for m in metrics)):
        out.append({"level": "info", "item": "未见价格、免费试用或优惠信息",
                    "impact": "促销方向（promo）缺真实活动依据，出稿后会提示需人工确认。"})
    if len(page.get("h2") or []) < 2:
        out.append({"level": "info", "item": "落地页没有分层的小标题",
                    "impact": "说明卖点表达较散，素材需要自己重建信息层级（本工具会按方向重排）。"})
    if len(points) < 3:
        out.append({"level": "warn", "item": f"可用卖点只有 {len(points)} 条",
                    "impact": "8 个方向的钩子会高度相似，建议先补充产品事实再批量出稿。"})
    return out


# ---------------- 创意方向推荐排序 ----------------
# 每个方向对不同信号的加减分；信号只来自 fw.site_analysis 与本地抽取事实，命中项会写进
# angle.reasons，报告里可逐条回溯「为什么推荐它」，不做黑盒排序。
_ANGLE_WEIGHTS = {
    "pain":       {"pain_points": 3, "audience": 1, "no_proof": 2, "no_price": 2},
    "scenario":   {"pain_points": 3, "audience": 2, "demographics": 1, "game": 1},
    "benefit":    {"strong_points": 2, "metrics": 1, "value_summary": 1},
    "proof":      {"metrics": 3, "endorsements": 2, "credibility": 1, "no_proof": -4},
    "comparison": {"strong_points": 2, "metric_point": 2, "differentiators": 2, "metrics": 1},
    "curiosity":  {"differentiators": 2, "strong_points": 1},
    "ugc":        {"audience": 2, "endorsements": 1, "game": 1, "no_price": 1},
    "promo":      {"high_risk": -3, "finance": -2},
}

_SIGNAL_LABELS = {
    "pain_points": "页面给出明确痛点",
    "audience": "识别到目标人群",
    "demographics": "有人群画像特征",
    "no_price": "页面未见价格",
    "no_proof": "缺量化/第三方背书",
    "strong_points": "有强卖点（含数字/背书）",
    "metrics": "有可量化指标",
    "metric_point": "卖点里带数字/证明",
    "value_summary": "有明确价值主张",
    "endorsements": "有媒体/认证背书",
    "credibility": "有可信度表述",
    "differentiators": "有差异化/对比线索",
    "game": "游戏/休闲品类",
    "high_risk": "存在合规高风险点",
    "finance": "金融品类（承诺类表述敏感）",
}


def _angle_signals(site: dict, metrics: list, gaps: list) -> dict:
    """把网站分析的受众/价值/背书/风险信号抽成布尔字典，供方向打分。"""
    val = site.get("value") or {}
    aud = site.get("audience") or {}
    pos = site.get("positioning") or {}
    prf = site.get("proof") or {}
    risk = site.get("risk") or {}
    points = [p for p in (val.get("points") or []) if isinstance(p, dict)]
    missing = [str(m) for m in ((site.get("gaps") or {}).get("missing") or [])]
    risk_items = [i for i in (risk.get("items") or []) if isinstance(i, dict)]
    cat = (pos.get("category_key") or "").strip()
    endorsements = [e for e in (prf.get("endorsements") or []) if e]
    missing_proof = any(("背书" in m or "证明" in m or "指标" in m or "证据" in m)
                        for m in missing)
    return {
        "pain_points": bool([p for p in (aud.get("pain_points") or []) if p]),
        "audience": bool((aud.get("primary") or "").strip()),
        "demographics": bool((aud.get("demographics") or "").strip()),
        "no_price": any(g.get("item", "").startswith("未见价格") for g in gaps),
        "no_proof": (not metrics and not endorsements) or missing_proof,
        "strong_points": any(p.get("strength") == "强" for p in points),
        "metrics": bool(metrics),
        "metric_point": any(p.get("type") in ("metric", "proof") for p in points),
        "value_summary": bool((val.get("summary") or "").strip()) or bool(points),
        "endorsements": bool(endorsements),
        "credibility": bool((prf.get("credibility") or "").strip()),
        "differentiators": bool([d for d in (pos.get("differentiators") or []) if d]),
        "game": cat == "game",
        "high_risk": any(i.get("level") in ("error", "warn") for i in risk_items),
        "finance": cat == "finance",
    }


def _rank_angles(angles, site: dict, metrics: list, gaps: list):
    """按网站分析信号给方向打分排序，返回 [(angle, {score, reasons, recommended})]。

    基础分沿用旧规则（有指标→benefit/proof/pain，无指标→pain/proof/benefit；
    未见价格→pain/benefit/ugc），再叠加 audience/value/proof/risk 信号，
    让 scenario（人群痛点/画像）与 comparison（强卖点/差异化）也能被推到前面。
    """
    sig = _angle_signals(site, metrics, gaps)
    prefer = ["pain", "proof", "benefit"] if not metrics else ["benefit", "proof", "pain"]
    if sig["no_price"]:
        prefer = ["pain", "benefit", "ugc"]
    base = {k: (3 - i) for i, k in enumerate(prefer)}

    scored = []
    for idx, a in enumerate(angles):
        score = base.get(a.key, 0)
        hits = []
        for signal, weight in _ANGLE_WEIGHTS.get(a.key, {}).items():
            if sig.get(signal):
                score += weight
                hits.append(f"{_SIGNAL_LABELS[signal]}{'+' if weight > 0 else ''}{weight}")
        if score > 0 and not hits:
            hits = ["基础推荐（指标/价格信号）"]
        scored.append((idx, a, score, hits))

    scored.sort(key=lambda t: (-t[2], t[0]))
    top_keys = {t[1].key for t in scored[:2] if t[2] > 0}
    return [(a, {"score": score, "reasons": hits, "recommended": a.key in top_keys})
            for idx, a, score, hits in scored]


def _compliance(domain: str, points: list[str]) -> list[dict]:
    rows = COMPLIANCE_BY_DOMAIN.get(domain or "app", COMPLIANCE_BY_DOMAIN["app"])
    out = [{"level": "warn", "item": item, "detail": detail} for item, detail in rows]
    joined = " ".join(points).lower()
    if re.search(r"\b(cure|treat|heal|clinically proven)\b|治愈|治疗|疗效", joined):
        out.insert(0, {"level": "error", "item": "原文含医疗/疗效级表述",
                       "detail": "这类表述直接用于广告会被拒登，文案层已做规避，素材文字请再人工确认一遍。"})
    if re.search(r"\b(guaranteed|risk[- ]free|\d+%\s*guarantee)\b|保证|零风险", joined):
        out.insert(0, {"level": "error", "item": "原文含「保证/零风险」类绝对化表述",
                       "detail": "绝对化承诺在多数市场属违规，不要直接搬进素材。"})
    return out


def _short_geo(geo: str) -> str:
    g = (geo or "").strip()
    if not g:
        return "地区未识别"
    if "未识别" in g or "建议先按" in g:
        return "地区待定"
    return re.split(r"[，,；;]", g)[0][:24]


def _price_frag(s: str, m, pad: int = 24) -> str:
    """把命中的价格/免费词扩成一段可直接引用的原文片段，不切在词中间。"""
    if re.search(r"[\u4e00-\u9fff]", s):
        seg = s[max(0, m.start() - 12): m.end() + 12]
    else:
        a, b = max(0, m.start() - pad), min(len(s), m.end() + pad)
        while a > 0 and s[a - 1].isalnum():
            a -= 1
        while b < len(s) and s[b].isalnum():
            b += 1
        seg = " ".join(s[a:b].split())
    seg = re.sub(r"^[^\w\u4e00-\u9fff]+", "", seg)
    seg = re.sub(r"[^\w\u4e00-\u9fff%]+$", "", seg)
    return (seg.strip() or m.group(0))[:60]


def _positioning_deep_section(site: dict) -> dict:
    """网站本质 + toC/toB 目标客户 + 吸引力亮点。

    专门解决两类问题：(1) 落地页定位被误判（如把营销平台误判为教育）；
    (2) 不总结广告主/渠道/流量商需求与产品亮点。模型在 site_analysis 里已给出
    business_nature / target_clients / appeal_highlights，这里只负责渲染成报告行。
    """
    bn = site.get("business_nature") or {}
    tc = site.get("target_clients") or {}
    needs = tc.get("needs") or {}
    hl = site.get("appeal_highlights") or []
    return {
        "key": "positioning_deep",
        "title": "网站定位与目标客户",
        "summary": (bn.get("note") or (
            f"网站本质：{bn.get('nature') or '未识别'}"
            + ("；这是面向广告主与渠道的营销/广告平台" if bn.get("is_marketing_platform") else ""))),
        "rows": [
            {"label": "网站本质", "value": bn.get("nature") or "—",
             "note": "综合全站内容判断，而非单页关键词"},
            {"label": "是否营销/广告平台", "value": "是（服务广告主/渠道/流量商）" if bn.get("is_marketing_platform") else "否"},
            {"label": "终端用户需求", "value": tc.get("toc") or "—"},
            {"label": "广告主需求", "value": needs.get("advertiser") or "—",
             "note": "该网站面向的广告主核心诉求"},
            {"label": "渠道/代理需求", "value": needs.get("channel") or "—",
             "note": "该网站面向的渠道/代理核心诉求"},
            {"label": "流量主/媒体需求", "value": needs.get("media") or "—",
             "note": "该网站面向的流量主/媒体核心诉求"},
            {"label": "吸引力亮点", "value": ("；".join(hl) if hl else "—"),
             "note": "对目标客户最有吸引力的价值钩子（为什么该用它）"},
        ],
    }


def _nine_elements_section(site: dict) -> dict:
    """九要素结构化总结：行业/类型/品类/需求/方案/模式/优势/差异/目的。"""
    ne = site.get("nine_elements") or {}
    return {
        "key": "nine_elements",
        "title": "九要素结构化总结",
        "summary": ne.get("purpose_summary") or "从行业/类型/品类/需求/方案/模式/优势/差异/目的九个维度看懂这个网站。",
        "rows": [
            {"label": "行业", "value": ne.get("industry") or "—"},
            {"label": "类型", "value": ne.get("type") or "—",
             "note": "网站/业务本质，如效果广告平台 / 消费品落地页 / SaaS"},
            {"label": "品类", "value": ne.get("category") or "—"},
            {"label": "满足需求", "value": ne.get("needs") or "—"},
            {"label": "解决方案", "value": ne.get("solution") or "—"},
            {"label": "商业模式", "value": ne.get("business_model") or "—",
             "note": "如何赚钱：广告变现/订阅/SaaS/佣金/CPA 等"},
            {"label": "优势对比", "value": ne.get("advantage_compare") or "—"},
            {"label": "差异化特色", "value": ne.get("differentiation") or "—"},
            {"label": "目的总结", "value": ne.get("purpose_summary") or "—",
             "note": "一段话概括网站核心目的"},
        ],
    }


def _extensions_section(site: dict) -> dict:
    """延伸输出：行业/竞品/需求/差异化/优势 + 推荐媒体与人群。"""
    ex = site.get("extensions") or {}
    return {
        "key": "extensions",
        "title": "延伸输出 · 行业 / 竞品 / 需求与推荐",
        "summary": "在九要素基础上延伸：行业趋势、竞品、市场需求、差异化打法、特色优势，并给出推荐媒体与人群。",
        "rows": [
            {"label": "行业分析", "value": ex.get("industry_insight") or "—"},
            {"label": "竞品分析", "value": ex.get("competitors") or "—"},
            {"label": "市场需求", "value": ex.get("market_demand") or "—"},
            {"label": "差异化方案", "value": ex.get("diff_solution") or "—"},
            {"label": "特色优势", "value": ex.get("edge_advantage") or "—"},
            {"label": "推荐媒体", "value": "、".join(ex.get("recommended_media") or []) or "—"},
            {"label": "推荐人群", "value": "、".join(ex.get("recommended_audience") or []) or "—"},
        ],
    }


def build_report(fw, angles=None, page: dict | None = None, text: str = "") -> dict:
    """生成结构化推广产品分析报告。

    V4.0：当 fw.site_analysis（大模型按提示词产出的网站核心内容）存在时，优先用它渲染
    9 大模块；缺失的维度回退到本地规则计算，并保留可信度评分 / 合规红线 / 缺口检测等
    交叉校验，保证没有模型也能给出可用报告。
    """
    page = page or (fw.evidence or {}).get("page") or {}
    chars = int(page.get("chars") or 0)
    fetched = bool(page.get("fetched")) if page else bool(fw.selling_points)
    points = [str(x) for x in (fw.selling_points or [])]
    metrics = [str(x) for x in (fw.metrics or [])]
    audience = fw.audience or ""
    ev = fw.evidence or {}
    audience_src = ((ev.get("audience") or {}).get("source")) or "—"
    domain, dmeta = detect_domain(" ".join(points) + " " + (fw.category or ""))
    if fw.domain:
        domain = fw.domain
        dmeta = {"label": fw.category or dmeta["label"], "task": dmeta.get("task", ""),
                 "audience_hint": dmeta.get("audience_hint", ""), "matched": dmeta.get("matched", [])}

    site = fw.site_analysis or {}
    site_val = site.get("value") or {}
    site_prf = site.get("proof") or {}
    site_aud = site.get("audience") or {}
    site_pg = site.get("page") or {}
    site_ch = site.get("channel") or {}
    site_risk = site.get("risk") or {}
    site_gap = site.get("gaps") or {}
    site_ns = site.get("next_steps") or []
    site_src = site.get("_source") or "local"

    score, score_label, reasons = _confidence(
        chars, points, metrics, audience_src,
        page.get("h1") or [], page.get("h2") or [], page.get("ctas") or [], fetched)

    # ---------------- 核心价值主张 ----------------
    value_props = []
    if site_val.get("points"):
        for i, p in enumerate(site_val["points"], 1):
            if not isinstance(p, dict):
                continue
            pt = (p.get("point") or "").strip()
            if not pt:
                continue
            t = p.get("type") or _prop_type(pt)
            st = p.get("strength") or _prop_strength(pt, t)
            evd = p.get("evidence") or ("大模型分析" if site_src == "llm" else "本地抽取")
            value_props.append({"rank": i, "point": pt, "type": t, "strength": st, "evidence": evd})
    if not value_props:
        for i, p in enumerate(points, 1):
            t = _prop_type(p)
            value_props.append({
                "rank": i, "point": p, "type": t, "strength": _prop_strength(p, t),
                "evidence": "原文句子" if fetched else "用户输入/推断",
            })
    value_summary = site_val.get("summary") or (
        f"共 {len(value_props)} 条，按信息密度排序；强弱代表它能不能直接当素材标题用。")

    # ---------------- 信任与量化背书 ----------------
    metric_rows = []
    if site_prf.get("metrics"):
        for m in site_prf["metrics"]:
            if not isinstance(m, dict) or not m.get("value"):
                continue
            d = _metric_detail(str(m["value"]))
            metric_rows.append({
                "value": str(m["value"]),
                "kind": m.get("kind") or d["kind"],
                "label": m.get("label") or d["label"],
            })
    if not metric_rows:
        metric_rows = [_metric_detail(m) for m in metrics]
    rating = next((m for m in metric_rows if m["kind"] == "rating"), None)
    scale = [m for m in metric_rows if m["kind"] == "scale"]
    ratios = [m for m in metric_rows if m["kind"] == "ratio"]
    prices = [m for m in metric_rows if m["kind"] == "price"]
    endorsements = [str(x) for x in (site_prf.get("endorsements") or []) if x]

    h1 = [x for x in (page.get("h1") or []) if x]
    title = page.get("title") or ""
    claim = h1[0] if h1 else (title.split("|")[0].split("—")[0].strip() if title else "")
    diffs = _diff_sentences(text, 3) or []
    if not diffs:
        diffs = [p for p, t in zip(points, [_prop_type(x) for x in points]) if t == "metric"][:2]

    # 价格行：metric 只认「数字 + 单位」，Try Calm for Free 这类纯免费表述抓不到，
    # 这里回查页面关键位置，避免「正文写了免费、背书却写未识别」自相矛盾。
    if prices:
        prices_text = " · ".join(m["value"] for m in prices)
        prices_note = "有价格才能做促销角标"
    else:
        ctas = [str(c).strip() for c in (page.get("ctas") or []) if str(c).strip()]
        hit_cta = next((c for c in ctas if FREE_RE.search(c) or PRICE_RE.search(c)), "")
        probe = " ".join([title, page.get("description") or ""] + h1
                         + list(page.get("h2") or []) + points)
        hit = FREE_RE.search(probe) or PRICE_RE.search(probe)
        if hit_cta:
            prices_text = f"免费表述：「{hit_cta[:60]}」"
            prices_note = "来自页面主按钮；原文没有具体金额，只能做「免费试用」角标，不要写价格数字"
        elif hit:
            prices_text = f"免费表述：「{_price_frag(probe, hit)}」"
            prices_note = "原文没有具体金额，只能做「免费试用」角标，不要写价格数字"
        else:
            prices_text = "未识别"
            prices_note = "有价格才能做促销角标"

    proof_summary = (site_prf.get("summary") or site_prf.get("credibility") or
                    ((f"识别到 {len(metrics)} 个量化指标" + ("，含评分 " + rating["value"] if rating else ""))
                     if metrics else "页面没有给出可量化证明，这是当前最大的转化阻力。"))

    # ---------------- 目标人群 ----------------
    audience_primary = site_aud.get("primary") or audience
    audience_demo = site_aud.get("demographics") or ""
    audience_pain = [str(x) for x in (site_aud.get("pain_points") or []) if x]
    audience_secondary = site_aud.get("secondary") or ""

    # ---------------- 落地页结构与转化路径 ----------------
    page_sections = site_pg.get("sections") or (list(h1) + list((page.get("h2") or [])[:6]))
    conversion_path = site_pg.get("conversion_path") or ""
    primary_cta = site_pg.get("primary_cta") or (
        ((page.get("ctas") or ["—"])[0]) if page.get("ctas") else "—")
    tone = site_pg.get("tone") or ""
    structure_note = site_pg.get("structure_note") or ""

    # ---------------- 各平台投放读法 ----------------
    platform_rows = []
    if site_ch:
        for k, v in site_ch.items():
            if not isinstance(v, dict):
                continue
            platform_rows.append({
                "platform": k,
                "note": v.get("tactics") or "",
                "role": PLATFORM_ROLE.get(k, ""),
                "hook": v.get("hook") or "",
                "selling_point": v.get("selling_point") or "",
                "compliance_note": v.get("compliance_note") or "",
            })
    if not platform_rows:
        notes = dict(fw.platform_analysis or PLATFORM_NOTES.get(domain, PLATFORM_NOTES["app"]))
        platform_rows = [{"platform": k, "note": v, "role": PLATFORM_ROLE.get(k, "")}
                         for k, v in notes.items()]

    # ---------------- 风险与合规（大模型 + 品类红线交叉校验）----------------
    risks = []
    for r in (site_risk.get("items") or []):
        if not isinstance(r, dict) or not r.get("item"):
            continue
        risks.append({"level": r.get("level") or "warn", "item": r["item"],
                      "detail": r.get("detail") or ""})
    risks.extend(_compliance(domain, points))
    _seen = set()
    dedup_risks = []
    for r in risks:
        key = (r["level"], r["item"])
        if key in _seen:
            continue
        _seen.add(key)
        dedup_risks.append(r)
    risks = dedup_risks

    # ---------------- 信息缺口（大模型 + 规则检测）----------------
    gaps = []
    for g in (site_gap.get("missing") or []):
        gaps.append({"level": "info", "item": "信息缺口", "impact": str(g)})
    gaps.extend(_gaps(fw, page, chars, fetched))
    _gseen = set()
    dedup_gaps = []
    for g in gaps:
        key = (g["level"], g["item"])
        if key in _gseen:
            continue
        _gseen.add(key)
        dedup_gaps.append(g)
    gaps = dedup_gaps

    # ---------------- 下一步（大模型 + 规则补充）----------------
    actions = list(site_ns) if site_ns else []
    angle_rows = []
    if angles:
        # 推荐排序：基础规则（指标/价格缺口）+ 网站分析的受众、价值、背书、风险信号，
        # 每个方向带 score 与 reasons，报告里可回溯「为什么推荐它」。
        for a, meta in _rank_angles(angles, site, metrics, gaps):
            angle_rows.append({
                "key": a.key, "name": a.name, "hook": a.hook or "",
                "hook_type": a.hook_type or "", "storyboard": a.storyboard or [],
                "insight": a.insight or "", "template": a.template or "",
                "kpi": a.kpi or "",
                "score": meta["score"], "reasons": meta["reasons"],
                "recommended": meta["recommended"],
            })
    if not actions:
        if angle_rows:
            rec = [a["name"] for a in angle_rows if a["recommended"]][:2]
            actions.append(f"先用「{' + '.join(rec)}」两个方向、每方向 2 个版位小预算测 CTR，"
                           f"跑赢的再铺满版位。")
        if gaps:
            worst = [g for g in gaps if g["level"] in ("error", "warn")]
            if worst:
                actions.append(f"先补「{worst[0]['item']}」，否则相关方向的素材会缺依据。")
        if metric_rows:
            actions.append(f"数字类素材优先用 {metric_rows[0]['value']}（{metric_rows[0]['label']}），"
                           f"但必须能回溯到落地页。")
        actions.append("竖版 1080x1920 优先（Reels/Stories/激励视频），再补 4:5 与 1:1。")

    # ---------------- 组装 9 模块 ----------------
    pos_one_liner = site.get("positioning", {}).get("one_liner") or claim
    pos_diff = site.get("positioning", {}).get("differentiators") or []
    sections = [
        {"key": "positioning", "title": "产品与定位",
         "summary": (f"{fw.product} 属于{dmeta.get('label', fw.category or '未分类')}；"
                     f"页面主张是「{pos_one_liner}」") if pos_one_liner
                    else f"{fw.product} 的定位未在页面上明确表达。",
         "rows": [
             {"label": "产品", "value": fw.product, "note": f"来源：{(ev.get('product') or {}).get('source', '—')}"},
             {"label": "品类", "value": fw.category or "未识别",
              "note": ("命中词：" + " / ".join((ev.get("category") or {}).get("matched_words") or [])[:80])
              if (ev.get("category") or {}).get("matched_words") else "按正文语义判断"},
             {"label": "主标题（H1）", "value": h1[0] if h1 else "页面无 H1", "note": "落地页第一视觉层级说的话"},
             {"label": "页面标题", "value": title or "—", "note": "浏览器标题，通常含品牌与品类词"},
             {"label": "差异化线索", "value": ("；".join(pos_diff) if pos_diff else
              ("；".join(diffs[:2]) if diffs else "未发现明确的对比/差异化表述")),
              "note": "来自分析（差异化 / 对比句）；没有就说明产品靠品类共性卖，创意要自己造差异"},
         ]},
        _positioning_deep_section(site),
        _nine_elements_section(site),
        {"key": "value", "title": "核心价值主张",
         "summary": value_summary, "items": value_props},
        {"key": "proof", "title": "信任与量化背书",
         "summary": proof_summary,
         "rows": [
             {"label": "评分", "value": rating["value"] if rating else "未识别",
              "note": "只有原文出现才会用于评分卡素材"},
             {"label": "规模", "value": " · ".join(m["value"] for m in scale) or "未识别",
              "note": "用户量 / 下载量，适合做数字主体"},
             {"label": "比例类", "value": " · ".join(m["value"] for m in ratios) or "未识别",
              "note": "提升幅度、留存率等，需确认统计口径"},
             {"label": "价格信息", "value": prices_text, "note": prices_note},
         ] + ([{"label": "背书/媒体/认证", "value": "；".join(endorsements), "note": "来自页面真实出现的第三方证明"}]
             if endorsements else [])},
        {"key": "audience", "title": "目标人群",
         "summary": audience_primary or "未识别到人群描述。",
         "rows": ([
             {"label": "人群", "value": audience_primary or "—", "note": f"来源：{audience_src}"},
             {"label": "人口/心理特征", "value": audience_demo or "—", "note": "用于画像与定向包定制"},
         ] + ([{"label": "痛点", "value": "；".join(audience_pain), "note": "创意钩子切入点"}] if audience_pain else [])
             + ([{"label": "次要人群", "value": audience_secondary, "note": "可分流投放的人群"}] if audience_secondary else [])
             + [
             {"label": "典型任务", "value": dmeta.get("task") or "—", "note": "该品类用户想解决的原始问题"},
             {"label": "地区", "value": fw.geo or "未识别", "note": "仅按原文提及判断，不代表实际投放地区"},
             {"label": "语言建议", "value": " / ".join(fw.languages or ["en"]), "note": "按原文语言推断"},
         ])},
        {"key": "page", "title": "落地页结构与转化路径",
         "summary": (structure_note or
                     (f"页面 {chars:,} 字，{page.get('images', 0)} 张图"
                      + ("，含视频" if page.get("has_video") else "")
                      + (f"，主按钮「{(page.get('ctas') or ['—'])[0]}」" if page.get("ctas") else "，未识别到明确按钮")))
                     if fetched else "未抓到页面，结构分析不可用。",
         "rows": ([
             {"label": "信息区块", "value": " ｜ ".join(page_sections[:6]) or "无", "note": "落地页信息架构顺序"},
             {"label": "转化路径", "value": conversion_path or "未识别", "note": "用户从进入到转化的主路径"},
             {"label": "主 CTA", "value": primary_cta, "note": "素材 CTA 应与落地页按钮动作一致，避免点击后预期落差"},
         ] + ([{"label": "语气", "value": tone, "note": "文案与素材的整体调性"}] if tone else []) + [
             {"label": "H1", "value": h1[0] if h1 else "—", "note": "首屏主张"},
             {"label": "H2 分层", "value": " ｜ ".join((page.get("h2") or [])[:5]) or "无", "note": "卖点是否分层表达"},
             {"label": "META 描述", "value": page.get("description") or "—", "note": "搜索引擎摘要"},
         ])},
        {"key": "channel", "title": "各平台投放读法",
         "summary": "同一产品在不同流量场的打法不一样，下面是按品类/产品给出的差异，不是通用建议。",
         "items": platform_rows},
        _extensions_section(site),
    ]

    return {
        "framework_id": fw.id,
        "source": {
            "url": (page.get("final_url") or ""),
            "fetched": fetched, "chars": chars, "status": page.get("status"),
            "title": title, "description": page.get("description") or "",
            "h1": h1, "h2": page.get("h2") or [], "ctas": page.get("ctas") or [],
            "images": page.get("images") or 0, "has_video": bool(page.get("has_video")),
            "lang": page.get("lang") or "",
            "analyzer": fw.analyzer or "local",
            "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "verdict": {"one_liner": f"{fw.product}｜{fw.category or '未分类'}｜{_short_geo(fw.geo)}",
                    "claim": claim, "confidence": score, "confidence_label": score_label,
                    "reasons": reasons},
        "sections": sections,
        "value_props": value_props,
        "proof": {"metrics": metric_rows, "rating": rating,
                  "scale": scale, "ratios": ratios, "prices": prices},
        "audience": {"primary": audience_primary, "source": audience_src,
                     "geo": fw.geo or "", "languages": fw.languages or ["en"],
                     "demographics": audience_demo,
                     "pain_points": audience_pain,
                     "secondary": audience_secondary},
        "creative": {"angles": angle_rows,
                     "platform_notes": {r["platform"]: r["note"] for r in platform_rows},
                     "hooks": [a["hook"] for a in angle_rows if a.get("hook")][:4]},
        "risks": risks,
        "gaps": gaps,
        "actions": actions,
        "raw": {"selling_points": points, "metrics": metrics, "domain": domain,
                "category_label": dmeta.get("label"), "matched_words": dmeta.get("matched", [])},
    }


def report_markdown(report: dict, product: str = "") -> str:
    """导出为 Markdown：内部评审时贴进文档/IM 就能用。"""
    s = report["source"]
    v = report["verdict"]
    lines = [f"# {product or '推广产品'} · 落地页分析报告", ""]
    lines.append(f"- 落地页：{s.get('url') or '未提供'}")
    lines.append(f"- 抓取：{'成功' if s.get('fetched') else '失败'}，{s.get('chars', 0):,} 字；"
                 f"分析器：{s.get('analyzer')}；时间：{s.get('extracted_at')}")
    lines.append(f"- 结论可信度：{v['confidence']}/100（{v['confidence_label']}）")
    lines.append("")
    for sec in report["sections"]:
        lines.append(f"## {sec['title']}")
        if sec.get("summary"):
            lines.append(sec["summary"])
        for r in sec.get("rows") or []:
            lines.append(f"- **{r['label']}**：{r['value']}" + (f"（{r['note']}）" if r.get("note") else ""))
        for it in sec.get("items") or []:
            if "point" in it:
                lines.append(f"{it['rank']}. {it['point']} —— 类型 {it['type']}，强度 {it['strength']}"
                             + (f"（依据：{it['evidence']}）" if it.get("evidence") else ""))
            elif "platform" in it:
                lines.append(f"- **{it['platform']}**：{it['note']}")
                if it.get("hook"):
                    lines.append(f"  - 前3秒钩子：{it['hook']}")
                if it.get("selling_point"):
                    lines.append(f"  - 主推卖点：{it['selling_point']}")
                if it.get("compliance_note"):
                    lines.append(f"  - 合规提示：{it['compliance_note']}")
            elif "hook" in it:
                flag = " ⭐推荐" if it.get("recommended") else ""
                sc = f"（推荐分 {it['score']}）" if it.get("score") is not None else ""
                lines.append(f"- **{it['name']}**{flag}{sc}（{it['kpi']}）钩子：{it['hook']}｜{it['insight']}")
                if it.get("reasons"):
                    lines.append(f"  - 推荐依据：{'；'.join(it['reasons'])}")
        lines.append("")
    # 创意方向不在 sections 里，单独存于 creative.angles；这里显式渲染，
    # 否则 Markdown 导出会漏掉方向与推荐依据（旧版只留了 sections 内的分支，实为死代码）。
    angles = (report.get("creative") or {}).get("angles") or []
    if angles:
        lines.append("## 创意方向（按推荐分排序）")
        for a in angles:
            flag = " ⭐推荐" if a.get("recommended") else ""
            sc = f"（推荐分 {a['score']}）" if a.get("score") is not None else ""
            lines.append(f"- **{a['name']}**{flag}{sc}（{a.get('kpi') or ''}）")
            if a.get("hook"):
                lines.append(f"  - 钩子：{a['hook']}")
            if a.get("insight"):
                lines.append(f"  - 洞察：{a['insight']}")
            if a.get("reasons"):
                lines.append(f"  - 推荐依据：{'；'.join(a['reasons'])}")
        lines.append("")
    if report["risks"]:
        lines.append("## 风险与合规")
        for r in report["risks"]:
            lines.append(f"- [{r['level']}] **{r['item']}**：{r['detail']}")
        lines.append("")
    if report["gaps"]:
        lines.append("## 信息缺口")
        for g in report["gaps"]:
            lines.append(f"- [{g['level']}] **{g['item']}**：{g['impact']}")
        lines.append("")
    if report["actions"]:
        lines.append("## 下一步")
        for a in report["actions"]:
            lines.append(f"- {a}")
    return "\n".join(lines)
