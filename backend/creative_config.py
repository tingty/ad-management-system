"""V4.41 / AI 改造第 3 期：ResolvedCreativeConfig + CreativeConcept + VisualBrief。

说明书 F03 / F04 要求：
- 文案概念必须先确定受众情境、购买阻力、核心承诺、证据和画面，再构建文生图提示词；
- 预设「编辑后的文本」必须完整参与生成，且策略字段与纯视觉字段要有明确作用范围；
- 生成器共用**同一份**解析结果，删除重复映射；保存最终提示词 / 配置 ID / 版本 / 哈希。

本模块是「通用主干」：不假设电商或订阅。行业差异由 `industry_profiles.py` 的
`visual_subject` / `value_axes` / `evidence_types` 提供，只做局部配置。
所有函数均为纯函数，便于用模拟供应商做确定性回归（T05 / T06 / T07）。
"""
from __future__ import annotations

import hashlib
import json
import re

from presets import build_directives, DIRECTION_TO_TEMPLATE

CREATIVE_CONFIG_VERSION = "4.41.1"

# 策略字段：参与文案生成与画面语义，但只是「表达倾向」，不是事实依据。
STRATEGY_FIELDS = ("direction_text", "style_text", "color_text",
                   "extra_prompt", "design_prompt")
# 纯视觉字段：只影响文生图提示词与本地合成，绝不进入文案大模型提示词。
VISUAL_FIELDS = ("styles", "palette", "template", "layout", "layout_hint", "dim_ratio")

# 说明书 F05 要求的五种布局：商品主视觉 / 使用演示 / 细节 / 优惠 / 评价。
LAYOUTS = ("hero", "demo", "detail", "offer", "review")
TEMPLATE_TO_LAYOUT = {
    "bigtype": "hero",
    "scenario": "demo",
    "stat": "detail",
    "rating": "review",
    "promo": "offer",
    "compare": "detail",
    "ugc": "review",
}

LAYOUT_COMPOSITION = {
    "hero": "large hero subject occupying the upper / right area; copy block on the lower-left; "
            "one short accent rule, generous negative space",
    "demo": "upper 55% reserved for a clean real-use demonstration; copy sits on a solid "
            "bottom panel; subject must not be covered by text",
    "detail": "left 45% reserved for an unobstructed close-up detail; copy in a narrow "
              "right column with an accent vertical rule",
    "offer": "centered symmetric composition with an accent top band and a prominent CTA "
             "pill; subject framed behind the copy, not recolored",
    "review": "light card with an accent quote bar on the left; small subject vignette in "
              "the upper-right; restrained, credible, no celebratory clutter",
    "banner": "single horizontal row: headline left, CTA right, logo in its own reserved "
              "box; no element may overlap another",
}

# 不同概念即使没有明显关键词，也必须给出不同的主体动作 / 场景，
# 避免「换文案不换画面」。用概念文本的稳定哈希从池中确定性选取。
_ACTION_POOL = (
    "a person actively demonstrating the product with both hands, clear step-by-step motion",
    "the product in use during a daily commute, candid street-level context and natural movement",
    "a close-up of the product's key mechanism being operated, tactile detail and material texture",
    "a calm side-by-side arrangement showing the product next to its everyday context",
    "a first-person point of view of someone reaching for and using the product",
)
_SETTING_POOL = (
    "bright uncluttered indoor tabletop with soft directional daylight",
    "real urban transit / street environment with natural depth of field",
    "neutral studio surface with gentle shadows and a single light source",
    "authentic home or workspace with believable everyday props",
    "clean outdoor daylight setting with soft background bokeh",
)

_CLEAN_RE = re.compile(r"clean|wash|stain|demo|demonstrat|before|after|清洗|清洁|去污|演示|对比", re.I)
_COMMUTE_RE = re.compile(r"commut|travel|on.the.go|portable|outdoor|pocket|通勤|路上|便携|随身", re.I)
_DETAIL_RE = re.compile(r"spec|material|detail|zoom|close.up|feature|参数|材质|细节|特写", re.I)
_OFFER_RE = re.compile(r"save|off|deal|sale|discount|free|限时|优惠|折扣|免费|立减", re.I)
_REVIEW_RE = re.compile(r"review|rating|testimonial|rated|proven|评价|口碑|评分|用户说", re.I)


def _sha(text: str, n: int = 12) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def _clean(s) -> str:
    return str(s or "").strip()


def resolve_creative_config(style_opts: dict | None, lang: str = "en",
                            overrides: dict | None = None) -> dict:
    """把风格选项解析成**唯一一份** `ResolvedCreativeConfig`。

    文案生成与图片生成都必须消费这份结果；任何调用点都不得再按预设 ID 自行
    重建风格映射（F04：删除重复映射）。返回值是可 JSON 序列化的快照。
    """
    so = dict(style_opts or {})
    direction = _clean(so.get("creative_direction"))
    style = _clean(so.get("content_style"))
    color = _clean(so.get("color_scheme"))
    ov = overrides or {}

    d = build_directives(direction, style, color, lang=lang, overrides=ov)
    design = dict(d.get("design_overrides") or {})

    # 允许显式局部覆盖；仍收口在这份解析结果里，不让调用点自己拼。
    if isinstance(so.get("palette"), dict) and so["palette"]:
        design["palette"] = {**(design.get("palette") or {}), **so["palette"]}
    if isinstance(so.get("styles"), list) and so["styles"]:
        design["styles"] = [_clean(x) for x in so["styles"] if _clean(x)][:3]

    template = _clean(d.get("template"))
    layout_hint = TEMPLATE_TO_LAYOUT.get(template, "")
    layout = _clean(so.get("layout"))
    if layout not in LAYOUTS:
        layout = ""
    try:
        dim_ratio = float(so.get("dim_ratio", 0.28))
    except (TypeError, ValueError):
        dim_ratio = 0.28
    dim_ratio = max(0.05, min(0.60, dim_ratio))

    custom = [pid for pid in (direction, style, color)
              if pid and _clean(ov.get(pid))]
    strategy = {k: _clean(d.get(k)) for k in STRATEGY_FIELDS}
    visual = {
        "styles": list(design.get("styles") or []),
        "palette": dict(design.get("palette") or {}),
        "template": template,
        "layout": layout,
        "layout_hint": layout_hint,
        "dim_ratio": dim_ratio,
    }

    payload = {
        "version": CREATIVE_CONFIG_VERSION,
        "lang": lang,
        "preset_ids": {"direction": direction, "style": style, "color": color},
        "custom_fields": custom,
        "strategy": strategy,
        "visual": visual,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        **payload,
        "config_id": "cc_" + digest[:12],
        "hash": digest,
        "scope": {
            "strategy": "参与文案与画面语义，仅作表达倾向；不得覆盖落地页事实，不得编造数字 / 折扣 / 背书",
            "visual": "只作用于文生图提示词与本地合成（风格 / 调色板 / 版式 / 遮罩），不进入文案大模型提示词",
            "snapshot": "每次生成把 config_id / version / hash / 最终提示词哈希写入图片与素材历史，后续修改预设不覆盖历史快照",
        },
    }


def strategy_block(config: dict) -> str:
    """F04：把编辑后的预设文本注入文案生成，且明确它只是表达倾向。"""
    s = (config or {}).get("strategy") or {}
    parts = []
    for label, key in (("创意方向", "direction_text"), ("内容风格", "style_text"),
                       ("配色语气", "color_text")):
        v = _clean(s.get(key))
        if v:
            parts.append(f"{label}：{v}")
    if not parts:
        return ""
    return ("【创意表达倾向 · 非事实依据】" + "；".join(parts)
            + "。仅用于调整语气、视角与措辞；不得据此编造商品事实、价格、条款或效果数据，"
              "且不得改变要求的 JSON 字段结构与字数上限。")


def visual_text_block(config: dict) -> str:
    """F04：把编辑后的全部预设文本注入文生图提示词（T06 的唯一标记必须出现在这里）。"""
    s = (config or {}).get("strategy") or {}
    parts = []
    for label, key in (("创意方向原文", "direction_text"), ("内容风格原文", "style_text"),
                       ("配色原文", "color_text"), ("设计规范原文", "design_prompt")):
        v = _clean(s.get(key))
        if v:
            parts.append(f"{label}: {v}")
    return "；".join(parts)


def build_concept(variant: dict, index: int, analysis: dict, profile: dict) -> dict:
    """F03：由用户勾选的一条文案组合构造 `CreativeConcept`。

    不调用大模型、不编造事实：受众来自落地页分析，购买阻力只从文案里显式出现
    的限定词推断，缺证据时明确写「未明示」。
    """
    v = variant if isinstance(variant, dict) else {}
    headline = _clean(v.get("headline"))
    sub = _clean(v.get("sub"))
    cta = _clean(v.get("cta"))
    text = " ".join(x for x in (headline, sub, cta) if x)
    audience = _clean((analysis or {}).get("audience"))
    barriers = re.findall(
        r"(?i)\b(?:no|not|never|without|risk|concern|worry|cancel|refund|"
        r"expensive|slow|hard|difficult|limited|only)\b|退款|退货|担心|顾虑|麻烦|太贵|限时",
        text)
    friction = ("、".join(sorted({b.lower() for b in barriers}))[:120]
                if barriers else "文案未明示购买阻力（不虚构）")
    key = _sha("|".join((headline, sub, cta)))
    return {
        "concept_id": _clean(v.get("concept_id")) or f"C{index + 1}",
        "concept_key": "ck_" + key,
        "label": _clean(v.get("label")) or f"组合 {index + 1}",
        "audience_scenario": audience or "落地页未标注受众（不虚构）",
        "purchase_friction": friction,
        "core_promise": headline or sub or "（用户未选定可用文案）",
        "evidence": sub or "（该概念未提供证据副标）",
        "cta": cta,
        "industry_profile": _clean((profile or {}).get("key")),
    }


def choose_layout(concept: dict, config: dict, w: int, h: int) -> str:
    """F05：按版位几何 + 内容需求选布局，而不是所有图共用一套。

    同一概念跨尺寸时布局可因比例变化，但 `core_promise` / `evidence` 不变（T05）。
    """
    w, h = int(w or 1080), int(h or 1080)
    if h <= 120 or w / h > 4:
        return "banner"
    explicit = _clean((config or {}).get("visual", {}).get("layout"))
    if explicit in LAYOUTS:
        return explicit
    text = " ".join((_clean(concept.get("core_promise")),
                     _clean(concept.get("evidence")), _clean(concept.get("cta"))))
    if _OFFER_RE.search(text):
        return "offer"
    if _REVIEW_RE.search(text):
        return "review"
    if _CLEAN_RE.search(text) or _COMMUTE_RE.search(text):
        return "demo"
    if _DETAIL_RE.search(text):
        return "detail"
    hint = _clean((config or {}).get("visual", {}).get("layout_hint"))
    return hint if hint in LAYOUTS else "hero"


def _pick(pool: tuple[str, ...], seed: str) -> str:
    return pool[int(seed, 16) % len(pool)]


def build_visual_brief(concept: dict, analysis: dict, profile: dict,
                       config: dict, w: int, h: int,
                       placement: str = "", ad_product: str = "") -> dict:
    """F03：把创意概念翻译成可被文生图供应商与本地合成共同消费的 `VisualBrief`。"""
    text = " ".join((_clean(concept.get("core_promise")), _clean(concept.get("evidence"))))
    seed = _sha(text or concept.get("concept_key") or "generic", 16)
    # 场景词优先于动作词：「Commute portable cleaning」是通勤场景，
    # 不能因为含 cleaning 就被判成清洗演示，否则两个概念仍会得到同一画面。
    if _COMMUTE_RE.search(text):
        action, setting = _ACTION_POOL[1], _SETTING_POOL[1]
    elif _CLEAN_RE.search(text):
        action, setting = _ACTION_POOL[0], _SETTING_POOL[0]
    elif _DETAIL_RE.search(text):
        action, setting = _ACTION_POOL[2], _SETTING_POOL[2]
    else:
        action, setting = _pick(_ACTION_POOL, seed), _pick(_SETTING_POOL, seed)

    layout = choose_layout(concept, config, w, h)
    pal = ((config or {}).get("visual") or {}).get("palette") or {}
    return {
        "concept_id": concept.get("concept_id", ""),
        "concept_key": concept.get("concept_key", ""),
        "layout": layout,
        "aspect": f"{int(w)}x{int(h)}",
        "placement": placement,
        "ad_product": ad_product,
        "subject": _clean((profile or {}).get("visual_subject")) or "与页面真实内容一致的中性主视觉",
        "action": action,
        "setting": setting,
        "composition": LAYOUT_COMPOSITION[layout],
        "core_promise": concept.get("core_promise", ""),
        "evidence": concept.get("evidence", ""),
        "audience_scenario": concept.get("audience_scenario", ""),
        "purchase_friction": concept.get("purchase_friction", ""),
        "palette": {"accent": pal.get("accent", ""), "bg1": pal.get("bg1", ""),
                    "light": bool(pal.get("light"))},
        "dim_ratio": ((config or {}).get("visual") or {}).get("dim_ratio", 0.28),
        "facts_boundary": "不得虚构商品外观、标签、规格、价格、评价与效果数据；"
                          "不得出现任何文字、字母、数字、Logo、水印与 UI 控件",
        "reference_mode": "none",
        "capability_note": "",
    }


def brief_prompt_block(brief: dict) -> str:
    """把 VisualBrief 渲染成文生图提示词段落。概念不同 → 段落字面不同（T05）。"""
    b = brief or {}
    lines = [
        "[VisualBrief / F03] concept_id=%s concept_key=%s layout=%s aspect=%s"
        % (b.get("concept_id", ""), b.get("concept_key", ""),
           b.get("layout", ""), b.get("aspect", "")),
        "Audience scenario: %s. Purchase friction: %s."
        % (b.get("audience_scenario", ""), b.get("purchase_friction", "")),
        "Core promise to visualise: %s" % b.get("core_promise", ""),
        "Evidence cue (only what the copy states): %s" % b.get("evidence", ""),
        "Subject: %s" % b.get("subject", ""),
        "Action: %s" % b.get("action", ""),
        "Setting: %s" % b.get("setting", ""),
        "Composition: %s" % b.get("composition", ""),
        "Facts boundary: %s" % b.get("facts_boundary", ""),
    ]
    return "\n".join(x for x in lines if x.strip())


def prompt_hash(prompt: str) -> str:
    """F04：把「实际发给供应商的最终提示词」记成哈希，随图片与历史归档。"""
    return _sha(prompt or "", 16)


def config_snapshot(config: dict) -> dict:
    """写进每张图片与素材历史的精简、稳定、不可被后续预设修改覆盖的快照。"""
    c = config or {}
    return {
        "config_id": c.get("config_id", ""),
        "version": c.get("version", ""),
        "hash": c.get("hash", ""),
        "preset_ids": dict(c.get("preset_ids") or {}),
        "custom_fields": list(c.get("custom_fields") or []),
        "visual": {
            "layout": _clean((c.get("visual") or {}).get("layout")),
            "template": _clean((c.get("visual") or {}).get("template")),
            "palette_accent": _clean(((c.get("visual") or {}).get("palette") or {}).get("accent")),
        },
    }
