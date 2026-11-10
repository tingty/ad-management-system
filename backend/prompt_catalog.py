"""
V4.35「素材提示词」单一数据源：统一目录 + 分类维度 + 优秀提示词总结库。

改造前的问题：素材创作涉及的提示词散落在 4 处，且「素材提示词」页只展示 5 条：
  1. services.py PROMPT_REGISTRY —— 系统提示词（仅 5 条落地页分析被展示）；
  2. presets.py —— 三大预设库 62 条提示词片段，页面完全看不到；
  3. media_ad.py —— 「广告推广文案 / 推广图片 / 分析结论注入」提示词硬编码，不可管理；
  4. media_ad.py _media_image_prompt —— 文生图提示词硬编码，不可管理。

本模块提供：
  - FUNC_TYPES / USAGE_TYPES：需求 2 的「功能类型 / 使用类型」两套分类维度；
  - PROMPT_META：给既有提示词逐条打标，不改其内容；
  - EXTRA_PROMPTS：把 media_ad.py 硬编码的 3 条提示词抽成可编辑模板（含安全占位符）；
  - preset_prompt_entries()：把三大预设库 62 条纳入统一目录，支持编辑并回写生效；
  - BEST_PRACTICES：需求 3 的「提示词总结库」，按 类型 / 风格 / 场景 / 覆盖对象 四维标签筛选，
    可一键「设为系统默认」——默认内容写入 prompt_configs，经 get_prompt 直接进入生成链路。

占位符语法统一为 [[NAME]]（不用 str.format，避免提示词正文里的 JSON 花括号被误解析）。
"""
from __future__ import annotations

import re
from typing import Optional

from presets import CREATIVE_DIRECTIONS, CONTENT_STYLES, COLOR_SCHEMES


# ===========================================================================
# 一、分类维度（需求 2：按功能类型、使用类型分门别类）
# ===========================================================================

FUNC_TYPES: list[dict] = [
    {"key": "landing", "label": "落地页分析", "desc": "解析落地页 URL / 正文，产出 8 字段与九要素结构化结论，是后续所有生成的依据"},
    {"key": "ad_copy", "label": "广告推广文案", "desc": "直接决定最终投放文案：主提示词、分析结论注入、总结库默认模板"},
    {"key": "ad_image", "label": "广告推广图片", "desc": "直接决定最终推广图片：视觉设计指导、文生图背景提示词、总结库默认模板"},
    {"key": "creative_direction", "label": "创意方向库", "desc": "D01–D20 创意母题，影响文案调性与画面叙事/构图"},
    {"key": "content_style", "label": "内容风格库", "desc": "S01–S26 美术风格，决定背景质感与视觉语言"},
    {"key": "color_scheme", "label": "配色方案库", "desc": "C01–C16 配色，映射到渲染调色板与文生图色彩描述"},
]

USAGE_TYPES: list[dict] = [
    {"key": "system", "label": "系统提示词", "desc": "设定模型角色、任务与输出结构，直接影响生成质量"},
    {"key": "user", "label": "用户提示词", "desc": "运行时动态拼接的输入（分析结论、平台、语言等）"},
    {"key": "constraint", "label": "输出约束", "desc": "字段口径、字数红线、合规与禁止编造等硬性规则"},
    {"key": "fragment", "label": "提示词片段", "desc": "可组合注入的短指令，由用户选择后叠加到生成链路"},
    {"key": "directive", "label": "生成指令", "desc": "驱动版式、背景风格、调色板等落地参数的指令"},
]

FUNC_LABEL = {x["key"]: x["label"] for x in FUNC_TYPES}
USAGE_LABEL = {x["key"]: x["label"] for x in USAGE_TYPES}
PRESET_FUNCS = {"creative_direction", "content_style", "color_scheme"}


# ===========================================================================
# 二、既有提示词的分类元数据（需求 2：不改变内容，只补齐标签）
# ===========================================================================

PROMPT_META: dict[str, dict] = {
    # V4.37：site_analysis / angle / copy / video / image 只服务于已下线的「素材管理」，
    # 随模块一起移除，避免目录里出现不可生效的失效提示词。
    "landing_framework":  {"func_type": "landing",   "usage_type": "system",     "category": "分析框架"},
    "landing_basic":      {"func_type": "landing",   "usage_type": "constraint", "category": "基础识别"},
    "landing_competitors": {"func_type": "landing",  "usage_type": "constraint", "category": "竞争分析"},
    "landing_advantages": {"func_type": "landing",   "usage_type": "constraint", "category": "价值提炼"},
    "landing_channels":   {"func_type": "landing",   "usage_type": "constraint", "category": "增长推广"},
}


# ===========================================================================
# 三、从 media_ad.py 抽出的 3 条可管理提示词（需求 1 + 需求 3 的落地基础）
# ===========================================================================

MEDIA_MODULE = "素材创作（营销推广设置）"

MEDIA_COPY_SYS = (
    "你是一名海外效果广告资深文案。必须依据下方「落地页分析结论」为媒体平台【[[PLATFORM]]】"
    "撰写可直接投放的广告文案。\n"
    "只输出 JSON、不要任何解释或 markdown。COPY_JSON\n"
    "字段结构（key 必须完全匹配，count>1 的字段用字符串数组）：[[SCHEMA]]\n"
    "字数红线（务必遵守，超长会被平台拒投）：[[LIMITS]]\n"
    "语言要求：用 [[LANGUAGE]] 撰写，语气贴合平台与目标人群。\n"
    "[[CREATIVE]]"
)

MEDIA_CONTEXT_SYS = (
    "以下是「落地页分析结论」，是本次文案与图片唯一的事实依据：\n"
    "[[CONTEXT]]\n"
    "请基于以上真实分析结论，为媒体平台【[[PLATFORM]]】撰写贴合其版位与受众调性的广告文案，"
    "不得编造页面未呈现的事实。"
)

MEDIA_IMAGE_SYS = (
    "High-quality advertising background visual for a [[SITE_TYPE]] in the [[INDUSTRY]] market.\n"
    "No text, no logo, no letters, no watermark, no UI; clean negative space for overlaid ad copy.\n"
    "[[MOOD]]\n"
    "Visual style: [[STYLE]].\n"
    "[[PALETTE]]\n"
    "[[BRAND_CONTEXT]]\n"
    "Photorealistic or illustrative, consistent with the described style, high detail, "
    "professional advertising quality."
)

# 输出契约：当「总结库」模板没有内嵌结构占位符时，系统自动追加，保证字段/字数/语言/合规底线不丢失。
COPY_OUTPUT_CONTRACT = (
    "【输出契约 · 系统强制】只输出 JSON，不要任何解释或 markdown，结尾标记 COPY_JSON。\n"
    "字段结构（key 必须完全匹配，count>1 的字段用字符串数组）：[[SCHEMA]]\n"
    "字数红线（超长会被平台拒投）：[[LIMITS]]\n"
    "语言要求：用 [[LANGUAGE]] 撰写，为媒体平台【[[PLATFORM]]】贴合其版位与受众调性。\n"
    "事实约束：仅使用上方落地页分析结论中真实出现的信息，禁止编造数字、折扣、倒计时、奖项与背书。"
)

IMAGE_OUTPUT_CONTRACT = (
    "No text, no letters, no numbers, no logo, no watermark, no price tag, no UI controls in the image; "
    "keep generous clean negative space for overlaid ad copy.\n"
    "【输出契约 · 系统强制】画面内禁止出现任何文字、字母、数字、logo、水印、价格标签与 UI 控件；"
    "保留足够干净负空间以叠加广告文案。\n"
    "High-quality advertising background visual for a [[SITE_TYPE]] in the [[INDUSTRY]] market.\n"
    "[[MOOD]] Visual style: [[STYLE]]. [[PALETTE]]\n"
    "[[BRAND_CONTEXT]]\n"
    "Professional advertising quality, high detail, consistent with the described style."
)

EXTRA_PROMPTS: list[dict] = [
    {
        "key": "media_copy_sys",
        "name": "广告推广文案 · 主提示词",
        "module": MEDIA_MODULE,
        "category": "推广文案生成",
        "description": (
            "「营销推广设置 → 生成广告文案」的系统提示词，直接决定最终投放文案质量。"
            "可用 [[SCHEMA]] / [[LIMITS]] / [[LANGUAGE]] / [[PLATFORM]] 占位符；"
            "若从总结库选择模板（不含占位符），系统会自动追加输出契约块。"
        ),
        "content": MEDIA_COPY_SYS,
        "func_type": "ad_copy", "usage_type": "system",
    },
    {
        "key": "media_context",
        "name": "广告推广文案 · 分析结论注入",
        "module": MEDIA_MODULE,
        "category": "推广文案生成",
        "description": (
            "把落地页 8 字段分析结论拼成用户提示词的模板，是文案/图片唯一的事实依据。"
            "可用 [[CONTEXT]] / [[PLATFORM]] 占位符。"
        ),
        "content": MEDIA_CONTEXT_SYS,
        "func_type": "ad_copy", "usage_type": "user",
    },
    {
        "key": "media_image_sys",
        "name": "广告推广图片 · 文生图背景提示词",
        "module": MEDIA_MODULE,
        "category": "推广图片生成",
        "description": (
            "「生成推广图片」时发给文生图大模型的背景提示词，直接决定最终图片观感。"
            "可用 [[INDUSTRY]] / [[SITE_TYPE]] / [[MOOD]] / [[STYLE]] / [[PALETTE]] / "
            "[[BRAND_CONTEXT]] 占位符；总结库模板会自动追加输出契约块。"
        ),
        "content": MEDIA_IMAGE_SYS,
        "func_type": "ad_image", "usage_type": "system",
    },
]


def render_prompt(template: str, variables: dict) -> str:
    """安全替换 [[NAME]] 占位符；未提供的占位符清空（不会把花括号当格式串解析）。"""
    out = template or ""
    for key, value in (variables or {}).items():
        out = out.replace("[[%s]]" % key, "" if value is None else str(value))
    out = re.sub(r"\[\[[A-Z_]+\]\]", "", out)
    # 去掉因空占位符产生的多余空行，保持提示词整洁
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def compose_copy_prompt(template: str, *, schema: str, limits: str,
                        language: str, platform: str, creative: str = "") -> str:
    """文案系统提示词 = 目录模板 / 总结库模板 + 系统强制输出契约 + 创意表达倾向。

    V4.41 / F04：`creative` 是 `ResolvedCreativeConfig.strategy` 解析出的预设文本，
    只作为表达倾向参与文案生成；纯视觉字段（调色板 / 版式 / 背景键）不进入这里。
    旧模板或用户在「素材提示词」里保存的自定义模板可能没有 `[[CREATIVE]]` 占位符，
    此时统一追加，保证编辑过的预设一定生效（说明书 T06）。
    """
    tpl = template or ""
    variables = {"SCHEMA": schema, "LIMITS": limits,
                 "LANGUAGE": language, "PLATFORM": platform,
                 "CREATIVE": creative or ""}
    has_contract = "[[SCHEMA]]" in tpl
    body = render_prompt(tpl, variables)
    if not has_contract:
        body += "\n" + render_prompt(COPY_OUTPUT_CONTRACT, variables)
    if creative and "[[CREATIVE]]" not in tpl:
        body += "\n" + creative
    return body


def compose_image_prompt(template: str, variables: dict) -> str:
    """文生图提示词 = 目录模板 / 总结库模板 + 系统强制输出契约。"""
    has_contract = "[[STYLE]]" in (template or "") and "[[MOOD]]" in (template or "")
    body = render_prompt(template, variables)
    if not has_contract:
        contract = render_prompt(IMAGE_OUTPUT_CONTRACT, variables)
        # 模板里的英文片段与契约之间留一行
        body = (body + "\n" + contract).strip() if body else contract
    return body


# ===========================================================================
# 四、三大预设库纳入统一目录（62 条提示词片段，可编辑并回写生效）
# ===========================================================================

PRESET_LIBS: list[tuple[str, str, list[dict]]] = [
    ("creative_direction", "创意方向库（D）", CREATIVE_DIRECTIONS),
    ("content_style", "内容风格库（S）", CONTENT_STYLES),
    ("color_scheme", "配色方案库（C）", COLOR_SCHEMES),
]


def preset_prompt_entries() -> list[dict]:
    """把 D/S/C 三个库展开成与 PROMPT_REGISTRY 同结构的目录条目。

    key 采用 preset_<编号>（如 preset_D01），与 load_preset_overrides 的读取键一致，
    因此页面上的编辑会直接覆盖 presets.build_directives 使用的 prompt 文本。
    """
    out: list[dict] = []
    for func_key, lib_label, items in PRESET_LIBS:
        for item in items:
            out.append({
                "key": "preset_" + item["id"],
                "name": "%s · %s" % (item["id"], item["name"]),
                "module": "素材创作（创意预设库）",
                "category": lib_label,
                "description": "%s｜适用：%s" % (item["desc"], item["applies"]),
                "content": item["prompt"],
                "func_type": func_key,
                "usage_type": "fragment",
            })
    return out


def load_preset_overrides(db) -> dict[str, str]:
    """读取管理员在「素材提示词」里编辑过的预设片段，供 build_directives 覆盖使用。"""
    try:
        from models import PromptConfig
        rows = (db.query(PromptConfig)
                .filter(PromptConfig.key.like("preset_%"), PromptConfig.is_active == True)
                .all())
        return {r.key[len("preset_"):]: r.content for r in rows if (r.content or "").strip()}
    except Exception:
        return {}


# ===========================================================================
# 五、优秀提示词总结库（需求 3）
# ===========================================================================

KINDS: list[dict] = [
    {"key": "ad_copy", "label": "广告推广文案", "target_key": "media_copy_sys",
     "desc": "决定最终投放文案的角色设定、方法论、写作准则与合规边界"},
    {"key": "ad_image", "label": "广告推广图片", "target_key": "media_image_sys",
     "desc": "决定文生图背景的构图、光影、主体、风格与禁忌"},
]

LIBRARY_DIMENSIONS: dict[str, list[str]] = {
    "type": ["转化导向", "痛点唤醒", "价值证明", "促销刺激", "情感共鸣", "场景沉浸", "产品展示", "品牌叙事"],
    "style": ["简洁直给", "故事叙事", "数据理性", "情绪张力", "高级克制", "活泼潮流", "权威专业", "写实自然"],
    "scene": ["信息流广告", "应用商店", "搜索广告", "大促节点", "新品上市", "再营销", "品牌曝光", "视频前贴"],
    "audience": ["toC 大众消费者", "Z 世代", "女性消费人群", "企业决策者", "广告主与渠道(toB)",
             "技术开发者", "游戏玩家", "新兴市场用户"],
}

DIM_LABEL = {"type": "提示词类型", "style": "风格调性", "scene": "投放场景", "audience": "覆盖对象"}


def _bp(ident, kind, name, typ, style, scene, audience, platforms, source, summary, content, tags):
    return {
        "id": ident, "kind": kind, "name": name,
        "type": typ, "style": style, "scene": scene, "audience": audience,
        "platforms": platforms, "source": source, "summary": summary,
        "content": content, "tags": tags,
    }


BEST_PRACTICES: list[dict] = [
    # ----------------------------- 广告推广文案（10） -----------------------------
    _bp("copy_aida", "ad_copy", "AIDA · 注意力→兴趣→欲望→行动", "转化导向", "简洁直给", "信息流广告", "toC 大众消费者",
        ["Facebook", "TikTok", "Google", "AppLovin"],
        "AIDA 模型（E. St. Elmo Lewis）／直效响应文案通用框架",
        "最经典的转化骨架：先打断滑动，再把卖点翻译成用户收益，最后给低门槛行动指令。适合通用品类与冷启动。",
        "你是一名资深效果广告文案，严格遵循 AIDA 模型撰写可直接投放的广告文案。\n"
        "【任务】仅依据下方「落地页分析结论」中的真实事实，为指定媒体平台产出结构化文案字段。\n"
        "【A · Attention】主文案/标题首句用与产品真实卖点强相关的钩子打断滑动；禁止「你是否还在…」「你知道吗」这类空泛开场。\n"
        "【I · Interest】用一句具体、可感知的场景或差异点承接，让目标人群立刻明白「这和我有关」。\n"
        "【D · Desire】把产品优势翻译成用户收益（省时间／省钱／更低风险／更高转化），只使用落地页中真实出现的数字与背书。\n"
        "【A · Action】CTA 用明确动词 + 低门槛动作，制造合理但不虚构的紧迫感。\n"
        "【写作准则】每条字段独立成立、可单独投放；短句优先，避免形容词堆砌；不编造事实、不虚构折扣与倒计时、不用绝对化最高级用语。\n"
        "【合规】规避医疗功效、收益承诺、未成年人定向与未授权数据宣称；语言贴合目标市场表达习惯，不做字面直译。",
        ["AIDA", "经典转化", "冷启动", "通用"]),
    _bp("copy_pas", "ad_copy", "PAS · 问题→激化→解决", "痛点唤醒", "情绪张力", "信息流广告", "toC 大众消费者",
        ["Facebook", "TikTok", "Moloco"],
        "PAS（Problem-Agitate-Solution）痛点文案框架",
        "效果广告转化率最高的框架之一：放大「没有它」的代价，让产品成为唯一合理解法。适合工具、效率、财务类。",
        "你是一名效果广告文案，使用 PAS 框架撰写广告文案。\n"
        "【Problem】用一句具体场景点出目标人群真实存在的痛点，不用抽象描述（写「报表要手动汇总到深夜」而不是「效率低」）。\n"
        "【Agitate】把痛点的时间成本／金钱成本／情绪成本具体化，但只做合理推演，不制造焦虑、不夸大后果。\n"
        "【Solution】以落地页中真实存在的产品能力作为解法收口，卖点必须可追溯到分析结论。\n"
        "【准则】钩子短、痛点准、解法快；标题与正文不要重复同一句话；CTA 指向可立即完成的动作。\n"
        "【禁止】编造用户故事与数据、虚构竞品缺陷、使用恐吓式表达、绝对化承诺。",
        ["PAS", "痛点", "高转化", "工具类"]),
    _bp("copy_bab", "ad_copy", "BAB · 之前→之后→桥梁", "转化导向", "故事叙事", "再营销", "toC 大众消费者",
        ["Facebook", "Google", "Mintegral"],
        "BAB（Before-After-Bridge）转化文案框架",
        "用「使用后的理想状态」建立向往，再把产品作为唯一桥梁。适合再营销与已有认知的人群。",
        "你是一名效果广告文案，使用 BAB 框架撰写广告文案。\n"
        "【Before】描摹目标人群当前的真实状态，具体、克制、可共情。\n"
        "【After】呈现使用产品后可达成的状态；只承诺落地页已明确支持的结果，不写无法验证的倍数与收益。\n"
        "【Bridge】用一句话把产品能力放到两者之间，说明「为什么是它」。\n"
        "【准则】After 与 Before 必须形成清晰对照；CTA 用「开始／试用／查看」等低门槛动词；整体语气积极，不用羞辱式对比。\n"
        "【禁止】虚构前后对比数据、编造用户评价、承诺确定性结果。",
        ["BAB", "再营销", "前后对比"]),
    _bp("copy_fab", "ad_copy", "FAB · 特性→优势→利益", "产品展示", "数据理性", "应用商店", "技术开发者",
        ["Google", "AppLovin", "Unity"],
        "FAB（Feature-Advantage-Benefit）卖点转化法",
        "把功能清单翻译成用户收益，避免「罗列参数」。适合 SaaS、工具、硬件与技术型产品。",
        "你是一名产品型广告文案，使用 FAB 法则撰写文案。\n"
        "【F 特性】只从落地页分析结论中选取真实存在的功能／参数／服务。\n"
        "【A 优势】说明该特性相对常规做法好在哪，必须可比较、可理解。\n"
        "【B 利益】落到用户真正获得的价值（省时、省钱、更少出错、更快上线），用目标人群的语言表达。\n"
        "【准则】每条文案完成一次 F→A→B 的完整推导，不要停在特性层；优先选带真实数字或权威背书的卖点；术语要转译为业务语言。\n"
        "【禁止】堆砌参数、编造基准测试数据、把「支持某能力」写成「保证某结果」。",
        ["FAB", "SaaS", "卖点提炼"]),
    _bp("copy_4p", "ad_copy", "4P · 承诺→描绘→证明→推动", "价值证明", "权威专业", "搜索广告", "企业决策者",
        ["Google", "Facebook", "LinkedIn"],
        "4P（Promise-Picture-Proof-Push）直效响应框架",
        "以可信证明支撑承诺，适合高决策成本、需要建立信任的 B 端与高客单产品。",
        "你是一名 B 端效果广告文案，使用 4P 框架撰写文案。\n"
        "【Promise】一句明确、可验证的价值承诺，不夸张。\n"
        "【Picture】用一句业务场景描绘价值兑现后的工作画面。\n"
        "【Proof】只引用落地页中真实出现的数字、客户、认证、案例或奖项作为证据；没有证据时改用可验证的产品能力，绝不虚构。\n"
        "【Push】给出低风险的下一步（查看方案／获取演示／免费试用），不使用虚假限时。\n"
        "【准则】语气专业克制，避免消费级煽动；标题承载承诺，正文承载证明；所有量化表述必须可追溯。\n"
        "【禁止】编造客户名与案例、承诺 ROI/收益、使用「唯一／第一／100%」等绝对化表述。",
        ["4P", "B端", "信任背书", "高客单"]),
    _bp("copy_hso", "ad_copy", "Hook-Story-Offer · 短视频信息流", "情感共鸣", "故事叙事", "视频前贴", "Z 世代",
        ["TikTok", "Facebook", "AppLovin"],
        "Hook-Story-Offer 短视频广告脚本结构",
        "前 3 秒定生死：钩子、微叙事、明确利益一气呵成，适配短视频与激励视频场景。",
        "你是一名短视频广告文案，使用 Hook-Story-Offer 结构撰写文案。\n"
        "【Hook】首句必须能在 3 秒内建立好奇或利益关联，句子短、口语化、可直接作为上屏字幕。\n"
        "【Story】用最小篇幅完成一个可感知的场景转折，不铺陈背景、不出现多个人物与支线。\n"
        "【Offer】清楚给出「现在能得到什么」及行动指令，利益与落地页真实能力一致。\n"
        "【准则】每条字段都短到能一眼读完；字幕与口播分工明确，不互相复述；语气自然，不写广告腔。\n"
        "【禁止】虚构折扣与倒计时、编造使用者反应、使用平台敏感词与夸大宣称。",
        ["Hook", "短视频", "Z世代", "信息流"]),
    _bp("copy_social", "ad_copy", "社会证明 · 评分/评价/权威背书", "价值证明", "写实自然", "再营销", "toC 大众消费者",
        ["Facebook", "Google", "TikTok"],
        "Social Proof 社会证明（Cialdini《影响力》）",
        "用真实存在的评价、评分、认证降低决策风险，适合犹豫期人群与再营销。",
        "你是一名效果广告文案，以「社会证明」为核心撰写文案。\n"
        "【素材限制】只使用落地页分析结论中真实出现的评分、评价数量、媒体名、认证与客户名；没有则不使用该手法，改为可验证的产品能力。\n"
        "【表达】把证据放在主张之后（先说价值，再给依据），避免生硬罗列；用群体规模或典型场景建立「别人也在用」的可信感。\n"
        "【准则】保留数字原文与表述原文，不四舍五入、不改写实价；CTA 承接信任（查看评价／了解方案）。\n"
        "【禁止】编造用户评价、虚构评分与下载量、杜撰权威机构、使用无法核实的「销量第一」。",
        ["社会证明", "信任", "再营销"]),
    _bp("copy_scarcity", "ad_copy", "稀缺紧迫 · 大促与限时", "促销刺激", "活泼潮流", "大促节点", "toC 大众消费者",
        ["Facebook", "TikTok", "Adsterra"],
        "Scarcity / Urgency 稀缺紧迫原理（合规版）",
        "把促销力度讲清楚、把行动理由讲充分，但不虚构倒计时与库存。适合大促与节点营销。",
        "你是一名大促广告文案，以「稀缺与紧迫」为核心撰写文案。\n"
        "【合规前提】只有落地页真实出现折扣、截止时间或限量信息时才可使用对应表述；否则只强调「当下值得行动」的理由，不得虚构限时、库存与倒计时。\n"
        "【表达】优惠信息前置且醒目，数字保持原文；用一句短 CTA 收口，减少阅读成本。\n"
        "【准则】主文案与标题分工：一个讲力度，一个讲理由；语气有能量但不喧闹；避免感叹号堆叠与全大写刷屏。\n"
        "【禁止】虚假倒计时、虚构库存、价格锚点造假、「错过再无」等无法证实的绝对表述。",
        ["稀缺", "大促", "合规促销"]),
    _bp("copy_ba", "ad_copy", "Before/After · 对比测评", "痛点唤醒", "数据理性", "新品上市", "女性消费人群",
        ["Facebook", "TikTok", "Google"],
        "Before-After 对比型广告框架",
        "用清晰对照让优势一眼可见，适合效果可视化强的品类与新品沟通。",
        "你是一名效果广告文案，使用 Before/After 对比结构撰写文案。\n"
        "【Before】一句话写出目标人群当前的真实状态或做法。\n"
        "【After】一句话写出采用该产品后可观察到的变化，变化必须来自落地页真实能力，不写无法验证的量化结果。\n"
        "【准则】对照关系要在一读之间成立；不使用贬低竞品的表述；CTA 指向「亲自验证」类低门槛动作。\n"
        "【禁止】编造前后对比数据、使用未经授权的人物形象描述、承诺确定性效果。",
        ["对比", "可视化", "新品"]),
    _bp("copy_local", "ad_copy", "本地化 · 多语种市场适配", "场景沉浸", "写实自然", "品牌曝光", "新兴市场用户",
        ["Facebook", "TikTok", "Google", "Adsterra"],
        "跨市场本地化文案实践（T1 / 拉美 / 东南亚）",
        "不是翻译而是重写：按目标市场语言习惯、节俗与支付/设备语境调整表达，降低广告感。",
        "你是一名跨市场本地化广告文案。\n"
        "【语言】按指定目标语言自然撰写，不做源语言字面直译；使用当地常用词序与惯用表达，避免生硬外来语。\n"
        "【语境】结合落地页分析结论中的目标地区与人群，选用贴合当地生活场景的表述；涉及节日、货币、单位时保持当地习惯。\n"
        "【准则】短句优先，避免需要文化背景才能理解的梗与双关；CTA 使用当地常见的行动动词；每条字段独立成立。\n"
        "【合规】遵守目标市场广告规范，规避收益承诺、医疗功效与未成年人定向；不编造本地化案例与数据。\n"
        "【禁止】机翻腔、混用语言、直接照搬英文句式。",
        ["本地化", "多语种", "拉美", "东南亚"]),

    # ----------------------------- 广告推广图片（10） -----------------------------
    _bp("img_hero", "ad_image", "产品主视觉 · Hero Shot", "产品展示", "写实自然", "信息流广告", "toC 大众消费者",
        ["Facebook", "Google", "AppLovin"],
        "Hero Shot 产品主视觉（电商 / 硬件通用广告摄影范式）",
        "产品作为唯一主体，演播级布光 + 大块负空间，最稳妥的通用背景。",
        "你是一名广告视觉总监与文生图提示词专家。\n"
        "【画面目标】生成一张可直接叠加广告文案的高质量背景图：产品主视觉（Hero Shot）。\n"
        "【构图】产品作为唯一主体居中或按三分法放置，边缘清晰，留出上方或一侧 ≥40% 干净负空间用于叠加标题与 CTA。\n"
        "【光影】演播级三点布光，柔和阴影与轮廓光，材质真实可辨；背景与品牌主色呼应但不抢主体。\n"
        "【适配】横版与竖版裁切下主体都保持完整，关键元素不贴近画面边缘。\n"
        "【禁止】任何文字、字母、数字、logo、水印、价格标签、UI 控件、多余产品堆叠与畸形产品。",
        ["Hero Shot", "产品主体", "通用"]),
    _bp("img_lifestyle", "ad_image", "生活方式 · 场景沉浸", "场景沉浸", "写实自然", "信息流广告", "女性消费人群",
        ["Facebook", "TikTok", "Instagram"],
        "Lifestyle / Aspirational 生活方式广告摄影",
        "让受众代入「这就是我的生活」，产品作为美好场景的一部分而非生硬主角。",
        "你是一名生活方式广告视觉总监。\n"
        "【画面目标】真实可代入的生活场景：明亮自然光、可信的环境细节、人物自然动作，产品被自然使用而非刻意摆拍。\n"
        "【构图】中景或环境人像，场景占据画面主体，产品处于视觉动线上；保留柔和、低对比区域用于叠加文案。\n"
        "【情绪】松弛、向往、真实；避免影楼感与过度摆拍。\n"
        "【禁止】画面内文字、logo、水印、夸张滤镜、不自然的手部与面部、多人拥挤构图。",
        ["Lifestyle", "场景", "代入感"]),
    _bp("img_split", "ad_image", "前后对比 · 左右分屏", "痛点唤醒", "数据理性", "再营销", "toC 大众消费者",
        ["Facebook", "TikTok", "Google"],
        "Before / After Split 对比构图",
        "左右或上下对照，把差异做成一眼可见的视觉事实，适合工具类与效果可视化品类。",
        "你是一名广告视觉设计师。\n"
        "【画面目标】清晰的左右（或上下）分屏对比构图，两侧氛围形成明确反差：一侧杂乱／暗调／低效，另一侧整洁／明亮／顺畅。\n"
        "【构图】分界线干净利落，两侧权重均衡；中部或上方保留可叠加短标题的干净区域。\n"
        "【表达】只做气氛与状态对比，不生成具体文字标签、箭头、勾选框或数据图表。\n"
        "【禁止】任何文字与数字、贬低性丑化、真人痛苦表情、医疗前后对照暗示。",
        ["Before/After", "分屏", "对比"]),
    _bp("img_ugc", "ad_image", "UGC 真实感 · 原生内容", "价值证明", "写实自然", "视频前贴", "Z 世代",
        ["TikTok", "Facebook", "AppLovin"],
        "UGC / Creator-style 原生内容视觉",
        "弱广告感、强真实感，模拟用户自拍视角，适合短视频平台与年轻人群。",
        "你是一名原生内容广告视觉设计师。\n"
        "【画面目标】模拟真实用户随手拍摄的竖屏画面：轻微手持感、日常环境光、自然构图、非完美对称。\n"
        "【质感】适度颗粒与真实景深，避免广告级精修；主体是人与产品的自然互动，不是产品棚拍。\n"
        "【构图】留出上方或下方安全区叠加上屏字幕；避免关键主体被裁切。\n"
        "【禁止】任何文字、字幕、logo、水印、UI 界面、过度美颜、畸形手指与多人重叠。",
        ["UGC", "原生感", "Z世代", "竖屏"]),
    _bp("img_minimal", "ad_image", "极简留白 · 高级克制", "品牌叙事", "高级克制", "品牌曝光", "企业决策者",
        ["Facebook", "Google", "LinkedIn"],
        "Minimal / Negative Space 极简广告美学",
        "大留白、单一主体、克制色彩，适合高端品牌与 B 端专业调性。",
        "你是一名极简主义广告视觉总监。\n"
        "【画面目标】大量负空间（≥60%）、单一明确主体、极少的视觉元素，传递克制与高级。\n"
        "【色彩】低饱和中性色或品牌单色，避免高饱和撞色与渐变堆叠。\n"
        "【光影】柔和均匀，边缘干净；构图秩序感强，主体置于三分点或居中。\n"
        "【禁止】任何文字、logo、水印、装饰元素堆叠、复杂纹理、多主体与拥挤构图。",
        ["极简", "留白", "高端", "B端"]),
    _bp("img_data", "ad_image", "数据权威 · 理性视觉", "价值证明", "数据理性", "搜索广告", "企业决策者",
        ["Google", "LinkedIn", "Facebook"],
        "Data-driven / Stat-centric 数据导向视觉",
        "以秩序感、网格与结构化光影建立专业可信，适合 SaaS 与 B 端。",
        "你是一名 B 端广告视觉设计师。\n"
        "【画面目标】理性、结构化、专业：细腻网格、有序几何、克制的冷色光与层次分明的空间感。\n"
        "【构图】留出大面积干净区域用于叠加数字型标题；视觉重心稳定，不用强透视与夸张动势。\n"
        "【质感】精密、清晰、可信，避免娱乐化与节庆感。\n"
        "【禁止】任何文字、数字、字母、图表标签、logo、水印、杂乱装饰。",
        ["数据", "权威", "SaaS", "B端"]),
    _bp("img_promo", "ad_image", "促销氛围 · 节日大促", "促销刺激", "活泼潮流", "大促节点", "toC 大众消费者",
        ["Facebook", "TikTok", "Adsterra"],
        "Promo / Festive 节点促销视觉",
        "高能量、暖色调、节庆氛围，让优惠信息在背景之上更醒目，但不生成任何文字。",
        "你是一名大促广告视觉设计师。\n"
        "【画面目标】温暖高能的节庆氛围：金橙暖调、柔和光斑、礼物／彩带／灯饰等无文字装饰元素，营造消费冲动。\n"
        "【构图】中心聚焦，四周保留干净区域用于叠加折扣文案；装饰不遮挡主体。\n"
        "【色彩】高饱和但不过曝，主色与品牌色协调。\n"
        "【禁止】任何文字、数字、价格、折扣标签、倒计时、logo、水印与品牌标识。",
        ["大促", "节日", "暖调", "促销"]),
    _bp("img_portrait", "ad_image", "人物情绪 · 情感共鸣", "情感共鸣", "情绪张力", "品牌曝光", "女性消费人群",
        ["Facebook", "TikTok", "Instagram"],
        "Emotional Portrait 情绪人像广告",
        "用一个真实情绪瞬间建立共鸣，适合品牌叙事与情感型品类。",
        "你是一名广告人像视觉总监。\n"
        "【画面目标】单个真实人物的自然情绪瞬间（放松、专注、喜悦、释然），环境光可信，情绪克制不夸张。\n"
        "【构图】中近景，人物视线或动势指向留白区；留出 ≥40% 干净区域叠加文案。\n"
        "【质感】自然肤色、真实景深、轻微颗粒，避免塑料感与过度磨皮。\n"
        "【禁止】任何文字、logo、水印、夸张表情、多人拥挤、畸形手部与面部。",
        ["人物", "情绪", "共鸣", "品牌"]),
    _bp("img_3d", "ad_image", "3D 渲染 · 科技未来", "产品展示", "权威专业", "新品上市", "技术开发者",
        ["AppLovin", "Unity", "Google"],
        "3D / CGI 科技感产品渲染",
        "材质光感立体、未来感强，适合硬件、AI 与工具类新品。",
        "你是一名 3D 广告视觉设计师。\n"
        "【画面目标】高精度三维渲染：金属／玻璃／磨砂材质、精确环境反射、悬浮或几何基座上的单一产品主体。\n"
        "【光影】冷调科技光、边缘轮廓光、细腻渐变背景，层次分明但不杂乱。\n"
        "【构图】主体居中偏下，上方保留干净负空间；横竖裁切都不切断主体。\n"
        "【禁止】任何文字、字母、logo、水印、UI 控件、多余产品与畸形几何。",
        ["3D", "CGI", "科技", "新品"]),
    _bp("img_local", "ad_image", "本地文化 · 区域视觉适配", "场景沉浸", "写实自然", "品牌曝光", "新兴市场用户",
        ["Facebook", "TikTok", "Adsterra"],
        "Localization 区域文化视觉适配",
        "把本地色彩、建筑、节俗与生活符号融入画面，提升目标市场的亲近感与相关性。",
        "你是一名跨市场广告视觉设计师。\n"
        "【画面目标】真实、尊重、不做刻板印象的本地生活场景：当地建筑与街景、自然光、日常物件与色彩偏好。\n"
        "【构图】保留足够干净负空间叠加多语种文案；主体明确，避免元素堆砌。\n"
        "【质感】写实自然、避免过度滤镜；节俗元素仅在确有大促语境时克制使用。\n"
        "【禁止】任何文字、字母、logo、水印、国旗与政治符号、刻板化人物形象、宗教敏感元素。",
        ["本地化", "区域适配", "多语种"]),
]


def library_dimensions() -> dict:
    """供前端渲染四维筛选器。"""
    return {
        "kinds": KINDS,
        "dimensions": [
            {"key": k, "label": DIM_LABEL[k], "options": v}
            for k, v in LIBRARY_DIMENSIONS.items()
        ],
    }


def library_entries(kind: Optional[str] = None, *, type: Optional[str] = None,
                    style: Optional[str] = None, scene: Optional[str] = None,
                    audience: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
    """按维度筛选总结库；所有维度取交集，关键词匹配名称/摘要/正文/标签/来源。"""
    filters = {"type": type, "style": style, "scene": scene, "audience": audience}
    keyword = (q or "").strip().lower()
    out = []
    for item in BEST_PRACTICES:
        if kind and item["kind"] != kind:
            continue
        if any(v and item.get(k) != v for k, v in filters.items()):
            continue
        if keyword:
            hay = " ".join([
                item["name"], item["summary"], item["source"], item["content"],
                " ".join(item["tags"]), " ".join(item["platforms"]),
            ]).lower()
            if keyword not in hay:
                continue
        out.append(item)
    return out


def get_practice(kind: str, ident: str) -> Optional[dict]:
    return next((x for x in BEST_PRACTICES
                 if x["kind"] == kind and x["id"] == ident), None)


def target_key_for_kind(kind: str) -> Optional[str]:
    return next((k["target_key"] for k in KINDS if k["key"] == kind), None)
