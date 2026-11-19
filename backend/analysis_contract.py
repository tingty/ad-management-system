"""分析结果的类型契约（V4.112）。

真实大模型输出的类型并不稳定：同一个字段这次给字符串、下次给对象、再下次给数组；
而 `LandingAnalysis` 对字段类型有严格约束。此前 `_build_cw_result` 把模型输出原样写进
`analysis`，文案 / 出图 / 出片接口在 Pydantic 校验阶段就会 422（例如 industry 给了
`{"main": "..."}`、advantages 给了 `"a, b, c"`、channels 给了 `["Meta"]`），而前端又把
异常吞成「未返回结果」，用户只能看到「文案未生成成功」。

这里做一次**只改类型、不改语义**的收敛：字符串字段统一成文本，字符串数组统一成
`list[str]`，channels 统一成 `[{platform, reason}]`。原文不丢、不截断、不编造。
"""

from __future__ import annotations

from typing import Any

# 必须是纯文本的字段（模型偶尔会把它们写成对象 / 数组）
TEXT_FIELDS = (
    "url", "logo", "language", "industry", "type", "audience", "source",
    "brand", "brand_status", "brand_reason", "logo_source", "logo_reason",
    "input_url", "final_url", "fetch_quality",
    "industry_profile", "industry_profile_label",
    "evidence_note", "evidence_gate", "gate_status",
    "evidence_snapshot_id", "evidence_fetched_at", "evidence_review_status",
)

# 必须是字符串数组的字段
LIST_FIELDS = (
    "competitors", "advantages", "brand_candidates", "redirect_chain",
    "facts", "assumptions", "gaps", "evidence_ids", "blocked_reasons",
    "recommendedPlatforms",
)

# 文本对象里常见的「有意义的取值键」，按优先级尝试
_TEXT_KEYS = ("text", "value", "name", "main", "label", "title", "content",
              "summary", "description", "platform", "reason")


def as_text(value: Any) -> str:
    """把任意模型输出收敛成一个可读字符串（不丢原文，只做连接）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                text = as_text(value.get(key))
                if text:
                    return text
        parts = [as_text(v) for v in value.values()]
        return "；".join([p for p in parts if p])
    if isinstance(value, (list, tuple, set)):
        parts = [as_text(v) for v in value]
        return "；".join([p for p in parts if p])
    return str(value).strip()


def as_text_list(value: Any) -> list[str]:
    """把任意模型输出收敛成 `list[str]`。

    字符串按换行 / 分号 / 竖线切分；逗号只在每段都较短（≤40 字）时切分，
    避免把一句完整描述拆成碎片。原文既不丢弃也不改写。
    """
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        for sep in ("\n", "；", ";", "|"):
            if sep in s:
                return [x.strip() for x in s.split(sep) if x.strip()]
        if "," in s:
            parts = [x.strip() for x in s.split(",")]
            if all(len(x) <= 40 for x in parts) and len(parts) > 1:
                return [x for x in parts if x]
        return [s]
    if isinstance(value, dict):
        vals = [as_text(x) for x in value.values()]
        vals = [x for x in vals if x]
        # {"0": "a", "1": "b"} 这类按下标存的数组
        if len(vals) > 1:
            return vals
        text = as_text(value)
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                out.extend(as_text_list(item))
            else:
                text = as_text(item)
                if text:
                    out.append(text)
        return out
    text = as_text(value)
    return [text] if text else []


def as_channels(value: Any) -> list[dict]:
    """推广途径统一成 `[{platform, reason}]`（去重，保序）。"""
    items: list[Any]
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    elif value is None or value == "":
        items = []
    else:
        items = as_text_list(value)
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            platform = as_text(item.get("platform") or item.get("media")
                               or item.get("name") or item.get("channel"))
            reason = as_text(item.get("reason") or item.get("why")
                             or item.get("description"))
        else:
            platform, reason = as_text(item), ""
        if not platform or platform in seen:
            continue
        seen.add(platform)
        out.append({"platform": platform, "reason": reason})
    return out


def normalize_analysis(analysis: dict | None) -> dict:
    """把统一分析收敛成接口可接受的类型（幂等）。"""
    data = dict(analysis or {})
    for key in TEXT_FIELDS:
        if key in data:
            data[key] = as_text(data.get(key))
    for key in LIST_FIELDS:
        if key in data:
            data[key] = as_text_list(data.get(key))
    if "channels" in data:
        data["channels"] = as_channels(data.get("channels"))
    # 推广途径缺失时，用推荐平台补平台名（reason 留空，不编造理由）
    if not data.get("channels") and data.get("recommendedPlatforms"):
        data["channels"] = as_channels(data["recommendedPlatforms"])
    return data
