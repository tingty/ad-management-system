"""V4.46 / D4：提示词编译（prompt_compiler）→ PromptBundle。

文档要求（D4「提示词编译和视觉制作的具体做法」）：
- 新增 `prompt_compiler`，把**事实与策略、参考资产、版位、供应商能力**编译为 PromptBundle；
- 统一事实边界，但按**资产角色**决定是否带文字 / Logo / 按钮；不能全局固定 no UI，
  也不能每个广告都烘焙 CTA；
- 组成：事实输入（确认产品 / 允许 claim / 限定条件 / 引用 ID / 禁止推断项）、概念输入
  （受众 / 场景 / 购买理由 / 画面叙事 / 推荐理由）、参考输入（官方商品或真实 UI 文件 /
  角色 / 身份与编辑权限）、画面指令（主体大小 / 位置 / 动作 / 光线 / 文字区与保护框）、
  输出约束（目标比例 / 禁止虚构物件 / 不生成第二个伪商品）、后期渲染（图内文案字体与
  预算 / Logo 位置 / 必要说明 / 导出格式）、追溯信息（事实 / 规则 / 提示词 / 配置 / 模型 /
  资产及计划版本）；
- 供应商失败后的纯渐变模板、过小不可读文案、商品外观不一致、claim 缺证据等结果进入
  draft 或 needs_revision（见 job_service QA 阶段）。

本模块只做确定性编译（不调用模型）。最终发送内容可追溯、可重现。
"""
from __future__ import annotations

import hashlib
import json

# 按资产角色决定「是否烘焙图内文案 / Logo / CTA 按钮」：
# - feed_image / story_vertical / splash 等主视觉：带图内短标题与 Logo，但 CTA 视版位而定；
# - banner / display_banner：文字极简、以 Logo 为主，CTA 不进画面；
# - native_image：图内不放 CTA 按钮，文字留给原生标题；
# 不允许「全局 no UI」一刀切，也不允许「每张都烘焙 CTA」。
ASSET_ROLE_RENDER = {
    "feed_image": {"bake_text": True, "bake_logo": True, "bake_cta": True, "copy_zone": "左下文字层"},
    "story_vertical": {"bake_text": True, "bake_logo": True, "bake_cta": True, "copy_zone": "底部文字层"},
    "reels_vertical": {"bake_text": True, "bake_logo": True, "bake_cta": True, "copy_zone": "底部文字层"},
    "app_portrait": {"bake_text": False, "bake_logo": True, "bake_cta": False, "copy_zone": "（界面即内容）"},
    "fullscreen_portrait": {"bake_text": False, "bake_logo": True, "bake_cta": False, "copy_zone": "（界面即内容）"},
    "splash_vertical": {"bake_text": False, "bake_logo": True, "bake_cta": False, "copy_zone": "角标区"},
    "display_banner": {"bake_text": True, "bake_logo": True, "bake_cta": False, "copy_zone": "左侧文字区"},
    "horizontal_still": {"bake_text": True, "bake_logo": True, "bake_cta": False, "copy_zone": "底部文字条"},
    "native_image": {"bake_text": False, "bake_logo": True, "bake_cta": False, "copy_zone": "（交由原生标题）"},
    "banner": {"bake_text": False, "bake_logo": True, "bake_cta": False, "copy_zone": "（极简 Logo）"},
    "in_feed_vertical": {"bake_text": True, "bake_logo": True, "bake_cta": True, "copy_zone": "底部文字层"},
    "unspecified": {"bake_text": True, "bake_logo": True, "bake_cta": False, "copy_zone": "左下文字层"},
}


def compile_prompt_bundle(concept: dict, brief: dict, references: list[dict] | None = None,
                          asset_role: str = "feed_image",
                          supplier_caps: dict | None = None) -> dict:
    """D4：把概念 + VisualBrief + 参考资产编译成可执行、可追溯的 PromptBundle。

    入参：
    - concept：来自 `creation_planner.build_structured_concepts` 的单个概念；
    - brief：同一对象的 VisualBrief；
    - references：官方商品图 / 真实 UI 文件清单（无则标记为「须先获取」）；
    - asset_role：资产角色，决定画面指令与文字 / Logo / CTA 策略；
    - supplier_caps：供应商能力声明（如是否支持商品环境融合、字体内嵌等）。

    返回 PromptBundle（system / task / references / render_spec / hashes）。
    """
    concept = concept if isinstance(concept, dict) else {}
    brief = brief if isinstance(brief, dict) else {}
    refs = references if isinstance(references, list) else []
    caps = supplier_caps if isinstance(supplier_caps, dict) else {}

    role_cfg = ASSET_ROLE_RENDER.get(asset_role) or ASSET_ROLE_RENDER["unspecified"]

    # --- 事实输入：统一事实边界与禁止推断项 ---
    fact_input = {
        "confirmed_product": brief.get("subject", ""),
        "allowed_claim": concept.get("promise", ""),
        "claim_ids": concept.get("claim_ids", []),
        "must_preserve_qualifiers": concept.get("must_preserve_qualifiers", []),
        "forbidden_inferences": concept.get("forbidden_inferences", []),
    }

    # --- 概念输入 ---
    concept_input = {
        "audience": concept.get("audience", ""),
        "situation": concept.get("situation", ""),
        "purchase_reason": concept.get("purchase_reason", ""),
        "narrative": concept.get("promise", ""),
        "distinct_reason": concept.get("distinct_reason", ""),
    }

    # --- 参考输入：官方商品 / 真实 UI；缺失则明确标记，不编造 ---
    ref_input = []
    for r in refs:
        if isinstance(r, dict):
            ref_input.append({
                "kind": r.get("kind", "official_product"),
                "file": r.get("file", ""),
                "role": r.get("role", ""),
                "edit_permission": r.get("edit_permission", "authorized"),
            })
    missing_refs = [k for k in ("official_product", "real_ui", "authorized_deliverable")
                    if not any(x.get("kind") == k for x in ref_input)]
    if missing_refs:
        for k in missing_refs:
            ref_input.append({"kind": k, "file": "", "role": "missing",
                              "edit_permission": "pending", "required": True})

    # --- 画面指令 ---
    render_spec = {
        "size": brief.get("size") or brief.get("layout") or "",
        "asset_role": asset_role,
        "subject": brief.get("subject", ""),
        "scene": brief.get("scene", ""),
        "composition": brief.get("composition", ""),
        "copy_zone": role_cfg["copy_zone"],
        "bake_text": role_cfg["bake_text"],
        "bake_logo": role_cfg["bake_logo"],
        "bake_cta": role_cfg["bake_cta"],
        "text_protection_box": role_cfg["bake_text"],
        "logo_placement": "右下角安全区" if role_cfg["bake_logo"] else "",
        "constraints": [
            "禁止生成第二个虚构商品或伪造品牌",
            "商品外观须与官方 / 已授权参考一致，不一致则进入 draft",
            "不超过 1 条图内短标题，不堆叠多段文案",
        ],
        "supplier_caps": caps,
        "no_fake_product": True,
    }

    # --- 后期渲染 ---
    post_render = {
        "font": "与系统字体回退一致，避免豆腐块",
        "export_format": "PNG",
        "logo_position": render_spec["logo_placement"],
        "caption": brief.get("short_copy", ""),
    }

    # --- system / task 提示词文本（确定性拼接，便于追溯）---
    system = (
        "你是按既定事实边界执行的视觉制作执行器。严格使用提供的确认产品与允许 claim；"
        "不得生成第二个虚构商品、不得伪造品牌、不得扩大限定条件或适用范围。"
        + ("禁止推断项：" + "；".join(fact_input["forbidden_inferences"]) + "。" if fact_input["forbidden_inferences"] else "")
    )
    task = (
        f"以【{fact_input['confirmed_product']}】为主体，在【{concept_input['situation']}】展示"
        f"【{fact_input['allowed_claim']}】；采用【{render_spec['composition']}】。"
        f"{('保留限定条件：' + '、'.join(fact_input['must_preserve_qualifiers']) + '。') if fact_input['must_preserve_qualifiers'] else ''}"
        f"文字区在【{render_spec['copy_zone']}】；"
        f"图内文案={'启用' if role_cfg['bake_text'] else '不启用'}，"
        f"Logo={'启用' if role_cfg['bake_logo'] else '不启用'}，"
        f"CTA 按钮={'启用' if role_cfg['bake_cta'] else '不启用'}。"
        + ("参考资产缺失，须先获取官方 / 授权资产再生成；不得用纯文生图自由重画主体。" if missing_refs else "")
    )

    bundle = {
        "schema_version": "1.0",
        "system": system,
        "task": task,
        "fact_input": fact_input,
        "concept_input": concept_input,
        "references": ref_input,
        "missing_references": missing_refs,
        "render_spec": render_spec,
        "post_render": post_render,
        "traceability": {
            "concept_id": concept.get("concept_id", ""),
            "claim_ids": concept.get("claim_ids", []),
            "asset_role": asset_role,
            "plan_version": brief.get("version", ""),
        },
        "hashes": _bundle_hashes(system, task, fact_input, concept_input, ref_input, render_spec),
        "note": "最终发送内容可追溯与可重现；本 Bundle 不含任何模型密钥。",
    }
    return bundle


def _bundle_hashes(system, task, fact_input, concept_input, ref_input, render_spec) -> dict:
    raw = json.dumps(
        {"s": system, "t": task, "f": fact_input, "c": concept_input,
         "r": ref_input, "rs": render_spec},
        ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {"bundle_hash": digest[:16], "full": digest}
