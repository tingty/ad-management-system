# 平台素材规格基线（v1.0）。可由管理员在素材库后台维护。
# copy_limits 为结构化字数红线，供规格校验使用。
PLATFORM_SPECS = [
    {
        "platform": "Facebook", "ad_placement": "Feed/Stories/Reels",
        "image_sizes": ["1080x1080", "1080x1350", "1200x628", "1080x1920"],
        "video_spec": "Feed 1-15s；Reels≤90s；1080x1080 / 1080x1920；mp4/mov",
        "copy_rules": "主文案≤125字（推荐）；标题25-40字；描述30字；语气亲和",
        "keyword_logic": "兴趣/行为定向为主，非关键词竞价",
        "copy_limits": {"title_max": 40, "description_max": 30, "primary_text_max": 125},
    },
    {
        "platform": "Google", "ad_placement": "Search/Display/UAC",
        "image_sizes": ["320x50", "300x250", "320x480", "728x90", "160x600", "1080x1920", "640x640"],
        "video_spec": "10-30s；720p/1080p；16:9 或竖版；YouTube",
        "copy_rules": "标题≤30字×3；描述≤90字×2；最终URL必填",
        "keyword_logic": "搜索词：广泛/词组/精确匹配",
        "copy_limits": {"title_max": 30, "description_max": 90},
    },
    {
        "platform": "Unity", "ad_placement": "Rewarded/Interstitial",
        "image_sizes": ["320x50", "728x90", "300x250", "160x600", "1080x1920"],
        "video_spec": "5-30s；1080x1920 / 1920x1080；mp4",
        "copy_rules": "极简 CTA（Play Now）；强视觉",
        "keyword_logic": "程序化/受众，非关键词",
        "copy_limits": {"title_max": 30, "description_max": 50},
    },
    {
        "platform": "AppLovin", "ad_placement": "App Discovery",
        "image_sizes": ["1200x1200", "300x250", "320x50", "728x90", "1080x1920"],
        "video_spec": "15-30s；1080x1920 / 1920x1080；mp4",
        "copy_rules": "利益点前置；强 CTA",
        "keyword_logic": "程序化，创意驱动",
        "copy_limits": {"title_max": 40, "description_max": 90},
    },
    {
        "platform": "Moloco", "ad_placement": "RTB DSP",
        "image_sizes": ["1200x1200", "1080x1920", "300x250", "320x50"],
        "video_spec": "15-30s；竖/横版 mp4",
        "copy_rules": "转化导向短文案",
        "keyword_logic": "程序化/受众扩展",
        "copy_limits": {"title_max": 40, "description_max": 90},
    },
    {
        "platform": "Adsterra", "ad_placement": "Popunder/Banner/Native",
        "image_sizes": ["300x250", "728x90", "160x600", "320x50", "300x600", "336x280", "980x120"],
        "video_spec": "300x250 / 480x360 / 640x480 等",
        "copy_rules": "直给利益点，短",
        "keyword_logic": "上下文/受众；CPM/CPA",
        "copy_limits": {"title_max": 40, "description_max": 60},
    },
    {
        "platform": "Mintegral", "ad_placement": "Mobile DSP/Playable",
        "image_sizes": ["1200x1200", "1080x1920", "300x250", "320x50", "728x90"],
        "video_spec": "15-30s；支持 HTML5 可玩广告",
        "copy_rules": "互动/可玩引导",
        "keyword_logic": "程序化，可玩优先",
        "copy_limits": {"title_max": 40, "description_max": 90},
    },
]

PLATFORMS = [s["platform"] for s in PLATFORM_SPECS]
MATERIAL_TYPES = ["image", "video", "copy", "keyword"]
LANGUAGES = ["en", "es", "pt", "id", "zh", "ja", "ko", "ar", "fr", "de"]
