"""
业务逻辑 V3：洞察 → 创意方向 → 按方向生产素材（图/文案/视频关键帧）。

与 V2 的差别：
- 分析层用本地抽取（insight.py）兜底，配置了模型再用模型润色，不再输出写死的通用卖点；
- 生产以「创意方向」为单位，同一方向跨版位重新排版，而不是同一张图换尺寸；
- 文案按平台字段结构输出并对齐字数，超长按词边界裁剪，最后做同质化检查。
"""
import asyncio
import html as html_lib
import json
import os
import re
import shutil
import subprocess

import httpx

from models import Framework, Campaign, Material, PlatformSpec, Angle, ModelConfig, PromptConfig
from providers import get_llm, get_image, get_video, parse_json
from insight import analyze_local, detect_lang
from creative import (ANGLE_LIBRARY, ANGLE_MAP, COPY_SCHEMA, build_copy_kit, map_to_platform,
                      copy_text, validate_copy, char_table, flag_duplicates, fit_text,
                      build_keywords, keyword_text)
from render import render_creative, render_keyframe, ANGLE_DESIGN
from validation import build_validation
from presets import (build_directives, creative_presets_payload, style_visual,
                     palette_prompt, DIRECTION_MOOD)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
IMAGE_MAX_SIZES = int(os.getenv("IMAGE_SIZES_PER_PLATFORM", "4"))
VIDEO_KEYFRAMES = 4

# V4.0 网站核心内容分析提示词：把落地页整理成可投放的结构化「网站核心内容」。
# 覆盖 9 大模块：产品与定位 / 核心价值主张 / 信任与量化背书 / 目标人群 /
# 落地页结构与转化路径 / 各平台投放读法 / 风险与合规 / 信息缺口 / 下一步。
# 设计原则：所有结论必须来自给定事实与正文，缺什么写进 gaps，绝不编造。
SYS_SITE_ANALYSIS = (
    "你是海外效果广告投放策略师，擅长从落地页提炼「可投放」的结构化洞察。"
    "输入：落地页 URL、页面结构（标题/H1/H2/CTA/META 描述）、正文（≤4000 字）、本地已抽取事实。"
    "任务：把网站内容整理成「网站核心内容」，严格输出如下 JSON（只输出 JSON，不要任何解释文字，"
    "结尾必须包含 MARKER:SITE_ANALYSIS_JSON）：\n"
    "{\n"
    '  "positioning": {"product": str, "category": str, "category_key": str, '
    '"one_liner": str, "differentiators": [str×2-3]},\n'
    '  "value": {"summary": str, "points": [{"point": str, "type": "benefit|proof|metric", '
    '"strength": "强|中|弱", "evidence": str}×3-5]},\n'
    '  "proof": {"summary": str, "metrics": [{"value": str, "kind": "rating|price|ratio|multiple|scale|other", '
    '"label": str}], "endorsements": [str], "credibility": str},\n'
    '  "audience": {"primary": str, "demographics": str, "pain_points": [str], "secondary": str},\n'
    '  "geo": "目标投放地区（如 北美, 拉美, 东南亚；依正文语言/提及地区/业务成熟度独立判断，'
    '无明确信号写 全球 或 T1 英语区）",\n'
    '  "languages": ["目标语言代码 en/es/pt/id/zh 等，依正文语言与受众判断，不要照搬本地抽取"],\n'
    '  "page": {"sections": [str], "structure_note": str, "conversion_path": str, '
    '"primary_cta": str, "tone": str},\n'
    '  "channel": {平台名: {"tactics": str, "hook": str, "selling_point": str, "compliance_note": str}},\n'
    '  "risk": {"items": [{"level": "error|warn|info", "item": str, "detail": str}], "compliance": str},\n'
    '  "gaps": {"missing": [str], "confidence": "高|中|低"},\n'
    '  "next_steps": [str×2-4],\n'
    '  "business_nature": {"nature": str, "is_marketing_platform": bool, "note": str},\n'
    '  "target_clients": {"toc": str, "tob": [str], '
    '"needs": {"advertiser": str, "channel": str, "media": str}},\n'
    '  "appeal_highlights": [str×2-3],\n'
    '  "nine_elements": {"industry": str, "type": str, "category": str, "needs": str, '
    '"solution": str, "business_model": str, "advantage_compare": str, '
    '"differentiation": str, "purpose_summary": str},\n'
    '  "extensions": {"industry_insight": str, "competitors": str, "market_demand": str, '
    '"diff_solution": str, "edge_advantage": str, '
    '"recommended_media": [str], "recommended_audience": [str]}\n'
    "}\n"
    "硬性约束：\n"
    "1. 所有结论必须来自给定的事实与正文，禁止编造；正文没有的信息写入 gaps.missing，不要猜测或补通用套话。\n"
    "2. 量化背书只摘录页面真实出现的数字/奖项/媒体名/认证；「免费」表述保留原文（如 \"Try X for Free\"），不要改写实价。\n"
    "3. category_key 从固定集合选最贴切者：fitness/finance/game/commerce/education/app/tool/travel/photo_ai/adtech/marketing/other；若网站是广告/营销/变现/代理/媒体平台，用 adtech 或 marketing，category 写「效果广告平台/广告变现服务/媒体代理」等，不要因页面含教程/案例就误判为教育。\n"
    "4. value.points 每条都是一条可独立成立的卖点/主张；strength 按「能否直接当素材标题」判：有数字或权威背书为强，纯描述为中。\n"
    "5. channel 聚焦「素材打法」：创意形式、前 3 秒钩子、主推卖点、需规避的合规点；至少覆盖 Facebook/Google/TikTok/Unity/AppLovin/Moloco/Mintegral/Adsterra。\n"
    "6. risk 结合品类给真实拒登点（医疗宣称、收益承诺、虚构倒计时、未成年人定向、未授权数据等）；level 按严重度 error/warn/info。\n"
    "7. next_steps 给投放侧可执行动作（补素材、A/B 方向、合规改写、落地页优化）。\n"
    "8. 输出前确认 JSON 合法，结尾必须包含 MARKER:SITE_ANALYSIS_JSON。\n"
    "9. 先判断「网站本质属性」(business_nature)：它是 toC 产品落地页、toB 服务/平台、广告技术/流量/媒体平台、营销服务，还是其他。若网站用于「帮助广告主获客、对接渠道与流量、提供广告/营销/变现/代理服务」，必须标记为「效果广告/营销平台（服务广告主与渠道/流量商）」，不得仅因页面出现教程/案例/博客就误判为教育、媒体或其他无关品类；综合全部内容锁定真实定位与核心目标客户。\n"
    "10. target_clients 必须区分两类：toc=终端用户及其需求；tob=它服务的企业/广告主/渠道方，并分别写出 advertiser(广告主)/channel(渠道或代理)/media(流量主或媒体)各自的核心诉求（如：需要更多优质广告主、需要稳定流量供给、需要更高的 eCPM/填充率）。\n"
    "11. appeal_highlights 写 2-3 条「对目标客户最有吸引力的亮点/价值钩子」，是对方为什么该用它，而不是功能罗列。\n"
    "12. nine_elements 是「看懂这个网站是什么」的核心总结：industry=所处行业；type=网站/业务类型；category=主营产品品类；needs=解决谁的什么问题；solution=怎么解决；business_model=如何赚钱（广告变现/订阅/SaaS/佣金/CPA 等）；advantage_compare=相比竞品或传统方式好在哪；differentiation=别人没有的特色；purpose_summary=用一段话概括这个网站的核心目的。\n"
    "13. extensions 是延伸输出：industry_insight=行业趋势与机会；competitors=主要竞品及对比；market_demand=目标市场需求规模与痛点；diff_solution=可落地的差异化打法；edge_advantage=特色优势；recommended_media=推荐投放的媒体/平台（如 Google/Facebook/TikTok/行业垂直媒体）；recommended_audience=推荐的目标人群标签。\n"
    "14. geo 与 languages 必须由你独立判断：本地抽取常不准（如把全英文页误判成多语、把全球产品误判成单一地区），"
    "请依据正文实际语言、明确提及的地区、产品成熟度给出真实判断，禁止照搬本地抽取事实。\n"
    "15. channel 的 tactics 必须针对该产品/品类定制（结合卖点与合规），不要复述通用的平台操作手册；"
    "至少覆盖 Facebook/Google/TikTok/Unity/AppLovin/Moloco/Mintegral/Adsterra。"
)

# 旧版基础框架提示词（仅用于兼容，已被 SYS_SITE_ANALYSIS 取代）；保留常量避免引用断裂。
SYS_FRAMEWORK = SYS_SITE_ANALYSIS
SYS_ANGLE = (
    "你是效果广告创意总监。基于产品事实，给出 8 个互不重复的创意方向，必须覆盖全部 key："
    "pain / benefit / proof / curiosity / ugc / promo / scenario / comparison。严格 JSON："
    '{"angles":[{"key":"pain|benefit|proof|curiosity|ugc|promo|scenario|comparison",'
    '"name":"中文名","insight":"为什么这个角度对这个产品有效",'
    '"hook":"该方向最短的一句钩子文案（目标语言）","visual":"画面具体长什么样","kpi":"主要影响指标"}]}。'
    "只输出 JSON。MARKER:ANGLE_JSON"
)
SYS_COPY = (
    "你是效果广告文案。严格按创意方向与语言撰写，不使用夸大或无法证实的数字。"
    "输出严格 JSON：{\"headlines\":[3条短标题],\"bodies\":[2条正文],\"cta\":\"按钮文案\"}。"
    "每条都必须能独立成立，且不超过给定字数上限。只输出 JSON。MARKER:COPY_JSON"
)
SYS_VIDEO = (
    "你是效果广告视频导演，为信息流/激励视频写 15 秒可拍摄分镜脚本，画面必须具体可拍、"
    "不使用夸大或无法证实的数字。输出严格 JSON："
    '{"hook":"前 3 秒钩子（目标语言）","cta":"结尾行动指令（目标语言）",'
    '"shots":[{"t":"0-3s","shot":"镜头名","visual":"拍摄说明：景别/主体/动作/场景",'
    '"text":"上屏广告字幕（目标语言，≤18字符）","vo":"旁白/口播（目标语言，≤15词）"}]}。'
    "shots 固定 4 镜，节奏 0-3s 钩子开场、3-8s 产品演示、8-12s 结果证明、12-15s CTA 收口；"
    "shot 是 3-8 个字的镜头名（如「痛点开场」），不是整句描述；"
    "字段分工是硬性要求：visual 只写拍摄说明（谁在做什么、什么景别），"
    "text 必须是能直接打在广告画面上的句子（用户看得懂的利益点或行动指令），"
    "严禁把「先给出问题现场」「展示产品演示」这类镜头解释、内部备注或拍摄指令写进 text；"
    "vo 是配音稿；text 与 vo 必须与创意方向和产品事实一致。只输出 JSON。MARKER:VIDEO_JSON"
)
SYS_IMAGE_DESIGN = (
    "你是效果广告视觉设计指导。基于产品与创意方向，为同一批素材的图片与视频关键帧"
    "输出差异化视觉设计规范，避免所有素材共用同一个纯色渐变底与同一套排版。输出严格 JSON："
    '{"styles":["背景风格，2-3 个，从 gradient/radial/split/wave/halftone/stripes/spotlight/'
    'light_panel/vignette 中选，第一个用于图片，其余供视频分镜逐镜轮换"],'
    '"layout":"default|side_left|bottom_stack|centered",'
    '"font_scale":0.9-1.2,'
    '"tone":"一句话设计意图（为什么这套视觉匹配该创意方向与受众情绪）"}。'
    "约束：1. 风格必须契合创意方向的情绪（痛点→戏剧性聚光/暗角，证明→浅色可信，"
    "促销→对撞色块，好奇→点阵/分割，UGC→斜纹真实感）；"
    "2. layout 与风格搭配，竖版画幅不要选 side_left；"
    "3. font_scale 控制在 0.9-1.2，促销可偏大、证明与场景可偏小；"
    "4. 只输出 JSON，不要解释。结尾必须包含 MARKER:IMAGE_DESIGN_JSON"
)

# ----------------------------- 提示词管理（设置页可查可改，保存即生效） -----------------------------
# 内置注册表：播种与「恢复默认」的唯一来源。编辑存 DB，调用时经 get_prompt 读取。
PROMPT_REGISTRY = [
    {
        "key": "site_analysis",
        "name": "网站核心内容分析",
        "module": "落地页分析（创作工作台 / 批量生成 / 分析报告）",
        "description": (
            "输入落地页 URL/正文，输出 9 模块结构化 JSON（定位/价值/背书/人群/页面/渠道/风险/缺口/下一步），"
            "落库 site_analysis 并驱动创意方向推荐排序与报告。注意：结尾的 MARKER:SITE_ANALYSIS_JSON 用于解析兜底路由，请保留。"
        ),
        "content": SYS_SITE_ANALYSIS,
    },
    {
        "key": "angle",
        "name": "创意方向规划",
        "module": "创意方向生成（POST /api/angles/plan）",
        "description": (
            "基于产品事实润色 8 个创意方向（pain/benefit/proof/curiosity/ugc/promo/scenario/comparison），"
            "仅覆盖 hook/insight/visual 三个字段，本地库兜底。注意：结尾的 MARKER:ANGLE_JSON 请保留。"
        ),
        "content": SYS_ANGLE,
    },
    {
        "key": "copy",
        "name": "按方向生产文案",
        "module": "素材生产与重生成（标题/正文/CTA）",
        "description": (
            "按选定创意方向与语言撰写 headlines（3 条）与 bodies（2 条）及 CTA，输出后统一走字数对齐。"
            "注意：结尾的 MARKER:COPY_JSON 请保留。"
        ),
        "content": SYS_COPY,
    },
    {
        "key": "video",
        "name": "视频分镜脚本",
        "module": "完整视频生成（创作工作台 投放设置「生成完整视频」/ 视频素材重生成）",
        "description": (
            "按创意方向与产品事实撰写 15 秒 4 镜分镜脚本（钩子/演示/证明/CTA），"
            "驱动关键帧渲染与完整视频 MP4 合成。visual 写拍摄说明、text 写上屏广告字幕（不得写镜头解释），"
            "关键帧只输出纯广告画面，说明与旁白在素材墙逐帧标注。脚本失败时回退内置分镜。"
            "注意：结尾的 MARKER:VIDEO_JSON 请保留。"
        ),
        "content": SYS_VIDEO,
    },
    {
        "key": "image",
        "name": "素材视觉设计指导",
        "module": "图片渲染 / 视频关键帧（创作工作台 / 批量生成 / 重生成 / 素材优化）",
        "description": (
            "按创意方向输出差异化视觉规范：背景风格（9 种）、文字版式（4 种）、字号节奏、设计意图，"
            "驱动图片与视频关键帧摆脱「纯色渐变 + 同一套排版」。字段值须在枚举范围内，"
            "失败时回退按方向内置的设计预设。注意：结尾的 MARKER:IMAGE_DESIGN_JSON 请保留。"
        ),
        "content": SYS_IMAGE_DESIGN,
    },
]

# ----------------------------- 素材创作（落地页分析）：8 字段 LLM 推理提示词框架 -----------------------------
# 5 段提示词在运行时拼接为「系统提示词」一次调用大模型，输出 8 个必要字段。
# 每段可单独在「素材提示词」中编辑；category 用于在提示词库里分门别类展示。
# 注意：本框架不依赖 MARKER 标记（解析走稳健 JSON 提取），编辑时无需保留特定结尾标记。
LANDING_MODULE = "素材创作（落地页分析）"

SYS_LANDING_FRAMEWORK = (
    "你是海外效果广告投放策略师。给定落地页 URL 与正文，请基于页面真实内容，用大模型推理能力提炼该网站的关键信息。\n"
    "任务：输出以下 8 个字段的结构化 JSON（只输出 JSON，不要任何解释文字）：\n"
    "{\n"
    '  "language": "网站主要语言（如 中文 / English / Español）",\n'
    '  "industry": "从网站主营信息推断出的行业（如 在线教育 / 跨境电商 / SaaS 工具 / 移动游戏）",\n'
    '  "type": "网站属性/类型（如 电商网站 / 技术服务 / 公益平台 / 政府网站 / 旅游服务 / 家政服务 / 营销·广告平台 / SaaS 工具 / 其他）",\n'
    '  "audience": "目标对象：面向哪些人群 / 企业 / 渠道 / 地区",\n'
    '  "competitors": ["全球排名 top 3 的主要竞品名称"],\n'
    '  "advantages": ["核心优势/卖点，提炼而非功能罗列，最多 5 条"],\n'
    '  "channels": [{"platform": "推荐用于用户增长的媒体平台", "reason": "推荐理由 / 数据依据"}]\n'
    "}\n"
    "硬性约束：\n"
    "1. 所有结论必须来自给定正文与页面结构，禁止编造；缺信息时对应字段填空字符串或空数组，不要补通用套话。\n"
    "2. type 与 industry 要区分：industry 是所处行业，type 是『这个网站是什么』（它的本质属性）。\n"
    "3. competitors 最多 3 个、advantages 最多 5 条、channels 最多 5 个；不足则少给，不要硬凑。\n"
    "4. channels 的 reason 必须具体（结合受众 / 产品形态 / 行业惯例或数据依据），避免『流量大』这类空话。"
)

SYS_LANDING_BASIC = (
    "请重点核对以下字段的提取准确性：\n"
    "- language：以页面正文与 <html lang> 的实际语言为准，不要被个别英文术语误导；多语站点取主语言。\n"
    "- industry：依据网站『在做什么业务、服务谁』来定，而不是页面装饰。页面有教程/博客不代表就是教育行业——要看它实际售卖/提供的核心服务。\n"
    "- type：判定网站本质属性，从「电商网站 / 技术服务 / 公益平台 / 政府网站 / 旅游服务 / 家政服务 / 媒体平台 / SaaS 工具 / 其他」中选最贴切者；"
    "若网站用于帮助广告主获客、对接渠道与流量、提供广告/营销/变现/代理服务，应判为「营销·广告平台」相关类型，不要因页面含教程或案例就误判。\n"
    "- audience：明确对象是谁（终端消费者 / 企业客户 / 渠道代理 / 流量主），以及主要覆盖地区。"
)

SYS_LANDING_COMPETITORS = (
    "competitors：列出该网站在『全球市场』上最主要的 3 个竞品（按知名度 / 市场份额 / 直接替代关系取 top 3），仅给名称数组。\n"
    "若网站为 niche / 新兴产品导致难以判定，给出最相近的 3 个替代方案名称；实在无参考则给空数组。不要编造不存在的竞品。"
)

SYS_LANDING_ADVANTAGES = (
    "advantages：从该网站的真实卖点中提炼『核心优势 / 差异化价值』，而不是罗列功能清单。\n"
    "每条是一句可独立成立的价值陈述（如『覆盖 200+ 国家的一件代发网络』『AI 自动生成投放创意，节省 70% 素材制作时间』）。\n"
    "聚焦技术特质、服务承诺、资源壁垒、性价比等真正构成竞争力的点；默认最多 5 条，不足则少给，不要硬凑。"
)

SYS_LANDING_CHANNELS = (
    "channels：推荐该网站用于『获取用户增长』的媒体 / 广告平台，最多 5 个。\n"
    "每个对象含 platform（平台名，如 Google / Meta / TikTok / 行业垂直媒体 / 应用商店 ASO）与 reason（为什么适合它的推荐理由，"
    "可结合受众、产品形态、行业惯例或数据依据，如『目标用户为 Z 世代，TikTok 短视频种草转化高』）。"
)

LANDING_PROMPTS = [
    {
        "key": "landing_framework",
        "name": "落地页分析 · 分析总框架",
        "module": LANDING_MODULE,
        "category": "分析框架",
        "description": "落地页分析的顶层指令：明确任务、输出 JSON 结构与硬性约束。其余提示词分别细化各字段的提取规则。",
        "content": SYS_LANDING_FRAMEWORK,
    },
    {
        "key": "landing_basic",
        "name": "落地页分析 · 基础识别",
        "module": LANDING_MODULE,
        "category": "基础识别",
        "description": "细化 language / industry / type / audience 四个字段的提取规则与判定要点（行业与类型区分、本质属性判定）。",
        "content": SYS_LANDING_BASIC,
    },
    {
        "key": "landing_competitors",
        "name": "落地页分析 · 竞品识别",
        "module": LANDING_MODULE,
        "category": "竞争分析",
        "description": "细化 competitors 字段：全球排名 top 3 竞品，含判定口径，禁止编造。",
        "content": SYS_LANDING_COMPETITORS,
    },
    {
        "key": "landing_advantages",
        "name": "落地页分析 · 优势提炼",
        "module": LANDING_MODULE,
        "category": "价值提炼",
        "description": "细化 advantages 字段：提炼核心优势，非功能罗列，默认 ≤5 条。",
        "content": SYS_LANDING_ADVANTAGES,
    },
    {
        "key": "landing_channels",
        "name": "落地页分析 · 推广途径",
        "module": LANDING_MODULE,
        "category": "增长推广",
        "description": "细化 channels 字段：推荐用于用户增长的媒体平台，每个含平台名 + 推荐理由/数据依据，默认 ≤5 个。",
        "content": SYS_LANDING_CHANNELS,
    },
]

# 把落地页分析提示词并入注册表（提示词管理 / 素材提示词 单一数据源）
PROMPT_REGISTRY = PROMPT_REGISTRY + LANDING_PROMPTS

_PROMPT_FALLBACK = {p["key"]: p["content"] for p in PROMPT_REGISTRY}

# 旧版默认提示词快照，只用于升级迁移：库里内容仍是这段未改动的默认值时刷新为新版，
# 用户自己编辑过的内容（已不等于快照）绝不覆盖。
_PROMPT_LEGACY = {
    "video": (
        "你是效果广告视频导演，为信息流/激励视频写 15 秒可拍摄分镜脚本，画面必须具体可拍、"
        "不使用夸大或无法证实的数字。输出严格 JSON："
        '{"hook":"前 3 秒钩子（目标语言）","cta":"结尾行动指令（目标语言）",'
        '"shots":[{"t":"0-3s","shot":"镜头名","visual":"画面内容（具体到景别/主体/动作）",'
        '"text":"画面字幕（目标语言，≤20字符）","vo":"旁白/口播（目标语言，≤15词）"}]}。'
        "shots 固定 4 镜，节奏 0-3s 钩子开场、3-8s 产品演示、8-12s 结果证明、12-15s CTA 收口；"
        "text 与 vo 必须与创意方向和产品事实一致。只输出 JSON。MARKER:VIDEO_JSON"
    ),
}


def get_prompt(db, key: str) -> str:
    """读取当前生效的提示词：DB 中启用版本优先，未配置/停用/读取失败回退内置默认。"""
    try:
        row = db.query(PromptConfig).filter_by(key=key, is_active=True).first()
        if row and (row.content or "").strip():
            return row.content
    except Exception:
        pass
    return _PROMPT_FALLBACK.get(key, "")


def sync_prompt_defaults(db) -> list:
    """把提示词默认值升级到当前版本：元信息（名称/模块/说明）始终跟随代码版本；
    正文只在库里仍是旧默认快照时刷新，用户自己改过的不动。返回被更新的 key 列表。
    """
    touched = []
    for item in PROMPT_REGISTRY:
        row = db.query(PromptConfig).filter_by(key=item["key"]).first()
        if not row:
            continue
        changed = False
        meta = (item["name"], item["module"], item["description"], item.get("category"))
        if (row.name, row.module, row.description, row.category) != meta:
            row.name, row.module, row.description = item["name"], item["module"], item["description"]
            row.category = item.get("category")
            changed = True
        legacy = (_PROMPT_LEGACY.get(item["key"]) or "").strip()
        if legacy and (row.content or "").strip() == legacy:
            row.content = item["content"]
            changed = True
        if changed:
            touched.append(item["key"])
    if touched:
        db.commit()
    return touched


def has_real(db, usage="analysis") -> bool:
    cfg = db.query(ModelConfig).filter_by(usage=usage, is_active=True).first()
    return bool(cfg and cfg.api_key and cfg.base_url and cfg.model)


def _spec_for(db, platform):
    return db.query(PlatformSpec).filter_by(platform=platform).first()


def _size_wh(size: str):
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1080


def _build_image_prompt(fw, key: str, design: dict, directives: dict, lang: str) -> str:
    """把创意方向 / 内容风格 / 配色 / 角度，拼成一句**具体可区分**的文生图提示词（背景层，不含文字）。

    关键改进：不再只把 Pillow 风格键（"cyber"/"split"）和中文内容描述丢给图像模型，
    而是把风格键翻译成具体英文视觉描述、把配色翻译成 hex 颜色、把创意方向翻译成情绪/构图意图，
    并按角度叠加不同情绪——让选不同方向/风格/配色时，AI 背景真正不同。
    """
    design = design or {}
    directives = directives or {}
    raw_styles = design.get("styles") or []
    if isinstance(raw_styles, str):
        raw_styles = [raw_styles]
    style_keys = [s for s in raw_styles if isinstance(s, str)]
    # 风格键 → 具体英文视觉描述（最多取 3 个，制造层次）
    style_desc = "; ".join(style_visual(s) for s in style_keys[:3]) or "modern advertising visual backdrop"

    # 创意方向 → 英文情绪/构图意图（按方向制造差异）
    dir_id = directives.get("direction_id") or ""
    dir_mood = DIRECTION_MOOD.get(dir_id, "")
    # 角度 → 各自情绪（ANGLE_DESIGN.tone），同一批次不同角度背景不同
    angle_name = ANGLE_MAP.get(key, {}).get("name", key)
    angle_tone = (ANGLE_DESIGN.get(key) or ANGLE_DESIGN["benefit"]).get("tone", "")
    tone = (design.get("tone") or "").strip()
    # 配色 → 具体 hex 描述
    palette_text = palette_prompt(design.get("palette"))

    parts = [
        f"High-quality advertising background visual for the product '{fw.product}'.",
        "No text, no logo, no letters, no watermark, no UI; clean negative space for overlaid ad copy.",
    ]
    if dir_mood:
        parts.append(f"Creative direction mood: {dir_mood}.")
    parts.append(f"Visual style: {style_desc}.")
    if palette_text:
        parts.append(palette_text)
    if angle_tone:
        parts.append(f"Angle '{angle_name}': {angle_tone}.")
    elif tone:
        parts.append(f"Design intent: {tone}.")
    parts.append(
        "Photorealistic or illustrative, consistent with the described style, high detail, "
        "professional advertising quality.")
    return " ".join(parts)


def _cleanup_ai_bgs():
    """删除生成过程中产生的中间 AI 背景图（已合成进最终素材，无需留存）。"""
    try:
        import glob
        for f in glob.glob(os.path.join(UPLOAD_DIR, "_aibg_*.png")):
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


def variant_label(version: int) -> str:
    return chr(64 + version) if 1 <= version <= 26 else f"V{version}"


# ----------------------------- 分析 -----------------------------
# 页面上的按钮/链接文案：判断这个落地页让用户"做什么"，是分析报告里转化路径的依据
CTA_TEXT_RE = re.compile(
    r"^(?:learn more|see more|read more|see how|shop now|buy now|order now|download(?: now)?|"
    r"install(?: now)?|try (?:it )?free|try [\w' .]{0,24}for free|get started|get offer|"
    r"sign ?up|start (?:free|now|trial)|subscribe|play (?:now|free)|book (?:now|a demo)|"
    r"了解更多|立即下载|立即体验|免费试用|立即购买|查看详情|开始使用|注册|预约)", re.I)

_PAGE_META_KEYS = ("title", "description", "lang", "h1", "h2", "ctas", "images", "has_video")


def _tag_text(inner: str) -> str:
    txt = re.sub(r"(?s)<[^>]+>", " ", inner or "")
    return re.sub(r"\s+", " ", html_lib.unescape(txt)).strip()


def parse_page_meta(html: str, final_url: str = "") -> dict:
    """从 HTML 里取"页面结构"，而不是只取正文。

    投放人员看落地页先看三件事：主标题在说什么、卖点怎么分层、按钮让用户做什么。
    这三件事在纯文本里会丢失，所以单独解析出来放进分析报告。
    """
    if not html:
        return {"title": "", "description": "", "lang": "", "h1": [], "h2": [],
                "ctas": [], "images": 0, "has_video": False, "final_url": final_url}

    def _first(pattern: str) -> str:
        m = re.search(pattern, html, re.I | re.S)
        return _tag_text(m.group(1)) if m else ""

    title = _first(r"<title[^>]*>(.*?)</title>")
    description = (_first(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)')
                   or _first(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)'))
    lang = ""
    m = re.search(r"<html[^>]+lang=[\"']([\w\-]+)", html, re.I)
    if m:
        lang = m.group(1).lower()

    def _heads(tag: str, limit: int) -> list[str]:
        out = []
        for inner in re.findall(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", html)[:limit * 2]:
            t = _tag_text(inner)
            if 2 <= len(t) <= 140 and t not in out:
                out.append(t)
            if len(out) >= limit:
                break
        return out

    ctas = []
    for inner in re.findall(r"(?is)<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", html):
        t = _tag_text(inner)
        if 2 <= len(t) <= 40 and CTA_TEXT_RE.match(t) and t.lower() not in [c.lower() for c in ctas]:
            ctas.append(t)
        if len(ctas) >= 6:
            break

    return {
        "title": title[:180], "description": description[:300], "lang": lang,
        "h1": _heads("h1", 3), "h2": _heads("h2", 8), "ctas": ctas,
        "images": len(re.findall(r"(?i)<img\b", html)),
        "has_video": bool(re.search(r"(?i)<video\b|youtube\.com/embed|player\.vimeo\.com", html)),
        "final_url": final_url,
    }


async def fetch_page(url: str) -> dict:
    """抓一次落地页，返回正文 + 页面结构。

    抓取失败不抛异常：网络问题不该变成 500，交由上层在报告里明确写"没抓到"。
    """
    empty = {"text": "", "chars": 0, "status": 0, "fetched": False,
             "title": "", "description": "", "lang": "", "h1": [], "h2": [],
             "ctas": [], "images": 0, "has_video": False, "final_url": url}
    if not url:
        return empty
    html, status = "", 0
    for attempt in range(2):          # 网关偶发 502，重试一次比直接失败更划算
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (compatible; AdFactory/3.2)"}) as cli:
                r = await cli.get(url)
                status = r.status_code
                if r.status_code < 400:
                    html = r.text
                    break
                print("[fetch] http", r.status_code, url)
        except Exception as e:
            print("[fetch] failed:", url, str(e)[:120])
        await asyncio.sleep(0.8)
    if not html:
        return {**empty, "status": status}

    meta = parse_page_meta(html, url)
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h[1-6]|section|header|footer|td)>", "\n", cleaned)
    text = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    text = html_lib.unescape(text)
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    body = "\n".join([l for l in lines if l])
    return {**empty, **meta, "text": body, "chars": len(body), "status": status, "fetched": True}


async def fetch_page_text(url: str) -> str:
    """兼容旧调用：只要正文。"""
    return (await fetch_page(url))["text"]


def build_site_prompt(page: dict, text: str, facts: dict, url: str = "") -> str:
    """构造网站核心内容分析的用户提示词：页面结构 + 正文 + 本地已抽取事实（以此为准）。"""
    pf = {
        "product": facts.get("product"),
        "category": facts.get("category"),
        "domain": facts.get("domain"),
        "audience": facts.get("audience"),
        "geo": facts.get("geo"),
        "languages": facts.get("languages"),
        "selling_points": facts.get("selling_points"),
        "metrics": facts.get("metrics"),
        "platform_analysis": facts.get("platform_analysis"),
    }
    return (
        f"落地页 URL: {url or page.get('final_url') or '无'}\n"
        f"页面结构: 标题={page.get('title') or '无'}；"
        f"H1={page.get('h1') or '无'}；H2={page.get('h2') or '无'}；"
        f"CTA={page.get('ctas') or '无'}；META描述={page.get('description') or '无'}\n"
        f"正文:\n{(text or '')[:4000]}\n\n"
        "### 本地初步抽取事实（仅供参考，可能不准确，请以落地页正文独立判断并纠正）\n"
        f"{json.dumps(pf, ensure_ascii=False)}\n\n"
        "请基于正文与页面结构，独立产出网站核心内容 JSON；若本地抽取与正文矛盾，以正文为准。"
    )


def _local_site_analysis(facts: dict, page: dict) -> dict:
    """无模型/模型失败时的兜底：用本地事实构造自洽的 9 模块结构化分析。"""
    points = [str(x) for x in (facts.get("selling_points") or []) if x]
    metrics = [str(x) for x in (facts.get("metrics") or []) if x]
    h1 = (page or {}).get("h1") or []
    title = (page or {}).get("title") or ""
    claim = h1[0] if h1 else (title.split("|")[0].split("—")[0].strip() if title else "")
    notes = facts.get("platform_analysis") or {}
    channel = {k: {"tactics": v, "hook": "", "selling_point": "", "compliance_note": ""}
               for k, v in notes.items()}
    return {
        "positioning": {
            "product": facts.get("product"),
            "category": facts.get("category"),
            "category_key": facts.get("domain") or "app",
            "one_liner": claim,
            "differentiators": points[:2],
        },
        "value": {
            "summary": f"共 {len(points)} 条卖点，按信息密度排序。",
            "points": [{"point": p, "type": "benefit", "strength": "中", "evidence": "本地抽取"}
                       for p in points],
        },
        "proof": {
            "summary": (f"识别到 {len(metrics)} 个量化指标。" if metrics
                        else "页面没有给出可量化证明，这是当前最大的转化阻力。"),
            "metrics": [{"value": m, "kind": "scale", "label": "量化"} for m in metrics],
            "endorsements": [],
            "credibility": "来自本地抽取",
        },
        "audience": {
            "primary": facts.get("audience") or "",
            "demographics": "",
            "pain_points": [],
            "secondary": "",
        },
        "page": {
            "sections": list(h1) + list((page or {}).get("h2") or []),
            "structure_note": "",
            "conversion_path": "落地页 → 主 CTA 转化",
            "primary_cta": (((page or {}).get("ctas") or ["—"])[0]
                            if (page or {}).get("ctas") else "—"),
            "tone": "",
        },
        "channel": channel,
        "risk": {"items": [], "compliance": ""},
        "gaps": {"missing": [], "confidence": "中"},
        "next_steps": [],
        "business_nature": {
            "nature": "（本地兜底未识别，建议改用模型分析以获得准确判断）",
            "is_marketing_platform": False,
            "note": "本地兜底未接入模型，请改用模型分析以识别网站本质与定位",
        },
        "target_clients": {
            "toc": facts.get("audience") or "",
            "tob": [],
            "needs": {"advertiser": "", "channel": "", "media": ""},
        },
        "appeal_highlights": points[:2] or [],
        "nine_elements": {
            "industry": facts.get("category") or "",
            "type": "（本地兜底未识别，建议改用模型分析）",
            "category": facts.get("category") or "",
            "needs": "",
            "solution": claim or "",
            "business_model": "",
            "advantage_compare": "",
            "differentiation": "；".join(points[:2]) if points else "",
            "purpose_summary": claim or "",
        },
        "extensions": {
            "industry_insight": "",
            "competitors": "",
            "market_demand": "",
            "diff_solution": "",
            "edge_advantage": "；".join(points[:2]) if points else "",
            "recommended_media": [],
            "recommended_audience": [],
        },
        "_source": "local",
    }


async def analyze_site(db, page, text, facts, url: str = "") -> dict:
    """调用大模型产出完整网站核心内容（9 模块）。

    真实模型可用时优先用真实模型；解析失败或无模型（走 Mock 兜底）时，
    由 `_local_site_analysis` 用本地事实构造结构化结果，保证下游报告始终有内容。

    复用策略：优先专用「分析」模型；若未单独配置「分析」模型，但已配置「文案」文本模型，
    则复用「文案」模型——避免仅配了一个大模型（如 qwen-plus）却让整段落地页分析默默走模板。
    """
    prompt = build_site_prompt(page, text, facts, url)
    llm = get_llm(db, "analysis")  # 真实模型（带 Mock 兜底）或 Mock
    source_usage = "analysis"
    if not has_real(db, "analysis") and has_real(db, "copy"):
        llm = get_llm(db, "copy")
        source_usage = "copy"
    try:
        resp = await llm.chat(get_prompt(db, "site_analysis"), prompt)
        sa = parse_json(resp)
        if isinstance(sa, dict) and sa.get("positioning"):
            # 只有「确实调用了真实模型且成功」才标 llm；FallbackLLM 静默回退 Mock 时如实标 mock。
            real = has_real(db, source_usage)
            sa["_source"] = "mock" if (getattr(llm, "used_fallback", False) or not real) else "llm"
            sa["_source_usage"] = source_usage
            return sa
        print(f"[analyze_site] 模型返回无法解析为 9 模块 JSON（len={len(resp)}），回退本地构造")
    except Exception as e:
        print("[analyze_site] llm failed:", str(e)[:140])
    return _local_site_analysis(facts, page)


async def analyze_landing_page(db, url, text, page=None) -> Framework:
    """抓取（无正文时）→ 本地抽取 → 可选模型润色 → 落库。

    page 是 fetch_page 的结果，分析报告要用它的页面结构；不传则内部抓一次。
    """
    from models import LandingPage
    if page is None and url and not (text or "").strip():
        page = await fetch_page(url)
    page = page or {}
    # 正文优先用调用方给的；只给了 page（前端已经抓过）时，必须从 page 里取回来，
    # 否则 analyze_local 拿到空串，卖点会退化成"请粘贴正文"。
    if not (text or "").strip() and page.get("text"):
        text = page["text"]

    page_slim = {k: v for k, v in page.items() if k != "text"} if page else {}
    lp = LandingPage(url=url, raw_text=text, parsed_json={"page": page_slim} if page_slim else None)
    db.add(lp); db.commit(); db.refresh(lp)

    facts = analyze_local(text or "", url or "")     # 永远先做本地抽取
    data = dict(facts)
    # V4.0：调用大模型产出完整「网站核心内容」（9 模块），失败/未配置模型时回退本地结构化构造。
    site = await analyze_site(db, page, text, facts, url or "")
    if site.get("positioning"):
        pos = site["positioning"]
        if pos.get("product"):
            data["product"] = pos["product"]
        if pos.get("category"):
            data["category"] = pos["category"]
        if pos.get("category_key"):
            data["domain"] = pos["category_key"]
    if site.get("value", {}).get("points"):
        sp = [p.get("point") for p in site["value"]["points"] if p.get("point")]
        if sp:
            data["selling_points"] = sp
    if site.get("proof", {}).get("metrics"):
        ms = [m.get("value") for m in site["proof"]["metrics"] if m.get("value")]
        if ms:
            data["metrics"] = ms
    if site.get("audience", {}).get("primary"):
        data["audience"] = site["audience"]["primary"]
    # 大模型独立判断的 geo / languages：覆盖本地抽取的薄弱结论
    if isinstance(site.get("geo"), str) and site["geo"].strip():
        data["geo"] = site["geo"].strip()
    if isinstance(site.get("languages"), list):
        ll = [str(x) for x in site["languages"] if str(x).strip()]
        if ll:
            data["languages"] = ll
    # 各平台打法：优先用大模型按产品定制的 channel，缺失平台用本地 PLATFORM_NOTES 兜底，
    # 避免「所有同品类产品共用一套固定打法模板」。
    if isinstance(site.get("channel"), dict) and site["channel"]:
        local_notes = facts.get("platform_analysis") or {}
        merged = {}
        for plat in set(list(local_notes.keys()) + list(site["channel"].keys())):
            ll = site["channel"].get(plat) or {}
            merged[plat] = (ll.get("tactics") or "").strip() or local_notes.get(plat) or ""
        merged = {k: v for k, v in merged.items() if v}
        if merged:
            data["platform_analysis"] = merged
    # 按本次分析的真实来源标注，不用「是否配置了模型」代替「是否真的用了模型」。
    src = site.get("_source", "local")
    data["analyzer"] = ("llm+local" if src == "llm"
                        else "mock+local" if src == "mock" else "local")

    evidence = dict(data.get("evidence") or {})
    # 维度级来源标注：让投放人员一眼看出哪些是真实大模型分析、哪些仍是本地规则/模板兜底。
    evidence["_sources"] = {
        "product": src if src != "local" else "local",
        "category": src if src != "local" else "local",
        "selling_points": src if src != "local" else "local",
        "metrics": src if src != "local" else "local",
        "audience": src if src != "local" else "local",
        "geo": "llm" if isinstance(site.get("geo"), str) and site["geo"].strip() else "local",
        "languages": "llm" if isinstance(site.get("languages"), list) and site["languages"] else "local",
        "platform_analysis": ("llm" if isinstance(site.get("channel"), dict) and site["channel"]
                              else "local-template"),
    }
    if page:
        # 页面结构单独存一份：报告需要，前端"抽取依据"也能看到
        evidence["page"] = {k: page.get(k) for k in _PAGE_META_KEYS + ("chars", "status", "fetched", "final_url")}

    fw = Framework(
        landing_page_id=lp.id,
        product=data.get("product"),
        category=data.get("category"),
        audience=data.get("audience"),
        geo=data.get("geo"),
        languages=data.get("languages"),
        selling_points=data.get("selling_points"),
        platform_analysis=data.get("platform_analysis"),
        raw_json=evidence,
        domain=data.get("domain"),
        metrics=data.get("metrics"),
        brand_color=data.get("brand_color"),
        assets=data.get("assets"),
        analyzer=data.get("analyzer", "local"),
        site_analysis=site,
    )
    db.add(fw); db.commit(); db.refresh(fw)
    lp.parsed_json = {**data, "page": page_slim} if page_slim else data
    db.commit()
    return fw


# ----------------------------- 素材创作：落地页分析（8 字段 LLM 推理） -----------------------------
# 调用已配置的「分析 / 文案」大模型（统一走系统「大模型配置」），用推理能力产出 8 个必要字段，
# 并回传实际调用了哪个模型，便于持续跟踪各模型优劣势。
LANDING_KEYS = ["landing_framework", "landing_basic", "landing_competitors", "landing_advantages", "landing_channels"]


def get_landing_prompt(db) -> str:
    """拼接 5 段提示词为一份系统提示词（按注册顺序）。每段都可单独在「素材提示词」编辑。"""
    parts = [get_prompt(db, k) for k in LANDING_KEYS]
    return "\n\n".join([p for p in parts if p]).strip()


def build_landing_prompt(url: str, text: str, page: dict) -> str:
    """构造落地页分析的用户提示词：URL（展示）+ 页面结构 + 正文。"""
    meta_bits = []
    if page:
        if page.get("title"):
            meta_bits.append(f"标题: {page.get('title')}")
        if page.get("h1"):
            meta_bits.append(f"H1: {page.get('h1')}")
        if page.get("h2"):
            meta_bits.append(f"H2: {page.get('h2')}")
        if page.get("ctas"):
            meta_bits.append(f"CTA: {page.get('ctas')}")
        if page.get("description"):
            meta_bits.append(f"META描述: {page.get('description')}")
    meta_str = "；".join(meta_bits) if meta_bits else "无"
    return (
        f"落地页 URL: {url or '无'}\n"
        f"页面结构: {meta_str}\n"
        f"正文:\n{(text or '')[:4000]}\n\n"
        "请基于以上页面真实内容，输出 8 字段 JSON。"
    )


def _resolve_model(db):
    """返回 (llm, info)。info 记录实际调用的模型与用途，前端据此展示"用了哪个模型"。

    优先用「分析」模型；若未单独配置分析模型，但已配置「文案」文本模型，则复用「文案」模型
    （V4.22 模式：避免只配了一个大模型却让落地页分析默默走 Mock）。
    """
    candidates = []
    for c in db.query(ModelConfig).filter_by(is_active=True).all():
        us = c.usages if c.usages is not None else [c.usage]
        if "analysis" in us and c.api_key and c.base_url and c.model:
            candidates.append((c, "analysis"))
        elif "copy" in us and c.api_key and c.base_url and c.model:
            candidates.append((c, "copy"))
    cfg, usage = None, None
    for want in ("analysis", "copy"):
        best = None
        for c, role in candidates:
            if role == want and (best is None or c.id > best.id):
                best = c
        if best:
            cfg, usage = best, want
            break
    llm = get_llm(db, usage or "analysis")   # 带 Mock 兜底
    info = {"provider": "", "model": "", "role": usage or "analysis", "fallback": True}
    if cfg:
        info["provider"] = cfg.provider
        info["model"] = cfg.model or ""
        info["fallback"] = bool(getattr(llm, "used_fallback", False))
    return llm, info


def _normalize_landing(raw: dict, url: str) -> dict:
    """把模型原始输出规整为 8 字段结构（裁剪长度、保证类型）。"""
    raw = raw if isinstance(raw, dict) else {}

    def as_str(v):
        return (str(v).strip() if v is not None else "")

    def as_str_list(v, limit):
        out = []
        if isinstance(v, list):
            for x in v:
                s = as_str(x)
                if s:
                    out.append(s)
                if len(out) >= limit:
                    break
        return out

    chs = []
    for c in (raw.get("channels") or []):
        if isinstance(c, dict):
            p = as_str(c.get("platform"))
            r = as_str(c.get("reason"))
            if p:
                chs.append({"platform": p, "reason": r})
        elif isinstance(c, str):
            s = as_str(c)
            if s:
                chs.append({"platform": s, "reason": ""})
        if len(chs) >= 5:
            break

    return {
        "url": url or as_str(raw.get("url")),
        "language": as_str(raw.get("language")),
        "industry": as_str(raw.get("industry")),
        "type": as_str(raw.get("type")),
        "audience": as_str(raw.get("audience")),
        "competitors": as_str_list(raw.get("competitors"), 3),
        "advantages": as_str_list(raw.get("advantages"), 5),
        "channels": chs,
    }


def _local_landing(url: str, page: dict) -> dict:
    """无模型 / 模型失败时的本地兜底：只做最小识别（语言），其余留空，明确表示未用大模型推理。

    用户要求必须用大模型推理，因此兜底结果必须如实标注 source=local，前端提示需配置大模型。
    """
    lang = (page or {}).get("lang") or ""
    return {
        "url": url, "language": lang, "industry": "", "type": "", "audience": "",
        "competitors": [], "advantages": [], "channels": [],
    }


async def analyze_landing_concise(db, url, text, page=None) -> dict:
    """素材创作：落地页分析。抓取（无正文时）→ 拼接提示词 → 调用已配置大模型推理 → 规整 8 字段。

    返回 dict 含 8 字段 + model_info + source。source=llm 表示真用了大模型；local 表示走了兜底。
    """
    url = (url or "").strip()
    text = (text or "").strip()
    if page is None and url and not text:
        page = await fetch_page(url)
    page = page or {}
    if not text and page.get("text"):
        text = page["text"]

    sys_prompt = get_landing_prompt(db)
    user_prompt = build_landing_prompt(url, text, page)
    llm, info = _resolve_model(db)

    # 没有任何可用的真实模型配置：直接走本地兜底，明确标注
    if not info["provider"]:
        return {**_local_landing(url, page), "model_info": info, "source": "local"}

    try:
        resp = await llm.chat(sys_prompt, user_prompt)
        raw = parse_json(resp)
        if isinstance(raw, dict) and (
            raw.get("industry") or raw.get("type") or raw.get("audience")
            or raw.get("language") or raw.get("advantages") or raw.get("channels")
        ):
            data = _normalize_landing(raw, url)
            return {**data, "model_info": info, "source": "mock" if info["fallback"] else "llm"}
        print(f"[landing] 模型返回无法解析为 8 字段 JSON（len={len(resp)}），回退本地构造")
    except Exception as e:
        print("[landing] llm failed:", str(e)[:140])
    # 模型调用 / 解析失败：本地兜底，但保留已识别到的模型信息进行追溯
    return {**_local_landing(url, page), "model_info": info, "source": "local"}


# ----------------------------- 创意方向 -----------------------------
def local_angles(fw, lang="en") -> list[dict]:
    """本地生成 6 个方向：钩子来自方向模板，落到产品名与首个卖点上。"""
    raw = fit_text((fw.selling_points or [fw.product])[0], 34)[0]
    benefit = raw if detect_lang(raw) == lang else ""
    out = []
    for i, a in enumerate(ANGLE_LIBRARY):
        kit = build_copy_kit(fw, a, lang, benefit)
        out.append({
            "key": a["key"], "name": a["name"], "insight": a["insight"],
            "visual": a["visual"], "template": a["template"], "kpi": a["kpi"],
            "platform_fit": a["platform_fit"], "hook": kit["headlines"][0],
            "hook_type": a.get("hook_type"), "storyboard": kit.get("storyboard"),
            "sort": i,
        })
    return out


async def plan_angles(db, fw, platforms=None, extra=None, lang=None) -> list[Angle]:
    """生成并落库创意方向（同框架重复调用会覆盖上一版）。"""
    lang = lang or (fw.languages or ["en"])[0]
    angles = local_angles(fw, lang if lang in ("en", "es", "pt", "id") else "en")

    if has_real(db, "copy"):
        llm = get_llm(db, "copy")
        prompt = (
            f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
            f"卖点: {fw.selling_points}\n可量化指标: {fw.metrics}\n目标语言: {lang}\n"
            f"投放平台: {platforms or '未知'}\n额外要求: {extra or '无'}\n"
            "给出 6-8 个创意方向，key 只能用 pain/benefit/proof/curiosity/ugc/promo/scenario/comparison。"
        )
        try:
            resp = parse_json(await llm.chat(get_prompt(db, "angle"), prompt))
            got = {x.get("key"): x for x in (resp.get("angles") or []) if x.get("key") in ANGLE_MAP}
            for a in angles:
                g = got.get(a["key"])
                if g:
                    a["hook"] = (g.get("hook") or a["hook"])[:80]
                    a["insight"] = (g.get("insight") or a["insight"])[:200]
                    a["visual"] = (g.get("visual") or a["visual"])[:200]
        except Exception:
            pass

    db.query(Angle).filter_by(framework_id=fw.id).delete()
    rows = []
    for a in angles:
        row = Angle(framework_id=fw.id, **a)
        db.add(row); rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


# ----------------------------- 文案 -----------------------------
async def _angle_copy(db, fw, angle_key, lang, extra):
    """返回 (fields, issues)。有真实模型时先用模型写，再统一走字数对齐。"""
    angle = ANGLE_MAP.get(angle_key) or ANGLE_LIBRARY[0]
    raw_benefit = fit_text((fw.selling_points or [fw.product])[0], 34)[0]
    # 卖点只在语言一致时直接复用，否则会产出中英夹杂的标题
    benefit = raw_benefit if detect_lang(raw_benefit) == lang else ""
    kit = build_copy_kit(fw, angle, lang, benefit)

    if has_real(db, "copy"):
        llm = get_llm(db, "copy")
        prompt = (
            f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
            f"已验证卖点: {fw.selling_points}\n可用指标: {fw.metrics}\n"
            f"创意方向: {angle['name']} —— {angle['insight']}\n"
            f"语言: {lang}\n额外要求: {extra or '无'}\n"
            "headlines 每条 ≤40 字符，bodies 每条 ≤90 字符。"
        )
        try:
            resp = parse_json(await llm.chat(get_prompt(db, "copy"), prompt))
            if resp.get("headlines"):
                kit = {
                    "headlines": [str(x) for x in resp["headlines"]][:3],
                    "bodies": [str(x) for x in (resp.get("bodies") or [])][:2] or kit["bodies"],
                    "cta": resp.get("cta") or kit["cta"],
                }
        except Exception:
            pass
    return kit


def _render_spec(fw, angle_key, fields, lang, template, metric=None, design=None):
    angle = ANGLE_MAP.get(angle_key) or ANGLE_LIBRARY[0]
    headline = fields.get("headline") or fields.get("title") or fw.product
    if isinstance(headline, list):
        headline = headline[0]
    sub = fields.get("primary_text") or fields.get("body") or fields.get("description") or ""
    if isinstance(sub, list):
        sub = sub[0]
    cta = fields.get("cta") or ""
    if cta in ("LEARN_MORE", "SHOP_NOW", "DOWNLOAD", "INSTALL_MOBILE_APP", "SIGN_UP",
               "GET_OFFER", "PLAY_GAME", "SUBSCRIBE"):
        cta = {"LEARN_MORE": "Learn more", "SHOP_NOW": "Shop now", "DOWNLOAD": "Download",
               "INSTALL_MOBILE_APP": "Install", "SIGN_UP": "Sign up",
               "GET_OFFER": "Get offer", "PLAY_GAME": "Play now", "SUBSCRIBE": "Subscribe"}[cta]
    m = metric or (fw.metrics or [""])[0]
    rating_value, rating_label = _rating_from_metrics(fw.metrics)
    if m and (_num_tokens(m) & _num_tokens(headline or "")):
        # "2M" 与 "Over 2 million" 是同一个数字：字符串不相等，但画面上是重复的
        m = ""
    return {
        "template": template, "headline": headline, "sub": sub, "cta": cta,
        "brand": fw.product, "brand_color": fw.brand_color, "metric": m,
        "product_img": (fw.assets or {}).get("product"),
        "before_label": "BEFORE", "after_label": "AFTER",
        "rating_value": rating_value, "rating_label": rating_label,
        "angle_key": angle_key, "design": design or {},
    }


async def _design_spec(db, fw, key: str, template: str, lang: str, ctx: str = "") -> dict:
    """按创意方向取差异化设计规范：大模型产出（提示词管理 image），失败回退内置预设。

    返回的 spec 由 render.normalize_design 做二次校验与合并——即使模型只给了一部分字段，
    也会用该方向的内置预设补齐（背景风格/版式/字号），保证不同方向的素材视觉确实不同。

    ctx：来自「素材创作」三大提示词库的风格/配色约束（presets.build_directives 的
    design_prompt），追加到提示词骨架，使大模型在 tone/layout 上呼应所选风格与配色。
    """
    angle = ANGLE_MAP.get(key) or {}
    user_prompt = (
        f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
        f"创意方向: {angle.get('name', key)} —— {angle.get('insight', '')}\n"
        f"画面模板: {template}\n目标语言: {lang}\n"
        f"卖点: {fw.selling_points}\n"
        "请给出该方向的视觉设计规范 JSON。"
    )
    if ctx and ctx.strip():
        user_prompt += f"\n\n【素材创作风格约束】请在上述规范中呼应以下方向与风格要求：{ctx.strip()}"
    try:
        parsed = parse_json(await get_llm(db, "copy").chat(get_prompt(db, "image"), user_prompt))
        if isinstance(parsed, dict) and (parsed.get("styles") or parsed.get("style")):
            return parsed
    except Exception as e:
        print("[design] llm failed:", str(e)[:120])
    return {}


def _num_tokens(text: str) -> set:
    """把 "2M" / "2 million" / "2,000,000" 归一成同一个数量，用于判重。"""
    out = set()
    for mt in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|m|b|k)?", text or "", re.I):
        try:
            v = float(mt.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (mt.group(2) or "").lower()
        v *= {"million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9,
              "thousand": 1e3, "k": 1e3}.get(unit, 1)
        out.add(v)
    return out


def _rating_from_metrics(metrics) -> tuple[str, str]:
    """评分卡的分数只能取自原文（"5-star"/"4.8"），取不到就只放星级不放数字。"""
    metrics = list(metrics or [])
    for m in metrics:
        if m.lower().endswith("-star"):
            # 不要拼 "5★"：Arial 没有 U+2605，会渲染成方框；星级本身已经画在图上了
            return m[:-5], "star reviews"
    for m in metrics:
        if re.fullmatch(r"[0-5](?:\.\d)?", m):
            return m, "user rating"
    for m in metrics:
        if re.fullmatch(r"\d[\d.,]*[KMB]?", m):
            return m, "reviews"
    return "", "user rating"


# ----------------------------- 生产 -----------------------------
async def produce_campaign(db, fw, campaign, angle_keys, platforms, types, langs,
                           extra=None, sizes_per_platform=None,
                           video_mode="all", full_video=False, directives=None) -> list[Material]:
    keys = [k for k in (angle_keys or []) if k in ANGLE_MAP] or ["benefit"]
    # 版位数量可配：默认 4，最少 1、最多 8（超过平台实际版位数时后面的循环自然截断）
    max_sizes = max(1, min(int(sizes_per_platform or IMAGE_MAX_SIZES), 8))
    video_keys = keys if video_mode == "all" else (keys[:1] if video_mode == "first" else [])
    mats, copy_index = [], []

    # 「素材创作」三大提示词库：方向 / 风格 / 配色 解析为生成链路指令
    directives = directives or {}
    design_overrides = directives.get("design_overrides") or {}
    design_ctx = directives.get("design_prompt") or ""
    # 创意方向 → 渲染版式（画面主体）。空字符串表示「沿用内部 angle_key 的默认版式」，向后兼容。
    template_override = (directives.get("template") or "").strip()
    extra_full = " ".join(filter(None, [extra, directives.get("extra_prompt")])).strip()
    extra = extra_full  # 后续文案生成、prompt_log、视频调用统一使用增强后的提示词
    video_ctx = directives.get("video_prompt") or extra

    # 文生图大模型：未配置（无 Key/URL/Model）时返回 None，下方出图走 Pillow 模板兜底。
    img_provider = get_image(db)

    # 设计规范：每个创意方向一份（LLM 生成，失败回退内置差异预设），图片与视频关键帧共用
    # 用户所选「内容风格 / 配色」覆盖（styles 背景键 + palette 调色板）优先生效，
    # 大模型只负责在其基础上补全 tone / layout 等未指定项。
    design_map = {}
    if "image" in types or ("video" in types and video_keys):
        for k in dict.fromkeys(list(keys) + list(video_keys)):
            llm_design = await _design_spec(
                db, fw, k, ANGLE_MAP.get(k, {}).get("template", ""), langs[0], ctx=design_ctx)
            base = dict(llm_design) if isinstance(llm_design, dict) else {}
            base.update(design_overrides)
            design_map[k] = base

    # 1) 先把文案算出来（模型调用串行，避免限流），再并行出图
    copy_jobs = []
    for key in keys:
        for platform in platforms:
            for lang in langs:
                copy_jobs.append((key, platform, lang))

    rendered = []
    for key, platform, lang in copy_jobs:
        kit = await _angle_copy(db, fw, key, lang, extra)
        mapped = map_to_platform(kit, platform, fw.product)
        fields = mapped["fields"]
        validation = validate_copy(fields, platform, mapped["issues"])
        if key == "promo":
            # 本地模板不知道这个产品当下有没有活动，"限时/本周截止"这类表述必须人工核对
            validation.setdefault("problems", []).append(
                {"level": "warn", "field": "活动真实性",
                 "msg": "促销方向默认带时效表述，投放前请确认活动真实存在"})
        mats.append(Material(
            campaign_id=campaign.id, type="copy", platform=platform, language=lang,
            angle_key=key, version=1, variant="A", prompt_log=extra,
            content={"fields": fields, "char_table": char_table(fields, platform),
                     "schema": COPY_SCHEMA.get(platform, [])},
            text_content=copy_text(fields, platform), validation=validation))
        if "keyword" in types:
            kw = build_keywords(fw, key, lang)
            mats.append(Material(
                campaign_id=campaign.id, type="keyword", platform=platform, language=lang,
                angle_key=key, version=1, variant="A", prompt_log=extra,
                content=kw, text_content=keyword_text(kw),
                validation=build_validation("keyword", kw)))

        # Google 的 description 是列表，这里统一取第一条做同质化比对
        raw_text = (fields.get("primary_text") or fields.get("body")
                    or fields.get("description") or "")
        if isinstance(raw_text, list):
            raw_text = raw_text[0] if raw_text else ""
        copy_index.append({"platform": platform, "language": lang,
                           "angle_name": ANGLE_MAP[key]["name"],
                           "text": str(raw_text), "angle_key": key, "warnings": []})

        if "image" in types:
            spec = _spec_for(db, platform)
            all_sizes = list(spec.image_sizes if spec else ["1080x1080"])
            data = _render_spec(fw, key, fields, lang,
                                template_override or ANGLE_MAP[key]["template"],
                                design=design_map.get(key))
            # 文生图大模型：配置了图像模型时，按创意方向与风格生成 AI 背景，再交 Pillow 叠加版式
            if img_provider:
                bg_prompt = _build_image_prompt(fw, key, design_map.get(key), directives, lang)
                bw, bh = _size_wh(all_sizes[0]) if all_sizes else (1080, 1080)
                bgp = await img_provider.generate(
                    bg_prompt, bw, bh, f"_aibg_{campaign.id}_{platform}_{key}_{lang}.png")
                if bgp:
                    data["bg_path"] = bgp
            for size in all_sizes[:max_sizes]:
                w, h = _size_wh(size)
                fn = f"{campaign.id}_{platform}_{key}_{lang}_{w}x{h}_v1.png"
                rendered.append({"kind": "image", "angle": key, "platform": platform,
                                 "lang": lang, "size": size, "w": w, "h": h,
                                 "allowed": all_sizes,
                                 "out": os.path.join(UPLOAD_DIR, fn), "data": data})

    # 2) 并行出图（Pillow 是同步的，放线程池）
    results = await asyncio.gather(*[
        asyncio.to_thread(render_creative, item["out"], item["w"], item["h"], item["data"])
        for item in rendered
    ], return_exceptions=True)

    for item, res in zip(rendered, results):
        if isinstance(res, Exception):
            print("[render] failed:", item["out"], res)
            continue
        mats.append(Material(
            campaign_id=campaign.id, type="image", platform=item["platform"],
            language=item["lang"], angle_key=item["angle"], version=1, variant="A",
            spec_json={"size": item["size"], "template": item["data"]["template"],
                       "angle": item["angle"], "w": item["w"], "h": item["h"],
                       "design": item["data"].get("design") or {}},
            file_path=item["out"], prompt_log=extra,
            validation=build_validation("image", None,
                                        {"size": item["size"], "all_sizes": item["allowed"]})))

    # 3) 视频关键帧（每个方向一条 15s 分镜，4 张关键帧 + 首帧封面），并行渲染
    if "video" in types and video_keys:
        vtasks = []
        for key in video_keys:
            for platform in platforms:
                lang = langs[0]
                spec = _spec_for(db, platform)
                vw, vh = (1080, 1920) if "1080x1920" in (spec.image_sizes if spec else []) else (1080, 1080)
                src = next((m for m in mats if m.type == "copy" and m.angle_key == key
                            and m.platform == platform and m.language == lang), None)
                fields = (src.content or {}).get("fields", {}) if src else {}
                if not fields:
                    continue
                data = _render_spec(fw, key, fields, lang,
                                    template_override or ANGLE_MAP[key]["template"],
                                    design=design_map.get(key))
                # 文生图大模型：为关键帧生成一张 AI 背景（4 镜复用，靠 design._shot 轮换风格制造差异）
                if img_provider:
                    bg_prompt = _build_image_prompt(fw, key, design_map.get(key), directives, lang)
                    bgp = await img_provider.generate(
                        bg_prompt, vw, vh, f"_aibg_v_{campaign.id}_{platform}_{key}.png")
                    if bgp:
                        data["bg_path"] = bgp
                vtasks.append(_make_video(db, campaign, fw, key, platform, lang, data, vw, vh, extra,
                                          full_video=full_video, video_ctx=video_ctx))
        for v in await asyncio.gather(*vtasks, return_exceptions=True):
            if isinstance(v, Material):
                mats.append(v)

    for m in mats:
        m.variant = m.variant or "A"
    db.add_all(mats)
    db.commit()
    for m in mats:
        db.refresh(m)

    flag_duplicates(copy_index)
    _apply_dup_warnings(mats, copy_index)
    db.commit()
    _cleanup_ai_bgs()  # 清理中间 AI 背景图（已合成进最终素材）
    return mats


def _apply_dup_warnings(mats, copy_index):
    by_id = {}
    for m in mats:
        if m.type == "copy":
            by_id[(m.angle_key, m.platform, m.language)] = m
    for item in copy_index:
        if not item["warnings"]:
            continue
        m = by_id.get((item["angle_key"], item["platform"], item["language"]))
        if m and isinstance(m.validation, dict):
            m.validation.setdefault("problems", []).extend(
                [{"level": "warn", "field": "创意方向", "msg": w} for w in item["warnings"]])


def _shot_duration(tc: str, default: float = 3.75) -> float:
    """从 '0-3s' / '3-8s' 之类的时间码解析镜头时长（秒），异常时给均分默认值。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)", tc or "")
    if m:
        d = float(m.group(2)) - float(m.group(1))
        if 0.3 < d <= 20:
            return round(d, 2)
    return default


def _ffmpeg_exe():
    """优先 imageio-ffmpeg 自带静态二进制，其次系统 PATH 的 ffmpeg。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _fallback_shots(data: dict) -> list:
    """内置 4 镜分镜：画面文字一律取自当前素材文案（目标语言），不写拍摄说明。"""
    headline = (data.get("headline") or "").strip()
    sub = (data.get("sub") or "").strip()
    cta = (data.get("cta") or "").strip() or "Install now"
    return [
        {"t": "0-3s", "shot": "痛点开场", "visual": "问题现场：使用前的受挫瞬间，近景手持",
         "text": headline, "vo": ""},
        {"t": "3-8s", "shot": "产品演示", "visual": "核心动作演示：两步内看到结果，屏幕录屏 + 手部特写",
         "text": sub or headline, "vo": ""},
        {"t": "8-12s", "shot": "结果证明", "visual": "结果与口碑：前后对比、评分卡或真实数据截图",
         "text": sub or headline, "vo": ""},
        {"t": "12-15s", "shot": "CTA 收口", "visual": "端卡：品牌标识 + 行动按钮，尾帧停留 3 秒",
         "text": cta, "vo": cta},
    ]


def _shot_payload(data: dict, i: int, total: int, tpls: list) -> dict:
    """按镜头推进裁剪广告文案：每一帧只出现该镜该说的内容，且全部是广告文案。

    钩子只留主标题（大字抓停）→ 演示补副标（说清价值）→ 证明给证据 → 收口换 CTA 端卡。
    镜头名/时间码/画面说明/旁白一律不进画面（会烧进成片，投放前还得二次裁切），
    只存在 frames 元数据里，由素材墙在图片旁标注。
    """
    d = dict(data)
    d.pop("caption", None)
    headline = (data.get("headline") or "").strip()
    sub = (data.get("sub") or "").strip()
    cta = (data.get("cta") or "").strip()
    d["template"] = tpls[(i - 1) % len(tpls)] or data.get("template")
    if i <= 1:
        d.update(headline=headline, sub="", cta="")
    elif i >= total:
        d.update(headline=cta or headline, sub="", cta="", template="bigtype")
    elif i == 2:
        d.update(headline=headline, sub=sub, cta="")
    else:
        d.update(headline=headline, sub=sub or (data.get("metric_label") or ""), cta="")
    return d


def _stitch_mp4(frames: list, out_path: str, vw: int, vh: int):
    """把关键帧按镜头时长合成完整视频（H.264/yuv420p 无声 MP4，各平台播放器兼容）。

    每镜单独按秒数编码再用 concat 无损拼接：concat demuxer 的 duration 指令必须在末尾
    重复最后一帧，那一帧会再占一镜时长，15s 脚本会变成 18s，投放侧按规格校验直接判超长。
    返回 (ok, err)。ffmpeg 不可用或合成失败时返回 False，由调用方降级为关键帧交付。
    """
    exe = _ffmpeg_exe()
    if not exe or not frames:
        return False, "ffmpeg 不可用"
    w, h = vw - (vw % 2), vh - (vh % 2)  # yuv420p 要求偶数尺寸
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p")
    seg_dir = out_path + ".segs"
    concat = out_path + ".txt"
    try:
        os.makedirs(seg_dir, exist_ok=True)
        segs = []
        for i, f in enumerate(frames, 1):
            dur = max(0.5, float(f.get("duration") or 3.75))
            seg = os.path.join(seg_dir, f"seg{i}.mp4")
            subprocess.run([exe, "-y", "-loop", "1", "-t", f"{dur:.2f}", "-i", f["file"],
                            "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-r", "30", "-an", seg],
                           check=True, capture_output=True, timeout=180)
            segs.append(seg)
        with open(concat, "w", encoding="utf-8") as fh:
            for s in segs:
                fh.write("file '" + s.replace("'", r"'\''") + "'\n")
        subprocess.run([exe, "-y", "-f", "concat", "-safe", "0", "-i", concat,
                        "-c", "copy", "-movflags", "+faststart", out_path],
                       check=True, capture_output=True, timeout=180)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0, ""
    except Exception as e:
        return False, str(e)[:200]
    finally:
        try:
            os.remove(concat)
        except OSError:
            pass
        shutil.rmtree(seg_dir, ignore_errors=True)


async def _make_video(db, campaign, fw, key, platform, lang, data, vw, vh, extra, full_video=False, video_ctx: str = ""):
    """视频素材生产：LLM 分镜脚本 → 关键帧渲染 →（可选）合成完整视频 MP4。

    分镜脚本走「提示词管理」的 video 提示词，失败回退内置 4 镜；完整视频依赖
    ffmpeg（imageio-ffmpeg 自带），不可用时降级为关键帧 + 分镜交付，绝不阻断。
    """
    from providers import StoryboardVideo
    angle = ANGLE_MAP.get(key) or {}

    # 1) LLM 分镜脚本（文本用途模型，失败回退内置分镜）
    user_prompt = (
        f"产品: {fw.product}\n品类: {fw.category}\n受众: {fw.audience}\n地区: {fw.geo}\n"
        f"创意方向: {angle.get('name', key)} —— {angle.get('insight', '')}\n语言: {lang}\n"
        f"已验证卖点: {fw.selling_points}\n可用指标: {fw.metrics}\n"
        f"文案: headline={data.get('headline')} sub={data.get('sub')} cta={data.get('cta')}\n"
        f"平台视频规格: {(_spec_for(db, platform).video_spec if _spec_for(db, platform) else '') or '未知'}"
    )
    if video_ctx and video_ctx.strip():
        user_prompt += f"\n\n【素材创作风格约束】务必遵循以下方向与风格要求生成分镜：{video_ctx.strip()}"
    llm_shots, llm_meta = None, {}
    llm = get_llm(db, "copy")
    try:
        parsed = parse_json(await llm.chat(get_prompt(db, "video"), user_prompt))
        cand = parsed.get("shots") if isinstance(parsed, dict) else None
        if isinstance(cand, list) and 2 <= len(cand) <= 6 and all(
                isinstance(s, dict) and (s.get("visual") or s.get("text")) for s in cand):
            llm_shots = cand[:VIDEO_KEYFRAMES]
            llm_meta = {"hook": parsed.get("hook") or "", "cta": parsed.get("cta") or ""}
    except Exception as e:
        print("[video] storyboard llm failed:", str(e)[:120])

    # 2) 关键帧渲染：满画幅只画广告画面；说明/旁白/时间码留在元数据，由素材墙逐帧标注
    scenes = (llm_shots or _fallback_shots(data))[:VIDEO_KEYFRAMES]
    total = len(scenes)
    tpls = [data.get("template"), "ugc", "rating", "bigtype"]
    kf_dir = os.path.join(UPLOAD_DIR, f"{campaign.id}_{platform}_{key}_{lang}_kf")
    os.makedirs(kf_dir, exist_ok=True)
    frames = []
    for i, sc in enumerate(scenes, 1):
        tc = sc.get("t") or f"{(i - 1) * 15 // max(1, total)}-{i * 15 // max(1, total)}s"
        d = _shot_payload(data, i, total, tpls)
        # 分镜逐镜轮换背景风格，避免四帧像同一张图复制
        base_design = dict(data.get("design") or {})
        base_design["_shot"] = i - 1
        d["design"] = base_design
        out = os.path.join(kf_dir, f"kf{i}.png")
        await asyncio.to_thread(render_keyframe, out, vw, vh, d)
        frames.append({"index": i, "scene": sc.get("shot") or f"镜头{i}", "timecode": tc,
                       "note": sc.get("visual") or "", "text": sc.get("text") or "",
                       "vo": sc.get("vo") or "", "duration": _shot_duration(tc),
                       "file": out, "ref": f"{campaign.id}_{platform}_{key}_{lang}_kf/kf{i}.png"})
    cover = os.path.join(UPLOAD_DIR, f"{campaign.id}_{platform}_{key}_{lang}_cover.png")
    await asyncio.to_thread(render_creative, cover, vw, vh, data)

    # 3) 分镜脚本元信息（平台规格 / 交付物说明）
    story = await StoryboardVideo().generate(
        f"{fw.product} · {platform} · {lang}", platform, "x.mp4",
        meta={"product": fw.product, "lang": lang, "headline": data.get("headline"),
              "sub": data.get("sub"), "cta": data.get("cta"),
              "aspect": "9:16" if vh > vw else "1:1", "duration": 15,
              "spec": (spec.video_spec if (spec := _spec_for(db, platform)) else "")})
    if llm_shots:
        story["shots"] = llm_shots
        story["provider"] = "llm_storyboard"
        if llm_meta.get("hook"):
            story["hook"] = llm_meta["hook"]
        if llm_meta.get("cta"):
            story["cta"] = llm_meta["cta"]
    story["keyframes"] = frames
    story["cover"] = cover
    story["design"] = data.get("design") or {}
    story["frame_mode"] = "clean"   # 关键帧=纯广告画面，说明只在素材墙标注

    # 4) 完整视频合成（投放设置勾选「生成完整视频」时）
    if full_video:
        mp4 = os.path.join(UPLOAD_DIR, f"{campaign.id}_{platform}_{key}_{lang}_full.mp4")
        ok, err = await asyncio.to_thread(_stitch_mp4, frames, mp4, vw, vh)
        if ok:
            story["video_file"] = mp4
            story["video_note"] = "成片画面即广告素材（H.264 无声 MP4，画面内无分镜说明），可直接上传投放"
            story["note"] = "已产出分镜脚本 + 纯画面关键帧 + 完整视频 MP4；镜头说明与旁白仅在素材墙标注，可用于配音或剪辑改版。"
        else:
            story["video_error"] = err or "合成失败"
            story["note"] = f"完整视频合成失败（{err or 'ffmpeg 不可用'}），已保留关键帧与分镜脚本。"

    return Material(
        campaign_id=campaign.id, type="video", platform=platform, language=lang,
        angle_key=key, version=1, variant="A", content=story,
        file_path=(story.get("video_file") if full_video and story.get("video_file") else cover),
        prompt_log=extra, validation=build_validation("video", story))


# ----------------------------- 重生成 -----------------------------
async def regenerate_material(db, material, extra):
    from sqlalchemy import func
    fw = db.query(Framework).join(Campaign).filter(Campaign.id == material.campaign_id).first()
    maxv = db.query(func.max(Material.version)).filter(
        Material.campaign_id == material.campaign_id, Material.type == material.type,
        Material.platform == material.platform, Material.language == material.language,
        Material.angle_key == material.angle_key).scalar() or 0
    version = int(maxv) + 1
    key = material.angle_key or "benefit"
    new = Material(campaign_id=material.campaign_id, type=material.type,
                   platform=material.platform, language=material.language or "en",
                   angle_key=key, version=version, variant=variant_label(version),
                   prompt_log=extra)

    if material.type in ("copy", "keyword"):
        if material.type == "keyword":
            from creative import COPY_SCHEMA  # noqa: F401
        fields_kit = await _angle_copy(db, fw, key, material.language or "en", extra)
        mapped = map_to_platform(fields_kit, material.platform, fw.product)
        new.content = {"fields": mapped["fields"],
                       "char_table": char_table(mapped["fields"], material.platform),
                       "schema": COPY_SCHEMA.get(material.platform, [])}
        new.text_content = copy_text(mapped["fields"], material.platform)
        new.validation = validate_copy(mapped["fields"], material.platform, mapped["issues"])
    elif material.type == "image":
        sj = material.spec_json or {}
        w, h = _size_wh(sj.get("size") or "1080x1080")
        fn = f"{material.campaign_id}_{material.platform}_{key}_{material.language}_{w}x{h}_v{version}.png"
        fw_like = fw or Framework(product="Ad", selling_points=["Ad"])
        kit = await _angle_copy(db, fw_like, key, material.language or "en", extra)
        fields = map_to_platform(kit, material.platform, fw_like.product)["fields"]
        data = _render_spec(fw_like, key, fields, material.language or "en", ANGLE_MAP[key]["template"],
                            design=await _design_spec(db, fw_like, key, ANGLE_MAP[key]["template"],
                                                      material.language or "en"))
        await asyncio.to_thread(render_creative, os.path.join(UPLOAD_DIR, fn), w, h, data)
        new.file_path = os.path.join(UPLOAD_DIR, fn)
        new.spec_json = {**sj, "version": version}
        new.validation = build_validation("image", None, new.spec_json)
    elif material.type == "video":
        fw_like = fw or Framework(product="Ad", selling_points=["Ad"])
        kit = await _angle_copy(db, fw_like, key, material.language or "en", extra)
        fields = map_to_platform(kit, material.platform, fw_like.product)["fields"]
        data = _render_spec(fw_like, key, fields, material.language or "en", ANGLE_MAP[key]["template"],
                            design=await _design_spec(db, fw_like, key, ANGLE_MAP[key]["template"],
                                                      material.language or "en"))
        camp = db.query(Campaign).get(material.campaign_id)
        fv = bool((camp.options or {}).get("full_video")) if camp else False
        vobj = await _make_video(db, type("C", (), {"id": material.campaign_id})(), fw_like,
                                 key, material.platform, material.language or "en", data, 1080, 1920, extra,
                                 full_video=fv)
        new.content = vobj.content
        new.file_path = vobj.file_path
        new.validation = vobj.validation
    db.add(new); db.commit(); db.refresh(new)
    return new


# ----------------------------- 素材优化 -----------------------------
async def optimize_campaign(db, campaign, instruction, scope="all", angle_keys=None) -> dict:
    """按优化要求重出素材：先算新文案，再用同一份文案重渲染图片，保证图文一致。

    版本号递增而不是覆盖：投放人员要能对比"改之前 / 改之后"，也便于回滚。
    """
    from optimize import apply_rules, parse_instruction
    fw = db.query(Framework).filter_by(id=campaign.framework_id).first()
    if not fw:
        raise ValueError("推广框架不存在")

    rules = parse_instruction(instruction)
    mats = db.query(Material).filter_by(campaign_id=campaign.id).all()
    wanted = {k for k in (angle_keys or []) if k}
    if not mats:
        raise ValueError("该批次还没有素材，请先生成素材再优化")

    base, maxv, size_ver, base_tpl = {}, {}, {}, {}
    # 版式/配色要沿最新版本继承：拿"第一张遇到的图"会导致每轮优化都退回 v1 的版式，
    # 上一轮刚换的 bigtype 和蓝色就这么被悄悄丢掉了。
    tpl_ver, last_color, last_metric = {}, {}, {}
    for m in mats:
        angle = m.angle_key or "benefit"
        if wanted and angle not in wanted:
            continue
        lang = m.language or "en"
        v = m.version or 1
        if m.type == "copy":
            k = (angle, m.platform, lang)
            if k not in base or v > (base[k].version or 1):
                base[k] = m
        mk = (m.type, angle, m.platform, lang)
        maxv[mk] = max(maxv.get(mk, 0), v)
        if m.type == "image":
            sj = m.spec_json or {}
            sk = (angle, m.platform, lang, sj.get("size") or "1080x1080")
            if sk not in size_ver or v > (size_ver[sk].version or 1):
                size_ver[sk] = m
            tk = (angle, m.platform, lang)
            if v >= tpl_ver.get(tk, 0):
                tpl_ver[tk] = v
                base_tpl[tk] = sj.get("template") or ""
                last_color[tk] = sj.get("brand_color") or ""
                # None = 这版没记录过，渲染时不要覆盖；"" = 上一轮主动清掉了量级，要沿用
                last_metric[tk] = (sj["metric"], sj.get("rating_value") or "") if "metric" in sj else None

    if not base:
        raise ValueError("没有可优化的文案素材（当前批次可能只出了图片或视频）")

    created, do_copy, do_image = 0, scope in ("all", "copy", "image"), scope in ("all", "image")
    merged, warnings, notes, noop = {}, [], [], []
    seen = {}

    for (angle, platform, lang), copy_mat in base.items():
        raw_fields = (copy_mat.content or {}).get("fields") or {}
        if not isinstance(raw_fields, dict) or not raw_fields:
            continue
        res = apply_rules(raw_fields, rules, platform, lang, angle, fw.product or "",
                          base_tpl.get((angle, platform, lang)) or
                          (ANGLE_MAP.get(angle) or {}).get("template", "bigtype"),
                          fw.metrics)
        fields = res["fields"]

        for item in res["applied"]:
            slot = merged.setdefault(item["rule"], {
                "rule": item["rule"], "label": item["label"], "note": item["note"],
                "changes": [], "hit": 0})
            slot["hit"] += 1
            for c in item["changes"]:
                key = (c["field"], c["before"], c["after"])
                bucket = seen.setdefault(item["rule"], set())
                if key in bucket or len(slot["changes"]) >= 6:
                    continue
                bucket.add(key)
                slot["changes"].append(c)
        for w in res["warnings"]:
            if w not in warnings:
                warnings.append(w)

        # 这轮规则对这份素材到底改了什么？文案没变、版式配色也没变，
        # 就不该再出版本——否则 v2 只是 v1 的复印件，交付时会顶掉真正的最新版。
        same_copy = fields == raw_fields
        group_imgs = [img for (ag, pf, lg, _sz), img in size_ver.items()
                      if (ag, pf, lg) == (angle, platform, lang)]
        look_changed = (
            bool(res["brand_color"])
            or res["template"] != (base_tpl.get((angle, platform, lang)) or res["template"])
            # 去数字规则即使文案本来没数字，也要看图上是否杵着量级
            or (any(r["key"] == "no_numbers" for r in rules)
                and any((img.spec_json or {}).get("metric") for img in group_imgs))
        )
        if same_copy and not look_changed:
            noop.append(f"{angle}·{platform}/{lang}")
            continue

        # 1) 新文案版本
        if do_copy and not same_copy:
            cv = maxv.get(("copy", angle, platform, lang), 1) + 1
            mapped_issues = [{"field": k, "issue": "优化时按字数上限裁剪"}
                             for k in fields if isinstance(fields.get(k), str)
                             and len(fields[k]) >= _field_max(platform, k)]
            db.add(Material(
                campaign_id=campaign.id, type="copy", platform=platform, language=lang,
                angle_key=angle, version=cv, variant=variant_label(cv), prompt_log=instruction,
                content={"fields": fields, "char_table": char_table(fields, platform),
                         "schema": COPY_SCHEMA.get(platform, []), "optimized": True},
                text_content=copy_text(fields, platform),
                validation=validate_copy(fields, platform, mapped_issues)))
            maxv[("copy", angle, platform, lang)] = cv
            created += 1

        # 2) 图片：同组每个尺寸各出一张新版本，版式/配色按规则结果。
        # 同一组的多个尺寸共用一个版本号，前端按版本切换时图文才对得上。
        if do_image and (not same_copy or look_changed):
            iv, made = maxv.get(("image", angle, platform, lang), 1) + 1, 0
            # 设计规范按方向取一次，组内各尺寸共用（逐尺寸调模型只会拿到不一致的视觉）
            opt_design = await _design_spec(db, fw, angle, res["template"], lang)
            for (ag, pf, lg, size), img in size_ver.items():
                if (ag, pf, lg) != (angle, platform, lang):
                    continue
                w, h = _size_wh(size)
                spec = _render_spec(fw, angle, fields, lang, res["template"], design=opt_design)
                lm = last_metric.get((angle, platform, lang))
                if lm is not None:
                    # 上一版主动去掉的量级/评分要沿用，否则每轮都从产品数据里重新捞回来
                    spec["metric"], spec["rating_value"] = lm
                if any(r["key"] == "no_numbers" for r in rules):
                    # 文案去了数字，图上还杵着 "2M" 就自相矛盾了
                    spec["metric"] = ""
                    spec["rating_value"] = ""
                if res["brand_color"]:
                    spec["brand_color"] = res["brand_color"]
                elif last_color.get((angle, platform, lang)):
                    # 本轮没要求改色，就沿用上一版的主色
                    spec["brand_color"] = last_color[(angle, platform, lang)]
                fn = f"{campaign.id}_{platform}_{angle}_{lang}_{w}x{h}_v{iv}.png"
                out = os.path.join(UPLOAD_DIR, fn)
                try:
                    await asyncio.to_thread(render_creative, out, w, h, spec)
                except Exception as e:      # 单张失败不该让整批优化回滚
                    print("[optimize] render failed", out, e)
                    notes.append(f"{platform} {size} 渲染失败，已跳过")
                    continue
                db.add(Material(
                    campaign_id=campaign.id, type="image", platform=platform, language=lang,
                    angle_key=angle, version=iv, variant=variant_label(iv),
                    file_path=out, prompt_log=instruction,
                    spec_json={**(img.spec_json or {}), "size": size, "w": w, "h": h,
                               # 版式/配色/量级都以本次实际渲染的 spec 为准落库，
                               # 否则下一轮优化从旧 spec 读不到新颜色，蓝色会被"忘掉"
                               "template": spec.get("template"),
                               "brand_color": spec.get("brand_color"),
                               "metric": spec.get("metric"),
                               "rating_value": spec.get("rating_value"),
                               "optimized": True, "angle": angle},
                    validation=build_validation("image", None,
                                                {"size": size,
                                                 "all_sizes": (img.spec_json or {}).get("all_sizes")
                                                 or _spec_sizes(db, platform)})))
                created += 1
                made += 1
            if made:
                maxv[("image", angle, platform, lang)] = iv

    if noop:
        head = "、".join(noop[:3]) + (" 等" if len(noop) > 3 else "")
        notes.append(f"{len(noop)} 组素材本轮无改动、保持原版本（{head}）：这些文案已在平台字数上限内，"
                     f"规则模式不做会破坏语义的硬裁")
    if campaign.materials and any(m.type == "video" for m in mats):
        notes.append("视频分镜未重生成：本轮只更新文案与图片。如需同步分镜，请重新生成视频。")
    if scope == "image":
        notes.append("仅重渲染图片：文案版本也一并更新，避免图上文字与投放文案不一致。")

    db.commit()
    version = max((v for v in maxv.values()), default=1)
    return {"created": created, "version": version,
            "applied": list(merged.values()), "warnings": warnings, "notes": notes,
            "rules": rules}


def _field_max(platform: str, key: str) -> int:
    for f in COPY_SCHEMA.get(platform) or []:
        if f["key"] == key:
            return f["max"]
    return 999


def _spec_sizes(db, platform):
    spec = _spec_for(db, platform)
    return list(spec.image_sizes if spec else [])


# ----------------------------- 兼容旧调用（批量任务） -----------------------------
async def generate_campaign_materials(db, fw, campaign, platforms, types, langs, extra):
    types = [t for t in types if t in ("image", "video", "copy", "keyword")]
    if not types:
        types = ["image", "copy"]
    return await produce_campaign(db, fw, campaign, ["benefit", "proof"], platforms,
                                  types, langs, extra, sizes_per_platform=2)
