"""V4.45 / D1–D3：自动创作的策划层（产品识别 → 推荐描述 → 覆盖摘要）。

文档要求：默认自动创作路径**不另建一套生成系统**，而是在现有
`GenerationJob` / `CreativeAsset` / 任务矩阵 / `VisualBrief` 之上增加策划与编排。
本模块只做「确定性策划」：规则负责事实、能力、规格与预算，模型负责此前的落地页理解；
推荐描述与结构化 `VisualBrief` 来自**同一个对象**，不允许两次独立生成后相互矛盾。

明确边界（文档 A04 / A08 / A14）：
- 多商品首页 / 博客 / 平台型网站不强行选某个 SKU，进入 needs_input 或品牌模式；
- 缺官方商品图 / 真实 UI / 授权交付物时只给草案（draft_only），不宣称可投放；
- 不从页面语言推断投放国家、不从域名推断商家授权或库存；
- 报价、日期、地区条件不完整时不生成价格承诺。
"""
from __future__ import annotations

import hashlib
import json
import re

from industry_profiles import (resolve_profile, scene_policy,
                               PROFILE_SCHEMA_VERSION)
from claims import (EvidenceSnapshot, qualifier_hits, numeric_tokens,
                    validate_evidence_refs, HARD_QUALIFIERS)
from media_platforms import (canonical_platform, MEDIA_PLATFORM_MAP,
                             SPEC_VERSION, SPEC_VERIFIED_ON)

PLANNER_VERSION = "1.1"

#: 面向投放人员的中文资产名，不把内部英文标识直接暴露到缺口提示里。
ASSET_LABELS = {
    "official_sku_image": "官方商品图（已确认 SKU）",
    "real_ui": "产品真实界面截图",
    "authorized_deliverable": "已授权的服务交付物",
    "authorized_destination": "已授权的目的地照片",
    "neutral_brand": "已确认构成的中性品牌主体",
}

#: D2 / StructuredConcept：三个「购买理由」轴，不是同一句话换措辞的变体。
#: 每个概念只使用页面已确认的事实，且必须带可定位的证据编号。
CONCEPT_AXES = (
    ("core_value", "核心使用价值", "产品能完成的具体任务或可验证能力"),
    ("proof", "可核验依据", "页面已给出的规格、认证或条款依据"),
    ("scenario", "适用场景", "该能力在什么真实场景中被使用"),
)

DEFAULT_WORKSPACE = {
    "country": "US",
    "language": "en",
    "os": "iOS/Android",
    "goal": "conversion",
    "budget_cap": 0,          # 0 = 未设置上限，前端显示「未设置」
    "concept_count": 1,
}

SUBJECT_TEXT = {
    "physical_good": "官网已确认款式的官方商品图",
    "software": "产品真实界面",
    "service": "已授权的服务流程或交付物",
    "travel": "已确认目的地的授权照片",
    "general": "已确认素材构成的中性品牌主体",
}

SCENE_TEXT = {
    "physical_good": "与页面已确认用途一致的真实使用场景",
    "software": "完成一个明确任务的真实工作界面",
    "service": "从检查到复盘的真实服务过程",
    "travel": "真实可售的出行场景",
    "general": "克制的品牌版面",
}

COMPOSITION_TEXT = {
    "hero": "主体置于右侧、左侧保留标题区的构图",
    "demo": "上演示下文字的分层构图",
    "detail": "左细节右说明的双栏构图",
    "offer": "居中对称、CTA 独立的构图",
    "review": "引用条 + 小主体特写的克制构图",
    "banner": "单行横排、文案与 Logo 各自留白",
}

# 60–120 字的直观描述必须同时回答「什么产品 / 什么场景 / 什么价值 / 怎么构图 /
# 文字放哪里 / 适配什么版位」。长文案先被截断会把后半段的构图与文字区整段丢掉，
# 因此每个槽位都有短版与硬上限，而不是靠事后截断。
SUBJECT_SHORT = {
    "physical_good": "官方商品图", "software": "产品真实界面",
    "service": "授权服务交付物", "travel": "授权目的地照片",
    "general": "中性品牌主体",
}
SCENE_SHORT = {
    "physical_good": "真实使用场景", "software": "真实任务界面",
    "service": "真实服务过程", "travel": "真实可售场景",
    "general": "克制品牌版面",
}
COMPOSITION_SHORT = {
    "hero": "右主体左标题", "demo": "上演示下文字", "detail": "左细节右说明",
    "offer": "居中对称独立 CTA", "review": "引用条配主体特写", "banner": "单行横排留白",
}

_MULTI_PRODUCT_RE = re.compile(
    r"marketplace|category|collection|blog|magazine|portal|多商品|目录页|博客|资讯|平台型", re.I)
_PRICE_RE = re.compile(r"(?i)(price|\$|usd|€|£|¥|trial|subscribe|per month|billed|价格|订阅|试用|月费|年费)")


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _facts(analysis: dict) -> list[str]:
    return [_clean(x)[:120] for x in (analysis.get("facts") or []) if _clean(x)][:6]


_QUAL_CUT_RE = re.compile(
    r"(?i)\b(?:up\s+to|at\s+least|as\s+(?:much|many)\s+as|maximum|max\.?|"
    r"per\s+month|billed\s+annually|terms?\s+apply|results?\s+may\s+vary|"
    r"laboratory|tested\s+under|subject\s+to|only\s+(?:if|for|when))\b|"
    r"\d+(?:[.,]\d+)?\s*(?:%|％|倍|折|小时|天|分钟|mAh|W\b|GB|TB|Mbps)|"
    r"最多|至多|最高|上限|不超过|至少|实验室|护理模式|实测|结果可能|因人而异|视.*?而定")
_DANGLING_TAIL = re.compile(
    r"(?i)\s+(?:with|and|or|of|to|for|in|on|by|from|less|more|up|at|as|is|"
    r"that|which|plus|包括|以及|并且|还有|可达|约|近)$")


def _safe_value(fact: str) -> str:
    """A07：推荐描述不裸奔量化承诺。

    验收样本里「电池老化降低 20%」把官网的「最多 / 护理模式 / 实验室条件 /
    结果可能不同」全部丢了。60–120 字的直观描述装不下完整限定条件，因此一旦
    事实含数字或硬限定词，就截到限定词之前、保留产品主干，并明确标注改用
    非量化表达；量化承诺只留在带 evidence_ids 与 must_preserve_qualifiers
    的结构化概念里，由文案链路逐条校验。
    """
    if not fact:
        return "页面已明示的服务价值（未标注具体事实）"
    # A05：价格 / 订阅条款整段不进推荐描述，避免只截掉数字却留下「仅售 $29.99」。
    if _PRICE_RE.search(fact):
        return "页面已明示的产品价值（已按非量化表达）"
    if not (numeric_tokens(fact) or
            any(k in qualifier_hits(fact) for k in HARD_QUALIFIERS)):
        return fact[:90]
    core = _QUAL_CUT_RE.split(fact, maxsplit=1)[0]
    core = _clean(core).strip(" -–—、,，;；")
    for _ in range(3):                       # 收掉截断导致的悬空连词
        core = _DANGLING_TAIL.sub("", core).strip(" -–—、,，;；")
    if len(core) < 6:
        return "已核验的产品能力（已按非量化表达）"
    head = core[:18] + "…" if len(core) > 18 else core
    return head + "（已按非量化表达）"


def _roles(platforms: list[str]) -> tuple[list[str], int]:
    """按所选平台目录计算「主要图片资产角色」与默认任务数（内部目录，未核验官方）。"""
    roles, tasks = [], 0
    for name in platforms:
        key = canonical_platform(name)
        spec = MEDIA_PLATFORM_MAP.get(key)
        if not spec:
            continue
        for pl in spec.get("placements", []):
            if not pl.get("default"):
                continue
            role = (pl.get("id") or "")
            label = f"{key} · {pl.get('name') or role}"
            if label not in roles:
                roles.append(label)
            tasks += len(pl.get("sizes") or [1])
    return roles[:12], tasks


def product_profile(analysis: dict, policy: dict) -> dict:
    """产品对象：只写页面已确认字段，缺项留空并标明不确定原因。"""
    a = analysis or {}
    brand = _clean(a.get("brand"))
    brand_status = _clean(a.get("brand_status")) or "unverified"
    ptype = " ".join((_clean(a.get("type")), _clean(a.get("industry"))))
    multi = bool(_MULTI_PRODUCT_RE.search(ptype))
    return {
        "entity_type": policy["entity_type"],
        "brand": brand,
        "brand_status": brand_status,
        "sku_or_plan": "",                 # 不从 URL / 域名推断
        "business_model": _clean(a.get("type")) or "未标注",
        "assets": [],                      # 真实资产由上传 / 官方素材接入，不虚构
        "source": a.get("final_url") or a.get("url") or "",
        "multi_product_page": multi,
        "uncertainty": ("页面为多商品 / 内容型页面，需人工明确推广对象" if multi else
                        "品牌未确认，需页面可核验证据" if brand_status != "confirmed" else ""),
    }


def build_visual_brief_seed(analysis: dict, profile: dict, policy: dict,
                            platforms: list[str]) -> dict:
    """推荐的唯一结构化对象；`recommended_visual_summary` 由它确定性渲染。"""
    facts = _facts(analysis)
    value = _safe_value(facts[0]) if facts else "页面已明示的服务价值（未标注具体事实）"
    layout = "demo" if policy["entity_type"] in ("software", "service") else (
        "banner" if len(platforms) == 0 else "hero")
    roles, tasks = _roles(platforms)
    return {
        "version": PLANNER_VERSION,
        "entity_type": policy["entity_type"],
        "subject": SUBJECT_TEXT[policy["entity_type"]],
        "subject_asset": policy["subject_asset"],
        "scene": SCENE_TEXT[policy["entity_type"]],
        "scene_types": list(policy["allowed_scene_types"]),
        "value": value,
        "product_facts": facts,
        "composition": COMPOSITION_TEXT[layout],
        "layout": layout,
        "detail": (_safe_value(facts[1]) if len(facts) > 1 else "页面可核验的细节"),
        "copy_zone": "底部文字层" if layout == "demo" else "左侧标题区",
        "short_copy": "一条已验证短标题",
        "asset_roles": roles,
        "required_tasks": tasks,
        "forbidden_inferences": list(policy["forbidden_inferences"]),
        "asset_requirement": "required" if policy["requires_asset"] else "optional",
    }


def _clip(value, limit: int) -> str:
    """限长但不切在英文单词 / 中文括号中间，避免「chargin…」「（量…」这类残句。"""
    s = _clean(value)
    if len(s) <= limit:
        return s
    cut = s[:limit - 1]
    if " " in cut and "（" not in cut:
        sp = cut.rfind(" ")
        if sp >= limit // 2:
            cut = cut[:sp]
    if cut.count("（") > cut.count("）"):     # 括号未闭合就退到括号前
        cut = cut[:cut.rfind("（")]
    return cut.rstrip(" ,，、;；") + "…"


def render_visual_summary(brief: dict) -> str:
    """按文档模板生成 60–120 汉字；与 VisualBrief 来自同一对象。

    每个槽位独立限长，保证「产品 / 场景 / 价值 / 构图 / 文字区 / 版位」六项
    都出现在成稿里；旧实现把长事实放在句首，事后 120 字截断会把构图、
    文字区与版位整段丢掉，只剩一句残句。
    """
    et = brief.get("entity_type") or "general"
    subject = _clip(SUBJECT_SHORT.get(et, brief["subject"]), 12)
    scene = _clip(SCENE_SHORT.get(et, brief["scene"]), 12)
    value = _clip(brief["value"], 34)
    comp = _clip(COMPOSITION_SHORT.get(brief["layout"], brief["composition"]), 14)
    detail = _clip(brief["detail"], 18)
    zone = _clip(brief["copy_zone"], 10)
    short_copy = _clip(brief["short_copy"], 12)
    short_roles = [r.split("·")[-1].strip() for r in brief["asset_roles"][:2]]
    roles = _clip("、".join(short_roles) or "所选平台主要图片角色", 20)
    text = _clean(
        f"以{subject}为主体，在{scene}展示{value}；采用{comp}构图，突出{detail}，"
        f"在{zone}放置{short_copy}，适配{roles}。"
    )
    if len(text) < 60:
        text += "方图与竖图分别安排留白，横幅只保留主体与单一卖点。"
    if len(text) > 120:
        # 兜底：在最近的句读处收尾并补句号，绝不以逗号 / 分号结尾留下残句
        cut = text[:120]
        boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("，"))
        tail = cut[:boundary] if boundary >= 70 else cut
        text = tail.rstrip("，；、 ") + "。"
    return text


def _fact_tokens(fact: str) -> list[str]:
    """把事实回连到原文：数字 token + 英文词 + 中文二元组，不用单个汉字误匹配。"""
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", fact)]
    zh_bigrams: list[str] = []
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", fact):
        zh_bigrams += [seg[i:i + 2] for i in range(max(0, len(seg) - 1))]
    return [str(t).lower() for t in (numeric_tokens(fact) + words + zh_bigrams[:10]) if str(t).strip()]


def _evidence_for_fact(fact: str, snap: EvidenceSnapshot, limit: int = 2) -> list[str]:
    """A06：只有能在本次快照原文中定位的事实，才允许成为广告承诺。"""
    tokens = _fact_tokens(fact)
    if not tokens:
        return []
    hits: list[str] = []
    for eid in sorted(snap.valid_ids):
        quote = snap.quote_of(eid).lower()
        if any(t in quote for t in tokens):
            hits.append(eid)
        if len(hits) >= limit:
            break
    return hits


def build_structured_concepts(analysis: dict, policy: dict, snap: EvidenceSnapshot,
                              brief: dict, count: int = 1) -> list[dict]:
    """D2 / CreativeConcept：1–3 个购买理由真正不同的概念。

    不靠哈希动作池或换词制造「多样性」：每个概念绑定一条页面事实，
    事实必须能回连到本次快照的 `[E###]` 原文，量化承诺定位不到就移除，
    源文出现的限定词随概念下发，供文案与变体保留（A06 / A07）。
    """
    a = analysis if isinstance(analysis, dict) else {}
    facts = _facts(a)
    audience = _clean(a.get("audience")) or "页面未标注目标受众（不推断）"
    n = max(1, min(3, int(count or 1), len(facts) or 1))
    source_qualifiers = qualifier_hits(snap.source_text())
    hard_fragments = [f for k in HARD_QUALIFIERS for f in source_qualifiers.get(k, [])]
    out: list[dict] = []
    for i in range(n):
        axis, axis_label, reason = CONCEPT_AXES[i]
        fact = facts[i] if i < len(facts) else ""
        eids = _evidence_for_fact(fact, snap) if fact else []
        unsupported = bool(fact and not eids)
        promise = (fact[:90] if fact and eids else
                   "页面已明示的价值（量化 / 规格承诺未定位原文，已移除）" if unsupported else
                   "页面已明示的服务价值（未标注具体事实，不生成量化承诺）")
        own_qualifiers = qualifier_hits(fact)
        out.append({
            "concept_id": f"C{i + 1:02d}",
            "axis": axis,
            "audience": audience,
            "situation": SCENE_TEXT[policy["entity_type"]],
            "purchase_reason": reason,          # 不同概念必须有不同的购买理由
            "promise": promise,
            "claim_ids": eids,
            "claim_status": "unsupported" if unsupported else (
                "locatable_not_reviewed" if eids else "no_claim"),
            "claim_audit": validate_evidence_refs(eids, snap, claim=promise),
            "qualifiers": {k: v for k, v in own_qualifiers.items() if k in HARD_QUALIFIERS},
            "must_preserve_qualifiers": hard_fragments[:6],
            "format": brief["layout"],
            "forbidden_inferences": list(policy["forbidden_inferences"]),
            "distinct_reason": f"{axis_label}：{reason}",
        })
    return out


def _quality_gate(product: dict, policy: dict, snap: EvidenceSnapshot) -> dict:
    """N03 / A15：可投放交付的门。V4.45 逐图质检（D5）与官方规格核验尚未上线，
    因此自动流程的产出一律记为草案，不得按「PNG 保存成功」计作合格商品广告。
    """
    checks = [
        {"key": "product_asset", "passed": not (policy["requires_asset"] and not product["assets"]),
         "note": "已取得官方商品图 / 真实 UI / 授权资产" if not (policy["requires_asset"] and not product["assets"])
         else f"缺少{ASSET_LABELS.get(policy['subject_asset'], policy['subject_asset'])}"},
        {"key": "evidence_snapshot", "passed": snap.available,
         "note": "证据可定位原文（商业真实性未审核）" if snap.available else "无可定位证据快照"},
        {"key": "official_spec", "passed": bool(SPEC_VERIFIED_ON),
         "note": "官方媒体规格已逐项核验" if SPEC_VERIFIED_ON else "内部目录，SPEC_VERIFIED_ON 为空"},
        {"key": "per_image_review", "passed": False,
         "note": "D5 逐图质检 / 商品外观比对 / OCR 尚未上线"},
    ]
    passed = all(c["passed"] for c in checks)
    return {
        "delivery_grade": "standard" if passed else "draft",
        "deliverable": passed,
        "checks": checks,
        "note": ("全部必需图片通过质检且规则已核验，才显示完整可交付。" if passed else
                 "当前产出为草案：不得计作可投放商品广告，也不得作为模板兜底转正。"),
    }


def build_recommendation(analysis: dict, platforms: list[str] | None = None,
                         *, workspace_defaults: dict | None = None,
                         mode: str = "auto") -> dict:
    """D2：确定性策划入口，可直接被接口与回归测试调用（不调用模型）。"""
    a = analysis if isinstance(analysis, dict) else {}
    plats = [str(x).strip() for x in (platforms or []) if str(x or "").strip()][:8]
    defaults = {**DEFAULT_WORKSPACE, **(workspace_defaults or {})}
    profile = resolve_profile(a, key=a.get("industry_profile") or "")
    policy = scene_policy(profile)
    product = product_profile(a, policy)
    snap = EvidenceSnapshot.from_analysis(a)
    brief = build_visual_brief_seed(a, profile, policy, plats)
    summary = render_visual_summary(brief)
    roles, tasks = _roles(plats)
    concepts = build_structured_concepts(a, policy, snap, brief,
                                         defaults.get("concept_count", 1))
    gate = _quality_gate(product, policy, snap)
    asset_label = ASSET_LABELS.get(policy["subject_asset"], policy["subject_asset"])

    missing: list[str] = []
    blocking: list[str] = []
    if product["multi_product_page"]:
        blocking.append("落地页含多个商品或为内容型页面，请明确推广对象，或改用品牌 / 服务推广（A04）")
    if not snap.available:
        blocking.append("无可定位的原文证据快照，不能自动生成含事实承诺的素材（需重新分析落地页）")
    unknown = [p for p in plats if not canonical_platform(p)]
    if unknown:
        blocking.append("未知媒体平台：" + "、".join(unknown)
                        + "；不静默套用其它平台规则，请从已配置目录选择（A10 / N04）")
    if policy["requires_asset"] and not product["assets"]:
        missing.append(f"缺少{asset_label}；当前只能产出草案，不能计作可投放商品广告（A08）")
    if product["brand_status"] != "confirmed":
        missing.append("品牌未经页面证据确认，Logo 与品牌名按未核实处理")
    unsupported = [c["concept_id"] for c in concepts if c["claim_status"] == "unsupported"]
    if unsupported:
        missing.append("以下概念的事实未在本次证据快照中定位到原文，已移除量化承诺："
                       + "、".join(unsupported) + "（A06）")

    # A05 / A14：投放国家是工作区默认值，不是从页面语言 / 域名推断出的证据。
    # 页面含价格或试用条款时，一律不生成地区报价，只询问「必要字段」。
    body = " ".join(_facts(a)) + " " + _clean(a.get("type"))
    has_price_terms = bool(_PRICE_RE.search(body))
    pricing_gate = {
        "has_price_terms": has_price_terms,
        "region_source": "workspace_default",
        "region_confirmed": False,
        "price_statement_allowed": False,
        "note": ("页面含价格 / 试用 / 订阅条款；投放地区仅为工作区默认值，"
                 "本计划不展示地区报价，也不推断计费周期（A05 / A14）"
                 if has_price_terms else
                 "页面未见价格 / 试用条款；投放地区仍来自工作区默认值，不从页面语言推断"),
    }
    if has_price_terms:
        missing.append("页面含价格 / 试用条款：只询问必要的投放地区，不猜价格、币种或计费周期（A05）")

    status = "needs_input" if blocking else ("draft_only" if missing else "ready")
    rationale = [
        f"产品与场景：{profile['label']} → {policy['entity_type']}，"
        f"主体使用{asset_label}，不套用无关的人物 / 通勤动作",
        f"证据充分性：可定位原文 {len(snap.valid_ids)} 段；"
        f"{'已定位，商业真实性未审核' if snap.available else '无快照，需重新分析'}",
        f"媒体呈现：所选 {len(plats)} 个平台约 {tasks} 个主要图片任务，"
        f"规则版本 {SPEC_VERSION} 为内部目录，投放前须官方核验",
    ]

    plan_hash = hashlib.sha256(json.dumps(
        {"a": a.get("url"), "p": plats, "b": brief, "d": defaults,
         "e": snap.snapshot_id, "pv": PROFILE_SCHEMA_VERSION, "sv": SPEC_VERSION},
        ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    plan_version = "pv" + hashlib.sha256(json.dumps(
        {"h": plan_hash, "c": concepts, "s": status, "d": defaults},
        ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return {
        "schema_version": PLANNER_VERSION,
        "mode": mode,
        "status": status,
        "recommended_visual_summary": summary,
        "rationale": rationale[:3],
        "missing_inputs": missing + blocking,
        "blocking_reasons": blocking,
        "product_profile": product,
        "visual_brief": brief,
        "structured_concepts": concepts,
        "industry_profile": profile["key"],
        "industry_profile_label": profile["label"],
        "industry_profile_version": profile.get("version") or PROFILE_SCHEMA_VERSION,
        "workspace_defaults": defaults,
        "evidence": {"snapshot_id": snap.snapshot_id, "count": len(snap.valid_ids),
                     "review_status": "locatable_not_reviewed" if snap.available
                     else "legacy_unverified"},
        "coverage_summary": {
            "platforms": plats, "asset_roles": roles, "required_tasks": tasks,
            "spec_verified": bool(SPEC_VERIFIED_ON),
            "spec_version": SPEC_VERSION,
            "estimate_note": "按平台默认版位估算；超过单批 24 任务 / 40MP 时须拆子批，不截断",
        },
        "quality_gate": gate,
        "delivery_grade": gate["delivery_grade"],
        "pricing_gate": pricing_gate,
        "claim_audit": {
            "checked": len(concepts),
            "unsupported": unsupported,
            "must_preserve_qualifiers": concepts[0]["must_preserve_qualifiers"] if concepts else [],
        },
        "plan_id": "cp_" + plan_hash,
        "plan_version": plan_version,
        "plan_hash": plan_hash,
        "note": "推荐描述、结构化概念与 VisualBrief 来自同一对象；规则确定边界，模型只负责既有的落地页理解。"
                "本版产出一律按草案记录，未宣称完成 PromptBundle / 多阶段编排 / 逐图质检 / 官方规格核验。",
    }
