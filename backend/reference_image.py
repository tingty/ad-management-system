"""参考图「风格学习」模块（V4.97）。

背景与定位
----------
创意工作台输入框的「参考图」用于**学习**——让文生图模型参考其配色、明暗、
整体色调与画面质感，生成一张**全新的**推广图。历史实现（V4.42 F03）在供应商
不支持参考编辑时走 `local_composite`，用 Pillow 把参考图原样 `paste` 到成品
主体区，等于把用户上传的图直接集成为素材，既不是 AI 生成、也与用户预期相反。

本模块用纯 Pillow 从参考图中提取可迁移的视觉特征（主色 / 配色 / 明暗 / 冷暖），
输出两部分供生成链路消费：
  1. `palette_override`：可覆盖到 ResolvedCreativeConfig.visual.palette 的十六进制色；
  2. `style_prompt`：注入文生图提示词的英文约束，指示「借鉴配色与质感、生成新画面」。

设计约束
--------
- 只提取**风格层**信号（颜色、明暗、冷暖），不复制原图的主体 / 文字 / Logo /
  水印，也不把原图像素写进任何输出文件。
- fail-open：文件缺失 / 解码失败 / 无法提取时返回 ok=False、空覆盖，绝不阻断出图；
  不修改入参文件，不做任何写操作。
- 不调用视觉大模型、不产生费用；与 V4.94 成片 OCR 视觉复核是不同用途。

对外 API
--------
  analyze_reference_style(path) -> dict
    {"ok": bool, "reason": str, "palette_override": {...},
     "style_prompt": str, "traits": {...}}
  render_reference_style_block(analysis) -> str
"""
from __future__ import annotations

import colorsys
import os

from PIL import Image

# 采样尺寸：足够代表整体色调，又不拖慢批量出图
_SAMPLE = 96
_MAX_COLORS = 6


def _hex(rgb: tuple) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(c))) for c in rgb)


def _luminance(rgb: tuple) -> float:
    r, g, b = [c / 255.0 for c in rgb[:3]]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def analyze_reference_style(path: str | None) -> dict:
    """从参考图提取风格层特征（配色 / 明暗 / 冷暖），不复制主体或像素。"""
    empty = {"ok": False, "reason": "", "palette_override": {},
             "style_prompt": "", "traits": {}}
    if not path or not os.path.isfile(path):
        return {**empty, "reason": "未提供可读取的参考图"}
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((_SAMPLE, _SAMPLE), Image.LANCZOS)
            small = im
            # 主色：量化取出现最多的颜色（跳过过暗 / 过亮的中性极值）
            quantized = small.quantize(colors=12, method=Image.MEDIANCUT).convert("RGB")
            # getcolors 直接给 (count, rgb) 对，避免 Pillow 14 弃用的 getdata
            counted = quantized.getcolors(maxcolors=quantized.width * quantized.height) or []
            ranked = sorted(((rgb, n) for n, rgb in counted),
                            key=lambda kv: kv[1], reverse=True)
            colors = [tuple(c) for c, _ in ranked[:_MAX_COLORS] if c]
            if not colors:
                return {**empty, "reason": "参考图无法提取颜色"}

            # 按亮度排序：最亮作 bg1、次亮 bg2、最饱和作 accent
            by_lum = sorted(colors, key=_luminance)
            bg1, bg2 = by_lum[-1], by_lum[max(0, len(by_lum) - 2)]

            def _sat(c):
                h, s, v = colorsys.rgb_to_hsv(c[0] / 255, c[1] / 255, c[2] / 255)
                return s * v

            accent = max(colors, key=_sat)
            light = _luminance(by_lum[-1]) >= 0.5
            fg = (18, 18, 18) if light else (245, 245, 245)
            sub = (90, 90, 90) if light else (200, 200, 200)

            # 冷暖倾向：色相落在蓝绿区间为 cool，落在红橙黄区间为 warm
            h_accent, _, _ = colorsys.rgb_to_hsv(
                accent[0] / 255, accent[1] / 255, accent[2] / 255)
            # HSV 色相：红≈0、黄≈0.17、绿≈0.33、青≈0.5、蓝≈0.67、品红≈0.83。
            # 红橙黄(0–0.18)与品红红端(>0.88)归暖，绿青蓝归冷。
            warm = (h_accent < 0.18 or h_accent > 0.88)
            tone = "warm" if warm else "cool"

            palette_override = {
                "accent": _hex(accent),
                "bg1": _hex(bg1),
                "bg2": _hex(bg2),
                "fg": _hex(fg),
                "sub": _hex(sub),
                "light": light,
            }
            traits = {
                "accent": _hex(accent), "bg1": _hex(bg1), "bg2": _hex(bg2),
                "tone": tone, "light": light, "colors": [_hex(c) for c in colors],
            }
            style_prompt = (
                "Reference style cue (learn only, do NOT copy the source image): "
                "adopt a %s palette led by %s (accent %s, base %s / %s), "
                "match the overall color mood and visual texture, "
                "then create a completely new advertising scene from the copy brief. "
                "Do not reproduce the reference subject, text, logo, watermark or pixels."
                % (tone, "light" if light else "deep", _hex(accent), _hex(bg1), _hex(bg2))
            )
            return {"ok": True, "reason": "", "palette_override": palette_override,
                    "style_prompt": style_prompt, "traits": traits}
    except Exception as e:
        return {**empty, "reason": "参考图风格提取失败：%s" % type(e).__name__}


def render_reference_style_block(analysis: dict | None) -> str:
    """把风格学习结论渲染成可拼接的提示词块；失败或无内容返回空串。"""
    if not (analysis or {}).get("ok"):
        return ""
    text = str(analysis.get("style_prompt") or "").strip()
    return ("[ReferenceStyle / learn-only] " + text) if text else ""
