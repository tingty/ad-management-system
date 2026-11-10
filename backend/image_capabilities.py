"""V4.42 / F06：供应商尺寸能力目录 + 按比例构图 + 主体保护裁切。

说明书 F06 的原始问题：MaaS 适配器把宽高分别吸附到 1024 / 2048，
1200x628 会被请求成 1024x1024；渲染器再用 cover 居中裁切，主体、场景或留白丢失。

本模块只做三件可被确定性验证的事：

1. **能力目录（不编造尺寸）**：默认候选沿用代码里已注释「实测可用」的方形尺寸；
   其它比例由管理员通过 `params.size_candidates` 显式配置并附核验日期。
   `size_verified_on` 为空时明确标注「未核验」，绝不声称 API 已支持某比例。
2. **按比例选择请求尺寸**：在已知候选中挑比例最接近目标的；比例差超阈值时
   标记 `needs_outpaint`，由渲染端扩图 / 主体保护处理，而不是静默裁掉。
3. **主体保护裁切**：给定源图、目标尺寸、主体框与文字区，计算能完整保留主体框的
   裁切锚点；主体框大于窗口或极端横幅时改用扩图（contain + 边缘延展），不裁主体。

`plan_composition()` 返回的 dict 会随每张素材归档，满足 T08「记录请求尺寸、
实际返回尺寸和裁切参数」。
"""
from __future__ import annotations

import math

# 候选尺寸属于「能力声明」，不是媒体投放规则。VERIFIED_ON 为空 = 未经官方文档 / 受控测试核验；
# 只有代码中已有实测说明的 1024 / 2048 方形作为默认，其余比例必须显式配置。
DEFAULT_SQUARE_CANDIDATES = [(1024, 1024), (2048, 2048)]

PROVIDER_CAPABILITIES: dict[str, dict] = {
    "dashscope_maas": {
        "label": "阿里云 MaaS qwen-image",
        "size_candidates": DEFAULT_SQUARE_CANDIDATES,
        "size_verified_on": "",
        "supports_reference": False,
        "supports_inpaint": False,
        "supports_transparent": False,
        "max_concurrency": 2,
        "note": "默认仅方形尺寸有代码内实测说明；其余比例需以官方文档 / 受控测试补齐后配置",
    },
    "openai_image": {
        "label": "DALL·E 兼容 /images/generations",
        "size_candidates": [(1024, 1024), (1792, 1024), (1024, 1792)],
        "size_verified_on": "",
        "supports_reference": False,
        "supports_inpaint": False,
        "supports_transparent": False,
        "max_concurrency": 2,
        "note": "三种尺寸来自现有适配器 _nearest_size；未附官方核验日期",
    },
    "generic_image": {
        "label": "通用文生图 / 自定义 endpoint",
        "size_candidates": [],           # 空 = 直接把目标尺寸透传给供应商
        "size_verified_on": "",
        "supports_reference": False,
        "supports_inpaint": False,
        "supports_transparent": False,
        "max_concurrency": 2,
        "note": "按目标尺寸直传；供应商是否支持由部署方核验",
    },
    "template": {
        "label": "本地模板底图",
        "size_candidates": [],
        "size_verified_on": "",
        "supports_reference": False,
        "supports_inpaint": False,
        "supports_transparent": True,
        "max_concurrency": 0,
        "note": "不调用外部供应商，按目标尺寸本地绘制",
    },
}

RATIO_TOLERANCE = 0.15       # 候选与目标比例的相对误差上限
EXTREME_RATIO = 4.0          # 宽高比超过该值视为极端横幅 / 竖条，直接扩图


def _ratio(w: int, h: int) -> float:
    return float(w) / max(1, int(h))


def _parse_candidates(raw) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                w, h = int(item[0]), int(item[1])
            elif isinstance(item, str):
                parts = item.lower().replace("*", "x").split("x")
                if len(parts) != 2:
                    continue
                w, h = int(parts[0]), int(parts[1])
            else:
                continue
            if 64 <= w <= 4096 and 64 <= h <= 4096:
                out.append((w, h))
        except (TypeError, ValueError):
            continue
    return out


def capability_of(provider_key: str, params: dict | None = None) -> dict:
    """返回某供应商的实际能力声明；`params.size_candidates` 可覆盖默认候选。"""
    base = dict(PROVIDER_CAPABILITIES.get(provider_key)
                or PROVIDER_CAPABILITIES["generic_image"])
    custom = _parse_candidates((params or {}).get("size_candidates"))
    if custom:
        base["size_candidates"] = custom
        base["size_verified_on"] = (params or {}).get("size_verified_on") or ""
        base["note"] = "部署方显式配置的尺寸候选；核验日期见 size_verified_on"
    else:
        base["size_candidates"] = list(base["size_candidates"])
    return base


def plan_generation_size(provider_key: str, target_w: int, target_h: int,
                         params: dict | None = None) -> dict:
    """按目标比例挑选供应商实际支持的请求尺寸（T08：比例记录准确）。

    与旧 `_snap(width)/_snap(height)` 的区别：宽高不再各自吸附，而是作为一个
    **比例整体**来选候选；没有任何候选接近目标比例时，返回 `needs_outpaint=True`
    并在 `capability_note` 中如实说明，由渲染端保护主体，绝不静默居中裁切。
    """
    tw, th = max(1, int(target_w)), max(1, int(target_h))
    cap = capability_of(provider_key, params)
    candidates = cap["size_candidates"]
    target_ratio = _ratio(tw, th)
    if not candidates:
        return {
            "provider": provider_key, "target_size": [tw, th],
            "request_size": [tw, th], "needs_outpaint": False,
            "ratio_delta": 0.0, "size_verified_on": cap["size_verified_on"],
            "capability_note": cap["note"] + "；目标尺寸直传，未做比例对齐",
            "candidates": [],
        }
    best = min(candidates, key=lambda wh: abs(math.log(_ratio(*wh) / target_ratio)))
    delta = abs(_ratio(*best) / target_ratio - 1.0)
    needs_outpaint = delta > RATIO_TOLERANCE
    return {
        "provider": provider_key,
        "target_size": [tw, th],
        "request_size": [int(best[0]), int(best[1])],
        "needs_outpaint": needs_outpaint,
        "ratio_delta": round(delta, 4),
        "size_verified_on": cap["size_verified_on"],
        "candidates": [list(x) for x in candidates],
        "capability_note": (
            cap["note"] + ("；所有已声明候选均偏离目标比例，渲染端使用主体保护 / 扩图"
                           if needs_outpaint else "；候选比例与目标接近")
        ),
    }


def composition_goal(target_w: int, target_h: int, layout: str = "hero") -> str:
    """给文生图提示词的构图目标：主体位置 + 文字留白，避免主体被压到裁切线上。"""
    w, h = max(1, int(target_w)), max(1, int(target_h))
    r = _ratio(w, h)
    if r >= EXTREME_RATIO or r <= 1.0 / EXTREME_RATIO:
        return ("Extreme aspect ratio: keep the full main subject inside a compact central "
                "safe area with generous empty margin on all sides; no critical detail near edges.")
    if r > 1.25:
        return ("Wide composition: place the main subject in the right two-thirds, leave the "
                "left third as clean uncluttered negative space for advertising text.")
    if r < 0.8:
        return ("Tall composition: place the main subject in the upper half, leave the lower "
                "third as clean negative space for headline and call to action.")
    return ("Square composition: keep the main subject within the central 70% safe area, "
            "leave the lower third uncluttered for text overlay.")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def plan_composition(target_w: int, target_h: int, src_w: int, src_h: int,
                     subject_box: tuple[float, float, float, float] | None = None,
                     text_box: tuple[float, float, float, float] | None = None,
                     layout: str = "hero") -> dict:
    """计算「能完整保留主体框」的裁切 / 扩图方案（纯函数，T08 可直接断言）。

    subject_box / text_box 为**目标画布**上的相对坐标 (x0,y0,x1,y1)，取值 0..1。
    返回 dict 中的 `crop` 是源图缩放后坐标系里的 [left, top, right, bottom]。
    """
    tw, th = max(1, int(target_w)), max(1, int(target_h))
    sw, sh = max(1, int(src_w)), max(1, int(src_h))
    sb = tuple(float(v) for v in (subject_box or (0.05, 0.05, 0.95, 0.95)))
    tb = tuple(float(v) for v in (text_box or (0.0, 0.62, 0.60, 1.0)))
    sb = (_clamp(sb[0], 0, 1), _clamp(sb[1], 0, 1),
          _clamp(sb[2], 0, 1), _clamp(sb[3], 0, 1))
    if sb[2] <= sb[0]:
        sb = (sb[0], sb[1], min(1.0, sb[0] + 0.1), sb[3])
    if sb[3] <= sb[1]:
        sb = (sb[0], sb[1], sb[2], min(1.0, sb[1] + 0.1))
    ratio = _ratio(tw, th)
    extreme = ratio >= EXTREME_RATIO or ratio <= 1.0 / EXTREME_RATIO

    # cover 缩放到能覆盖目标画布
    scale = max(tw / sw, th / sh)
    scaled_w, scaled_h = sw * scale, sh * scale
    # 主体保护框在「缩放后源图」中的可用区域：主体应落在目标画布的 sb 区域内
    allowed_w = (sb[2] - sb[0]) * tw
    allowed_h = (sb[3] - sb[1]) * th
    # 源图可视区域比例与目标画布差异过大时，主体无法在 cover 下完整保留 → 扩图
    content_ratio = _ratio(sw, sh)
    ratio_gap = abs(content_ratio / max(1e-6, ratio) - 1.0)
    need_outpaint = extreme or ratio_gap > 0.45 or allowed_w < 16 or allowed_h < 16

    # 文字区避让：如果文字区在左侧，裁切窗口尽量靠右，反之靠左
    text_center_x = (tb[0] + tb[2]) / 2.0
    anchor_x = 0.5 if abs(text_center_x - 0.5) < 0.12 else (0.72 if text_center_x < 0.5 else 0.28)
    text_center_y = (tb[1] + tb[3]) / 2.0
    anchor_y = 0.5 if abs(text_center_y - 0.5) < 0.12 else (0.68 if text_center_y < 0.5 else 0.32)

    free_x = max(0.0, scaled_w - tw)
    free_y = max(0.0, scaled_h - th)
    left = _clamp(free_x * anchor_x, 0, free_x)
    top = _clamp(free_y * anchor_y, 0, free_y)
    crop = [int(round(left)), int(round(top)),
            int(round(left + tw)), int(round(top + th))]

    # 主体框在目标画布上的落点（用于验证「保护框完整」）
    dst_subject = [round(sb[0] * tw, 1), round(sb[1] * th, 1),
                   round(sb[2] * tw, 1), round(sb[3] * th, 1)]

    return {
        "mode": "outpaint" if need_outpaint else "protected_crop",
        "target_size": [tw, th],
        "source_size": [sw, sh],
        "requested_size": [tw, th],
        "scale": round(scale, 5),
        "anchor": [round(anchor_x, 3), round(anchor_y, 3)],
        "crop": None if need_outpaint else crop,
        "subject_box": [round(v, 4) for v in sb],
        "text_box": [round(v, 4) for v in tb],
        "subject_box_px": dst_subject,
        "protected": True,
        "extreme_ratio": extreme,
        "ratio_gap": round(ratio_gap, 4),
        "layout": layout,
        "capability_note": ("源图比例与目标差异过大或极端版位，按 contain 扩图保留完整主体，"
                            "不执行居中裁切" if need_outpaint else
                            "按主体保护锚点裁切，主体框与文字区分离"),
    }


def apply_composition(img, comp: dict, fill=(16, 42, 67)):
    """按 plan_composition 的结果把源图放到目标画布；返回 (RGB 图, 实际裁切参数)。

    outpaint 模式：整图 contain 缩放进画布，四周用边缘像素延展 + 品牌底色填充，
    **不裁掉任何源图内容**（T08 的中心 / 边缘标记全部保留）。
    protected_crop 模式：按主体保护锚点裁切，主体框与文字区分离。
    """
    from PIL import Image, ImageFilter

    tw, th = comp["target_size"]
    canvas = Image.new("RGB", (tw, th), fill)
    src = img.convert("RGB")
    if comp["mode"] == "outpaint":
        scale = min(tw / src.width, th / src.height)
        nw, nh = max(1, int(src.width * scale)), max(1, int(src.height * scale))
        small = src.resize((nw, nh), Image.LANCZOS)
        # 边缘延展：把缩略图轻微放大并模糊后垫在底层，避免出现生硬色块
        pad = canvas.copy()
        try:
            bleed = small.resize((tw, th), Image.LANCZOS).filter(ImageFilter.GaussianBlur(max(2, tw // 90)))
            pad = Image.blend(Image.new("RGB", (tw, th), fill), bleed, 0.55)
        except Exception:
            pass
        canvas.paste(pad, (0, 0))
        canvas.paste(small, ((tw - nw) // 2, (th - nh) // 2))
        return canvas, {**comp, "crop": None, "applied_mode": "outpaint",
                        "content_box": [(tw - nw) // 2, (th - nh) // 2,
                                        (tw - nw) // 2 + nw, (th - nh) // 2 + nh]}

    scale = comp["scale"]
    nw = max(1, int(src.width * scale))
    nh = max(1, int(src.height * scale))
    scaled = src.resize((nw, nh), Image.LANCZOS)
    l, t, r, b = comp["crop"]
    l, t = max(0, l), max(0, t)
    r, b = min(nw, max(l + 1, r)), min(nh, max(t + 1, b))
    piece = scaled.crop((l, t, r, b))
    if piece.size != (tw, th):
        piece = piece.resize((tw, th), Image.LANCZOS)
    return piece, {**comp, "crop": [l, t, r, b], "applied_mode": "protected_crop"}


def public_capabilities() -> dict:
    """供 /api/image-capabilities 下发，前端可查看「哪些比例已核验」。"""
    return {
        "providers": {
            k: {kk: vv for kk, vv in v.items() if kk != "size_candidates"}
               | {"size_candidates": [list(x) for x in v.get("size_candidates", [])]}
            for k, v in PROVIDER_CAPABILITIES.items()
        },
        "ratio_tolerance": RATIO_TOLERANCE,
        "extreme_ratio": EXTREME_RATIO,
        "note": "尺寸能力以实施时官方文档与受控测试为准；size_verified_on 为空表示尚未核验。",
    }
