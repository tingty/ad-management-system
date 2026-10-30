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
                    "impact": "6 个方向的钩子会高度相似，建议先补充产品事实再批量出稿。"})
    return out


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


def build_report(fw, angles=None, page: dict | None = None, text: str = "") -> dict:
    """生成结构化推广产品分析报告。所有结论都来自 fw 的抽取结果，不补通用套话。"""
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

    score, score_label, reasons = _confidence(
        chars, points, metrics, audience_src,
        page.get("h1") or [], page.get("h2") or [], page.get("ctas") or [], fetched)

    value_props = []
    for i, p in enumerate(points, 1):
        t = _prop_type(p)
        value_props.append({
            "rank": i, "point": p, "type": t, "strength": _prop_strength(p, t),
            "evidence": "原文句子" if fetched else "用户输入/推断",
        })

    metric_rows = [_metric_detail(m) for m in metrics]
    rating = next((m for m in metric_rows if m["kind"] == "rating"), None)
    scale = [m for m in metric_rows if m["kind"] == "scale"]
    ratios = [m for m in metric_rows if m["kind"] == "ratio"]
    prices = [m for m in metric_rows if m["kind"] == "price"]

    h1 = [x for x in (page.get("h1") or []) if x]
    title = page.get("title") or ""
    claim = h1[0] if h1 else (title.split("|")[0].split("—")[0].strip() if title else "")
    diffs = _diff_sentences(text, 3) or []
    if not diffs:
        diffs = [p for p, t in zip(points, [_prop_type(x) for x in points]) if t == "metric"][:2]

    # 价格行：metric 只认「数字 + 单位」，Try Calm for Free 这类纯免费表述抓不到，
    # 这里回查页面关键位置，避免「正文写了免费、背书却写未识别」自相矛盾。
    # 优先取转化按钮原文——CTA 是最干净的免费信号，不会和别的小标题拼在一起。
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

    # 各平台读法：优先用框架里按品类生成的分析，再补平台角色
    notes = dict(fw.platform_analysis or PLATFORM_NOTES.get(domain, PLATFORM_NOTES["app"]))
    platform_rows = [{"platform": k, "note": v, "role": PLATFORM_ROLE.get(k, "")}
                     for k, v in notes.items()]

    gaps = _gaps(fw, page, chars, fetched)
    angle_rows = []
    if angles:
        # 推荐方向：命中该品类常见瓶颈的排前面（缺失证明时优先 proof，等等）
        prefer = ["pain", "proof", "benefit"] if not metrics else ["benefit", "proof", "pain"]
        if any(g["item"].startswith("未见价格") for g in gaps):
            prefer = ["pain", "benefit", "ugc"]
        ordered = sorted(angles, key=lambda a: (prefer.index(a.key) if a.key in prefer else 9))
        for a in ordered:
            angle_rows.append({
                "key": a.key, "name": a.name, "hook": a.hook or "",
                "insight": a.insight or "", "template": a.template or "",
                "kpi": a.kpi or "", "recommended": a.key in prefer[:2],
            })

    risks = _compliance(domain, points)

    sections = [
        {"key": "positioning", "title": "产品与定位",
         "summary": f"{fw.product} 属于{dmeta.get('label', fw.category or '未分类')}；"
                    f"页面主张是「{claim}」" if claim else f"{fw.product} 的定位未在页面上明确表达。",
         "rows": [
             {"label": "产品", "value": fw.product, "note": f"来源：{(ev.get('product') or {}).get('source', '—')}"},
             {"label": "品类", "value": fw.category or "未识别",
              "note": ("命中词：" + " / ".join((ev.get("category") or {}).get("matched_words") or [])[:80])
              if (ev.get("category") or {}).get("matched_words") else "按正文语义判断"},
             {"label": "主标题（H1）", "value": h1[0] if h1 else "页面无 H1", "note": "落地页第一视觉层级说的话"},
             {"label": "页面标题", "value": title or "—", "note": "浏览器标题，通常含品牌与品类词"},
             {"label": "差异化线索", "value": "；".join(diffs[:2]) if diffs else "未发现明确的对比/差异化表述",
              "note": "来自正文中的对比句；没有就说明产品靠品类共性卖，创意要自己造差异"},
         ]},
        {"key": "value", "title": "核心价值主张",
         "summary": f"共 {len(value_props)} 条，按信息密度排序；强弱代表它能不能直接当素材标题用。",
         "items": value_props},
        {"key": "proof", "title": "信任与量化背书",
         "summary": (f"识别到 {len(metrics)} 个量化指标" + ("，含评分 " + rating["value"] if rating else ""))
         if metrics else "页面没有给出可量化证明，这是当前最大的转化阻力。",
         "rows": [
             {"label": "评分", "value": rating["value"] if rating else "未识别",
              "note": "只有原文出现才会用于评分卡素材"},
             {"label": "规模", "value": " · ".join(m["value"] for m in scale) or "未识别",
              "note": "用户量 / 下载量，适合做数字主体"},
             {"label": "比例类", "value": " · ".join(m["value"] for m in ratios) or "未识别",
              "note": "提升幅度、留存率等，需确认统计口径"},
             {"label": "价格信息", "value": prices_text, "note": prices_note},
         ]},
        {"key": "audience", "title": "目标人群",
         "summary": audience or "未识别到人群描述。",
         "rows": [
             {"label": "人群", "value": audience or "—", "note": f"来源：{audience_src}"},
             {"label": "典型任务", "value": dmeta.get("task") or "—", "note": "该品类用户想解决的原始问题"},
             {"label": "地区", "value": fw.geo or "未识别", "note": "仅按原文提及判断，不代表实际投放地区"},
             {"label": "语言建议", "value": " / ".join(fw.languages or ["en"]), "note": "按原文语言推断"},
         ]},
        {"key": "page", "title": "落地页结构与转化路径",
         "summary": (f"页面 {chars:,} 字，{page.get('images', 0)} 张图"
                     + ("，含视频" if page.get("has_video") else "")
                     + (f"，主按钮「{(page.get('ctas') or ['—'])[0]}」" if page.get("ctas") else "，未识别到明确按钮"))
         if fetched else "未抓到页面，结构分析不可用。",
         "rows": [
             {"label": "H1", "value": h1[0] if h1 else "—", "note": "首屏主张"},
             {"label": "H2 分层", "value": " ｜ ".join((page.get("h2") or [])[:5]) or "无",
              "note": "卖点是否分层表达"},
             {"label": "转化按钮", "value": " · ".join(page.get("ctas") or []) or "未识别",
              "note": "素材 CTA 应与落地页按钮动作一致，避免点击后预期落差"},
             {"label": "META 描述", "value": page.get("description") or "—", "note": "搜索引擎摘要"},
         ]},
        {"key": "channel", "title": "各平台投放读法",
         "summary": "同一产品在不同流量场的打法不一样，下面是按品类给出的差异，不是通用建议。",
         "items": platform_rows},
    ]

    actions = []
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
        "audience": {"primary": audience, "source": audience_src,
                     "geo": fw.geo or "", "languages": fw.languages or ["en"]},
        "creative": {"angles": angle_rows,
                     "platform_notes": notes,
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
                lines.append(f"{it['rank']}. {it['point']} —— 类型 {it['type']}，强度 {it['strength']}")
            elif "platform" in it:
                lines.append(f"- **{it['platform']}**：{it['note']}")
            elif "hook" in it:
                lines.append(f"- **{it['name']}**（{it['kpi']}）钩子：{it['hook']}｜{it['insight']}")
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
