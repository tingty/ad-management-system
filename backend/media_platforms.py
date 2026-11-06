"""
营销推广的媒体平台设置 —— 平台规格目录（单一数据源）。

这是「素材创作 → 营销推广的媒体平台设置」模块的平台单一数据源：
- 前端选中平台后，据此展示「支持的图片素材数量 / 规格 / 尺寸信息」；
- 默认按「常规使用方案」预选版位与尺寸、给出默认生成数量，用户可按需增删；
- 后端文案 / 图片生成按此目录取版位、尺寸、字数红线与常规用法。

覆盖平台（与用户需求一致）：Facebook / Google / Mintegral / Unity / Adsterra / AppLovin / TikTok。
注意：TikTok 在旧版 specs_data 中缺失，这里补齐；Mintegral/AppLovin 即用户原文的 Mitegral/Applovin。

字段说明（每个平台）：
  platform          平台名（与后端 COPY_SCHEMA / 前端枚举对齐）
  placements        广告版位（位置）列表，含该版位支持尺寸与是否默认预选
  image_sizes       该平台支持的全部图片尺寸（供总览）
  recommended_sizes 常规方案默认勾选的尺寸（"尽量按常规使用方案设置"）
  recommended_count 常规方案默认生成图片数量
  copy_limits       结构化字数红线（标题/正文/描述/主文案上限），供文案校验
  usage             常规使用方案说明（人读）
  cta_options       可选 CTA 文案（展示文案可从此选择）
"""

# 各平台常规版位与尺寸（基于主流投放规范整理，供展示与预选）
MEDIA_PLATFORMS = [
    {
        "platform": "Facebook",
        "image_sizes": ["1080x1080", "1080x1350", "1200x628", "1080x1920"],
        "recommended_sizes": ["1080x1080", "1080x1350", "1080x1920"],
        "recommended_count": 3,
        "copy_limits": {"title_max": 40, "description_max": 30, "primary_text_max": 125},
        "usage": "信息流(Feed)以方形/竖版为主，快拍(Stories)/Reels 用全屏竖版；主文案≤125、标题≤40、描述≤30。常规测试 3 张：1 方版 + 1 竖版 + 1 横版。",
        "cta_options": ["Shop Now", "Learn More", "Download", "Install App", "Sign Up", "Get Offer", "Play Game", "Subscribe"],
        "placements": [
            {"id": "feed", "name": "信息流 Feed", "sizes": ["1080x1080", "1080x1350", "1200x628"],
             "desc": "主页信息流，方形/竖版/横版横滑", "default": True},
            {"id": "stories", "name": "快拍 Stories", "sizes": ["1080x1920"],
             "desc": "全屏竖版沉浸式", "default": True},
            {"id": "reels", "name": "Reels", "sizes": ["1080x1920"],
             "desc": "短视频流，强互动", "default": False},
        ],
    },
    {
        "platform": "Google",
        "image_sizes": ["300x250", "336x280", "728x90", "160x600", "320x50", "970x250", "320x480", "1080x1920", "640x640"],
        "recommended_sizes": ["300x250", "728x90", "320x50", "1080x1920"],
        "recommended_count": 4,
        "copy_limits": {"title_max": 30, "description_max": 90},
        "usage": "展示广告(Display)以 300x250/728x90/320x50 横幅为主，UAC 用竖版 1080x1920；标题≤30、描述≤90。常规测试 4 张覆盖主要版位。",
        "cta_options": ["Learn More", "Shop Now", "Download", "Install", "Sign Up", "Get Started"],
        "placements": [
            {"id": "display_mrec", "name": "展示广告 MREC", "sizes": ["300x250", "336x280"],
             "desc": "中等矩形，信息流内嵌", "default": True},
            {"id": "display_leader", "name": "展示广告 Leaderboard", "sizes": ["728x90"],
             "desc": "页首横幅", "default": True},
            {"id": "display_mobile", "name": "展示广告 移动横幅", "sizes": ["320x50", "320x480"],
             "desc": "移动端横幅/插屏", "default": True},
            {"id": "uac", "name": "UAC 竖版", "sizes": ["1080x1920", "640x640"],
             "desc": "应用广告系列竖版大图", "default": True},
            {"id": "display_half", "name": "展示广告 半页", "sizes": ["300x600", "970x250"],
             "desc": "大尺寸高曝光", "default": False},
        ],
    },
    {
        "platform": "Unity",
        "image_sizes": ["1080x1920", "320x480", "320x50", "728x90"],
        "recommended_sizes": ["1080x1920", "320x50"],
        "recommended_count": 2,
        "copy_limits": {"title_max": 30, "body_max": 50, "cta_max": 20},
        "usage": "游戏/工具类首选，Rewarded/Interstitial 用全屏竖版 1080x1920，Banner 用 320x50；极简 CTA（Play Now）。常规测试 2 张：竖版 + 横幅。",
        "cta_options": ["Play Now", "Install Now", "Download", "Tap to Play", "Get the App"],
        "placements": [
            {"id": "rewarded", "name": "激励视频 Rewarded", "sizes": ["1080x1920"],
             "desc": "全屏竖版，强视觉", "default": True},
            {"id": "interstitial", "name": "插屏 Interstitial", "sizes": ["1080x1920", "320x480"],
             "desc": "全屏/插屏", "default": True},
            {"id": "banner", "name": "横幅 Banner", "sizes": ["320x50", "728x90"],
             "desc": "底部横幅", "default": False},
        ],
    },
    {
        "platform": "AppLovin",
        "image_sizes": ["1200x1200", "1080x1920", "300x250", "320x50", "728x90"],
        "recommended_sizes": ["1200x1200", "1080x1920", "320x50"],
        "recommended_count": 3,
        "copy_limits": {"title_max": 40, "body_max": 90, "cta_max": 20},
        "usage": "App 安装导向，大图 1200x1200 与竖版 1080x1920 为主，利益点前置 + 强 CTA；标题≤40、正文≤90。常规测试 3 张。",
        "cta_options": ["Install Now", "Download", "Get the App", "Play Now", "Try Free"],
        "placements": [
            {"id": "app_discovery", "name": "App Discovery 大图", "sizes": ["1200x1200", "1080x1920"],
             "desc": "应用发现流大图", "default": True},
            {"id": "mrec", "name": "MREC", "sizes": ["300x250"],
             "desc": "中等矩形", "default": True},
            {"id": "banner", "name": "横幅 Banner", "sizes": ["320x50", "728x90"],
             "desc": "底部横幅", "default": False},
        ],
    },
    {
        "platform": "Adsterra",
        "image_sizes": ["300x250", "728x90", "160x600", "320x50", "300x600", "336x280", "980x120"],
        "recommended_sizes": ["300x250", "728x90", "320x50"],
        "recommended_count": 3,
        "copy_limits": {"title_max": 40, "description_max": 60, "cta_max": 20},
        "usage": "多元广告位（Popunder/Banner/Native），直给利益点、短文案；标题≤40、描述≤60。常规测试 3 张覆盖主流版位。",
        "cta_options": ["Click Here", "Learn More", "Get Now", "Try Free", "Download", "Join Now"],
        "placements": [
            {"id": "banner_mrec", "name": "Banner / MREC", "sizes": ["300x250", "336x280"],
             "desc": "中等矩形横幅", "default": True},
            {"id": "leader", "name": "Leaderboard", "sizes": ["728x90", "980x120"],
             "desc": "页首横幅", "default": True},
            {"id": "skyscraper", "name": "Skyscraper", "sizes": ["160x600", "300x600"],
             "desc": "竖条高曝光", "default": True},
            {"id": "mobile", "name": "Mobile Banner", "sizes": ["320x50"],
             "desc": "移动横幅", "default": False},
        ],
    },
    {
        "platform": "Mintegral",
        "image_sizes": ["1200x1200", "1080x1920", "300x250", "320x50", "728x90"],
        "recommended_sizes": ["1080x1920", "1200x1200", "320x50"],
        "recommended_count": 3,
        "copy_limits": {"title_max": 40, "body_max": 90, "cta_max": 20},
        "usage": "移动 DSP + 可玩广告，竖版 1080x1920 与方版 1200x1200 为主，互动/可玩引导；标题≤40、正文≤90。常规测试 3 张。",
        "cta_options": ["Play Now", "Install Now", "Tap to Play", "Download", "Get the App"],
        "placements": [
            {"id": "rewarded", "name": "Rewarded / Interstitial", "sizes": ["1080x1920", "320x480"],
             "desc": "全屏竖版/插屏", "default": True},
            {"id": "mrec", "name": "MREC", "sizes": ["300x250", "1200x1200"],
             "desc": "中等矩形/大图", "default": True},
            {"id": "banner", "name": "横幅 Banner", "sizes": ["320x50", "728x90"],
             "desc": "底部横幅", "default": False},
        ],
    },
    {
        "platform": "TikTok",
        "image_sizes": ["1080x1920", "1080x1080", "720x1280", "1280x720"],
        "recommended_sizes": ["1080x1920", "1080x1080"],
        "recommended_count": 2,
        "copy_limits": {"title_max": 40, "body_max": 100, "cta_max": 20},
        "usage": "以全屏竖版 1080x1920（In-Feed/TopView/Spark）为主，方版 1080x1080 用于信息流；标题≤40、文案≤100。常规测试 2 张（竖版 + 方版）。",
        "cta_options": ["Shop Now", "Learn More", "Download", "Install", "Sign Up", "Get Quote", "Book Now"],
        "placements": [
            {"id": "in_feed", "name": "In-Feed 信息流", "sizes": ["1080x1920", "720x1280"],
             "desc": "全屏竖版沉浸式", "default": True},
            {"id": "topview", "name": "TopView / Brand Takeover", "sizes": ["1080x1920"],
             "desc": "开屏超级曝光", "default": True},
            {"id": "square", "name": "方版信息流", "sizes": ["1080x1080"],
             "desc": "方版投放", "default": False},
            {"id": "horizontal", "name": "横版", "sizes": ["1280x720"],
             "desc": "横版素材", "default": False},
        ],
    },
]

# 平台名 -> 规格 的索引
MEDIA_PLATFORM_MAP = {p["platform"]: p for p in MEDIA_PLATFORMS}


def get_media_platform(name: str) -> dict | None:
    """按平台名取规格；不存在返回 None。"""
    return MEDIA_PLATFORM_MAP.get(name)


def list_media_platforms() -> list[dict]:
    """返回全部平台规格（供前端构建选择器与展示）。"""
    return MEDIA_PLATFORMS
