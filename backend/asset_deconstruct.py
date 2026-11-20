"""V4.118 素材创意模板库 · 图片解构引擎（framework_version: asset-deconstruct/1.0）。

把一张导入的推广图片，用**真实视觉模型**按固定维度字典解构成结构化 JSON，供后续
分类 / 归并 / 沉淀为可复用模板（V4.119+）。设计红线（沿用项目一贯的诚实交付原则）：

1. **绝不走 Mock / Fallback**：直接复用 video_vision_audit 的同源视觉通道
   （_vision_model_cfg 取真实配置 + base64 data URL + OpenAI 兼容 /chat/completions）。
   无配置 / 非 OpenAI 协议 / 调用失败 / 返回不可解析，一律 status=unavailable，
   dims_json 不臆造、不冒充已解构。
2. **效果层只做创意推断**：effect 每项带 caveat「创意推断，非真实投放数据」，
   绝不编造 CTR/CVR（导入的是别人的素材，没有真实投放数据）。
3. **框架版本化**：framework_version 固定，维度字典集中在此，便于回归防维度漂移。
4. **完整度可量化**：按 Q6 口径，12 个必填计分项中"有值且 conf≥0.6"的占比。

固定六步流程中，本模块负责第 3–6 步（视觉解构 / 结构文案解构 / 效果推断 / 分类与
模板归属建议）；第 1–2 步（导入登记 / 规范化）由前端导入 + upload 接口完成。
"""
from __future__ import annotations

import base64
import json
import re
from typing import Optional

FRAMEWORK_VERSION = "asset-deconstruct/1.0"

# 主分类轴 12 类（冻结口径，Q4 已确认），供模型归属与归并键使用。
PRIMARY_CATEGORIES = [
    "前后对比", "问题-方案", "社会证明", "利益清单", "限时促销", "权威背书",
    "场景沉浸", "产品特写", "悬念钩子", "挑战实测", "情感共鸣", "UGC 原生",
]
# 辅助标签维度（冻结口径 Q4）：purpose 参与归并键。
PURPOSES = ["拉新", "激活", "转化", "召回", "品牌认知"]
HOOK_TYPES = ["价格", "结果", "痛点", "好奇", "社会证明"]
EVIDENCE_KINDS = ["数据数字", "用户评价", "对比画面", "权威认证", "无证据"]

# 必填计分项（12 项）：布局3 + 视觉3 + 信息4 + 分类2；完整度分母。
_COMPLETENESS_KEYS = [
    ("layout", "composition"), ("layout", "focal_path"), ("layout", "subject_position"),
    ("visual", "palette"), ("visual", "lighting"), ("visual", "texture"),
    ("info", "headline_role"), ("info", "benefits"), ("info", "cta"), ("info", "evidence_kind"),
    ("category", "primary"), ("category", "purpose"),
]

_SYSTEM = (
    "你是广告素材解构分析师。只根据画面肉眼可见内容，把这张推广图按固定维度拆解，"
    "只输出严格 JSON，不要解释、不要 Markdown、不要编造画面里看不到的事实或数字。"
    "每个维度输出 {\"value\": <字符串或数组>, \"confidence\": 0到1}；确实看不出时 value 用空字符串、confidence 用 0，绝不猜测。\n"
    "JSON 结构：\n"
    "{\"layout\":{\"composition\":{\"value\":\"构图套路\",\"confidence\":0.8},\"focal_path\":{\"value\":\"视觉动线\",\"confidence\":0.6},\"subject_position\":{\"value\":\"主体位置\",\"confidence\":0.9},\"negative_space\":{\"value\":\"留白\",\"confidence\":0.5}},\n"
    "\"visual\":{\"palette\":{\"value\":\"配色\",\"confidence\":0.8},\"lighting\":{\"value\":\"光线\",\"confidence\":0.7},\"texture\":{\"value\":\"质感\",\"confidence\":0.6}},\n"
    "\"info\":{\"headline_role\":{\"value\":\"标题角色\",\"confidence\":0.7},\"benefits\":{\"value\":[\"卖点\"],\"confidence\":0.8},\"cta\":{\"value\":\"行动号召原文或描述\",\"confidence\":0.6},\"evidence_kind\":{\"value\":\"证据形式\",\"confidence\":0.6},\"text_on_image\":{\"value\":false,\"confidence\":0.9}},\n"
    "\"effect\":{\"hook_type\":{\"value\":\"钩子类型\",\"confidence\":0.7},\"emotion\":{\"value\":\"情绪基调\",\"confidence\":0.6},\"intent\":{\"value\":\"传达意图\",\"confidence\":0.6}},\n"
    "\"category\":{\"primary\":{\"value\":\"主分类\",\"confidence\":0.7},\"purpose\":{\"value\":[\"推广目的\"],\"confidence\":0.7},\"hook\":{\"value\":\"钩子\",\"confidence\":0.6},\"tags\":{\"value\":{\"风格\":\"写实\"},\"confidence\":0.5}},\n"
    "\"template_guess\":{\"name\":\"推测的模板名\",\"confidence\":0.7,\"diff\":[\"与典型模板的差异\"]}}\n"
    f"category.primary 只能从这 12 类取一个：{' / '.join(PRIMARY_CATEGORIES)}。"
    f"category.purpose 从这些取：{' / '.join(PURPOSES)}。"
    f"category.hook 从这些取：{' / '.join(HOOK_TYPES)}。"
    "effect 只描述创意 / 传达层，不推断任何真实投放数据（CTR/CVR/销量）。"
)
_USER = "按系统给定的 JSON 结构解构这张推广图。看不到的维度 value 填空、confidence 填 0。"


def _unavailable(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "framework_version": FRAMEWORK_VERSION,
            "dims_json": {}, "category_json": {}, "template_guess": {},
            "completeness": 0.0, "confidence": 0.0}


def _value_of(cell) -> object:
    if isinstance(cell, dict):
        return cell.get("value")
    return None


def _conf_of(cell) -> float:
    if isinstance(cell, dict):
        try:
            return max(0.0, min(1.0, float(cell.get("confidence") or 0)))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _has_value(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict)):
        return len(v) > 0
    return True


def compute_completeness(dims: dict, threshold: float = 0.6) -> tuple[float, float]:
    """按 Q6 口径算完整度与综合置信度。

    返回 (completeness, confidence)：completeness = 12 项中「有值且 conf≥threshold」占比；
    confidence = 所有非空格的 conf 均值。维度缺失 / 空值不计分。
    """
    if not isinstance(dims, dict):
        return 0.0, 0.0
    scored = 0
    confs: list[float] = []
    for section, key in _COMPLETENESS_KEYS:
        cell = (dims.get(section) or {}).get(key) if isinstance(dims.get(section), dict) else None
        val, conf = _value_of(cell), _conf_of(cell)
        if _has_value(val):
            confs.append(conf)
            if conf >= threshold:
                scored += 1
    completeness = round(scored / len(_COMPLETENESS_KEYS), 4)
    confidence = round(sum(confs) / len(confs), 4) if confs else 0.0
    return completeness, confidence


def _normalize_cell(cell) -> dict:
    return {"value": _value_of(cell), "confidence": _conf_of(cell)}


def _normalize(raw: dict) -> dict:
    """把模型输出收敛成稳定结构：维度白名单化、分类归一、effect 加 caveat。"""
    get = lambda k: raw.get(k) if isinstance(raw, dict) else None
    layout_src = get("layout") if isinstance(get("layout"), dict) else {}
    visual_src = get("visual") if isinstance(get("visual"), dict) else {}
    info_src = get("info") if isinstance(get("info"), dict) else {}
    effect_src = get("effect") if isinstance(get("effect"), dict) else {}
    cat_src = get("category") if isinstance(get("category"), dict) else {}

    dims = {
        "layout": {k: _normalize_cell(layout_src.get(k)) for k in
                   ("composition", "focal_path", "subject_position", "negative_space")},
        "visual": {k: _normalize_cell(visual_src.get(k)) for k in ("palette", "lighting", "texture")},
        "info": {k: _normalize_cell(info_src.get(k)) for k in
                 ("headline_role", "benefits", "cta", "evidence_kind", "text_on_image")},
        "effect": {k: _normalize_cell(effect_src.get(k)) for k in ("hook_type", "emotion", "intent")},
    }
    # effect 诚实标注：只创意推断，非投放数据（Q3）。
    for v in dims["effect"].values():
        v["caveat"] = "创意推断，非真实投放数据"

    primary = str(_value_of(cat_src.get("primary")) or "").strip()
    if primary not in PRIMARY_CATEGORIES:
        # 模型给了自由文本：保留原值但标未归一，供人工确认；不硬塞进 12 类。
        primary_norm = primary[:40]
    else:
        primary_norm = primary
    def _str_list(cell):
        v = _value_of(cell)
        if isinstance(v, str):
            return [v.strip()] if v.strip() else []
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()][:8]
        return []
    purposes = [p for p in _str_list(cat_src.get("purpose")) if p in PURPOSES]
    hooks = [h for h in _str_list(cat_src.get("hook")) if h in HOOK_TYPES]
    category = {
        "primary": {"value": primary_norm, "confidence": _conf_of(cat_src.get("primary")),
                    "in_taxonomy": primary in PRIMARY_CATEGORIES},
        "purpose": {"value": purposes, "confidence": _conf_of(cat_src.get("purpose"))},
        "hook": {"value": hooks, "confidence": _conf_of(cat_src.get("hook"))},
        "tags": _normalize_cell(cat_src.get("tags")),
    }
    dims["category"] = category
    completeness, confidence = compute_completeness(dims)

    guess_src = get("template_guess") if isinstance(get("template_guess"), dict) else {}
    diff = guess_src.get("diff")
    template_guess = {
        "name": str(guess_src.get("name") or "")[:80],
        "confidence": _conf_of({"confidence": guess_src.get("confidence")}),
        "diff": [str(x).strip() for x in diff if str(x).strip()][:8] if isinstance(diff, (list, tuple)) else [],
    }
    return {
        "framework_version": FRAMEWORK_VERSION,
        "dims_json": dims,
        "category_json": {
            "primary": primary_norm, "purposes": purposes, "hooks": hooks,
            "taxonomy_version": "asset-category/1.0",
        },
        "template_guess": template_guess,
        "completeness": completeness,
        "confidence": confidence,
        "status": "analyzed",
    }


async def deconstruct_image(image_bytes: bytes, model_cfg: Optional[dict]) -> dict:
    """用真实视觉模型解构单张图片；任何不可用都返回 status=unavailable，不臆造。

    model_cfg 来自 creative_tasks._vision_model_cfg(db)（真实配置，非 Mock）。
    返回 dict 直接对应 AssetAnalysisCreate 的字段（含 model_info 归因）。
    """
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    missing = [k for k in ("api_key", "base_url", "model") if not str(cfg.get(k) or "").strip()]
    if missing:
        return _unavailable("未配置可用的视觉模型：" + "/".join(missing))
    try:
        from llm_catalog import _resolve_protocol
        if _resolve_protocol(str(cfg.get("provider") or "")) != "openai":
            return _unavailable("图片解构仅支持 OpenAI 兼容协议的视觉模型")
    except Exception:
        return _unavailable("视觉协议识别失败")

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": _USER},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")}},
            ]},
        ],
        "temperature": 0,
        "max_tokens": 2048,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(str(cfg["base_url"]).rstrip("/") + "/chat/completions",
                             headers={"Authorization": "Bearer " + str(cfg["api_key"]),
                                      "Content-Type": "application/json"},
                             json=payload)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return _unavailable("视觉解构调用失败：" + type(e).__name__ + ": " + str(e)[:120])

    cleaned = re.sub(r"^```json\s*|\s*```$", "", str(raw or "").strip(), flags=re.I)
    try:
        data = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return _unavailable("视觉解构返回不可解析 JSON")
        try:
            data = json.loads(m.group(0))
        except Exception:
            return _unavailable("视觉解构返回不可解析 JSON")
    if not isinstance(data, dict):
        return _unavailable("视觉解构结果不是 JSON 对象")

    result = _normalize(data)
    result["model_info"] = {
        "provider": str(cfg.get("provider") or ""), "model": str(cfg.get("model") or ""),
        "role": "vision", "fallback": False,
    }
    # 全空解构（模型几乎没给出任何有效维度）按不可用处理，不冒充已解构。
    if result["completeness"] <= 0:
        u = _unavailable("视觉解构结果无有效维度（模型可能未识别到广告素材内容）")
        u["model_info"] = result["model_info"]
        return u
    if result["completeness"] < 0.5:
        result["status"] = "low_confidence"
    return result
