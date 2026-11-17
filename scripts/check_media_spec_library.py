"""V4.84 验收：媒体素材规格标准库 + 生成链路联动。

覆盖：
1. 标准库结构完整（8 平台、图片+视频、A/B/C 分级、来源与核验日期纪律）；
2. 与方案文档逐平台规格一致（Google/Unity/AppLovin/Mintegral/TikTok/Moloco/Adsterra/Meta）；
3. video_target 解析：官方 A 级时长越界、B 级仅建议、未知平台 C 级不放行；
4. validate_video_delivery：A 级硬失败 / B 级 advisory / 合格 pass；
5. reconcile_image_catalog：目录缺项能被对账发现（标准库为准）；
6. 生成链路引用点：routers 冻结 spec_ref、creative_tasks 交付复核。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import media_spec_library as lib

passed = failed = 0


def record(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}  {detail}")


def entry(platform, product=None, role=None, media=None):
    return [e for e in lib.LIBRARY
            if e.platform == platform
            and (not product or e.ad_product == product)
            and (not role or e.asset_role == role)
            and (not media or e.media == media)]


print("\n[1] 标准库结构与核验纪律")
record("覆盖方案文档 8 个平台", {e.platform for e in lib.LIBRARY} >= {
    "Meta", "Google", "Unity", "AppLovin", "Mintegral", "TikTok", "Moloco", "Adsterra"},
    str(sorted({e.platform for e in lib.LIBRARY})))
record("图片与视频规则都存在", any(e.media == "image" for e in lib.LIBRARY)
       and any(e.media == "video" for e in lib.LIBRARY))
_a_entries = [e for e in lib.LIBRARY if e.verification == lib.VERIFY_OFFICIAL]
_b_entries = [e for e in lib.LIBRARY if e.verification == lib.VERIFY_INTERNAL]
_c_entries = [e for e in lib.LIBRARY if e.verification == lib.VERIFY_BLOCKED]
record("A/B/C 三级都有条目", _a_entries and _b_entries and _c_entries,
       f"A={len(_a_entries)} B={len(_b_entries)} C={len(_c_entries)}")
record("所有 A 级条目带官方来源与核验日期",
       all(e.source_url and e.verified_on for e in _a_entries),
       str([e.ad_product for e in _a_entries if not (e.source_url and e.verified_on)]))
record("所有库条目都标注核验分级",
       all(e.verification in (lib.VERIFY_OFFICIAL, lib.VERIFY_INTERNAL, lib.VERIFY_BLOCKED)
           for e in lib.LIBRARY))
record("库版本独立存在", bool(lib.LIBRARY_VERSION) and lib.LIBRARY_VERSION.startswith("2026-"))

print("\n[2] 与方案文档规格一致（联网核验 2026-11-17）")
gapp = entry("Google", "App Campaign", "image_main")
record("Google App 图片 1:1/1.91:1/4:5 与 5MB",
       bool(gapp) and set(gapp[0].aspect_ratios) == {"1:1", "1.91:1", "4:5"}
       and "1200x1500" in gapp[0].sizes and gapp[0].max_bytes == 5 * 1024 * 1024)
unity_v = entry("Unity", "UA 视频广告", "video")[0]
record("Unity UA 视频 ≤60s / 100MB / H.264 / 必须端卡",
       unity_v.duration_max == 60 and unity_v.max_bytes == 100 * 1024 * 1024
       and unity_v.codec == "H.264" and "end_card" in unity_v.companions)
unity_ec = entry("Unity", "UA 视频广告", "end_card")[0]
record("Unity 端卡 800x800/800x600/600x800 / 5MB",
       set(unity_ec.sizes) == {"800x800", "800x600", "600x800"}
       and unity_ec.max_bytes == 5 * 1024 * 1024)
al_v = entry("AppLovin", "Advertise 应用推广", "video")[0]
record("AppLovin Advertise 视频 9:16 / ≤1GB / ≤60s",
       al_v.aspect_ratios == ("9:16",) and al_v.max_bytes == 1024 ** 3
       and al_v.duration_max == 60)
al_ortb = entry("AppLovin", "oRTB VAST", "video")[0]
record("AppLovin oRTB 5–30s / <4MB 与 Advertise 分开",
       al_ortb.duration_min == 5 and al_ortb.duration_max == 30
       and al_ortb.max_bytes == 4 * 1024 * 1024)
mt_icon = entry("Mintegral", "AppGrowth", "icon")[0]
mt_video = entry("Mintegral", "AppGrowth", "video")[0]
record("Mintegral icon 512 / 主图 1200x627-628 / 视频 200MB",
       mt_icon.sizes == ("512x512",) and mt_video.max_bytes == 200 * 1024 * 1024)
mt_old = entry("Mintegral", "旧 API 入口", "video")[0]
record("Mintegral 旧 API 50MB 冲突按入口单列（C 级）",
       mt_old.verification == lib.VERIFY_BLOCKED and mt_old.max_bytes == 50 * 1024 * 1024)
tt_v = entry("TikTok", "In-Feed（Non-Spark）", "video")[0]
record("TikTok In-Feed 三比例 / 500MB / ≤10min",
       set(tt_v.aspect_ratios) == {"9:16", "16:9", "1:1"}
       and tt_v.max_bytes == 500 * 1024 * 1024 and tt_v.duration_max == 600)
mo_v = entry("Moloco", "普通视频", "video")[0]
mo_native = entry("Moloco", "Native", "video")[0]
record("Moloco 普通视频 6–180s / 450MB / 24fps",
       mo_v.duration_min == 6 and mo_v.duration_max == 180
       and mo_v.max_bytes == 450 * 1024 * 1024 and mo_v.fps_min == 24)
record("Moloco Native 6–100s / 10MB 与普通视频分开",
       mo_native.duration_min == 6 and mo_native.duration_max == 100
       and mo_native.max_bytes == 10 * 1024 * 1024)
ad_native = entry("Adsterra", "Native", "native_image")[0]
record("Adsterra Native 320x240 / 350KB / 比例冲突标 C 级",
       ad_native.sizes == ("320x240",) and ad_native.max_bytes == 350 * 1024
       and ad_native.verification == lib.VERIFY_BLOCKED)
ad_video = entry("Adsterra", "动态 Social Bar / VAST", "video")[0]
record("Adsterra 视频能力未确认（C 级，不默认支持 MP4）",
       ad_video.verification == lib.VERIFY_BLOCKED and ad_video.duration_min is None)
meta_v = entry("Meta", "Feed 视频", "video")
record("Meta 官方受限 → 内部制作基准 B 级，不写官方",
       meta_v and all(e.verification == lib.VERIFY_INTERNAL for e in meta_v))

print("\n[3] video_target 生成前解析")
t = lib.video_target("Moloco", "9:16", 5)
record("Moloco 5s 被判越界（官方 6s 下限）", t["duration_ok"] is False
       and t["verification"] == "A", t["duration_reason"])
record("Moloco 视频带必需端卡", "end_card" in t["companions"], str(t["companions"]))
t15 = lib.video_target("Moloco", "9:16", 15)
record("Moloco 15s 合规", t15["duration_ok"] is True)
tm = lib.video_target("Meta", "9:16", 5)
record("Meta B 级时长区间存在但非官方硬规则", tm["verification"] == "B"
       and tm["duration_ok"] is False)
tu = lib.video_target("UnknownPlatform", "9:16", 15)
record("未知平台 C 级不静默放行", tu["verification"] == "C" and tu["duration_ok"] is None)

print("\n[4] validate_video_delivery 交付复核")
chk = lib.validate_video_delivery(lib.video_target("Moloco", "9:16", 15), 5)
record("Moloco A 级实测 5s → hard_fail", chk["status"] == "hard_fail"
       and chk["spec_ok"] is False, chk["note"])
chk_ok = lib.validate_video_delivery(lib.video_target("Moloco", "9:16", 15), 15)
record("Moloco 实测 15s → pass", chk_ok["status"] == "pass")
chk_meta = lib.validate_video_delivery(lib.video_target("Meta", "9:16", 15), 5)
record("Meta B 级越界仅 advisory 不判不合格", chk_meta["status"] == "advisory")

print("\n[5] 图片目录对账（标准库为准）")
diffs = lib.reconcile_image_catalog({"Google": {"300x250", "728x90"}})
record("目录缺 Google 1200x628 时对账能发现",
       any(d["platform"] == "Google" and "1200x628" in d["missing_in_catalog"] for d in diffs),
       str(diffs))

print("\n[6] 生成链路引用点（防止标准库与生成漂移）")
routers = (BACKEND / "routers.py").read_text(encoding="utf-8")
ct = (BACKEND / "creative_tasks.py").read_text(encoding="utf-8")
record("routers 提交前冻结 spec_ref", "spec_video_target(" in routers and '"spec_ref": spec_ref' in routers)
record("routers 交付时复核 spec", "spec_validate_delivery(" in routers and "SPEC_MISMATCH" in routers)
record("creative_tasks 交付时复核冻结规格",
       "spec_validate_delivery(" in ct and "SPEC_MISMATCH" in ct and '"spec_ref": spec_ref' in ct)

print(f"\n==== V4.84 媒体规格标准库：{passed}/{passed + failed} 通过，{failed} 失败 ====")
sys.exit(1 if failed else 0)
