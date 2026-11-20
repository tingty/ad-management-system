"""素材创意模板库 · 模板基础可用性校验 + 模板骨架出图适配（纯函数 / DB 查询层）。

产品决议：
1. 模板只允许影响图片（Q9）：本模块把 `image_skeleton_json` 转成一条**视觉路线**
   注入 `style_opts.creative_plan`，复用既有图片提示词规则；文案生成链路完全不读模板。
2. 工作坊按模板创作前只校验**模板自身**是否可用（归属 / 状态 / 骨架 / 引用素材完整），
   给出可执行的 `required_action`，不静默降级。

不直接依赖 FastAPI，方便专项测试；DB 查询只在本模块内以函数参数注入 session。
"""
from __future__ import annotations

from typing import Any, Optional


def template_gate(db, template_id: Optional[int], owner_id: int) -> dict:
    """校验模板在工作坊按模板创作前是否可用（仅模板自身属性）。

    返回 {template, ok, reason, required_action}；DB 异常不外泄给用户细节。
    """
    out = {"template": None, "ok": False, "reason": "", "required_action": ""}
    if not template_id or not str(template_id).isdigit():
        out.update(reason="请选择一条素材模板", required_action="先在素材创意模板库沉淀模板")
        return out
    from models import CreativeAssetSource, CreativeTemplate

    t = db.query(CreativeTemplate).filter_by(id=int(template_id), owner_id=owner_id).first()
    if not t:
        out.update(reason="模板不存在或无权使用", required_action="重新选择本人创建的模板")
        return out
    out["template"] = t
    if str(t.status or "active").strip().lower() != "active":
        out.update(reason=f"模板状态为 {t.status or '未知'}，当前不可用",
                   required_action="请在素材创意模板库启用该模板")
        return out
    ids = list(t.merged_asset_ids or [])
    if t.golden_asset_id and t.golden_asset_id not in ids:
        ids.append(t.golden_asset_id)
    if not ids:
        out.update(reason="模板没有可追溯的素材表达（golden / 归并记录缺失）",
                   required_action="请重新沉淀模板")
        return out
    assets = db.query(CreativeAssetSource).filter(
        CreativeAssetSource.owner_id == owner_id,
        CreativeAssetSource.id.in_(ids)).all()
    if len(assets) != len(ids):
        out.update(reason="模板引用的素材已不存在，按模板创作已拦截",
                   required_action="请重新沉淀模板或补回素材")
        return out
    skeleton = t.image_skeleton_json if isinstance(t.image_skeleton_json, dict) else {}
    if not skeleton:
        out.update(reason="模板没有可用的图片骨架，不能驱动按模板创作",
                   required_action="请编辑模板补齐图片骨架")
        return out
    out["ok"] = True
    return out


def _text(value: Any, limit: int = 160) -> str:
    import re
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def template_style_opts(template: Any, platform: str) -> dict:
    """把模板骨架转成出图规则（只影响图片），返回可并入 style_opts 的 dict。

    只借用视觉结构（构图 / 视线动线 / 主体位置 / 留白 / 配色 / 光线 / 质感 / 情绪），
    不把 golden 素材的品牌、具体文案、数字带进新素材；当次产品事实由分析与文案提供。
    """
    sk = template.image_skeleton_json if isinstance(template.image_skeleton_json, dict) else {}
    visual_labels = (
        ("composition", "构图"), ("focal_path", "视线动线"),
        ("subject_position", "主体位置"), ("negative_space", "留白"),
        ("palette", "配色"), ("lighting", "光线"),
        ("texture", "质感"), ("emotion", "情绪"),
    )
    bits = [f"{label}={_text(sk.get(key), 80)}" for key, label in visual_labels if sk.get(key)]
    name = _text(template.name, 40) or "素材模板"
    route = {
        "key": f"T{template.id}",
        "name": f"按模板创作 · {name}",
        "angle": "复用已沉淀模板的视觉表达骨架；产品事实与利益点由本次分析重新提供",
        "description": "；".join(bits) or "沿用该模板的版式层级与视觉调性",
        "tags": [str(template.primary_category or "")] + [
            str(x) for x in (template.purpose or [])][:3],
        "framework": "",
        "hook": "以本次文案钩子为准，不沿用模板素材的原始钩子文案",
        "proof": "以本次证据包为准，无证据不编造数字或效果",
        "visual_hook": _text(sk.get("focal_path") or sk.get("composition"), 120),
        "cta_role": "CTA 由合成层按本次投放目标绘制，生成画面保持零文字",
        "user_note": "仅复刻构图与视觉表达结构；禁止沿用模板来源素材的品牌、具体文案、价格与数字",
    }
    return {
        "fit_overlay": True,
        "creative_plan": {
            "routes": [route],
            "supplement": (
                f"按素材模板「{name}」的版式与视觉表达骨架出图，"
                "仅借用构图 / 配色 / 光线 / 质感 / 信息层级；"
                "所有产品事实、卖点、CTA 与证据均由本次分析和文案决定，"
                "不得沿用模板来源素材的具体品牌、文案、价格与数字。"),
            "platform": str(platform or ""),
            "overlay_mode": "text_button",
        },
        "template_id": int(template.id),
        "template_name": name,
    }
