"""V4.98「提示词管理」：三类通用提示词模板 + 六层心理链条 + 变量来源。

设计约束（需求硬要求）
----------------------
1. 三类提示词：文案 / 图片 / 视频，每类一条通用中文模板。
2. 「想表达什么」= intent，一句话意图概括。
3. 心理链条六层可多选；可按产品分析自动匹配，也可全选六层。
4. 模板变量**严格取自系统真实生成逻辑的变量名**，不凭空产生：
   - 文案：services.MEDIA_COPY_SYS / MEDIA_CONTEXT_SYS + media_ad.compose_copy_prompt 的
     [[PLATFORM]] [[LANGUAGE]] [[SCHEMA]] [[LIMITS]] [[CREATIVE]] [[CONTEXT]]；
   - 图片：media_ad._media_image_prompt 的 variables 字典
     [[INDUSTRY]] [[SITE_TYPE]] [[AUDIENCE]] [[STRENGTHS]] [[COMPETITORS]]
     [[PLATFORM]] [[MOOD]] [[STYLE]] [[PALETTE]] [[BRAND_CONTEXT]]；
   - 视频：routers._cw_video_request_build 真实消费的字段
     PRODUCT / PROMOTION_GOAL / SELLING_POINTS / DURATION / ASPECT / SHOTS /
     EVIDENCE_CONTEXT / PROMPT_HINT（视频链路为结构化拼装，此处以 [[VAR]] 表达同一批字段）。

三条模板注册进 PROMPT_REGISTRY（module=提示词管理），走既有的编辑 / 保存即生效机制；
它们是「管理 / 沉淀 / 复制」用的通用模板，不替换现有生成链路的提示词（不改既有出图出片行为）。
"""
from __future__ import annotations

# ----------------------------- 六层心理链条 -----------------------------
LAYER_ORDER = ["pain", "desire", "proof", "attribution", "decision", "cta"]

PSYCHOLOGICAL_LAYERS: list[dict] = [
    {"key": "pain", "label": "痛点识别", "desc": "先点出用户未被满足的现状或代价，让受众认出「这是我」"},
    {"key": "desire", "label": "渴望激发", "desc": "描绘理想结果并命名渴望，把用户带向「我想要」"},
    {"key": "proof", "label": "可信证据", "desc": "用对比、事实或数据证明结果真实，让落差本身说话"},
    {"key": "attribution", "label": "能力归因", "desc": "把结果归因到产品的具体能力，完成从心动到可信的一跳"},
    {"key": "decision", "label": "决策降本", "desc": "用卖点清单、规则或适用场景压缩决策成本"},
    {"key": "cta", "label": "行动收口", "desc": "用明确的低风险行动（免费 / 试用 / 立即）收口转化"},
]
LAYER_LABEL = {x["key"]: x["label"] for x in PSYCHOLOGICAL_LAYERS}

# ----------------------------- 三类提示词 -----------------------------
PROMPT_TYPES: list[dict] = [
    {"key": "copy", "label": "文案提示词", "desc": "驱动广告文案生成：字段结构、字数红线、语言与创意倾向"},
    {"key": "image", "label": "图片提示词", "desc": "驱动文生图背景：行业、人群、卖点、风格、配色与品牌上下文"},
    {"key": "video", "label": "视频提示词", "desc": "驱动分镜与出片：产品、目标、卖点、时长比例、分镜与证据契约"},
]
TYPE_LABEL = {x["key"]: x["label"] for x in PROMPT_TYPES}

# ----------------------------- 变量来源（严格对应真实生成逻辑） -----------------------------
VARIABLE_SOURCES: dict[str, dict[str, str]] = {
    "copy": {
        "CONTEXT": "落地页分析结论（media_ad._analysis_context → media_context 模板）",
        "PLATFORM": "目标媒体平台（get_media_platform / copy_schema_for）",
        "LANGUAGE": "生成语言（LANG_NAME，来自 lang 入参）",
        "SCHEMA": "字段结构说明（media_ad.copy_schema_for，按平台 / 广告产品）",
        "LIMITS": "字数红线（媒体平台 copy_limits，按 schema 展开）",
        "CREATIVE": "创意表达倾向（ResolvedCreativeConfig.strategy 的预设文本）",
    },
    "image": {
        "INDUSTRY": "所属行业（analysis.industry）",
        "SITE_TYPE": "网站 / 站点类型（analysis.type，缺省回退行业）",
        "AUDIENCE": "目标人群（analysis.audience）",
        "STRENGTHS": "核心优势（analysis.advantages，取前 3 条）",
        "COMPETITORS": "主要竞品（analysis.competitors，取前 3 条）",
        "PLATFORM": "目标媒体平台（platform 入参）",
        "MOOD": "创意方向情绪（DIRECTION_MOOD，按 direction 预设）",
        "STYLE": "视觉风格（presets.style_visual，取前 3 个风格键）",
        "PALETTE": "配色描述（presets.palette_prompt，按 visual.palette）",
        "BRAND_CONTEXT": "品牌上下文（行业画像价值维度 + 卖点 / 受众 / 竞品）",
    },
    "video": {
        "PRODUCT": "产品名称（analysis.product 或 analysis.title）",
        "PROMOTION_GOAL": "推广目标（brief.promotionGoal）",
        "SELLING_POINTS": "核心卖点（brief.sellingPoints，取前 3 条）",
        "DURATION": "视频时长秒数（plan.duration_sec 或 options.duration，缺省 15）",
        "ASPECT": "输出比例（plan.aspect 或 options.aspect，缺省 9:16）",
        "SHOTS": "分镜序列（plan.shots：时间点 + 画面 + 旁白）",
        "EVIDENCE_CONTEXT": "事实证据与限定契约（video_claims.video_evidence_context）",
        "PROMPT_HINT": "用户补充要求（options.prompt_hint，仅调节表达）",
    },
}

# ----------------------------- 中文通用模板（带真实变量） -----------------------------
COPY_TEMPLATE_CN = (
    "你是海外效果广告资深文案。请只依据【[[CONTEXT]]】中真实出现的分析结论，"
    "为媒体平台【[[PLATFORM]]】撰写可直接投放的广告文案。\n"
    "输出语言：[[LANGUAGE]]；字段结构（key 必须完全匹配，多值字段用数组）：[[SCHEMA]]；\n"
    "字数红线（超限会被平台拒投）：[[LIMITS]]。\n"
    "表达倾向：[[CREATIVE]]。\n"
    "硬性要求：只输出 JSON、不要解释；不得编造分析结论之外的数字、折扣、倒计时、奖项与背书；"
    "文案须按所勾选的心理链条组织（痛点 → 渴望 → 证据 → 能力 → 决策 → 行动）。"
)

IMAGE_TEMPLATE_CN = (
    "为【[[SITE_TYPE]]】生成一张广告背景视觉，行业为【[[INDUSTRY]]】，目标人群【[[AUDIENCE]]】。\n"
    "核心优势【[[STRENGTHS]]】；主要竞品【[[COMPETITORS]]】；投放平台【[[PLATFORM]]】。\n"
    "情绪基调【[[MOOD]]】；视觉风格【[[STYLE]]】；配色【[[PALETTE]]】；品牌上下文【[[BRAND_CONTEXT]]】。\n"
    "硬性要求：画面内不出现任何文字、字母、数字、Logo、水印与 UI 控件，保留干净负空间供后期叠加文案；"
    "不编造页面未呈现的事实；按所勾选的心理链条安排视觉证据。"
)

VIDEO_TEMPLATE_CN = (
    "你是出海效果广告视频创意导演。产品【[[PRODUCT]]】，推广目标【[[PROMOTION_GOAL]]】，"
    "核心卖点【[[SELLING_POINTS]]】。\n"
    "成片时长【[[DURATION]]】秒，输出比例【[[ASPECT]]】；分镜【[[SHOTS]]】。\n"
    "事实证据与限定契约【[[EVIDENCE_CONTEXT]]】；补充要求【[[PROMPT_HINT]]】。\n"
    "硬性要求：按钩子 → 真实功能 → 可信支撑 → 品牌收口组织镜头；画面零文字，字幕 / 旁白仅用于策划与配音；"
    "任何数字与承诺必须能在证据契约中定位，不编造；品牌字样不在画面绘制，由后期叠加。"
)

MODULE = "提示词管理"
# V4.100：旧模块名仅作查询兼容（老缓存 / 外部按旧名筛选仍能取到同一批模板），
# 新数据与新菜单统一使用 MODULE；模板按 key 存储与更新，改名不丢用户已保存内容。
LEGACY_MODULE = "素材提示管理"

MATERIAL_PROMPTS: list[dict] = [
    {
        "key": "material_prompt_copy", "name": "文案提示词 · 通用模板", "module": MODULE,
        "category": "文案提示词", "func_type": "copy", "usage_type": "system",
        "intent": "用真实落地页结论和平台规则，生成可直接投放、字段与字数都合规的广告文案。",
        "psychological_layers": "desire,proof,attribution,decision,cta",
        "description": "V4.98 通用中文模板；变量严格对应文案生成链路。可编辑，保存后在「提示词管理」生效。",
        "content": COPY_TEMPLATE_CN,
    },
    {
        "key": "material_prompt_image", "name": "图片提示词 · 通用模板", "module": MODULE,
        "category": "图片提示词", "func_type": "image", "usage_type": "system",
        "intent": "按产品分析与平台规格生成零文字、可叠加文案的广告背景视觉，用画面呈现产品价值。",
        "psychological_layers": "pain,desire,proof,attribution",
        "description": "V4.98 通用中文模板；变量严格对应文生图链路。可编辑，保存后在「提示词管理」生效。",
        "content": IMAGE_TEMPLATE_CN,
    },
    {
        "key": "material_prompt_video", "name": "视频提示词 · 通用模板", "module": MODULE,
        "category": "视频提示词", "func_type": "video", "usage_type": "system",
        "intent": "把分镜与证据契约编译成可直接出片的提示词，确保有真实动态、零画面文字与合规承诺。",
        "psychological_layers": "pain,desire,proof,cta",
        "description": "V4.98 通用中文模板；变量对应视频请求构建函数的真实字段。可编辑，保存后在「提示词管理」生效。",
        "content": VIDEO_TEMPLATE_CN,
    },
]


def material_prompt_entries() -> list[dict]:
    """供 services.PROMPT_REGISTRY 合入；返回副本避免调用方改动模块常量。"""
    return [dict(x) for x in MATERIAL_PROMPTS]


def variables_of(ptype: str) -> list[dict]:
    """某类提示词用到的变量 + 来源说明（按模板出现顺序）。"""
    src = VARIABLE_SOURCES.get(ptype, {})
    entry = next((x for x in MATERIAL_PROMPTS if x["func_type"] == ptype), None)
    names = []
    if entry:
        import re
        names = re.findall(r"\[\[([A-Z_]+)\]\]", entry["content"])
    out, seen = [], set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append({"name": n, "source": src.get(n, "未登记来源")})
    return out


def _truthy(v) -> bool:
    if isinstance(v, str):
        return bool(v.strip())
    return bool(v)


def auto_match_layers(analysis: dict | None) -> dict:
    """按产品分析内容自动匹配心理链条覆盖层（启发式，用户可再手动全选）。

    规则来源：分析结论里真实存在的字段（advantages / competitors / audience /
    channels / evidence），不臆造痛点字段；效果广告一律保留「行动收口」。
    """
    a = analysis or {}
    if isinstance(a.get("analysis"), dict):
        a = a.get("analysis") or {}
    matched: set[str] = set()
    if _truthy(a.get("competitors")):
        matched.add("pain")            # 有竞品 → 需要痛点对比才有差异
    if _truthy(a.get("audience")):
        matched.add("desire")          # 有人群画像 → 可描绘其向往
    if _truthy(a.get("advantages")):
        matched.add("proof")           # 有卖点 → 可作事实证据
        matched.add("attribution")     # 卖点同时是能力归因
    if _truthy(a.get("channels")):
        matched.add("decision")        # 有推广途径 → 可降决策成本
    matched.add("cta")                 # 效果广告必有行动收口
    keys = [k for k in LAYER_ORDER if k in matched]
    return {"layers": keys, "labels": [LAYER_LABEL[k] for k in keys],
            "reason": "基于分析结论中已存在的字段自动匹配；可手动调整为全部六层。"}
