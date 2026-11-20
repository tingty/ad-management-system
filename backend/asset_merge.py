"""V4.119 素材创意模板库 · 分类归并 + golden 沉淀（纯函数层）。

承接 V4.118 的 asset-deconstruct/1.0 解构结果，按 Q4 冻结口径把素材归成候选组，
再由**人工确认**沉淀为一条模板（唯一表达）：

1. 归并键：主分类相同 + 推广目的相同 + 钩子类型相同 + 信息结构相似度 ≥ 阈值。
2. 唯一表达：只在「分析成功 + 完整度 ≥ 0.5 + 分类已归一」的素材中选 golden，
   完整度最高者胜；并列按最近导入打破（仅 tie-break），再按置信度 / id 稳定排序。
3. 人工始终可覆盖：确认归并时可选 golden、可修正分类；soft merge 只打标记，不删原件。
4. 相似度只基于解构出的信息结构（标题角色 / 卖点 / CTA / 证据形式），不调用模型、
   不编造效果数据；无结构可比的素材独立成组，不强行并入。

本模块不碰数据库、不依赖 FastAPI，方便专项测试直接验证判定口径。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from asset_deconstruct import (
    FRAMEWORK_VERSION as DECONSTRUCT_VERSION,
    HOOK_TYPES, PRIMARY_CATEGORIES, PURPOSES,
)
from asset_video_deconstruct import FRAMEWORK_VERSION as VIDEO_DECONSTRUCT_VERSION

# V4.121：图片 / 视频两套解构框架共用同一套分类字典、归并键与 golden 口径。
SUPPORTED_FRAMEWORKS = frozenset({DECONSTRUCT_VERSION, VIDEO_DECONSTRUCT_VERSION})

MERGE_FRAMEWORK_VERSION = "asset-merge/1.0"
CATEGORY_TAXONOMY_VERSION = "asset-category/1.0"
#: 信息结构 Jaccard 相似度阈值（Q4 归并键）。低于此值不自动并入同组。
SIMILARITY_THRESHOLD = 0.45
#: 低于此完整度的解构不进候选（Q6：完整度低 / 失败 / 不可用不进候选）。
MIN_COMPLETENESS = 0.5


def taxonomy() -> dict:
    """分类字典与阈值的单一来源，供前端下拉与候选规则说明读取。"""
    return {
        "primary_categories": list(PRIMARY_CATEGORIES),
        "purposes": list(PURPOSES),
        "hooks": list(HOOK_TYPES),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "min_completeness": MIN_COMPLETENESS,
        "deconstruct_framework": DECONSTRUCT_VERSION,
        "video_deconstruct_framework": VIDEO_DECONSTRUCT_VERSION,
        "supported_deconstruct_frameworks": sorted(SUPPORTED_FRAMEWORKS),
        "merge_framework": MERGE_FRAMEWORK_VERSION,
        "taxonomy_version": CATEGORY_TAXONOMY_VERSION,
    }


def _value(cell) -> object:
    return cell.get("value") if isinstance(cell, dict) else None


def _cell(dims: dict, section: str, key: str) -> dict:
    if not isinstance(dims, dict):
        return {}
    part = dims.get(section)
    cell = part.get(key) if isinstance(part, dict) else None
    return cell if isinstance(cell, dict) else {}


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    return str(value or "")


def _tokens(value) -> set[str]:
    """中文按相邻 2 字切 token，英文 / 数字按词；用于信息结构的粗粒度相似度。"""
    text = _text(value).lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    cn = re.sub(r"[^一-龥]", "", text)
    tokens.update(cn[i:i + 2] for i in range(len(cn) - 1))
    if not tokens and cn:
        tokens.add(cn)
    return tokens


def info_signature(dims: dict) -> set[str]:
    """信息结构签名：标题角色 / 卖点 / CTA / 证据形式（四类信息维度）。"""
    sig: set[str] = set()
    for key in ("headline_role", "benefits", "cta", "evidence_kind"):
        sig |= _tokens(_value(_cell(dims, "info", key)))
    return sig


def information_similarity(a: dict, b: dict) -> float:
    """Jaccard 相似度；任一侧无可比结构返回 0，绝不臆造相似。"""
    sa, sb = info_signature(a), info_signature(b)
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 4)


def first_valid(values, allowed: Iterable[str]) -> str:
    for v in values or []:
        s = str(v or "").strip()
        if s in allowed:
            return s
    return ""


def effective_category(analysis: dict) -> tuple[str, str, str, str]:
    """取生效分类：人工确认优先，否则用 AI 解构建议。

    返回 (primary, purpose, hook, source)；purpose / hook 取字典内首个合法值作为归并键。
    """
    cat = analysis.get("category_json") if isinstance(analysis, dict) else {}
    cat = cat if isinstance(cat, dict) else {}
    confirmed = cat.get("confirmed") if isinstance(cat.get("confirmed"), dict) else {}
    src = cat.get("primary") or ""
    purposes = cat.get("purposes") or []
    hooks = cat.get("hooks") or []
    source = "ai"
    if confirmed.get("primary"):
        src = confirmed.get("primary")
        purposes = confirmed.get("purposes") or purposes
        hooks = confirmed.get("hooks") or hooks
        source = "manual"
    primary = str(src or "").strip()
    return (primary,
            first_valid(purposes, PURPOSES),
            first_valid(hooks, HOOK_TYPES),
            source)


def eligibility(analysis: dict) -> dict:
    """判断一条解构能否进归并候选，并给出可展示的排除原因。"""
    analysis = analysis if isinstance(analysis, dict) else {}
    primary, purpose, hook, source = effective_category(analysis)
    result = {"eligible": False, "reason": "", "primary": primary,
              "purpose": purpose, "hook": hook, "category_source": source,
              "completeness": float(analysis.get("completeness") or 0)}
    status = str(analysis.get("status") or "")
    if status != "analyzed":
        result["reason"] = f"解构状态为 {status or '未知'}，仅已解构素材可参与归并"
        return result
    fw = str(analysis.get("framework_version") or DECONSTRUCT_VERSION)
    if fw not in SUPPORTED_FRAMEWORKS:
        result["reason"] = f"解构框架版本 {fw} 与当前归并规则不匹配"
        return result
    if result["completeness"] < MIN_COMPLETENESS:
        result["reason"] = f"框架完整度 {result['completeness']:.0%} 低于 {MIN_COMPLETENESS:.0%}，不进候选"
        return result
    if primary not in PRIMARY_CATEGORIES:
        result["reason"] = "主分类未归一到 12 类字典，请先人工确认分类"
        return result
    if not purpose:
        result["reason"] = "缺少推广目的，请先人工确认分类"
        return result
    if not hook:
        result["reason"] = "缺少钩子类型，请先人工确认分类"
        return result
    result["eligible"] = True
    return result


def _timestamp(value) -> float:
    """把 ISO 字符串 / naive datetime 统一成 UTC 时间戳；无法解析视为最早。"""
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def choose_golden(members: list[dict]) -> Optional[dict]:
    """Q6 唯一表达：完整度优先；并列时最近导入，再依次置信度 / id 稳定打破。"""
    eligible = [m for m in members if m.get("eligible", True)]
    if not eligible:
        return None
    return sorted(eligible, key=lambda m: (
        -float(m.get("completeness") or 0),
        -_timestamp(m.get("created_at")),
        -float(m.get("confidence") or 0),
        int(m.get("asset_id") or 0),
    ))[0]


def build_skeleton(analysis: dict) -> dict:
    """从 golden 解构生成只含图片骨架的模板（Q9：文案不受模板影响）。"""
    dims = analysis.get("dims_json") if isinstance(analysis, dict) else {}
    skeleton = {
        "composition": _value(_cell(dims, "layout", "composition")),
        "focal_path": _value(_cell(dims, "layout", "focal_path")),
        "subject_position": _value(_cell(dims, "layout", "subject_position")),
        "negative_space": _value(_cell(dims, "layout", "negative_space")),
        "palette": _value(_cell(dims, "visual", "palette")),
        "lighting": _value(_cell(dims, "visual", "lighting")),
        "texture": _value(_cell(dims, "visual", "texture")),
        "headline_role": _value(_cell(dims, "info", "headline_role")),
        "benefits": _value(_cell(dims, "info", "benefits")),
        "cta": _value(_cell(dims, "info", "cta")),
        "evidence_kind": _value(_cell(dims, "info", "evidence_kind")),
        "hook_type": _value(_cell(dims, "effect", "hook_type")),
        "emotion": _value(_cell(dims, "effect", "emotion")),
        "intent": _value(_cell(dims, "effect", "intent")),
        # V4.121：golden 可能来自视频解构，溯源记录实际框架版本（仍是统一 12 类口径）。
        "source_framework": str(analysis.get("framework_version") or DECONSTRUCT_VERSION),
        "golden_analysis_id": analysis.get("id"),
    }
    return {k: v for k, v in skeleton.items() if v not in (None, "", [], {})}


def build_variables() -> dict:
    """图片骨架的变量字典：只约定占位，不写入任何具体产品事实或数字。"""
    return {
        "{{产品/品牌}}": "由当次创作的产品事实填入，不沿用 golden 素材的具体品牌",
        "{{核心利益点}}": "由当次文案结果的卖点替换",
        "{{CTA}}": "由当次投放目标产生的行动号召替换",
        "{{证据}}": "由当次证据包提供，无证据时留空，不编造数字",
    }


def template_name(primary: str, purpose: str, hook: str) -> str:
    return f"{primary} · {purpose} · {hook}钩子"


def _cluster(members: list[dict]) -> list[list[dict]]:
    """同键内按信息结构相似度做并查集聚类；无结构可比者独立成组。"""
    parent = list(range(len(members)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if information_similarity(members[i]["analysis"].get("dims_json") or {},
                                      members[j]["analysis"].get("dims_json") or {}) >= SIMILARITY_THRESHOLD:
                a, b = find(i), find(j)
                if a != b:
                    parent[b] = a
    buckets: dict[int, list[dict]] = {}
    for i, m in enumerate(members):
        buckets.setdefault(find(i), []).append(m)
    return list(buckets.values())


def build_candidates(items: list[dict]) -> dict:
    """构造归并候选视图。

    items: [{"asset": {...}, "analysis": {...}, "merged_template_id": int|None}, ...]
    返回 {"groups": [...], "excluded": [...], "rules": {...}}。所有输入由调用方按 owner 过滤。
    """
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    excluded: list[dict] = []
    for item in items:
        asset = item.get("asset") or {}
        analysis = item.get("analysis") or {}
        e = eligibility(analysis)
        row = {
            "asset_id": asset.get("id"), "title": asset.get("title") or "未命名素材",
            "completeness": e["completeness"], "reason": e["reason"],
            "merged_template_id": item.get("merged_template_id"),
            # V4.121：图片 / 视频共用归并键，候选视图需标出素材来源类型。
            "media_kind": asset.get("media_kind") or "image",
        }
        if not e["eligible"]:
            excluded.append(row)
            continue
        key = (e["primary"], e["purpose"], e["hook"])
        buckets.setdefault(key, []).append({
            "asset_id": asset.get("id"), "title": row["title"],
            "analysis_id": analysis.get("id"), "analysis": analysis,
            "completeness": e["completeness"], "confidence": float(analysis.get("confidence") or 0),
            "created_at": asset.get("created_at") or analysis.get("created_at"),
            "category_source": e["category_source"], "eligible": True,
            "merged_template_id": item.get("merged_template_id"),
            "media_kind": asset.get("media_kind") or "image",
            "framework_version": analysis.get("framework_version") or DECONSTRUCT_VERSION,
        })

    groups: list[dict] = []
    for (primary, purpose, hook), members in buckets.items():
        for cluster in _cluster(members):
            sims = [information_similarity(a["analysis"].get("dims_json") or {},
                                           b["analysis"].get("dims_json") or {})
                    for i, a in enumerate(cluster) for b in cluster[i + 1:]]
            golden = choose_golden(cluster)
            groups.append({
                "key": f"{primary}|{purpose}|{hook}",
                "primary": primary, "purpose": purpose, "hook": hook,
                "members": [{k: v for k, v in m.items() if k != "analysis"} for m in cluster],
                "size": len(cluster),
                "similarity": round(sum(sims) / len(sims), 4) if sims else 0.0,
                "golden_asset_id": golden["asset_id"] if golden else None,
                "golden_reason": ("框架完整度最高" if golden and len(cluster) > 1 else "唯一候选"),
                "suggested_name": template_name(primary, purpose, hook),
                "category_source": "manual" if any(m["category_source"] == "manual" for m in cluster) else "ai",
            })
    groups.sort(key=lambda g: (-g["size"], -max(m["completeness"] for m in g["members"]),
                               g["primary"], g["purpose"], g["hook"]))
    return {
        "groups": groups,
        "excluded": excluded,
        "rules": taxonomy(),
    }


def confirm_category(analysis: dict, primary: str, purposes: list[str], hooks: list[str],
                     by: str, at: str) -> dict:
    """人工确认 / 修正分类：保留 AI 原始建议，生效值改为人工值，返回新的 category_json。"""
    cat = dict(analysis.get("category_json") or {})
    if "ai_suggestion" not in cat:
        cat["ai_suggestion"] = {
            "primary": cat.get("primary") or "", "purposes": list(cat.get("purposes") or []),
            "hooks": list(cat.get("hooks") or []),
        }
    cat["primary"] = primary
    cat["purposes"] = list(purposes)
    cat["hooks"] = list(hooks)
    cat["confirmed"] = {"primary": primary, "purposes": list(purposes), "hooks": list(hooks),
                        "by": by, "at": at}
    cat["taxonomy_version"] = CATEGORY_TAXONOMY_VERSION
    return cat
