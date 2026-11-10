"""行业 / 品类适配层（V4.39 · AI 改造第 1 期横切基础）。

说明书的样本是「海外电商购买 + 订阅转化」，但 F01–F12 全部位于通用链路：
事实采集 → 文案生成 → 视觉制作 → 校验 → 归档。因此主干逻辑对任何行业一致，
本模块只负责**局部调整**：

- 价值维度（压缩文案时优先保留什么）；
- 必须保留的语义（否定、价格条件、期限、订阅/退款限制等，跨行业通用 + 行业补充）；
- 需核验的事实类型（价格/条款/资质/课时…）；
- 视觉主体与画面重点（供第 3 期 VisualBrief 使用）；
- 品牌与 Logo 的来源规则（任何行业都不允许从追踪域名自动定稿品牌）。

电商与订阅只是其中两个 profile；未命中任何关键词时使用 `general`，
不猜产品事实、不编造价格或功效。后续期次只需扩展配置，不改通用主干。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 通用语义保护：任何行业都不能在「压缩 / 裁剪」中丢失
# ---------------------------------------------------------------------------
GENERIC_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\b(?:no|not|never|without|unless|except|only|up to|at least|subject to|"
     r"limited to|while supplies last|non-?refundable)\b[^,.;!?。；]{0,44}", "否定 / 限制条件"),
    (r"[$€£¥]\s?\d[\d,.]*(?:\s?(?:off|per|/)\s?(?:month|mo|year|yr|item))?"
     r"|\b\d+(?:\.\d+)?\s?%|\b\d+\s?(?:days?|months?|years?|hours?|weeks?)\b", "价格 / 折扣 / 期限"),
    (r"(?i)\b(?:free trial|trial period|subscription|auto-?renew(?:al|s)?|renew(?:al|s)?|"
     r"cancel(?:lation| anytime)?|refund|money[- ]back|terms apply|conditions apply|"
     r"first payment|billed (?:monthly|annually)|per month|per year|cancel anytime)\b", "订阅 / 退款 / 续费"),
    (r"(?i)\b(?:until|before|after|valid through|expires? on|ends? on)\b[^,.;!?。；]{0,32}"
     r"|\b\d{4}-\d{2}-\d{2}\b", "有效期 / 时间条件"),
    (r"不含|不包括|无需|仅限|除外|不支持|不可|不得|免费试用|自动续费|随时取消|"
     r"退款|有效期|续费|取消|限前\d+名|\d+天无理由", "中文限制条件"),
]

# 英文残句的典型「悬空词」结尾（说明书 T01：Book in minutes. → Book in）
_DANGLING_EN = frozenset(
    "a an and or but to of for with in at on by from is are was were be been the "
    "this that these those your our their its as if than then when while not no "
    "can will may must per via into over under more most less only".split()
)
_SENTENCE_END = tuple(".!?。！？;；:")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def protected_fragments(text: str, profile: dict | None = None) -> list[str]:
    """返回文本中「不可在压缩中丢失」的语义片段（去重、保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    patterns = list(GENERIC_PATTERNS)
    if profile:
        patterns += [(p, "行业限定") for p in (profile.get("protected_extra") or [])]
    for pattern, _label in patterns:
        for m in re.finditer(pattern, text or ""):
            frag = m.group(0).strip()
            key = _norm(frag)
            if frag and key and key not in seen:
                seen.add(key)
                out.append(frag)
    return out


def missing_protected(original: str, candidate: str, profile: dict | None = None) -> list[str]:
    """压缩前后比对：返回被丢掉的受保护语义片段。"""
    cand = _norm(candidate)
    lost = []
    for frag in protected_fragments(original, profile):
        # 大小写 / 空格归一化后按子串匹配；数值、百分比、日期因此必须逐字保留
        if _norm(frag) not in cand:
            lost.append(frag)
    return lost


def is_complete_sentence(text: str) -> bool:
    """判断文案是否为完整短句（用于阻断 'Book in' 这类残句被判合格）。"""
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith("…") or s.endswith("..."):
        return False
    if s.endswith(",") or s.endswith("，") or s.endswith("、") or s.endswith("-"):
        return False
    # 英文：以悬空介词 / 连词 / 冠词收尾视为残句
    words = re.findall(r"[A-Za-z']+", s)
    if words and re.fullmatch(r"[A-Za-z0-9 ,.'%$€£¥\-/&]+", s):
        last = words[-1].lower()
        if last in _DANGLING_EN:
            return False
    # 以标点收尾的完整句，或无标点但语义自足的短标题，都视为完整
    return True


def _profile(key: str, label: str, aliases: list[str], value_axes: list[str],
             evidence_types: list[str], visual_subject: str,
             must_preserve: list[str], copy_focus: str,
             protected_extra: list[str] | None = None,
             placement_preferences: list[str] | None = None) -> dict:
    """V4.40 / 第 2 期：`placement_preferences` 只是版位建议，不改变通用任务矩阵主干。

    值为 media_platforms.PLACEMENT_RULES 中的 placement id；前端仅作提示，
    用户仍可自由勾选任意版位。其它行业新增画像时只需在此登记偏好。
    """
    return {
        "key": key, "label": label, "aliases": aliases,
        "value_axes": value_axes, "evidence_types": evidence_types,
        "visual_subject": visual_subject, "must_preserve": must_preserve,
        "copy_focus": copy_focus, "protected_extra": protected_extra or [],
        "placement_preferences": placement_preferences or [],
    }


INDUSTRY_PROFILES: dict[str, dict] = {
    "ecommerce": _profile(
        "ecommerce", "电商零售 / 跨境商品",
        ["电商", "购物", "商城", "零售", "跨境电商", "独立站", "shop", "store", "e-commerce",
         "ecommerce", "retail", "dropshipping", "marketplace", "商品", "购物车"],
        ["具体商品与规格", "价格与配送保障", "退换货与真实评价"],
        ["价格与币种", "优惠起止时间", "退换货条款", "SKU / 库存"],
        "真实商品、包装与使用场景（不虚构商品外观）",
        ["价格 / 折扣数值", "限时条件", "退换货限制"],
        "把购买理由落到具体商品价值与购买保障，不写空泛促销语",
        [r"(?i)\b(?:free shipping|shipping|delivery|returns?|warranty|in stock|COD|cash on delivery)\b"],
    ),
    "subscription": _profile(
        "subscription", "订阅 / 会员 / SaaS 转化",
        ["订阅", "会员", "续费", "saas", "subscription", "membership", "premium plan",
         "pricing plan", "free trial", "按月订阅", "年费"],
        ["首次使用价值", "试用与续费规则", "取消与退款保障"],
        ["试用天数", "首期与续费价格", "自动续费与取消条款", "适用地区"],
        "真实产品界面、使用流程与订阅权益（不虚构界面数字）",
        ["试用 / 续费条件", "价格与周期", "取消与退款限制"],
        "清楚区分购买、试用与首次付费，不把限制条件压缩掉",
        [r"(?i)\b(?:trial|billed|renew|cancel|refund|per month|per year|annual|monthly|plan)\b"],
    ),
    "app_game": _profile(
        "app_game", "App / 游戏 / 工具",
        ["app", "应用", "手游", "游戏", "工具", "game", "mobile app", "utility", "sdk", "下载"],
        ["核心玩法或功能", "上手成本", "设备与系统适配"],
        ["版本号", "支持系统", "内购与广告说明", "商店评分来源"],
        "真实 UI 截图、操作场景或角色画面（不虚构界面）",
        ["系统 / 版本限定", "免费与内购条件"],
        "说明能做什么、在哪能用，不编造下载量或评分",
        [r"(?i)\b(?:iOS|Android|APK|free to play|in-?app purchases?|offline|no ads)\b"],
    ),
    "b2b_service": _profile(
        "b2b_service", "B2B / 企业服务",
        ["b2b", "企业服务", "saas 平台", "解决方案", "代理商", "api", "wholesale", "enterprise"],
        ["可验证的业务结果", "接入与实施成本", "服务范围"],
        ["服务范围", "合同与 SLA", "案例来源", "报价有效期"],
        "真实工作流、团队协作或数据看板（不虚构客户 Logo 与指标）",
        ["服务边界", "报价与合同条件"],
        "用可核对的业务事实替代「行业领先」等空话",
        [r"(?i)\b(?:SLA|MOQ|quote|lead time|integration|onboarding|enterprise)\b"],
    ),
    "travel_local": _profile(
        "travel_local", "旅游 / 本地生活 / 预约",
        ["旅游", "酒店", "机票", "预订", "预约", "travel", "hotel", "booking", "flight", "tour", "当地体验"],
        ["行程或服务内容", "可订日期与地点", "取消与改期规则"],
        ["价格包含项", "可订日期", "取消 / 改期条款", "适用人群"],
        "真实目的地或服务场景（不虚构景点与酒店）",
        ["日期 / 地点限制", "取消与改期条件"],
        "把时间、地点、包含项写清楚，不编造库存与评价",
        [r"(?i)\b(?:check-?in|check-?out|per night|itinerary|reschedule|cancellation|blackout dates)\b"],
    ),
    "education": _profile(
        "education", "教育 / 课程 / 培训",
        ["教育", "课程", "培训", "学习", "course", "education", "training", "class", "tutor"],
        ["学习成果与内容", "课时与形式", "退款与有效期"],
        ["课时数", "开课与有效期", "退款条款", "证书 / 资质来源"],
        "真实课堂、学习界面或练习场景（不虚构通过率）",
        ["课时 / 期限", "退款条件"],
        "说明学什么、怎么学，不承诺未经验证的效果数据",
        [r"(?i)\b(?:lessons?|hours? of content|lifetime access|certificate|cohort|enrollment)\b"],
    ),
    "finance": _profile(
        "finance", "金融 / 保险 / 合规敏感品类",
        ["金融", "保险", "贷款", "理财", "支付", "finance", "insurance", "loan", "banking", "fintech"],
        ["产品条款与费率", "资质与风险提示", "适用地区"],
        ["费率与计息方式", "牌照 / 资质来源", "风险提示", "适用地区与有效期"],
        "抽象信任视觉或真实产品界面（不虚构收益与背书）",
        ["费率 / 数值", "风险与合规限定", "适用地区"],
        "条款优先，禁止出现未核验的收益、返现或「保证」表述",
        [r"(?i)\b(?:APR|interest|fee|premium|coverage|eligibility|terms and conditions|risk)\b"],
    ),
    "general": _profile(
        "general", "通用 / 未分类",
        [], ["核心功能或价值", "可信证据", "适用条件"],
        ["可核对的事实来源", "价格与条件（如有）", "适用地区与时间"],
        "与页面真实内容一致的中性主视觉",
        ["否定与限定条件", "数值与期限"],
        "只写页面能支撑的事实，缺资料时标注待补充而不是补写",
        [],
    ),
}

# V4.40 / 第 2 期：行业局部配置 —— 版位偏好（placement id）。
# 只用于「素材创作」的版位建议提示与批次规则标注，不写死电商版位、不自动替用户勾选。
# 新增行业时在此登记即可，任务矩阵主干（F07）与服务端规则（F08）无需改动。
PLACEMENT_PREFERENCES: dict[str, list[str]] = {
    "ecommerce": ["feed", "stories", "in_feed", "square"],
    "subscription": ["feed", "uac", "stories", "app_discovery"],
    "app_game": ["uac", "rewarded", "interstitial", "app_discovery", "in_feed"],
    "b2b_service": ["feed", "display_mrec", "display_leader", "square"],
    "travel_local": ["feed", "stories", "in_feed", "display_mrec"],
    "education": ["feed", "stories", "square", "uac"],
    "finance": ["feed", "display_mrec", "display_leader", "square"],
    "general": ["feed", "stories", "square"],
}
for _key, _prefs in PLACEMENT_PREFERENCES.items():
    if _key in INDUSTRY_PROFILES:
        INDUSTRY_PROFILES[_key]["placement_preferences"] = list(_prefs)

# 多级公共后缀：避免 shop.example.co.uk → "Co"、x.com.au → "Com"
MULTI_SUFFIXES = (
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "com.br", "com.cn", "com.hk",
    "com.sg", "com.mx", "co.jp", "co.kr", "co.nz", "co.za", "com.tr", "com.ar",
)
# 追踪/跳转域名特征：这些地址不是产品身份
TRACKING_HINTS = ("track", "click", "convert", "redirect", "go.", "lnk.", "ad.", "utm",
                  "aff.", "ref.", "bit.ly", "t.co", "cutt.ly")


def host_of(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def host_brand_candidate(url: str) -> dict:
    """只给出「域名推导的候选」，绝不作为已确认品牌返回。

    返回 {candidate, is_tracking, is_multi_suffix, reason}；供 F02 说明为什么不能自动定稿。
    """
    host = host_of(url)
    if not host:
        return {"candidate": "", "is_tracking": False, "is_multi_suffix": False,
                "reason": "无法解析主机名"}
    labels = host.split(".")
    is_multi = any(host.endswith("." + s) for s in MULTI_SUFFIXES)
    is_tracking = any(h in host for h in TRACKING_HINTS)
    # 去掉公共后缀后再取主域名段；多级后缀要多去掉一段
    core = labels[:]
    if is_multi and len(core) >= 3:
        core = core[:-2]
    elif len(core) >= 2:
        core = core[:-1]
    candidate = (core[-1] if core else "").capitalize()
    reason = ("追踪 / 跳转域名，不能代表产品品牌" if is_tracking else
              "多级公共后缀，域名推导不可靠" if is_multi else
              "域名仅为候选，需由结构化品牌资料或人工审核确认")
    return {"candidate": candidate, "is_tracking": is_tracking,
            "is_multi_suffix": is_multi, "reason": reason}


def brand_from_page(analysis: dict | None, page: dict | None = None,
                    final_url: str = "", input_url: str = "") -> dict:
    """按证据强度确定品牌，不从追踪域名自动定稿（说明书 F02）。

    证据优先级：
      1) 结构化数据 / 用户明确提供 → confirmed；
      2) 官方页面资料（JSON-LD Organization / og:site_name）→ unverified（待核实，可用但需标注）；
      3) 域名推导 → 仅列为 candidate，brand 留空、status=needs_input。
    """
    analysis, page = analysis or {}, page or {}
    candidates: list[str] = []

    structured = str(analysis.get("brand") or analysis.get("brand_name") or "").strip()
    if structured:
        return {"brand": structured[:80], "status": "confirmed",
                "candidates": [structured[:80]], "reason": "来自结构化商品 / 品牌数据",
                "host": host_of(final_url or input_url),
                "input_url": input_url, "final_url": final_url}

    official = (str(page.get("jsonld_brand") or "").strip()
                or str(page.get("og_site_name") or "").strip())
    if official:
        candidates.append(official[:80])

    hc = host_brand_candidate(final_url or input_url)
    if hc["candidate"]:
        candidates.append(hc["candidate"])
    candidates = list(dict.fromkeys([c for c in candidates if c]))

    if official:
        return {"brand": official[:80], "status": "unverified", "candidates": candidates,
                "reason": "来自官方页面资料（JSON-LD / og:site_name），待人工核实",
                "host": hc["host"] if "host" in hc else host_of(final_url or input_url),
                "input_url": input_url, "final_url": final_url}
    return {"brand": "", "status": "needs_input", "candidates": candidates,
            "reason": "未找到可核验的品牌资料；" + hc["reason"],
            "host": host_of(final_url or input_url),
            "input_url": input_url, "final_url": final_url}


def resolve_profile(analysis: dict | None = None, text: str = "",
                    key: str = "") -> dict:
    """按显式选择 > 关键词识别 > general 的顺序解析行业画像。"""
    if key and key in INDUSTRY_PROFILES:
        return INDUSTRY_PROFILES[key]
    a = analysis or {}
    hay = " ".join(str(a.get(k) or "") for k in ("industry", "type", "audience", "url"))
    hay = (hay + " " + (text or "")[:1500]).lower()
    best, best_len = None, 0
    for p in INDUSTRY_PROFILES.values():
        for alias in p["aliases"]:
            al = alias.lower()
            if al and al in hay and len(al) > best_len:
                best, best_len = p, len(al)
    return best or INDUSTRY_PROFILES["general"]


def list_profiles() -> list[dict]:
    """供前端「行业 / 品类」局部调整选择器使用（不暴露正则实现）。"""
    return [{k: p[k] for k in ("key", "label", "value_axes", "evidence_types",
                               "visual_subject", "must_preserve", "copy_focus",
                               "placement_preferences")}
            for p in INDUSTRY_PROFILES.values()]
