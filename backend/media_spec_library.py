"""媒体素材规格标准库（单一事实来源 / Spec Library）。

定位
----
这是「创意工作台」图片与视频素材规格的**唯一权威标准库**。凡是需要判断
「某平台某广告产品该出什么尺寸 / 比例 / 时长 / 格式 / 伴随素材」，都从这里取，
不允许图片页、视频页、导出逻辑各写一套数字。

数据来源与纪律（对应《创意工作台状态一致性与主流媒体素材规格诊断实施方案》第五节）
----
每条规则带三个可选核验维度，禁止把内部建议冒充官方硬规则：
  - verification: 'A' 官方帮助文档已核验 | 'B' 内部制作基准 | 'C' 官方受限 / 入口冲突 / 待账户确认
  - source_url:   该条规则的官方来源（A 级必须有）
  - verified_on:  核验日期 YYYY-MM-DD（A 级必须有；B/C 级可为空）
未知字段一律 None，不填 0、不编造最大值。'建议' 永不被提升为强制。

与生成链路的联动（关键）
----
- 图片：``image_targets(platform)`` 返回该平台**已登记**的图片资产角色与目标尺寸，
  供任务矩阵复用；``media_platforms.py`` 的目录通过 ``reconcile_image_catalog()``
  与本库对账，两侧不一致时以**本库为准**并给出差异，保证展示与生成统一。
- 视频：``video_target(platform, aspect, duration, ad_product)`` 返回目标比例、
  制作尺寸、允许时长区间、伴随素材与核验状态；``_cw_video_request_build`` 在提交前
  冻结该结果写入 meta/spec_ref，``validate_video_delivery`` 在落盘后用实测值复核。
  这样「选了 Moloco 却出 5 秒竖片」在提交/交付两端都能被同一份规则识别。

版本
----
LIBRARY_VERSION 独立递增；与 media_platforms.SPEC_VERSION 解耦，避免改标准库被迫
改动被测试锁定的目录版本常量。每次规则更新必须同时更新本版本与对应条目的
verified_on / source_url。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

#: 标准库结构版本。规则内容变更时递增。
LIBRARY_VERSION = "2026-11-17.1"
#: 本轮联网核验日期（Meta 受限、Adsterra 部分入口冲突，见各条 verification）。
REVIEWED_ON = "2026-11-17"

VERIFY_OFFICIAL = "A"   # 官方帮助文档已核验
VERIFY_INTERNAL = "B"   # 内部制作基准（非官方硬规则）
VERIFY_BLOCKED = "C"    # 官方受限 / 入口冲突 / 账户能力待确认

VERIFY_LABEL = {
    VERIFY_OFFICIAL: "官方已核验",
    VERIFY_INTERNAL: "内部制作基准",
    VERIFY_BLOCKED: "待官方/账户确认",
}

# 官方来源链接（与方案文档第十五节「官方依据」一致，2026-11-17 联网复核）
SRC = {
    "google_search_img": "https://support.google.com/adspolicy/answer/10347108?hl=en",
    "google_rda": "https://support.google.com/google-ads/answer/7005917/create-a-responsive-display-ad",
    "google_app": "https://support.google.com/google-ads/answer/9948381?hl=en",
    "google_pmax_img": "https://support.google.com/google-ads/answer/14530211?hl=en",
    "google_upload_banner": "https://support.google.com/google-ads/answer/1722096?hl=en",
    "google_app_video": "https://support.google.com/google-ads/answer/17091671",
    "google_pmax_video": "https://support.google.com/google-ads/answer/10724748?hl=en",
    "google_video_reach": "https://support.google.com/google-ads/answer/17091270?hl=en",
    "google_skippable": "https://support.google.com/google-ads/answer/11462260?hl=en-001",
    "unity_video": "https://docs.unity.com/en-us/grow/acquire/creatives/video/specifications",
    "unity_endcard": "https://docs.unity.com/en-us/grow/acquire/creatives/end-cards/static",
    "applovin_advertise": "https://support.applovin.com/en/growth/promoting-your-apps/welcome-to-applovin/creative-specs-and-guidelines",
    "applovin_ortb": "https://support.applovin.com/en/max/demand-partners/demand-side-platforms/applovin-ortb-specification/creative-types",
    "mintegral_asset": "https://helpcenter.mintegral.com/en/docs/asset-specs",
    "mintegral_faq": "https://helpcenter.mintegral.com/en/docs/ad-asset",
    "mintegral_old_api": "https://adv-new.mintegral.com/doc/en/guide/appendix/creative.html",
    "tiktok_infeed": "https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads?redirected=2",
    "tiktok_carousel": "https://ads.tiktok.com/resources/help/article/specifications-for-carousel-ads",
    "moloco_image": "https://help.moloco.com/hc/en-us/articles/7049805175447-Image-creative-guide",
    "moloco_video": "https://help.moloco.com/hc/en-us/articles/7104841219095-Video-creative-guide",
    "moloco_native": "https://help.moloco.com/hc/en-us/articles/7104698037911-Native-creative-guide",
    "adsterra_banner": "https://adsterra.com/blog/how-banner-ads-make-money/",
    "adsterra_native": "https://adsterra.com/blog/native-banners-short-guide/",
    "adsterra_socialbar": "https://adsterra.com/blog/interstitial-ads-by-adsterra-grab-all-target-views-and-clicks/",
    "meta_image": "https://www.facebook.com/business/ads-guide/image/facebook-feed",
    "meta_video": "https://www.facebook.com/business/ads-guide/video/instagram-reels",
}


@dataclass(frozen=True)
class SpecEntry:
    """一条资产规格规则。所有尺寸为 'WxH' 字符串；未知项为 None。"""
    platform: str
    ad_product: str                 # 广告产品，如 'App Campaign' / 'PMax' / 'UA'
    asset_role: str                 # 资产角色：main_image / end_card / icon / video ...
    media: str                      # 'image' | 'video'
    verification: str               # A / B / C
    source_url: Optional[str] = None
    verified_on: Optional[str] = None
    sizes: tuple = ()               # 推荐/常用制作尺寸（WxH）
    min_sizes: tuple = ()           # 官方最低尺寸（WxH），无则 ()
    aspect_ratios: tuple = ()       # 允许比例 '9:16' 等
    formats: tuple = ()             # 文件格式
    max_bytes: Optional[int] = None # 文件大小上限（字节）；None = 未知/分入口
    duration_min: Optional[float] = None
    duration_max: Optional[float] = None
    fps_min: Optional[int] = None
    codec: Optional[str] = None
    companions: tuple = ()          # 必需的伴随资产角色
    note: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("sizes", "min_sizes", "aspect_ratios", "formats", "companions"):
            d[k] = list(d[k] or ())
        d["verification_label"] = VERIFY_LABEL.get(self.verification, "未标注")
        d["library_version"] = LIBRARY_VERSION
        return d


def _a(platform, product, role, media, source, sizes=(), min_sizes=(), aspects=(),
       formats=(), max_bytes=None, dmin=None, dmax=None, fps=None, codec=None,
       companions=(), note="", verified_on=REVIEWED_ON) -> SpecEntry:
    """官方核验（A 级）条目快捷构造：强制带来源与核验日期。"""
    return SpecEntry(platform, product, role, media, VERIFY_OFFICIAL, source, verified_on,
                     tuple(sizes), tuple(min_sizes), tuple(aspects), tuple(formats),
                     max_bytes, dmin, dmax, fps, codec, tuple(companions), note)


def _b(platform, product, role, media, sizes=(), aspects=(), formats=(), max_bytes=None,
       dmin=None, dmax=None, fps=None, codec=None, companions=(), note="") -> SpecEntry:
    """内部制作基准（B 级）：无官方来源，不宣称合规。"""
    return SpecEntry(platform, product, role, media, VERIFY_INTERNAL, None, None,
                     tuple(sizes), (), tuple(aspects), tuple(formats), max_bytes,
                     dmin, dmax, fps, codec, tuple(companions), note)


def _c(platform, product, role, media, source=None, note="", **kw) -> SpecEntry:
    """受限 / 入口冲突 / 待确认（C 级）：只登记已知信息，明确不自动合规。"""
    return SpecEntry(platform, product, role, media, VERIFY_BLOCKED, source, None,
                     tuple(kw.get("sizes", ())), tuple(kw.get("min_sizes", ())),
                     tuple(kw.get("aspect_ratios", ())), tuple(kw.get("formats", ())),
                     kw.get("max_bytes"), kw.get("duration_min"), kw.get("duration_max"),
                     kw.get("fps_min"), kw.get("codec"), tuple(kw.get("companions", ())), note)


# ---------------------------------------------------------------------------
# 标准库条目（按平台 → 广告产品 → 资产角色）
# ---------------------------------------------------------------------------
LIBRARY: tuple[SpecEntry, ...] = (
    # ============ Google（A 级，官方文档可访问）============
    _a("Google", "Search 图片资产", "image_main", "image", SRC["google_search_img"],
       sizes=("1200x1200", "1200x628"), min_sizes=("300x300", "600x314"),
       aspects=("1:1", "1.91:1"), formats=("JPG", "PNG"), max_bytes=5120 * 1024,
       note="方图必需、横图可选；不得叠加广告文字或图形 Logo。"),
    _a("Google", "响应式展示广告 RDA", "image_landscape", "image", SRC["google_rda"],
       sizes=("1200x628",), min_sizes=("600x314",), aspects=("1.91:1",),
       max_bytes=5120 * 1024),
    _a("Google", "响应式展示广告 RDA", "image_square", "image", SRC["google_rda"],
       sizes=("1200x1200",), min_sizes=("300x300",), aspects=("1:1",),
       max_bytes=5120 * 1024),
    _a("Google", "响应式展示广告 RDA", "logo_square", "image", SRC["google_rda"],
       sizes=("1200x1200",), min_sizes=("128x128",), aspects=("1:1",),
       max_bytes=5120 * 1024, note="Logo 为独立角色，不作为产品主图。"),
    _a("Google", "响应式展示广告 RDA", "logo_landscape", "image", SRC["google_rda"],
       sizes=("1200x300",), min_sizes=("512x128",), aspects=("4:1",),
       max_bytes=5120 * 1024),
    _a("Google", "App Campaign", "image_main", "image", SRC["google_app"],
       sizes=("1200x1200", "1200x628", "1200x1500"),
       min_sizes=("200x200", "600x314", "320x400"),
       aspects=("1:1", "1.91:1", "4:5"), formats=("JPG", "PNG"), max_bytes=5 * 1024 * 1024,
       note="9:16 不是 App 图片清单的标准竖图。"),
    _a("Google", "PMax", "image_main", "image", SRC["google_pmax_img"],
       sizes=("1200x628", "1200x1200", "960x1200"),
       min_sizes=("600x314", "300x300", "480x600"),
       aspects=("1.91:1", "1:1", "4:5"), formats=("JPG", "PNG"), max_bytes=5 * 1024 * 1024,
       note="另配方形 Logo 及可选横 Logo；中心 80% 保留主体。",
       companions=("logo_square",)),
    _a("Google", "上传式展示广告", "display_banner", "image", SRC["google_upload_banner"],
       sizes=("300x250", "728x90", "320x50", "160x600", "300x600", "970x250"),
       formats=("GIF", "JPG", "PNG"), max_bytes=150 * 1024,
       note="150KB 规则，与 RDA 5MB 不同；区域尺寸不可默认全球可投。GIF 动画≤30s、<5fps。"),
    _a("Google", "App Campaign", "video", "video", SRC["google_app_video"],
       aspects=("16:9", "9:16", "1:1"), dmin=10, dmax=60,
       note="须先上传 YouTube；制作 1920x1080/1080x1920/1080x1080 为内部基准。"),
    _a("Google", "PMax", "video", "video", SRC["google_pmax_video"],
       aspects=("16:9", "9:16", "1:1"), dmin=10, dmax=60,
       note="官方要求长于 10s；推荐 10–60s，取 15/30s 避免边界；需上传 YouTube。"),
    _a("Google", "视频覆盖广告", "video", "video", SRC["google_video_reach"],
       sizes=("1920x1080", "1080x1920", "1080x1080"), aspects=("16:9", "9:16", "1:1"),
       dmin=6, dmax=60, note="横版 15s 为建议；Shorts/方版推荐 6–60s。"),
    _a("Google", "不可跳过广告", "video", "video", SRC["google_skippable"],
       aspects=("16:9", "9:16", "1:1"), dmin=7, dmax=15,
       note="16–30s CTV 不可跳过须横版；入口与设备不同，不混为统一 30s。"),

    # ============ Unity（A 级）============
    _a("Unity", "UA 视频广告", "video", "video", SRC["unity_video"],
       sizes=("1920x1080", "1080x1920"), aspects=("16:9", "9:16"),
       formats=("MP4",), max_bytes=100 * 1024 * 1024, dmax=60, codec="H.264",
       companions=("end_card",),
       note="推荐 10MB；30–60s 为 Beta；横竖各一条更优；所有 UA 视频必须配端卡。",
       verified_on=REVIEWED_ON),
    _a("Unity", "UA 视频广告", "end_card", "image", SRC["unity_endcard"],
       sizes=("800x800", "800x600", "600x800"), aspects=("1:1", "4:3", "3:4"),
       formats=("JPG", "PNG", "GIF"), max_bytes=5 * 1024 * 1024,
       note="推荐方形；横图左右、竖图上下各留 100px 安全区。"),

    # ============ AppLovin（A 级，Advertise 与 oRTB 分入口）============
    _a("AppLovin", "Advertise 应用推广", "video", "video", SRC["applovin_advertise"],
       sizes=("1080x1920",), aspects=("9:16",), formats=("MP4", "MOV"),
       max_bytes=1024 * 1024 * 1024, dmax=60, note="≤1GB、≤60s。"),
    _a("AppLovin", "Advertise 应用推广", "end_card", "image", SRC["applovin_advertise"],
       sizes=("1080x1920",),        min_sizes=("270x480",), aspects=("9:16",),
       formats=("GIF", "JPEG", "PNG"), max_bytes=10 * 1024 * 1024,
       note="IMG_INTER_P；另接受 320x480/320x512/640x1138/768x1024；GIF≤60s。"),
    _a("AppLovin", "Advertise 应用推广", "banner", "image", SRC["applovin_advertise"],
       min_sizes=("320x50",), aspects=("32:5",), max_bytes=10 * 1024 * 1024),
    _a("AppLovin", "Advertise 应用推广", "mrec", "image", SRC["applovin_advertise"],
       min_sizes=("300x250",), aspects=("6:5",), max_bytes=10 * 1024 * 1024),
    _a("AppLovin", "Advertise 应用推广", "icon", "image", SRC["applovin_advertise"],
       min_sizes=("50x50",), aspects=("1:1",), max_bytes=10 * 1024 * 1024),
    _a("AppLovin", "oRTB VAST", "video", "video", SRC["applovin_ortb"],
       dmin=5, dmax=30, max_bytes=4 * 1024 * 1024,
       note="激励视频建议 20–30s；推荐<2MB；与 Advertise 1GB 入口不同，不混用。"),

    # ============ Mintegral（A 级，容量分入口）============
    _a("Mintegral", "AppGrowth", "icon", "image", SRC["mintegral_asset"],
       sizes=("512x512",), aspects=("1:1",), formats=("JPG", "JPEG", "PNG", "GIF", "BMP"),
       max_bytes=5 * 1024 * 1024, note="必传 icon。"),
    _a("Mintegral", "AppGrowth", "main_image", "image", SRC["mintegral_asset"],
       sizes=("1200x627", "1200x628"), formats=("JPG", "JPEG", "PNG", "GIF", "BMP"),
       max_bytes=5 * 1024 * 1024, note="主图/端卡；视频场景不可省略。"),
    _a("Mintegral", "AppGrowth", "splash", "image", SRC["mintegral_asset"],
       sizes=("720x1280",), aspects=("9:16",), max_bytes=5 * 1024 * 1024),
    _a("Mintegral", "AppGrowth", "video", "video", SRC["mintegral_asset"],
       sizes=("1080x1920", "1920x1080", "1280x720", "720x1280"),
       formats=("MP4",), max_bytes=200 * 1024 * 1024, dmin=6, dmax=120,
       companions=("main_image", "icon"),
       note="建议 6/15/30/60s；当前帮助中心≤200MB，旧 API 附录 50MB、旧手册图片500KB——按入口区分，不写统一上限。"),
    _c("Mintegral", "旧 API 入口", "video", "video", SRC["mintegral_old_api"],
       note="旧 API 附录取值上限 50MB，与帮助中心 200MB 冲突；走旧 API 时须单独核定，不能据本库自动合规。",
       max_bytes=50 * 1024 * 1024),

    # ============ TikTok（A 级；轮播与视频分角色）============
    _a("TikTok", "In-Feed（Non-Spark）", "video", "video", SRC["tiktok_infeed"],
       sizes=("1080x1920", "960x540", "640x640"),
       min_sizes=("540x960", "960x540", "640x640"),
       aspects=("9:16", "16:9", "1:1"), max_bytes=500 * 1024 * 1024,
       dmax=600, note="≥516kbps；非 Spark 最长 10 分钟；制作推荐 1080x1920、15/30s 为内部基准。"),
    _a("TikTok", "Spark Ads", "video", "video", SRC["tiktok_infeed"],
       formats=("MP4", "MOV"), note="继承已授权自然内容；官方该页无时长限制；需实际投放入口校验。"),
    _a("TikTok", "轮播广告", "carousel_image", "image", SRC["tiktok_carousel"],
       sizes=("1200x628", "640x640", "720x1280"), formats=("JPG", "JPEG", "PNG"),
       note="2–35 张；音乐时长≥2s、MP3≤10MB；张数不足或缺音乐不算完整轮播。"),

    # ============ Moloco（A 级，普通图/Native/视频分规则）============
    _a("Moloco", "普通图片", "display_banner", "image", SRC["moloco_image"],
       sizes=("300x250", "320x480", "320x50", "728x90"),
       formats=("JPEG", "JPG", "PNG", "GIF"), max_bytes=500 * 1024,
       note="完整尺寸按国家/OS 清单；GIF≤1MB。无地区信息时只作通用包，不声称全地区可投。"),
    _a("Moloco", "Native", "native_image", "image", SRC["moloco_native"],
       sizes=("1200x628", "1200x600", "1200x222", "720x720", "720x960", "720x1280", "1200x1600"),
       formats=("JPEG", "JPG", "PNG", "GIF"), max_bytes=500 * 1024,
       note="部分尺寸绑定交易所（如韩国 Kakao 需 1200x600）；GIF≤1MB。"),
    _a("Moloco", "Native", "icon", "image", SRC["moloco_native"],
       min_sizes=("256x256",), aspects=("1:1",), max_bytes=500 * 1024,
       formats=("PNG", "JPEG", "JPG", "GIF"), note="PNG 推荐。"),
    _a("Moloco", "普通视频", "video", "video", SRC["moloco_video"],
       min_sizes=("640x360",), aspects=("16:9", "9:16", "1:1"),
       formats=("MP4",), max_bytes=450 * 1024 * 1024,
       dmin=6, dmax=180, fps=24, companions=("end_card",),
       note="至少一边≥640px（推荐≥720px）；转码后<18MB；短于 30s 会被自动循环，仍记录原文件实际时长。"),
    _a("Moloco", "普通视频", "end_card", "image", SRC["moloco_video"],
       min_sizes=("320x320",), formats=("JPEG", "JPG", "PNG", "GIF"), max_bytes=500 * 1024,
       note="方向须与视频一致；GIF≤1MB。"),
    _a("Moloco", "Native", "video", "video", SRC["moloco_native"],
       sizes=("1280x720", "720x1280"), min_sizes=("640x640",),
       aspects=("16:9", "9:16", "1:1"), formats=("MP4",),
       max_bytes=10 * 1024 * 1024, dmin=6, dmax=100, fps=24,
       companions=("native_thumbnail",),
       note="需配同比例缩略图；与普通视频 450MB/180s 不同，不混用。"),

    # ============ Adsterra（A/C 混合，视频能力多为待确认）============
    _a("Adsterra", "常见 Banner", "display_banner", "image", SRC["adsterra_banner"],
       sizes=("300x250", "728x90", "160x600", "320x50", "468x60"),
       note="博客列常见库存；上传格式与文件上限须按账户入口再核定。"),
    _c("Adsterra", "Native", "native_image", "image", SRC["adsterra_native"],
       sizes=("320x240",), formats=("JPG", "PNG"), max_bytes=350 * 1024,
       note="官方原文写 320x240（即 4:3）却标 16:9，自相矛盾；按明确像素核对账户，比例待确认。"),
    _a("Adsterra", "Social Bar 插屏", "interstitial_image", "image", SRC["adsterra_socialbar"],
       sizes=("600x400",), aspects=("3:2",), max_bytes=350 * 1024,
       note="具体皮肤与格式以账户模板确认。"),
    _a("Adsterra", "Social Bar 插屏", "icon", "image", SRC["adsterra_socialbar"],
       sizes=("192x192",), aspects=("1:1",), max_bytes=350 * 1024),
    _c("Adsterra", "动态 Social Bar / VAST", "video", "video", None,
       note="未取得广告主上传分辨率/时长/容量表；VAST 为交付协议，不代表当前账户可上传视频。不默认支持任意 MP4。"),

    # ============ Meta（本轮官方页访问受限 → B/C 级，不写官方硬规则）============
    _b("Meta", "Feed 图片", "image_main", "image",
       sizes=("1080x1080", "1080x1350", "1200x628"), aspects=("1:1", "4:5", "1.91:1"),
       formats=("JPG", "PNG"), max_bytes=5 * 1024 * 1024,
       note="内部制作基准；可制作 1440x1800 高分版。官方当前最大值待核定。"),
    _b("Meta", "Stories / Reels 图片", "story_vertical", "image",
       sizes=("1080x1920",), aspects=("9:16",), formats=("JPG", "PNG"),
       note="是否支持静态图须绑定具体广告位与产品。"),
    _b("Meta", "Feed 视频", "video", "video",
       sizes=("1080x1080", "1080x1350"), aspects=("1:1", "4:5"),
       formats=("MP4",), codec="H.264", dmin=15, dmax=30,
       note="内部基准；30fps、AAC 或静音；时长为建议非官方上限。"),
    _b("Meta", "Stories / Reels 视频", "video", "video",
       sizes=("1080x1920",), aspects=("9:16",), formats=("MP4",), codec="H.264",
       dmin=15, dmax=30, note="内部基准；安全区按当前官方模板复核。"),
    _c("Meta", "官方广告指南", "reference", "image", SRC["meta_image"],
       note="2026-11-17 官方 Ads Guide 页面跳转登录/临时限制，未取得可核验的完整当前参数；不写 SPEC_VERIFIED_ON=官方。"),
)


# ---------------------------------------------------------------------------
# 索引与查询
# ---------------------------------------------------------------------------
def _norm(v) -> str:
    return str(v or "").strip().lower().replace("×", "x")


def all_entries() -> list[SpecEntry]:
    return list(LIBRARY)


def library_payload() -> dict:
    """供 API / 导出使用的完整标准库快照。"""
    return {
        "library_version": LIBRARY_VERSION,
        "reviewed_on": REVIEWED_ON,
        "verification_label": VERIFY_LABEL,
        "entries": [e.as_dict() for e in LIBRARY],
    }


def entries_for(platform: str, media: str = "", ad_product: str = "") -> list[SpecEntry]:
    key = _norm(platform)
    return [e for e in LIBRARY
            if _norm(e.platform) == key
            and (not media or e.media == media)
            and (not ad_product or _norm(e.ad_product) == _norm(ad_product))]


def image_targets(platform: str, ad_product: str = "", asset_role: str = "") -> list[dict]:
    """V4.88：图片生成目标解析（与 video_target 对称，供任务矩阵与提示词共用）。

    只返回本库已登记的图片规则；未知平台 / 未知广告产品返回空列表，调用方不得据此
    编造尺寸，保留旧目录时也必须标注“标准库未登记”。
    """
    out: list[dict] = []
    for e in entries_for(platform, "image", ad_product):
        if asset_role and _norm(e.asset_role) != _norm(asset_role):
            continue
        out.append({
            "platform": e.platform,
            "ad_product": e.ad_product,
            "asset_role": e.asset_role,
            "sizes": list(e.sizes or ()),
            "min_sizes": list(e.min_sizes or ()),
            "aspect_ratios": list(e.aspect_ratios or ()),
            "formats": list(e.formats or ()),
            "max_bytes": e.max_bytes,
            "verification": e.verification,
            "verification_label": VERIFY_LABEL.get(e.verification, "未标注"),
            "source_url": e.source_url,
            "verified_on": e.verified_on,
            "note": e.note,
            "library_version": LIBRARY_VERSION,
        })
    return out


def image_target_for_size(platform: str, size: str, ad_product: str = "",
                          asset_role: str = "") -> dict | None:
    """按目标像素尺寸找已登记规则；未登记返回 None，不把内部目录冒充官方规则。"""
    key = _norm(size).replace(" ", "")
    for row in image_targets(platform, ad_product, asset_role):
        if any(_norm(s) == key for s in row["sizes"]):
            return row
    return None


def video_target(platform: str, aspect: str = "", duration=None,
                 ad_product: str = "") -> dict:
    """视频生成目标解析：把平台/产品/用户选择映射为一份**冻结的规格目标**。

    返回字段供 ``_cw_video_request_build`` 写入 meta 并在交付时复核：
      - target_aspect/target_size：该平台广告产品支持的制作比例与尺寸
      - duration_min/max：官方或内部时长区间（None = 未知）
      - duration_ok/duration_reason：用户所选时长是否落在区间内
      - companions：必需伴随素材角色
      - verification/source_url/verified_on：这条规则的核验状态
    未知平台返回 verification=C、verification_note 说明，不静默放行。
    """
    aspect = str(aspect or "").strip() or "9:16"
    try:
        dur = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        dur = None

    candidates = entries_for(platform, "video", ad_product)
    # 优先选比例命中的条目；否则取该平台视频规则里最严格（有 max_bytes）的一条作基准
    hit = next((e for e in candidates if aspect and any(_norm(a) == _norm(aspect) for a in e.aspect_ratios)), None)
    base = hit or (candidates[0] if candidates else None)

    if base is None:
        return {
            "platform": platform, "ad_product": ad_product or None,
            "target_aspect": aspect, "target_size": None,
            "duration_min": None, "duration_max": None,
            "duration_ok": None,
            "duration_reason": f"标准库未登记平台「{platform}」的视频规格，无法核对比例与时长。",
            "companions": [], "verification": VERIFY_BLOCKED,
            "verification_label": VERIFY_LABEL[VERIFY_BLOCKED],
            "source_url": None, "verified_on": None,
            "library_version": LIBRARY_VERSION,
        }

    dmin, dmax = base.duration_min, base.duration_max
    if dur is None:
        duration_ok, duration_reason = None, "未指定时长，无法核对区间。"
    elif dmin is None and dmax is None:
        duration_ok, duration_reason = None, "该规则未登记官方时长区间，不据本库判定。"
    elif (dmin is not None and dur < dmin) or (dmax is not None and dur > dmax):
        rng = _range_text(dmin, dmax)
        duration_ok = False
        duration_reason = (f"所选 {dur:g}s 不在「{base.ad_product}」规格区间 {rng} 内"
                           f"（{VERIFY_LABEL.get(base.verification, '未标注')}）。")
    else:
        duration_ok, duration_reason = True, f"所选 {dur:g}s 落在规格区间 {_range_text(dmin, dmax)} 内。"

    target_size = ""
    if hit and hit.sizes:
        target_size = next((s for s in hit.sizes if _aspect_of(s) == _norm(aspect)), hit.sizes[0])
    elif base.sizes:
        target_size = base.sizes[0]

    return {
        "platform": platform, "ad_product": base.ad_product,
        "target_aspect": aspect, "target_size": target_size or None,
        "duration_min": dmin, "duration_max": dmax,
        "duration_ok": duration_ok, "duration_reason": duration_reason,
        "companions": list(base.companions or ()),
        "verification": base.verification,
        "verification_label": VERIFY_LABEL.get(base.verification, "未标注"),
        "source_url": base.source_url, "verified_on": base.verified_on,
        "note": base.note, "library_version": LIBRARY_VERSION,
    }


def _range_text(dmin, dmax) -> str:
    if dmin is not None and dmax is not None:
        return f"{dmin:g}–{dmax:g}s"
    if dmin is not None:
        return f"≥{dmin:g}s"
    if dmax is not None:
        return f"≤{dmax:g}s"
    return "未登记"


def _aspect_of(size: str) -> str:
    parts = str(size or "").lower().replace("×", "x").split("x")
    if len(parts) != 2:
        return ""
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        return ""
    from math import gcd
    g = gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def validate_video_delivery(spec: dict, measured_duration: float,
                            measured_aspect: str = "") -> dict:
    """生成后交付复核：用实测时长/比例对照冻结的规格目标。

    只输出结论，不改变文件；结果并入现有 delivery_status / error_code 体系。
    规格未核验（B/C）时 status='advisory'，不据此判不合格（避免把内部基准冒充硬规则）。
    """
    spec = spec or {}
    verification = spec.get("verification")
    result = {
        "spec_ok": None, "status": "advisory", "reasons": [],
        "library_version": spec.get("library_version") or LIBRARY_VERSION,
    }
    reasons: list[str] = []
    hard = verification == VERIFY_OFFICIAL

    dmin, dmax = spec.get("duration_min"), spec.get("duration_max")
    has_range = dmin is not None or dmax is not None
    if measured_duration and has_range:
        bad = ((dmin is not None and measured_duration < dmin)
               or (dmax is not None and measured_duration > dmax))
        reasons.append(
            f"实测 {measured_duration:.1f}s "
            + ("不在" if bad else "符合")
            + f"规格区间 {_range_text(dmin, dmax)} 内"
        )
        if bad:
            result["spec_ok"] = False
            result["status"] = "hard_fail" if hard else "advisory"
        else:
            result["spec_ok"] = True
            result["status"] = "pass" if hard else "advisory"

    result["reasons"] = reasons
    result["note"] = ("；".join(reasons) or "无可核对的规格项") + (
        f"（{VERIFY_LABEL.get(verification, '未标注')}"
        + ("，官方规则" if hard else "，仅建议不判不合格") + "）")
    return result


def reconcile_image_catalog(catalog_sizes_by_platform: dict) -> list[dict]:
    """把现有 media_platforms 目录与本标准库对账，返回差异（本库为准）。

    入参形如 {'Google': {'1200x628', ...}, ...}（平台允许尺寸集合）。
    差异用于回归校验，防止有人只改展示目录不改标准库（或反之）。
    """
    diffs: list[dict] = []
    for platform, sizes in (catalog_sizes_by_platform or {}).items():
        lib_image = {s for e in entries_for(platform, "image") for s in (e.sizes or ())}
        cat = {str(x).lower().replace("×", "x") for x in (sizes or ())}
        lib = {str(x).lower().replace("×", "x") for x in lib_image}
        missing_in_catalog = sorted(lib - cat)   # 标准库有、目录缺 → 目录应补
        if missing_in_catalog:
            diffs.append({
                "platform": platform,
                "missing_in_catalog": missing_in_catalog,
                "note": "标准库已登记但展示/任务目录缺失，建议同步（以标准库为准）。",
            })
    return diffs
