"""AI 改造分期路线图（V4.39 起）。

数据分两层，避免「文档写完成、系统没发布」的偏差：

1. 本文件只保存**静态规划**：4 期 × 3 个问题、目标、验收用例、适用行业说明。
2. **完成状态由 CHANGELOG 驱动**：每个改造版本按规范写 `**改造期次**：第 N 期（F01 / F02 / F10）`，
   `release_notes.py` 解析出版本号与问题编号后，交给 `resolve_roadmap()` 把对应问题标记为
   `done` 并绑定实际发布版本。没发版的期次一律显示「规划中」。

这样「每做完一期 → 总结成版本更新文案 → 同步 git → 新版通知自动显示进度」形成闭环，
不需要在两个地方手工维护状态。

行业适用：说明书样本为海外电商购买与订阅转化，但 12 个问题都位于通用链路。
每期都标注 `industry_scope`，说明主干能力与行业局部配置的边界。
"""
from __future__ import annotations

import re

BASELINE_COMMIT = "0ddbf3f159eeef4f15f2ff893f29d7ba9bd5106b"
SOURCE_DOC = "广告素材平台问题诊断与AI改造实施说明书.docx v1.0（2026-11-10）"
TRACKER_DOC = "docs/REMEDIATION_TRACKER.md"

PHASES: list[dict] = [
    {
        "index": 1,
        "version": "V4.39",
        "title": "输入与输出可信度",
        "goal": "先修复确定性缺陷：完整文案、正确品牌与最终地址、可追踪的模型调用归因。",
        "industry_scope": "建立 industry_profiles.py 通用主干；语义压缩保护词、品牌来源规则、模型归因规则对全行业一致，各 profile 只提供局部词表与价值维度。",
        "issues": [
            {"id": "F01", "title": "截断文案被判定合格", "cases": ["T01", "T02"]},
            {"id": "F02", "title": "域名被误当品牌和最终站点", "cases": ["T03", "T04"]},
            {"id": "F10", "title": "实际模型和来源标记不可靠", "cases": ["T13", "T14"]},
        ],
    },
    {
        "index": 2,
        "version": "V4.40",
        "title": "任务与规则可靠性",
        "goal": "版位任务矩阵完整覆盖、媒体规则版本化、并发生成与临时文件隔离。",
        "industry_scope": "版位矩阵与媒体规则读取 profile 的偏好，不写死电商版位；未知平台显式拒绝。",
        "issues": [
            {"id": "F07", "title": "任务截断和文案轮换破坏覆盖", "cases": ["T09"]},
            {"id": "F08", "title": "媒体与接口规则不足以保证交付", "cases": ["T10"]},
            {"id": "F11", "title": "批次失败和临时文件缺少隔离", "cases": ["T15"]},
        ],
    },
    {
        "index": 3,
        "version": "V4.41",
        "title": "创意与视觉表达",
        "goal": "概念进入背景生成、预设完整生效、多布局与品牌色板、真实商品 / 界面优先。",
        "industry_scope": "profile 的 visual_subject / 配色 / 布局偏好驱动 VisualBrief；其它行业只改配置即可输出对应主视觉。",
        "issues": [
            {"id": "F03", "title": "文案概念没有进入背景生成", "cases": ["T05"]},
            {"id": "F04", "title": "预设编辑结果没有完整参与生成", "cases": ["T06"]},
            {"id": "F05", "title": "固定排版和固定色板削弱表达", "cases": ["T07"]},
        ],
    },
    {
        "index": 4,
        "version": "V4.42",
        "title": "事实与工程化",
        "goal": "比例与主体保护、事实 / 证据链、服务端持久任务与自动归档。",
        "industry_scope": "profile 的 evidence_types 决定需核验的事实类型；服务端任务、幂等与归档全行业通用。",
        "issues": [
            {"id": "F06", "title": "请求比例与居中裁切不保护主体", "cases": ["T08"]},
            {"id": "F09", "title": "摘要丢失事实并允许空证据继续分析", "cases": ["T11", "T12"]},
            {"id": "F12", "title": "浏览器长请求无法可靠恢复和归档", "cases": ["T16"]},
        ],
    },
]

_ISSUE_RE = re.compile(r"\bF\d{2}\b")


def planned_issue_ids() -> set[str]:
    return {i["id"] for p in PHASES for i in p["issues"]}


def parse_phase(text: str) -> dict:
    """解析 `第 1 期（F01 / F02 / F10）` → {index, issues}。"""
    out: dict = {"index": None, "issues": []}
    if not text:
        return out
    m = re.search(r"第\s*(\d+)\s*期", text)
    if m:
        out["index"] = int(m.group(1))
    out["issues"] = list(dict.fromkeys(_ISSUE_RE.findall(text)))
    return out


def resolve_roadmap(notes: list[dict]) -> dict:
    """根据结构化版本通知，把每期 / 每个问题标记为已完成并绑定实际版本。

    notes: release_notes.get_release_notes()["notes"]（已按版本倒序）。
    只接受「已发布版本」作为完成证据；同一问题出现在多个版本时取最新版本。
    """
    published: dict[str, dict] = {}
    for n in notes:
        pid = n.get("phase_index")
        for iid in n.get("issue_ids") or []:
            if iid not in published:
                published[iid] = {"version": n["version"], "date": n.get("date"),
                                  "phase_index": pid, "title": n.get("title", "")}

    phases = []
    done_count = 0
    for p in PHASES:
        items = []
        for i in p["issues"]:
            pub = published.get(i["id"])
            if pub:
                done_count += 1
            items.append({**i, "status": "done" if pub else "planned",
                          "released_version": pub["version"] if pub else None,
                          "released_date": pub["date"] if pub else None})
        phase_done = sum(1 for x in items if x["status"] == "done")
        phases.append({
            **p,
            "issues": items,
            "done_count": phase_done,
            "status": "done" if phase_done == len(items) else ("in_progress" if phase_done else "planned"),
            "released_version": next((x["released_version"] for x in items if x["released_version"]), None),
        })
    total = sum(len(p["issues"]) for p in PHASES)
    return {
        "baseline_commit": BASELINE_COMMIT,
        "source_doc": SOURCE_DOC,
        "tracker_doc": TRACKER_DOC,
        "phases": phases,
        "total": total,
        "done_count": done_count,
        "industry_note": (
            "改造主干适用于全部行业与品类；电商购买 / 订阅转化只是两个行业配置。"
            "价值维度、必须保留的语义、证据类型、视觉主体与版位偏好按 industry_profiles 局部调整。"
        ),
    }
