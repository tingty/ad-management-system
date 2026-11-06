"""素材创作三大提示词库（创意方向 / 内容风格 / 配色方案）与生成映射。

这是「素材创作」模块的提示词单一数据源：
- 前端「素材提示词管理」与「素材创作」生成均从此处取数；
- 后端 /api/settings/creative-presets 返回同样的库，便于后续运营在后台扩充。

内容来源：《素材创作模块功能优化说明书》V2.1 第 6.2 / 6.3 / 6.4 节（P0 内置常量）。

映射关系：
- STYLE_TO_BG：内容风格（S01-S26）→ 渲染层背景风格键（render.py 的 STYLE_KEYS）；
- COLOR_TO_PALETTE：配色方案（C01-C16）→ 调色板覆盖（accent / bg1 / bg2 / fg / sub / card / on_accent + light 标记）；
- build_directives()：把用户所选的 方向 / 风格 / 配色 / 视频市场洞察 解析成可直接注入
  生成链路的指令（extra_prompt / design_overrides / design_prompt / video_prompt）。
"""

from __future__ import annotations

from typing import Optional


# ----------------------------- 创意方向库（D01–D20） -----------------------------
# 每个方向是一套创意母题：影响文案调性与画面叙事（注入 copy / design / video 提示词）。
CREATIVE_DIRECTIONS: list[dict] = [
    {"id": "D01", "name": "卖点直击", "desc": "直接展示产品核心功能 / 卖点", "applies": "图片/视频",
     "prompt": "画面直接呈现产品核心功能与关键卖点，主视觉突出产品本身，配一句短文案点明价值，避免铺垫与无关信息。"},
    {"id": "D02", "name": "痛点唤醒", "desc": "描绘未解决问题，引出产品", "applies": "图片/视频",
     "prompt": "先呈现用户未被满足的痛点场景（混乱 / 焦虑 / 低效），再引出产品作为解决方案，形成强对比，放大“没有它”的代价。"},
    {"id": "D03", "name": "场景代入", "desc": "真实使用场景，提升代入感", "applies": "图片/视频",
     "prompt": "以真实生活 / 使用场景为画面背景，让用户代入“这就是我”，自然带出产品在场景中的价值，弱化广告感。"},
    {"id": "D04", "name": "信任背书", "desc": "数据 / 奖项 / 认证 / 权威机构", "applies": "图片/视频",
     "prompt": "画面突出权威背书元素：数据图表、奖项徽章、认证标识、知名机构 logo，建立可信度与专业感。"},
    {"id": "D05", "name": "限时优惠", "desc": "折扣 / 促销，制造紧迫", "applies": "图片/视频",
     "prompt": "突出折扣力度与“限时 / 倒计时”标签，营造稀缺与紧迫，价格与优惠信息醒目，引导立即行动。"},
    {"id": "D06", "name": "对比测评", "desc": "使用前 vs 使用后 / 竞品对比", "applies": "图片/视频",
     "prompt": "采用左右或前后对比构图，明确标注 before / after 或本品 vs 竞品，量化差异，让优势一目了然。"},
    {"id": "D07", "name": "用户证言", "desc": "真实用户评价 / 案例故事", "applies": "图片/视频",
     "prompt": "以真实用户口吻与评价 / 案例故事为主视觉，配合头像与评分，增强真实感与从众效应。"},
    {"id": "D08", "name": "国潮流潮", "desc": "国风 / 潮流文化元素", "applies": "图片/视频",
     "prompt": "融入国风或潮流文化视觉符号（传统纹样、潮流字体、街头元素），贴合年轻化表达与节日节点。"},
    {"id": "D09", "name": "极简高级", "desc": "少即是多，高级留白", "applies": "图片/视频",
     "prompt": "大留白、克制的元素与高级质感，突出单一主体与一句主张，拒绝堆砌，传递高端调性。"},
    {"id": "D10", "name": "科技未来", "desc": "科技感 / 未来视觉", "applies": "图片/视频",
     "prompt": "运用科技蓝、光效、网格与未来感构图，传达先进与前瞻，适合工具 / 硬件 / AI 类产品。"},
    {"id": "D11", "name": "生活方式", "desc": "向往的生活状态表达", "applies": "图片/视频",
     "prompt": "以理想生活方式画面唤起向往（自由、精致、松弛），产品作为美好生活的组成部分而非主角。"},
    {"id": "D12", "name": "节日氛围", "desc": "节点 / 节日情绪", "applies": "图片/视频",
     "prompt": "结合节日色彩与符号（红金、灯饰、礼物、雪花），营造应景情绪与消费冲动。"},
    {"id": "D13", "name": "权威数据", "desc": "行业数据建立专业感", "applies": "图片",
     "prompt": "以大字号行业数据 / 统计图表为主视觉，建立专业与权威感，让结论可被快速读取。"},
    {"id": "D14", "name": "幽默趣味", "desc": "轻松有趣，拉近距离", "applies": "视频",
     "prompt": "用幽默桥段、夸张反差或趣味表演抓住注意力，降低广告感，拉近与受众的距离。"},
    {"id": "D15", "name": "情感共鸣", "desc": "情绪价值 / 共鸣故事", "applies": "视频",
     "prompt": "以情绪叙事引发共鸣（亲情 / 奋斗 / 孤独 / 喜悦），在情感高点自然带出产品，提升记忆度。"},
    {"id": "D16", "name": "身份认同", "desc": "圈层 / 身份归属感", "applies": "图片/视频",
     "prompt": "呈现圈层符号与身份标签，让目标人群产生“这就是我”的归属感，强化品牌与圈层的绑定。"},
    {"id": "D17", "name": "稀缺紧迫", "desc": "限量 / 抢购心理", "applies": "图片/视频",
     "prompt": "强调限量、抢购、库存紧张，配合计数与紧迫文案，促成即时行动。"},
    {"id": "D18", "name": "新品尝鲜", "desc": "新品上市尝鲜感", "applies": "图片/视频",
     "prompt": "突出“新”与首发感，营造尝鲜冲动，配合新品专属视觉与标签。"},
    {"id": "D19", "name": "本地化", "desc": "本地文化 / 语言适配", "applies": "图片/视频",
     "prompt": "融入本地文化符号、节俗与语言习惯，提升本地受众的亲近感与相关性。"},
    {"id": "D20", "name": "KOL 同款", "desc": "达人 / 网红同款种草", "applies": "视频",
     "prompt": "以达人视角开箱 / 种草 / 实测，口播自然，营造“同款”跟风效应。"},
]


# ----------------------------- 创意内容风格库（S01–S26） -----------------------------
# 影响画面美术风格与背景处理；通过 STYLE_TO_BG 映射到渲染层背景风格键。
CONTENT_STYLES: list[dict] = [
    {"id": "S01", "name": "纯色背景图", "desc": "单一品牌色 / 纯色底，突出主体", "applies": "通用",
     "prompt": "纯色或品牌色背景，主体居中突出，无多余装饰，干净聚焦。"},
    {"id": "S02", "name": "人物实拍风", "desc": "真实人物摄影质感", "applies": "图片/视频",
     "prompt": "真实人物摄影质感，自然光线与表情，增强真实可信。"},
    {"id": "S03", "name": "动漫二次元", "desc": "动画 / 二次元角色演绎", "applies": "通用",
     "prompt": "二次元 / 动画美术风格，鲜明角色与夸张表情，吸引年轻受众。"},
    {"id": "S04", "name": "风景自然", "desc": "自然 / 城市风光烘托", "applies": "通用",
     "prompt": "以自然或城市风光为氛围底，产品融入场景，清新通透。"},
    {"id": "S05", "name": "国画水墨", "desc": "中国传统水墨意境", "applies": "图片/视频",
     "prompt": "水墨晕染、留白与书法笔意，东方意境，适合国风题材。"},
    {"id": "S06", "name": "油画古典", "desc": "油画质感 / 古典美学", "applies": "图片/视频",
     "prompt": "油画笔触与古典光影、厚重肌理，传达高级艺术感。"},
    {"id": "S07", "name": "扁平插画", "desc": "扁平化矢量插画", "applies": "图片",
     "prompt": "扁平矢量插画，明快色块与简练造型，现代亲和。"},
    {"id": "S08", "name": "3D 渲染", "desc": "三维建模渲染质感", "applies": "通用",
     "prompt": "三维建模与渲染，材质光感立体，科技与高级感兼具。"},
    {"id": "S09", "name": "赛博朋克", "desc": "霓虹 / 未来都市", "applies": "通用",
     "prompt": "赛博朋克霓虹、雨夜都市与故障光效，强未来感与冲击力。"},
    {"id": "S10", "name": "复古胶片", "desc": "胶片颗粒 / 复古色调", "applies": "通用",
     "prompt": "胶片颗粒、漏光与复古色调，怀旧质感。"},
    {"id": "S11", "name": "极简几何", "desc": "几何图形 / 大量留白", "applies": "图片",
     "prompt": "几何形状与大量留白，理性秩序与极简美学。"},
    {"id": "S12", "name": "波普艺术", "desc": "高饱和撞色波普", "applies": "图片",
     "prompt": "波普艺术高饱和撞色与网点，活泼潮流。"},
    {"id": "S13", "name": "手绘涂鸦", "desc": "手绘 / 涂鸦质感", "applies": "图片",
     "prompt": "手绘线条与涂鸦笔触，随性活泼的年轻表达。"},
    {"id": "S14", "name": "孟菲斯", "desc": "Memphis 拼接色块", "applies": "图片",
     "prompt": "孟菲斯风格几何拼接、波点与亮色碰撞，趣味装饰感。"},
    {"id": "S15", "name": "蒸汽波", "desc": "Vaporwave 粉紫渐变", "applies": "图片/视频",
     "prompt": "蒸汽波粉紫渐变、网格与古典雕塑混搭，梦幻复古未来。"},
    {"id": "S16", "name": "低多边形", "desc": "Low Poly 几何块面", "applies": "图片",
     "prompt": "低多边形块面造型，抽象几何与渐变光影。"},
    {"id": "S17", "name": "像素风", "desc": "8-bit 像素艺术", "applies": "图片",
     "prompt": "8-bit 像素块造型与复古游戏配色，怀旧游戏感。"},
    {"id": "S18", "name": "莫兰迪色系", "desc": "低饱和高级灰", "applies": "通用",
     "prompt": "莫兰迪低饱和灰调，柔和高级，温润不刺眼。"},
    {"id": "S19", "name": "新中式", "desc": "现代中式美学", "applies": "通用",
     "prompt": "现代中式留白与极简线条，传统意境当代表达。"},
    {"id": "S20", "name": "INS 风", "desc": "小清新 / 网红风", "applies": "图片/视频",
     "prompt": "清新明亮、柔和滤镜与生活方式构图，网红打卡质感。"},
    {"id": "S21", "name": "商务专业", "desc": "商务蓝 / 专业稳重", "applies": "图片/视频",
     "prompt": "商务蓝与稳重排版，专业可信，适合 B 端与工具类。"},
    {"id": "S22", "name": "糖果色", "desc": "马卡龙甜美", "applies": "图片/视频",
     "prompt": "马卡龙糖果色，甜美柔和，适合女性与生活方式。"},
    {"id": "S23", "name": "暗黑哥特", "desc": "暗黑 / 金属质感", "applies": "视频",
     "prompt": "暗黑基调、金属与哥特符号，神秘酷感。"},
    {"id": "S24", "name": "剪纸风", "desc": "镂空剪纸艺术", "applies": "图片",
     "prompt": "剪纸镂空层叠与民俗纹样，手工温度与民族风。"},
    {"id": "S25", "name": "霓虹光影", "desc": "霓虹光效 / 光污染美学", "applies": "视频",
     "prompt": "霓虹光效与光污染色彩，赛博夜景与动感转场。"},
    {"id": "S26", "name": "故障艺术", "desc": "Glitch 故障特效", "applies": "视频",
     "prompt": "Glitch 故障错位与 RGB 分离，前卫数字艺术感。"},
]


# ----------------------------- 配色方案库（C01–C16） -----------------------------
# 通过 COLOR_TO_PALETTE 转换为渲染层调色板覆盖（十六进制）。
# C12 品牌同色系 = 跟随品牌色（不覆盖，返回 None）。
COLOR_SCHEMES: list[dict] = [
    {"id": "C01", "name": "多彩渐变", "desc": "多彩渐变 / 彩虹过渡", "applies": "通用",
     "prompt": "使用多彩渐变与彩虹过渡，活力明快，吸引眼球。"},
    {"id": "C02", "name": "简洁单色", "desc": "单一主色 + 留白", "applies": "通用",
     "prompt": "单一主色配合大量留白，克制高级，焦点清晰。"},
    {"id": "C03", "name": "深色高级", "desc": "深色背景 + 高光", "applies": "通用",
     "prompt": "深色背景衬托，高光与微光提升质感，沉稳高级。"},
    {"id": "C04", "name": "浅色清新", "desc": "浅色底 + 柔和色", "applies": "通用",
     "prompt": "浅色背景与柔和色调，干净清新，舒适亲和。"},
    {"id": "C05", "name": "纯色块", "desc": "大面积纯色平铺", "applies": "通用",
     "prompt": "大面积纯色平铺，强视觉冲击与品牌识别。"},
    {"id": "C06", "name": "莫兰迪", "desc": "低饱和高级灰组合", "applies": "通用",
     "prompt": "莫兰迪低饱和灰调组合，柔和高级，协调耐看。"},
    {"id": "C07", "name": "马卡龙", "desc": "甜美粉彩", "applies": "图片/视频",
     "prompt": "马卡龙粉彩色系，甜美柔和，年轻女性向。"},
    {"id": "C08", "name": "高对比撞色", "desc": "强对比双色", "applies": "图片",
     "prompt": "强对比双色碰撞，视觉张力强，记忆点突出。"},
    {"id": "C09", "name": "金橙暖调", "desc": "暖色 / 促销氛围", "applies": "图片/视频",
     "prompt": "金橙暖色调，温暖促销与食欲感，适合大促。"},
    {"id": "C10", "name": "蓝绿冷调", "desc": "冷静 / 科技 / 医疗", "applies": "图片/视频",
     "prompt": "蓝绿冷色调，冷静科技与洁净专业感。"},
    {"id": "C11", "name": "黑白灰", "desc": "极简无彩色", "applies": "通用",
     "prompt": "黑白灰无彩色，极简高级，强调结构与质感。"},
    {"id": "C12", "name": "品牌同色系", "desc": "跟随品牌色衍生（默认）", "applies": "通用",
     "prompt": "以解析出的品牌色为主色，自动衍生邻近色与对比色，确保与品牌档案一致。"},
    {"id": "C13", "name": "霓虹荧光", "desc": "荧光高亮", "applies": "视频",
     "prompt": "荧光高亮配色，夜光与能量感，适合潮流视频。"},
    {"id": "C14", "name": "大地色", "desc": "棕 / 米 / 自然色", "applies": "图片/视频",
     "prompt": "棕米大地色系，自然质朴，温润亲和。"},
    {"id": "C15", "name": "国风朱红", "desc": "朱红 + 墨黑 + 金", "applies": "图片/视频",
     "prompt": "朱红配墨黑与金，传统国风庄重喜庆。"},
    {"id": "C16", "name": "糖果撞色", "desc": "多糖果色拼接", "applies": "图片",
     "prompt": "多糖果色拼接碰撞，活泼童趣，年轻化。"},
]


# ----------------------------- 风格 → 渲染背景键 -----------------------------
# 内容风格库（S01-S26）映射到 render.py 的 STYLE_KEYS（含本模块新增的 solid/ink/oil/
# cyber/retro/vapor/pixel/paper/neon/glitch/geo）。
STYLE_TO_BG: dict[str, str] = {
    "S01": "solid", "S02": "spotlight", "S03": "vapor", "S04": "wave",
    "S05": "ink", "S06": "oil", "S07": "geo", "S08": "radial",
    "S09": "cyber", "S10": "retro", "S11": "geo", "S12": "halftone",
    "S13": "paper", "S14": "geo", "S15": "vapor", "S16": "geo",
    "S17": "pixel", "S18": "gradient", "S19": "ink", "S20": "light_panel",
    "S21": "split", "S22": "wave", "S23": "vignette", "S24": "paper",
    "S25": "neon", "S26": "glitch",
}


# ----------------------------- 风格键 → 文生图视觉描述 -----------------------------
# 文生图大模型（qwen-image 等）无法理解 Pillow 风格键（如 "cyber"/"split"），
# 需要把它翻译成模型能落地的具体视觉描述。这里把 STYLE_KEYS 逐一映射成
# 英文画面说明，拼接进 _build_image_prompt，让所选「内容风格 / 创意方向」真正改变背景。
STYLE_VISUAL: dict[str, str] = {
    "gradient": "smooth diagonal color gradient backdrop with soft light transition",
    "radial": "radial glow emanating from center, luminous halo fading to dark edges",
    "split": "bold diagonal split composition with two contrasting color blocks colliding",
    "wave": "flowing wave-like curves and clean airy lines, fresh and light",
    "halftone": "halftone dot pattern and pop-art texture, playful dot gradient",
    "stripes": "diagonal stripes texture suggesting authentic user-generated realism",
    "spotlight": "dramatic dark scene with a single spotlight beam on the subject, high contrast",
    "light_panel": "clean light panel / soft card surface, bright trustworthy background",
    "vignette": "immersive vignette darkening toward edges, atmospheric depth",
    "solid": "solid brand-tone background, clean and focused, single dominant color",
    "ink": "east-asian ink-wash painting mood, soft ink diffusion and negative space",
    "oil": "oil-painting texture with classical chiaroscuro and rich brushwork",
    "cyber": "neon-lit cyberpunk cityscape, glowing blue-purple grid lines, futuristic",
    "retro": "retro film grain, light leaks and vintage color grading, nostalgic",
    "vapor": "vaporwave pink-purple gradient with grid horizon and classical sculpture silhouette",
    "pixel": "8-bit pixel art blocks with retro game palette, chunky pixelated shapes",
    "paper": "hand-drawn paper doodle texture, sketchy lines, casual youthful feel",
    "neon": "neon glow and light-pollution color streaks, energetic night-city vibe",
    "glitch": "glitch art with RGB channel split and digital displacement, avant-garde",
    "geo": "geometric shapes and generous negative space, rational minimalist order",
}


def style_visual(key: str) -> str:
    """风格键 → 文生图可用的英文视觉描述；未知键回退中性描述。"""
    return STYLE_VISUAL.get(key) or "modern advertising visual backdrop"


# ----------------------------- 创意方向 → 文生图情绪描述 -----------------------------
# 文生图提示词按「创意方向」区分画面情绪/构图意图。把 D01-D20 翻译成简短英文情绪，
# 让不同方向产出情绪不同的背景（痛点=暗场张力，促销=对撞冲击，对比=左右对照…）。
DIRECTION_MOOD: dict[str, str] = {
    "D01": "benefit-forward: clean hero shot of the product with its core value made obvious",
    "D02": "pain-point awakening: dark tense scene amplifying the cost of not having the solution",
    "D03": "scenario immersion: real-life usage environment the viewer can step into",
    "D04": "trust building: authoritative badges, charts and certification cues, credible",
    "D05": "limited-time promo: high-impact discount energy, urgency and celebration",
    "D06": "before-vs-after comparison: clear left/right contrast of old vs new",
    "D07": "user testimonial: authentic, candid real-person vibe, social proof",
    "D08": "trendy cultural: oriental or street-culture symbols, youthful and festive",
    "D09": "minimal luxury: generous negative space, restrained elegant single subject",
    "D10": "tech futurism: glowing tech-blue, grid lines and forward-looking sci-fi mood",
    "D11": "lifestyle aspiration: desirable free and refined way of living, product as part of it",
    "D12": "festive mood: holiday colors and symbols, warm celebratory impulse",
    "D13": "authority data: huge statistic number as the dominant subject, professional",
    "D14": "humor: light-hearted exaggerated contrast that lowers ad feel",
    "D15": "emotional resonance: touching story moment that earns memory",
    "D16": "identity belonging: circle/tribe symbols, 'this is me' belonging",
    "D17": "scarcity urgency: low stock / rushing energy, immediate action",
    "D18": "new arrival: fresh launch excitement, debut exclusivity",
    "D19": "localization: local cultural symbols and language cues, familiar and relevant",
    "D20": "KOL same-style: creator unboxing / review vibe, follow-the-trend energy",
}


def palette_prompt(palette: dict | None) -> str:
    """调色板覆盖 → 文生图可用的颜色描述（如 'warm orange #FF8A1E on deep brown #2A1402'）。"""
    if not isinstance(palette, dict):
        return ""
    accent = palette.get("accent")
    bg1 = palette.get("bg1")
    out = []
    if accent:
        out.append(f"accent color {accent}")
    if bg1:
        out.append(f"background base {bg1}")
    if not out:
        return ""
    return "Color palette: " + ", ".join(out) + "."


# ----------------------------- 配色 → 渲染调色板覆盖 -----------------------------
# 十六进制调色板。字段：accent 强调色 / bg1 背景主色 / bg2 背景次色 /
# fg 正文色 / sub 次要文字色 / card 卡片色 / on_accent 强调底上的文字色 / light 是否浅底。
# C12 不在表中 → 返回 None（跟随品牌色，render 默认行为）。
COLOR_TO_PALETTE: dict[str, dict] = {
    "C01": {"accent": "#FF5C8A", "bg1": "#20143A", "bg2": "#3B2A6B", "fg": "#FFFFFF", "sub": "#C9C2E8", "card": "#FFFFFF", "on_accent": "#FFFFFF", "light": False},
    "C02": {"accent": "#FFB020", "bg1": "#161616", "bg2": "#2A2A2A", "fg": "#FFFFFF", "sub": "#B8B8B8", "card": "#FFFFFF", "on_accent": "#1A1A1A", "light": False},
    "C03": {"accent": "#C9A24B", "bg1": "#0E0E12", "bg2": "#1B1B22", "fg": "#FFFFFF", "sub": "#C7C2B6", "card": "#FFFFFF", "on_accent": "#0E0E12", "light": False},
    "C04": {"accent": "#2E9BE6", "bg1": "#EAF3FB", "bg2": "#D6E8F6", "fg": "#16313F", "sub": "#4A6678", "card": "#FFFFFF", "on_accent": "#FFFFFF", "light": True},
    "C05": {"accent": "#FF5C5C", "bg1": "#C0392B", "bg2": "#922B21", "fg": "#FFFFFF", "sub": "#F7D7D2", "card": "#FFFFFF", "on_accent": "#FFFFFF", "light": False},
    "C06": {"accent": "#A7B0A0", "bg1": "#6E7268", "bg2": "#565A52", "fg": "#F2F1EC", "sub": "#D6D4CC", "card": "#FFFFFF", "on_accent": "#3A3A32", "light": False},
    "C07": {"accent": "#FF9EC4", "bg1": "#FFE3EE", "bg2": "#FBD0E2", "fg": "#7A3B52", "sub": "#B06A82", "card": "#FFFFFF", "on_accent": "#FFFFFF", "light": True},
    "C08": {"accent": "#00E5FF", "bg1": "#0A0A0A", "bg2": "#1A1A1A", "fg": "#FFFFFF", "sub": "#9FE9F2", "card": "#FFFFFF", "on_accent": "#0A0A0A", "light": False},
    "C09": {"accent": "#FF8A1E", "bg1": "#2A1402", "bg2": "#4A2406", "fg": "#FFFFFF", "sub": "#F3D2A8", "card": "#FFFFFF", "on_accent": "#2A1402", "light": False},
    "C10": {"accent": "#19C3B1", "bg1": "#06262A", "bg2": "#0E3D42", "fg": "#FFFFFF", "sub": "#BFE9E4", "card": "#FFFFFF", "on_accent": "#06262A", "light": False},
    "C11": {"accent": "#FFFFFF", "bg1": "#0D0D0D", "bg2": "#1F1F1F", "fg": "#FFFFFF", "sub": "#9A9A9A", "card": "#FFFFFF", "on_accent": "#0D0D0D", "light": False},
    "C13": {"accent": "#39FF14", "bg1": "#05060A", "bg2": "#0C1018", "fg": "#FFFFFF", "sub": "#B6FFC9", "card": "#FFFFFF", "on_accent": "#05060A", "light": False},
    "C14": {"accent": "#B07A4A", "bg1": "#2A1D12", "bg2": "#422C1B", "fg": "#F3E7D8", "sub": "#D8BEA2", "card": "#FFFFFF", "on_accent": "#2A1D12", "light": False},
    "C15": {"accent": "#C8102E", "bg1": "#1A0505", "bg2": "#330A0A", "fg": "#FBE3D6", "sub": "#E6A99A", "card": "#FFFFFF", "on_accent": "#1A0505", "light": False},
    "C16": {"accent": "#FF6FB5", "bg1": "#3A1A4A", "bg2": "#5A2A6B", "fg": "#FFFFFF", "sub": "#F3D2E8", "card": "#FFFFFF", "on_accent": "#3A1A4A", "light": False},
}


# ----------------------------- 创意方向 → 渲染版式（画面主体 / 构图） -----------------------------
# 这是「创意方向」真正驱动视觉的关键：之前方向只进了文案提示词，画面主体完全由内部
# 8 个 angle_key 决定，所以切换创意方向图片/视频完全不变。这里把每个 D 映射到一个
# 渲染版式（render.py 的 template），让选不同方向产出不同「画面里画什么」。
# 取值必须是 render.py 已实现的版式：bigtype / stat / rating / promo / ugc / compare / scenario。
DIRECTION_TO_TEMPLATE: dict[str, str] = {
    "D01": "bigtype",   # 卖点直击：主视觉大字突出产品
    "D02": "bigtype",   # 痛点唤醒：聚光暗场 + 大字
    "D03": "scenario",  # 场景代入：上下分区，场景面板
    "D04": "rating",    # 信任背书：评分 / 认证卡
    "D05": "promo",     # 限时优惠：折扣角标
    "D06": "compare",   # 对比测评：左右对照
    "D07": "ugc",       # 用户证言：UGC 手机框
    "D08": "bigtype",   # 国潮流潮：大字 + 国风背景
    "D09": "bigtype",   # 极简高级：留白大字
    "D10": "bigtype",   # 科技未来：大字 + 科技背景
    "D11": "bigtype",   # 生活方式：大字 + 清新背景
    "D12": "promo",     # 节日氛围：折扣角标
    "D13": "stat",      # 权威数据：大字号数字主体
    "D14": "bigtype",   # 幽默趣味：大字（视频）
    "D15": "bigtype",   # 情感共鸣：大字（视频）
    "D16": "bigtype",   # 身份认同：大字 + 几何背景
    "D17": "promo",     # 稀缺紧迫：折扣角标
    "D18": "promo",     # 新品尝鲜：折扣角标
    "D19": "bigtype",   # 本地化：大字 + 几何背景
    "D20": "ugc",       # KOL 同款：UGC 手机框（视频）
}

# ----------------------------- 创意方向 → 兜底背景风格键 -----------------------------
# 当用户「没有」单独选内容风格(S)时，按创意方向自带背景，保证只切方向画面背景也会变
# （而非恒为品牌色渐变）。取值必须是 render.py 的 STYLE_KEYS。
DIRECTION_TO_BG: dict[str, str] = {
    "D01": "solid",       # 纯色聚焦
    "D02": "spotlight",   # 暗场聚光
    "D03": "vignette",    # 暗角沉浸场景
    "D04": "light_panel", # 浅色可信卡
    "D05": "split",       # 对撞色块
    "D06": "split",       # 分栏对比
    "D07": "stripes",     # 斜纹真实感
    "D08": "ink",         # 水墨国风
    "D09": "solid",       # 极简纯色
    "D10": "cyber",       # 赛博科技
    "D11": "wave",        # 清新波浪
    "D12": "radial",      # 节日光晕
    "D13": "halftone",    # 点阵数据感
    "D14": "paper",       # 手绘轻松
    "D15": "vignette",    # 情绪暗角
    "D16": "geo",         # 几何身份感
    "D17": "split",       # 对撞紧迫
    "D18": "radial",      # 新品光晕
    "D19": "geo",         # 本地几何
    "D20": "stripes",     # UGC 斜纹
}


# ----------------------------- 索引辅助 -----------------------------
def _index(items: list[dict]) -> dict[str, dict]:
    return {it["id"]: it for it in items}


DIRECTIONS_BY_ID = _index(CREATIVE_DIRECTIONS)
STYLES_BY_ID = _index(CONTENT_STYLES)
COLORS_BY_ID = _index(COLOR_SCHEMES)

LIB_MAP = {
    "directions": CREATIVE_DIRECTIONS,
    "styles": CONTENT_STYLES,
    "colors": COLOR_SCHEMES,
}


def get_preset(lib: str, pid: Optional[str]) -> Optional[dict]:
    """按库名（directions / styles / colors）与编号取单个预设；不存在返回 None。"""
    if not pid:
        return None
    return _index(LIB_MAP.get(lib, []))[pid]


def creative_presets_payload() -> dict:
    """GET /api/settings/creative-presets 的返回体。"""
    return {
        "directions": CREATIVE_DIRECTIONS,
        "styles": CONTENT_STYLES,
        "colors": COLOR_SCHEMES,
    }


def build_directives(
    creative_direction: Optional[str] = None,
    content_style: Optional[str] = None,
    color_scheme: Optional[str] = None,
    market_insight: Optional[str] = None,
    lang: str = "en",
) -> dict:
    """把用户所选的 方向 / 风格 / 配色 / 视频市场洞察 解析成生成链路可直接使用的指令。

    返回：
      - direction_text / style_text / color_text：人类可读的提示词指令（用于拼接）；
      - extra_prompt：注入文案生成（copy）的提示词（方向 + 风格 + 配色）；
      - design_prompt：注入视觉设计规范生成（_design_spec）的提示词；
      - design_overrides：渲染层覆盖项（styles 背景键、palette 调色板覆盖）；
      - video_prompt：注入视频分镜的提示词（含可选市场洞察）。
    若某项未选，则对应指令为空，不影响既有生成逻辑（向后兼容）。
    """
    d = get_preset("directions", creative_direction)
    s = get_preset("styles", content_style)
    c = get_preset("colors", color_scheme)

    direction_text = d["prompt"] if d else ""
    style_text = s["prompt"] if s else ""
    color_text = c["prompt"] if c else ""

    parts = [p for p in (direction_text, style_text, color_text) if p]
    extra_prompt = "；".join(parts)

    design_parts = []
    if d:
        design_parts.append(f"创意方向：{d['name']} —— {direction_text}")
    if s:
        design_parts.append(f"内容风格：{s['name']} —— {style_text}")
    if c:
        design_parts.append(f"配色：{c['name']} —— {color_text}")
    design_prompt = "；".join(design_parts)

    # 渲染层覆盖：背景风格键 + 调色板
    # 背景优先级：用户选了「内容风格」→ 用它的映射；没选则回落到「创意方向」自带背景，
    # 保证即便只切了方向、不动风格，画面背景也随之改变（而非恒为品牌色渐变）。
    overrides: dict = {}
    bg_key = None
    if s and content_style in STYLE_TO_BG:
        bg_key = STYLE_TO_BG[content_style]
    elif d and creative_direction in DIRECTION_TO_BG:
        bg_key = DIRECTION_TO_BG[creative_direction]
    if bg_key:
        overrides["styles"] = [bg_key]
    if c and color_scheme in COLOR_TO_PALETTE:
        overrides["palette"] = dict(COLOR_TO_PALETTE[color_scheme])

    # 创意方向 → 渲染版式（画面主体 / 构图）。这是「创意方向」真正驱动视觉的关键一环：
    # 之前方向只进了文案提示词，画面主体完全由内部 8 个 angle_key 决定，所以换方向画面不变。
    template = DIRECTION_TO_TEMPLATE.get(creative_direction) or ""

    # 视频提示词：在文案指令基础上，可选叠加“市场洞察再创作”
    video_parts = list(parts)
    if market_insight and market_insight.strip():
        video_parts.append(
            "借鉴以下市场总结再创作（将行业 / 竞品 / 市场需求 / 差异化方案 / 特色优势映射到"
            f"“钩子—痛点—方案—证明—行动”五段编排）：{market_insight.strip()}")
    video_prompt = "；".join(video_parts)

    return {
        "direction_id": creative_direction,
        "style_id": content_style,
        "color_id": color_scheme,
        "direction_text": direction_text,
        "style_text": style_text,
        "color_text": color_text,
        "extra_prompt": extra_prompt,
        "design_prompt": design_prompt,
        "design_overrides": overrides,
        "template": template,
        "video_prompt": video_prompt,
    }
