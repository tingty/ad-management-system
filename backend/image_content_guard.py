"""图片内容体检门（V4.91）：拦截「纯色 / 无画面 / 只有颜色」的无效成品图。

背景
----
媒体平台不接受没有任何画面内容的纯色 / 纯渐变图片。历史的产生链路：
  1. 未配置 image 模型，或文生图供应商超时 / 报错 / 返回空 → `bg_path` 为空；
  2. `render_ad_png` 的 `_prepare_bg` 在无 AI 底图时回退本地渐变 `_gradient`；
  3. 纯图片模式（overlay_mode=pure）不叠加任何文字 / Logo / 商品合成；
  4. 结果是一张只有品牌渐变的「纯色图」，却仍以 status=fallback 计入合格图片
     （images / images_json / creative_assets），被前端正常展示与导出。

本模块在图片**落库与返回之前**做最后一道内容体检，纯色 / 无画面图一律判为
不合格（needs_attention），不进入合格素材清单，也不调用任何模型、不产生费用。

判据（实测校准，仅用 Pillow，无 numpy 依赖）
--------------------------------------------
把图缩到 64x64，计算三个指标：
  - grad：灰度图相邻像素差均值（横向 + 纵向）/2，反映「有没有画面结构 / 边缘」；
  - std_mean：RGB 三通道标准差均值，反映整体色彩离散度；
  - uniq：量化后的近似颜色数，反映颜色丰富度。

实测样本（64x64）：
  纯色 (30,60,90)      grad=0.00  std=0.00   uniq=1
  近纯色微噪            grad=0.14  std=0.28   uniq=3
  品牌渐变兜底(_gradient) grad=0.48  std=10.12  uniq=56
  浅柔和渐变            grad=0.30  std=5.28   uniq=30
  ---- 以下应放行 ----
  白底 + 中央产品色块    grad=3.08  std=70.22  uniq=54
  真实场景(色块/圆/线)   grad=5.90  std=61.12  uniq=1003
  纯色背景 + 大字        grad=17.2  std=90.72  uniq=125

判定为「无画面 / 纯色」当且仅当同时满足：
  grad  < 1.2  且  std_mean < 20  且  uniq < 90
采用「三条件同时满足」而非单一阈值，是为了宁可漏判也不误杀有真实内容（含
大面积纯色背景但主体清晰、叠加文字等）的素材。

对外 API
--------
  inspect_image_content(path) -> dict
    {"ok": bool, "verdict": "has_content"|"blank", "reason": str,
     "metrics": {"grad","std_mean","uniq","width","height"}, "thresholds": {...}}

设计约束：不修改入参文件；不做任何写操作；异常一律降级为「放行 + 说明」，
    绝不因体检模块自身故障阻断正常出图（fail-open，但如实标注）。
"""
from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageStat

# 体检采样尺寸：足够区分纯色与场景，又不显著拖慢批量渲染
_SAMPLE = 64

# 阈值：三条件同时满足才判为无画面
GRAD_MAX = 1.2
STD_MAX = 20.0
UNIQ_MAX = 90


def _metrics(img: "Image.Image") -> dict:
    """计算 64x64 采样下的三个指标；输入已被调用方转为 RGB。"""
    im = img.convert("RGB").resize((_SAMPLE, _SAMPLE), Image.BILINEAR)
    w, h = img.size

    stat = ImageStat.Stat(im)
    std_mean = sum(stat.stddev) / 3.0

    # 近似颜色数：每通道右移 4 位（16 级）后统计不同的 (r,g,b) 组合，
    # 比直接数 uniq 更抗压缩噪点，且足够区分「纯渐变」与「真实场景」。
    small = im.convert("RGB")
    rgb = small.load()
    uniq = len({(rgb[x, y][0] >> 4, rgb[x, y][1] >> 4, rgb[x, y][2] >> 4)
                for y in range(_SAMPLE) for x in range(_SAMPLE)})

    gray = im.convert("L")
    sx = ImageChops.difference(gray, ImageChops.offset(gray, 1, 0))
    sy = ImageChops.difference(gray, ImageChops.offset(gray, 0, 1))
    gx = ImageStat.Stat(sx).mean[0]
    gy = ImageStat.Stat(sy).mean[0]
    grad = (gx + gy) / 2.0

    return {
        "grad": round(float(grad), 3),
        "std_mean": round(float(std_mean), 3),
        "uniq": int(uniq),
        "width": int(w),
        "height": int(h),
    }


_THRESHOLDS = {"grad_lt": GRAD_MAX, "std_lt": STD_MAX, "uniq_lt": UNIQ_MAX}


def inspect_image_content(path: str | None, extended_check: dict | None = None) -> dict:
    """体检一张图片是否为纯色 / 无画面（V4.91），并承载 V4.104 扩展质检结论。

    - 旧字段 ok / verdict / metrics / thresholds 语义完全不变：纯色仍硬拦截（fail-open
      仍保留 has_content），不破坏已锁定该行为的测试。
    - V4.104 / 方案E：新增 quality_status（ok / fail / unverified）与 checks。
      `extended_check` 是调用方异步算好传入的扩展检查结论（产品参与 / 价值可见 /
      视觉冲突 / OCR）。未传、模型不可用或检查缺失时，扩展维度标 unverified——
      **不冒充已通过**，也不因工具缺失阻断交付（质量状态独立于文件生成状态）。
    """
    base = {
        "ok": True,
        "verdict": "has_content",
        "reason": "",
        "metrics": {},
        "thresholds": dict(_THRESHOLDS),
        # V4.104：默认「扩展质量未核验」，只有调用方传入明确结论才升级为 ok/fail。
        "quality_status": "unverified",
        "checks": {},
    }
    _apply_extended(base, extended_check)
    if not path or not os.path.isfile(path):
        base["reason"] = "文件不存在，跳过体检（不误判）"
        return base
    try:
        with Image.open(path) as im:
            im.load()
            metrics = _metrics(im)
    except Exception as e:
        base["reason"] = f"体检读取失败，放行：{type(e).__name__}"
        return base

    base["metrics"] = metrics
    grad, std, uniq = metrics["grad"], metrics["std_mean"], metrics["uniq"]
    blank = grad < GRAD_MAX and std < STD_MAX and uniq < UNIQ_MAX
    if blank:
        base["ok"] = False
        base["verdict"] = "blank"
        base["quality_status"] = "fail"
        base["reason"] = (
            f"检测到纯色 / 无画面图片（grad={grad} < {GRAD_MAX}, "
            f"std={std} < {STD_MAX}, uniq={uniq} < {UNIQ_MAX}）；"
            "未交付，避免使用无内容的纯色素材"
        )
    return base


def _apply_extended(base: dict, extended_check: dict | None) -> None:
    """把调用方传入的扩展质检结论并入结果，缺失一律保持 unverified。"""
    ec = extended_check if isinstance(extended_check, dict) else {}
    checks = ec.get("checks") if isinstance(ec.get("checks"), dict) else {}
    base["checks"] = dict(checks)
    if not ec or not checks:
        base["checks"] = {
            dim: {"status": "unverified", "detail": "未执行扩展质检（开关关闭或模型不可用）"}
            for dim in ("product_presence", "value_visibility", "visual_conflict", "ocr")
        }
        return
    statuses = [str((v or {}).get("status") or "") for v in checks.values() if isinstance(v, dict)]
    ec_status = str(ec.get("status") or "")
    if "fail" in statuses or ec_status == "fail":
        base["quality_status"] = "fail"
    elif all(s == "ok" for s in statuses) and ec_status in ("ok", ""):
        base["quality_status"] = "ok"
    else:
        base["quality_status"] = "unverified"
