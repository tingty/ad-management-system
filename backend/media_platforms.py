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

V4.40 / F08：目录从「按平台名 + 尺寸字符串」升级为**版本化交付规则**。
- 每个版位补 `ad_product` / `asset_role` / `os`，避免 Google RSA 文案混到 UAC 图片、
  以及同尺寸不同用途被当成同一交付物；
- 规则分三层：`hard`（服务端强制，模型调用前拦截）/ `policy`（业务政策，显式提示）
  / `advisory`（建议，不阻断）；
- `SPEC_SOURCE` / `SPEC_VERIFIED_ON` 明确规则来源与核验日期：**本目录是内部整理，
  不是官方投放规范的永久标准**，上线前须按官方文档复核并更新 `SPEC_VERSION`。
"""

# ---------------------------------------------------------------------------
# V4.40 / F08：规则版本、来源与三层规则
# ---------------------------------------------------------------------------
import re

SPEC_VERSION = "2026-11-10.3"
SPEC_SOURCE = "内部整理：media_platforms.py + 《广告素材平台问题诊断与AI改造实施说明书》v1.0 静态审查"
SPEC_VERIFIED_ON = ""      # 空 = 尚未按各平台官方文档核验；核验后填 YYYY-MM-DD
SPEC_DISCLAIMER = ("目录中的尺寸、字数与安全区为内部参考，不是官方投放规范的永久标准；"
                   "正式投放前须按平台官方文档复核，并同步更新 SPEC_VERSION / SPEC_VERIFIED_ON。")

#: 服务端强制上限。总像素按全部任务累加，用于在调用模型前挡住异常请求。
MEDIA_LIMITS = {
    "max_slots": 24,
    "max_total_pixels": 40_000_000,
    "max_slot_pixels": 8_300_000,
    "min_side": 16,
    "max_side": 4096,
    "max_copy_variants": 40,
}

MEDIA_RULES = {
    "spec_version": SPEC_VERSION,
    "spec_source": SPEC_SOURCE,
    "spec_verified_on": SPEC_VERIFIED_ON,
    "disclaimer": SPEC_DISCLAIMER,
    "limits": dict(MEDIA_LIMITS),
    # 强制规则：违反即在调用任何模型 / 文生图接口之前返回明确错误
    "hard": [
        "platform 必须是目录中的已知平台，未知平台不得静默回退到其它平台 schema",
        "slots.size 必须为 WxH 且在平台允许尺寸清单内，边长与单张像素数在上限内",
        "slots 数量与累计像素总量不得超过 MEDIA_LIMITS",
        "concept_index 若提供，必须是非负整数且落在本次文案组合范围内",
        "V4.44 / N04：任务若标注 placement / placement_id，必须能解析到目录版位，"
        "且尺寸属于该版位的 sizes；未知版位与尺寸错配在调用模型前拒绝",
    ],
    # 业务政策：不阻断生成，但必须在结果 / 导出里显式标注，不允许静默替换
    "policy": [
        "同一批次混用不同 ad_product 时逐张标注适用产品，不合并为同一交付物",
        "Google RSA 文案字段与 UAC 图片素材分开标注，避免把 RSA 标题当应用广告素材",
        "品牌、价格、评价等事实不得由目录或域名推导补齐（见 V4.39 / F02）",
        "未核验官方规则时，导出只标注内部规则版本，不宣称符合平台审核规范",
    ],
    # 建议：仅提示，不阻断
    "advisory": [
        "优先使用 recommended_sizes 覆盖主要版位，再按需扩展",
        "小横幅需为文字与 Logo 预留安全区，避免贴边裁切",
        "规则更新必须附来源链接与核验日期，不把本目录的旧尺寸当永久标准",
    ],
}

_SIZE_RE = re.compile(r"^(\d{1,5})[xX×](\d{1,5})$")


class MediaRuleError(ValueError):
    """F08：调用模型前被规则挡下；errors 为可直接展示给用户的原因列表。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors))


def parse_size(size: str) -> tuple[int, int]:
    """严格解析 `1080x1080`；不合法时抛 ValueError（含可读原因）。"""
    m = _SIZE_RE.match(str(size or "").strip())
    if not m:
        raise ValueError(f"尺寸格式不合法：{size!r}，应形如 1080x1080")
    w, h = int(m.group(1)), int(m.group(2))
    if not (MEDIA_LIMITS["min_side"] <= w <= MEDIA_LIMITS["max_side"]
            and MEDIA_LIMITS["min_side"] <= h <= MEDIA_LIMITS["max_side"]):
        raise ValueError(f"尺寸 {w}x{h} 超出允许边长 "
                         f"[{MEDIA_LIMITS['min_side']}, {MEDIA_LIMITS['max_side']}]")
    if w * h > MEDIA_LIMITS["max_slot_pixels"]:
        raise ValueError(f"尺寸 {w}x{h} 单张像素 {w * h:,} 超过上限 "
                         f"{MEDIA_LIMITS['max_slot_pixels']:,}")
    return w, h


#: 每个版位的交付语义（platform → placement id → 规则）。
#: asset_role 相同 + 尺寸相同 = 默认视为重复任务（F07 去重依据）；
#: 广告产品不同仍可通过前端「保留同尺寸不同资产角色」显式保留。
PLACEMENT_RULES: dict[str, dict[str, dict]] = {
    "Facebook": {
        "feed": {"ad_product": "Facebook Feed Image Ad", "asset_role": "feed_image", "os": "iOS/Android/Web"},
        "stories": {"ad_product": "Facebook Stories", "asset_role": "story_vertical", "os": "iOS/Android"},
        "reels": {"ad_product": "Facebook Reels", "asset_role": "reels_vertical", "os": "iOS/Android"},
    },
    "Google": {
        "display_mrec": {"ad_product": "Google Display (上传式展示图)", "asset_role": "display_banner", "os": "Web"},
        "display_leader": {"ad_product": "Google Display (上传式展示图)", "asset_role": "display_banner", "os": "Web"},
        "display_mobile": {"ad_product": "Google Display (上传式展示图)", "asset_role": "display_banner", "os": "Android/iOS Web"},
        "display_half": {"ad_product": "Google Display (上传式展示图)", "asset_role": "display_banner", "os": "Web"},
        "uac": {"ad_product": "Google App Campaign (UAC)", "asset_role": "app_portrait", "os": "Android/iOS"},
    },
    "Unity": {
        "rewarded": {"ad_product": "Unity Rewarded", "asset_role": "fullscreen_portrait", "os": "Android/iOS"},
        "interstitial": {"ad_product": "Unity Interstitial", "asset_role": "fullscreen_portrait", "os": "Android/iOS"},
        "banner": {"ad_product": "Unity Banner", "asset_role": "banner", "os": "Android/iOS"},
    },
    "AppLovin": {
        "app_discovery": {"ad_product": "AppLovin App Discovery", "asset_role": "app_large", "os": "Android/iOS"},
        "mrec": {"ad_product": "AppLovin MREC", "asset_role": "display_banner", "os": "Android/iOS"},
        "banner": {"ad_product": "AppLovin Banner", "asset_role": "banner", "os": "Android/iOS"},
    },
    "Adsterra": {
        "banner_mrec": {"ad_product": "Adsterra Banner / MREC", "asset_role": "display_banner", "os": "Web"},
        "leader": {"ad_product": "Adsterra Leaderboard", "asset_role": "display_banner", "os": "Web"},
        "skyscraper": {"ad_product": "Adsterra Skyscraper", "asset_role": "display_banner", "os": "Web"},
        "mobile": {"ad_product": "Adsterra Mobile Banner", "asset_role": "banner", "os": "Android/iOS Web"},
    },
    "Mintegral": {
        "rewarded": {"ad_product": "Mintegral Rewarded / Interstitial", "asset_role": "fullscreen_portrait", "os": "Android/iOS"},
        "mrec": {"ad_product": "Mintegral MREC", "asset_role": "display_banner", "os": "Android/iOS"},
        "banner": {"ad_product": "Mintegral Banner", "asset_role": "banner", "os": "Android/iOS"},
    },
    "TikTok": {
        "in_feed": {"ad_product": "TikTok In-Feed", "asset_role": "in_feed_vertical", "os": "Android/iOS"},
        "topview": {"ad_product": "TikTok TopView", "asset_role": "splash_vertical", "os": "Android/iOS"},
        "square": {"ad_product": "TikTok In-Feed Square", "asset_role": "feed_image", "os": "Android/iOS"},
        "horizontal": {"ad_product": "TikTok Horizontal", "asset_role": "horizontal_still", "os": "Android/iOS"},
    },
    # V4.44 / N04：目录补齐 Moloco 图片 / 原生角色。规格为内部整理，
    # SPEC_VERIFIED_ON 为空，正式投放前须按账户广告产品与官方文档复核。
    "Moloco": {
        "image_square": {"ad_product": "Moloco Image Creative", "asset_role": "feed_image", "os": "Android/iOS"},
        "image_vertical": {"ad_product": "Moloco Image Creative", "asset_role": "story_vertical", "os": "Android/iOS"},
        "image_horizontal": {"ad_product": "Moloco Image Creative", "asset_role": "horizontal_still", "os": "Android/iOS"},
        "native": {"ad_product": "Moloco Native", "asset_role": "native_image", "os": "Android/iOS"},
    },
}

_UNKNOWN_ROLE = {"ad_product": "未标注广告产品", "asset_role": "unspecified", "os": "unknown"}

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
    # V4.44 / N04：Moloco 图片素材按国家 / 系统 / 角色组织，并保留文件大小限制提示。
    # 目录为内部整理（SPEC_VERIFIED_ON 为空），不是官方核验结论。
    {
        "platform": "Moloco",
        "image_sizes": ["1080x1080", "1080x1920", "1200x628", "600x600"],
        "recommended_sizes": ["1080x1080", "1080x1920", "1200x628"],
        "recommended_count": 3,
        "copy_limits": {"title_max": 40, "body_max": 90, "cta_max": 20},
        "usage": "图片 / 原生角色按国家与系统分别组织；官方图片指南强调地区差异与文件大小限制。"
                 "本目录尺寸为内部整理，正式投放前须按账户广告产品复核。",
        "cta_options": ["Install Now", "Shop Now", "Learn More", "Book Now"],
        "placements": [
            {"id": "image_square", "name": "图片 · 方版", "sizes": ["1080x1080", "600x600"],
             "desc": "图片创意方版", "default": True},
            {"id": "image_vertical", "name": "图片 · 竖版", "sizes": ["1080x1920"],
             "desc": "图片创意竖版", "default": True},
            {"id": "image_horizontal", "name": "图片 · 横版", "sizes": ["1200x628"],
             "desc": "图片创意横版", "default": True},
            {"id": "native", "name": "原生 · 主图", "sizes": ["1200x628", "1080x1080"],
             "desc": "原生广告主图，与小图标分开交付", "default": False},
        ],
    },
]

# 平台名 -> 规格 的索引（大小写不敏感的别名便于旧调用兼容）
MEDIA_PLATFORM_MAP = {p["platform"]: p for p in MEDIA_PLATFORMS}
_PLATFORM_ALIASES = {k.lower(): k for k in MEDIA_PLATFORM_MAP}


def canonical_platform(name: str) -> str:
    return _PLATFORM_ALIASES.get(str(name or "").strip().lower(), "")


def validate_platform(name: str) -> str:
    """F08：未知平台必须显式拒绝，不能静默套用其它平台的文案 schema。"""
    key = canonical_platform(name)
    if not key:
        raise MediaRuleError([
            f"未知媒体平台：{name!r}；当前规则版本 {SPEC_VERSION} 支持："
            + "、".join(MEDIA_PLATFORM_MAP.keys()),
            "请从「素材创作 → 营销推广的媒体平台设置」选择已配置平台；系统不会静默改用其它平台规则。",
        ])
    return key


def placement_rule(platform: str, placement_id: str) -> dict:
    return (PLACEMENT_RULES.get(platform, {}).get(placement_id)
            or dict(_UNKNOWN_ROLE))


def resolve_placement(platform: str, placement: str = "",
                      placement_id: str = "") -> dict:
    """V4.44 / N04：按完整规则主键解析版位，未知版位不静默降级。

    返回目录中的版位（含 sizes / asset_role / ad_product / os）；找不到抛
    `MediaRuleError`，错误信息直接指出无效的 id 或名称与该平台可用版位。
    """
    key = canonical_platform(platform)
    spec = MEDIA_PLATFORM_MAP.get(key)
    if not spec:
        raise MediaRuleError([f"未知媒体平台：{platform!r}（规则版本 {SPEC_VERSION}）"])
    pid, pname = str(placement_id or "").strip(), str(placement or "").strip()
    if not pid and not pname:
        raise MediaRuleError([f"{key} 任务未标注版位：请提供 placement_id 或 placement；"
                              "系统不再把未标注版位静默当作 unspecified 放行"])
    for pl in spec.get("placements", []):
        if (pid and pl["id"] == pid) or (pname and pl["name"] == pname):
            rule = PLACEMENT_RULES.get(key, {}).get(pl["id"])
            if not rule:
                raise MediaRuleError([f"{key} 版位 {pl['id']} 未登记交付语义（ad_product / "
                                     "asset_role / os），不能生成可交付图片"])
            return {**pl, **rule}
    known = "、".join(f"{pl['id']}({pl['name']})" for pl in spec.get("placements", []))
    raise MediaRuleError([f"{key} 未知广告版位：id={pid or '（空）'} / name={pname or '（空）'}；"
                          f"规则版本 {SPEC_VERSION} 支持：{known}"])


def _enrich(spec: dict) -> dict:
    out = dict(spec)
    rules = PLACEMENT_RULES.get(spec["platform"], {})
    out["placements"] = [{**pl, **rules.get(pl["id"], dict(_UNKNOWN_ROLE))}
                         for pl in spec.get("placements", [])]
    out["ad_products"] = sorted({r["ad_product"] for r in rules.values()})
    out["spec_version"] = SPEC_VERSION
    out["spec_source"] = SPEC_SOURCE
    out["spec_verified_on"] = SPEC_VERIFIED_ON
    out["spec_disclaimer"] = SPEC_DISCLAIMER
    out["rules"] = MEDIA_RULES
    return out


def get_media_platform(name: str) -> dict | None:
    """按平台名取规格（含版位交付语义与规则版本）；不存在返回 None。"""
    key = canonical_platform(name)
    return _enrich(MEDIA_PLATFORM_MAP[key]) if key else None


def list_media_platforms() -> list[dict]:
    """返回全部平台规格（供前端构建选择器与任务矩阵）。"""
    return [_enrich(p) for p in MEDIA_PLATFORMS]


def allowed_sizes(platform: str) -> set[str]:
    """允许尺寸 = 平台总览尺寸 ∪ 所有版位尺寸（避免目录漏登记导致误拒）。"""
    spec = MEDIA_PLATFORM_MAP.get(canonical_platform(platform))
    if not spec:
        return set()
    out = set(spec.get("image_sizes") or [])
    for pl in spec.get("placements", []):
        out.update(pl.get("sizes") or [])
    return out


def match_placement(platform: str, placement: str = "", placement_id: str = "") -> dict:
    """前端可能传版位 id 或展示名；两者都尝试匹配，匹配不到返回未标注规则。"""
    spec = MEDIA_PLATFORM_MAP.get(canonical_platform(platform))
    if not spec:
        return {}
    for pl in spec.get("placements", []):
        if (placement_id and pl["id"] == placement_id) or (placement and pl["name"] == placement):
            return {**pl, **placement_rule(spec["platform"], pl["id"])}
    return {}


def media_rules_payload() -> dict:
    """`GET /api/media-rules`：把规则版本与限制显式暴露给前端，避免前后端各写一套。"""
    from industry_profiles import list_profiles
    return {
        **MEDIA_RULES,
        "platforms": {p: sorted(allowed_sizes(p)) for p in MEDIA_PLATFORM_MAP},
        "industry_placement_preferences": {
            x["key"]: x.get("placement_preferences", []) for x in list_profiles()
        },
    }


def validate_task_matrix(platform: str, slots: list, total_pixels: int | None = None,
                         variant_count: int = 0, profile: dict | None = None) -> dict:
    """F08：在调用任何模型 / 文生图之前校验整批任务。

    返回 `{"slots": [...], "meta": {...}}`；不合规则抛 `MediaRuleError`，
    errors 中逐条给出可读原因。全部尺寸与广告产品由**服务端目录**重新解析，
    不信任前端传入的 ad_product / spec_version。
    """
    errors: list[str] = []
    key = canonical_platform(platform)
    if not key:
        errors.append(f"未知媒体平台：{platform!r}（规则版本 {SPEC_VERSION}）")
        raise MediaRuleError(errors)
    rows = list(slots or [])
    if not rows:
        errors.append("任务清单为空：请至少选择一个广告版位")
        raise MediaRuleError(errors)
    if len(rows) > MEDIA_LIMITS["max_slots"]:
        errors.append(f"任务数 {len(rows)} 超过上限 {MEDIA_LIMITS['max_slots']}，请减少版位或分批生成")

    allowed = allowed_sizes(key)
    normalized: list[dict] = []
    pixels = 0
    seen: set[tuple] = set()
    dropped: list[dict] = []
    products: set[str] = set()
    placement_warnings: list[str] = []
    for i, raw in enumerate(rows):
        slot = raw if isinstance(raw, dict) else {}
        size = str(slot.get("size") or "").strip()
        if size.lower().replace("×", "x") not in {s.lower() for s in allowed}:
            errors.append(f"第 {i + 1} 个任务尺寸 {size or '(空)'} 不在 {key} 允许清单内")
            continue
        try:
            w, h = parse_size(size)
        except ValueError as e:
            errors.append(f"第 {i + 1} 个任务：{e}")
            continue
        pixels += w * h
        ci = slot.get("concept_index")
        if ci is not None:
            try:
                ci = int(ci)
            except (TypeError, ValueError):
                errors.append(f"第 {i + 1} 个任务 concept_index 不是整数：{ci!r}")
                ci = None
            else:
                if ci < 0 or (variant_count and ci >= variant_count):
                    errors.append(f"第 {i + 1} 个任务 concept_index={ci} 超出本次文案组合范围"
                                 f"（0..{max(0, variant_count - 1)}）")
        # V4.44 / N04：完整规则主键 = platform + placement + ad_product + asset_role + size。
        # 传了版位就必须能解析，且尺寸必须属于该版位；未知版位不再静默返回 unspecified。
        has_placement = bool(str(slot.get("placement") or slot.get("placement_id") or "").strip())
        if has_placement:
            try:
                pl = resolve_placement(key, slot.get("placement") or "",
                                       slot.get("placement_id") or "")
            except MediaRuleError as e:
                errors.append(f"第 {i + 1} 个任务：" + "；".join(e.errors))
                continue
            pl_sizes = {str(s).lower() for s in (pl.get("sizes") or [])}
            if size.lower().replace("×", "x") not in pl_sizes:
                errors.append(
                    f"第 {i + 1} 个任务尺寸 {size} 与版位 {pl['id']}({pl['name']}) 不匹配；"
                    f"该版位仅支持 {'、'.join(sorted(pl_sizes)) or '（无）'}")
                continue
        else:
            pl = match_placement(key, "", "") or {}
            placement_warnings.append(
                f"第 {i + 1} 个任务未标注版位，按旧调用兼容放行（asset_role=unspecified，"
                "不可作为已核验的版位交付物）")
        role = pl.get("asset_role") or _UNKNOWN_ROLE["asset_role"]
        product = pl.get("ad_product") or _UNKNOWN_ROLE["ad_product"]
        products.add(product)
        # 前端已确认的任务矩阵（带 concept_index）服务端不再删行，避免预览与实际不一致；
        # 仅旧调用（concept_index 为空）才按「同尺寸 + 同资产角色」合并无意义重复任务。
        dedupe_key = (size.lower(), role, pl.get("os") or "unknown", ci)
        row = {
            "size": size.lower(), "placement": slot.get("placement") or pl.get("name") or "",
            "placement_id": slot.get("placement_id") or pl.get("id") or "",
            "concept_index": ci,
            "ad_product": product,
            "asset_role": role,
            "os": pl.get("os") or "unknown",
            "spec_version": SPEC_VERSION,
            "w": w, "h": h,
        }
        if ci is None and dedupe_key in seen:
            dropped.append({"size": row["size"], "placement": row["placement"],
                            "asset_role": role, "reason": "旧调用中同尺寸且同资产角色的重复任务"})
            continue
        seen.add(dedupe_key)
        normalized.append(row)

    if pixels > MEDIA_LIMITS["max_total_pixels"]:
        errors.append(f"累计像素 {pixels:,} 超过单批上限 {MEDIA_LIMITS['max_total_pixels']:,}")
    # 旧调用发生去重时，服务端像素总量会小于客户端上报值，此时跳过一致性核对。
    if total_pixels is not None and not dropped and total_pixels != pixels:
        errors.append(f"客户端上报像素总量 {total_pixels:,} 与服务端解析 {pixels:,} 不一致")
    if errors:
        raise MediaRuleError(errors)

    pref = (profile or {}).get("placement_preferences") or []
    meta = {
        "spec_version": SPEC_VERSION,
        "spec_source": SPEC_SOURCE,
        "spec_verified_on": SPEC_VERIFIED_ON,
        "disclaimer": SPEC_DISCLAIMER,
        "platform": key,
        "requested_tasks": len(rows),
        "effective_tasks": len(normalized),
        "dropped_duplicates": dropped,
        "placement_warnings": placement_warnings,
        "placement_validation": "strict_primary_key" if not placement_warnings else "mixed_legacy",
        "total_pixels": pixels,
        "ad_products": sorted(products),
        "mixed_ad_products": len(products) > 1,
        "industry_profile": (profile or {}).get("key", "general"),
        "industry_preferred_placements": pref,
        "policy": MEDIA_RULES["policy"],
        "advisory": MEDIA_RULES["advisory"],
    }
    return {"slots": normalized, "meta": meta}
