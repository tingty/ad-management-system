"""V4.105 / 方案C：结构化创作意图（creative_intent），文案 / 图片 / 视频三类素材共用。

问题（V4.100 诊断 C01）：V4.101 的 brief 已进入文案 / 路线 / 图片 / 视频规划，但
「分析」阶段不接收任何用户意图——补充框里的文字只作用于图片视觉，路线卡只能勾选
不能修改，于是用户想说的「面向谁、重点讲什么、不要什么」到不了概念层。

本模块只做三件事，且全部是纯函数（不调用模型、可复现、零成本）：

1. `parse_text()`：把一段自然语言按规则拆成 intent_patch（受众 / 目标 / 核心价值 /
   场景 / 风格 / 禁止项）。不调用大模型，避免为了「听懂一句话」再付一次费用，
   也让解析结果在测试里可断言。
2. `merge()` / `conflicts()`：把 patch 合并进已确认意图，返回字段级变更摘要与
   冲突提示（例如禁止项同时出现在风格或核心价值里）。
3. `classify_change()`：判断这次改动属于「视觉项」还是「概念项」——只改风格 / 场景
   只需重编译视觉；改受众 / 目标 / 核心价值 / 禁止项必须重策划概念与文案。

禁止项是硬约束：与其它要求冲突时以禁止项优先，绝不因为「画面更好看」而放行。
"""
from __future__ import annotations

import re
from typing import Iterable

#: 结构化字段（顺序即为展示顺序）。
FIELDS = ("audience", "goal", "core_value", "scenario", "style", "avoid")

LABELS = {
    "audience": "目标受众",
    "goal": "推广目标",
    "core_value": "核心价值",
    "scenario": "使用场景",
    "style": "视觉风格",
    "avoid": "禁止项",
}

#: 视觉项：改动只需重编译视觉，不必重策划概念。
VISUAL_FIELDS = ("style", "scenario")
#: 概念项：改动必须重策划概念与文案。
CONCEPT_FIELDS = ("audience", "goal", "core_value", "avoid")

MAX_ITEM_LEN = 60
MAX_ITEMS = 8

_SPLIT_RE = re.compile(r"[；;。\n\r]+|，|,(?=\s*[^\d])|\s{2,}")

# 规则按「更具体的语义」优先：先禁止项，再受众，再核心价值 / 场景 / 风格 / 目标。
_AVOID_RE = re.compile(
    r"^(?:不要|不做|不需要|不用|不必|避免|禁止|严禁|切勿|勿|别|不许|不得|不能|不想|无需)(?:再)?(.+)$")
_AUDIENCE_RE = re.compile(
    r"^(?:(?:面向|针对|适合|给|对)|(?:目标|主要)(?:人群|用户|受众|客户)(?:是|为|:|：)?)(.+)$")
_CORE_RE = re.compile(
    r"^(?:重点(?:是|在|说|讲|突出|强调)?|突出|强调|主打|核心(?:价值|卖点|信息)?(?:是|为|:|：)?"
    r"|关键(?:是|在)?|务必|一定要|让人看到|看清|讲清|说清)(.+)$")
_SCENARIO_RE = re.compile(r"^(?:场景|使用场景|应用场景|投放场景)(?:是|为|:|：)?(.+)$")
_SCENARIO_IN_RE = re.compile(r"^在(.{2,40}?)(?:的)?(?:时候|时|场景|过程中)")
_STYLE_RE = re.compile(r"^(?:风格|调性|视觉|画面|配色|色调|语气|口吻)(?:上|方面)?(?:是|为|:|：)?(.+)$")
_GOAL_RE = re.compile(r"^(?:目标|目的|推广目标|转化目标|营销目标)(?:是|为|:|：)?(.+)$")

#: 冲突判定的最小词长（太短的词做包含匹配误报率高）。
_MIN_CONFLICT_LEN = 2


def empty_intent(raw_text: str = "") -> dict:
    """空意图：列表字段给空数组，文本字段给空串。"""
    intent = {f: ([] if f in ("audience", "avoid") else "") for f in FIELDS}
    intent["raw_text"] = (raw_text or "").strip()
    return intent


def _clean_items(values: Iterable, limit: int = MAX_ITEMS) -> list:
    out, seen = [], set()
    for v in values or []:
        s = re.sub(r"\s+", " ", str(v or "")).strip(" ，,、;；。:：")
        if not s:
            continue
        s = s[:MAX_ITEM_LEN]
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def normalize(raw: dict | None) -> dict:
    """把任意来源（前端提交 / 历史草稿 / 已存分析）的意图归一成固定结构。"""
    raw = raw if isinstance(raw, dict) else {}
    intent = empty_intent(str(raw.get("raw_text") or ""))
    for f in FIELDS:
        val = raw.get(f)
        if f in ("audience", "avoid"):
            if isinstance(val, str):
                val = [x for x in re.split(r"[、,，;；/|]+", val)]
            intent[f] = _clean_items(val if isinstance(val, (list, tuple)) else [])
        else:
            if isinstance(val, (list, tuple)):
                val = "、".join(str(x) for x in val if str(x or "").strip())
            intent[f] = str(val or "").strip()[:MAX_ITEM_LEN * 2]
    return intent


def is_empty(intent: dict | None) -> bool:
    """没有任何结构化字段（raw_text 不参与，避免「解释不了的一句话」被当成有效意图）。"""
    it = normalize(intent)
    return not any(it[f] for f in FIELDS)


def _split(text: str) -> list:
    parts = [p.strip() for p in _SPLIT_RE.split(str(text or "")) if p and p.strip()]
    return parts


def parse_text(text: str, base: dict | None = None) -> dict:
    """把自然语言拆成 intent_patch（只返回识别到的字段）。

    返回：{"patch": {...}, "notes": [...], "unmatched": [...]}
    - 未识别的片段不丢：进入 notes 提示「已作为原文附加」，并在 prompt block 里保留，
      避免用户的约束因为「没匹配上正则」被静默忽略。
    """
    patch: dict = {}
    notes: list = []
    unmatched: list = []
    src = str(text or "").strip()
    if not src:
        return {"patch": patch, "notes": notes, "unmatched": unmatched}

    for seg in _split(src):
        seg = seg.strip(" ，,、")
        if not seg:
            continue
        body = None
        # ① 禁止项：最高优先级，先判
        m = _AVOID_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、")
            body = re.sub(r"^(?:出现|使用|生成|做成|变成|画|写|提|加|放|带|做|用)", "", body).strip()
            if body:
                patch.setdefault("avoid", []).append(body)
                continue
        # ② 受众
        m = _AUDIENCE_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、。")
            if body:
                patch.setdefault("audience", []).append(body)
                continue
        # ③ 场景（含「在…时」句式）
        m = _SCENARIO_RE.match(seg) or _SCENARIO_IN_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、。")
            if body:
                patch["scenario"] = (patch.get("scenario") or "") or body
                continue
        # ④ 风格
        m = _STYLE_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、。")
            if body:
                patch["style"] = (patch.get("style") or "") or body
                continue
        # ⑤ 目标
        m = _GOAL_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、。")
            if body:
                patch["goal"] = (patch.get("goal") or "") or body
                continue
        # ⑥ 核心价值（放最后：关键字最多，避免抢走受众 / 场景）
        m = _CORE_RE.match(seg)
        if m:
            body = m.group(1).strip(" ，,、。")
            if body:
                patch["core_value"] = (patch.get("core_value") or "") or body
                continue
        unmatched.append(seg)

    # 整段都没识别出字段：把整段当核心价值参考，并明确写进 notes（不静默丢弃）
    if not patch and src:
        patch["core_value"] = src[:MAX_ITEM_LEN * 2]
        notes.append("未识别出明确字段，整段原文已作为核心价值参考传入")
        unmatched = []
    elif unmatched:
        notes.append("以下片段未归类，已按原文附加保留：" + "；".join(unmatched[:4]))
    if base is not None:
        merged = merge(base, patch)
        notes.extend(f"补全：{c}" for c in merged["changes"])
    return {"patch": normalize_patch(patch), "notes": notes, "unmatched": unmatched}


def normalize_patch(patch: dict | None) -> dict:
    """只保留实际带值的字段（patch 语义：未提及 = 不改）。"""
    out: dict = {}
    p = patch if isinstance(patch, dict) else {}
    for f in FIELDS:
        v = p.get(f)
        if f in ("audience", "avoid"):
            items = _clean_items(v if isinstance(v, (list, tuple)) else ([v] if v else []))
            if items:
                out[f] = items
        else:
            s = str(v or "").strip()
            if s:
                out[f] = s
    return out


def merge(base: dict | None, patch: dict | None) -> dict:
    """把 patch 合并进 base，返回 {"intent": 新意图, "changes": [字段级变更摘要]}。"""
    cur = normalize(base)
    p = normalize_patch(patch)
    out = {f: (list(cur[f]) if isinstance(cur[f], list) else cur[f]) for f in FIELDS}
    out["raw_text"] = cur.get("raw_text") or ""
    changes: list = []
    for f, v in p.items():
        if isinstance(v, list):
            exist = {x.lower() for x in out.get(f) or []}
            added = [x for x in v if x.lower() not in exist]
            if added:
                out[f] = _clean_items((out.get(f) or []) + added)
                changes.append(f"{LABELS.get(f, f)} + {'、'.join(added)}")
        else:
            if str(out.get(f) or "").strip() != v:
                changes.append(f"{LABELS.get(f, f)} → {v}")
                out[f] = v
    return {"intent": out, "changes": changes}


def conflicts(intent: dict | None) -> list:
    """冲突提示：禁止项与其它字段的直接包含关系（禁止项优先）。"""
    it = normalize(intent)
    av = [a for a in it.get("avoid") or [] if len(a) >= _MIN_CONFLICT_LEN]
    if not av:
        return []
    out: list = []
    for f in ("style", "core_value", "scenario", "goal"):
        val = str(it.get(f) or "")
        if not val:
            continue
        for a in av:
            if a and a.lower() in val.lower():
                out.append(f"禁止项「{a}」与{LABELS[f]}「{val}」直接冲突，生成时以禁止项为准")
    for a in av:
        for b in it.get("audience") or []:
            if a and a.lower() in str(b).lower():
                out.append(f"禁止项「{a}」出现在目标受众「{b}」中，请确认受众描述")
    # 去重保序
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:6]


def classify_change(old: dict | None, new: dict | None) -> str:
    """判定改动类型：none / visual / concept。"""
    a, b = normalize(old), normalize(new)
    changed = [f for f in FIELDS if a.get(f) != b.get(f)]
    if not changed:
        return "none"
    if all(f in VISUAL_FIELDS for f in changed):
        return "visual"
    return "concept"


def summary(intent: dict | None) -> str:
    """一行摘要，供前端在路线区展示（不引入新的布局块）。"""
    it = normalize(intent)
    bits = []
    if it.get("audience"):
        bits.append("受众 " + "、".join(it["audience"][:2]))
    if it.get("core_value"):
        bits.append("重点 " + it["core_value"][:24])
    if it.get("style"):
        bits.append("风格 " + it["style"][:16])
    if it.get("avoid"):
        bits.append("不做 " + "、".join(it["avoid"][:3]))
    return "｜".join(bits)


def prompt_block(intent: dict | None) -> str:
    """生成可注入 analyze / routes / 文案 / 图片 / 视频提示词的意图块；空意图返回空串。"""
    if is_empty(intent):
        return ""
    it = normalize(intent)
    lines = ["【创作意图（用户确认，优先级高于通用默认）】"]
    for f in ("audience", "goal", "core_value", "scenario", "style"):
        vals = it.get(f)
        if isinstance(vals, list):
            vals = "、".join(vals)
        if vals:
            lines.append(f"- {LABELS[f]}：{vals}")
    if it.get("avoid"):
        lines.append("- 禁止项（硬约束）：不得出现 / 不得声称：" + "、".join(it["avoid"]))
    lines.append("要求：上述意图必须落到概念与表达上；禁止项与任何其它要求冲突时，以禁止项为准；"
                 "意图未提供的信息不得编造，也不得用通用卖点替代。")
    return "\n".join(lines)


def from_analysis(analysis: dict | None) -> dict:
    """从统一分析里取回意图：兼容 analysis.creative_intent 与 analysis.analysis.creative_intent。"""
    a = analysis if isinstance(analysis, dict) else {}
    for path in (a, a.get("analysis") if isinstance(a.get("analysis"), dict) else {}):
        if isinstance(path, dict) and isinstance(path.get("creative_intent"), dict):
            return normalize(path["creative_intent"])
    return empty_intent()
