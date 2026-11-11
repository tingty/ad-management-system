"""
版本通知：以「系统运行版本」为锚点，自动同步每次版本更新的总结内容（V4.43）。

单一完整归档仍是仓库根目录 `CHANGELOG.md`；本模块负责：
1. 解析每个版本段落，抽取「更新要点」等总结式内容，产出精简的展示结构；
2. 以 `version.APP_VERSION` 为权威版本，若 CHANGELOG 尚未写入该版本，
   **自动生成一条明确标注的兜底通知**，保证系统升级后通知不会停留在旧版本；
3. 缓存按文件内容签名失效，接口禁用浏览器缓存，前端重新进入页面即可看到新版本。

展示结构（前端只消费这些字段，不再下发影响范围 / 验证结果 / 完整发版记录 /
改造进度等与「版本更新内容」无关的信息）：

    {version, title, date, summary, points[], change_types[], modules[], auto_generated}

CHANGELOG 段落仍按完整结构撰写，便于归档与发版校验：

    ## V4.43 版本标题
    **发布日期**：YYYY-MM-DD
    **变更类型**：优化
    **涉及模块**：模块A、模块B
    **变更摘要**：一句话总结本次更新

    **更新要点**
    - 模块A：一句总结
    - 模块B：一句总结

    **本次优化与更改的功能 / 模块**
    - 【优化】模块A / 功能：具体改动（完整归档用，不下发到通知列表）

    **影响范围** ...   **验证** ...

历史版本没有「更新要点」时，自动从结构化改动里按模块聚合短句；
既不丢版本记录，也不展示所有功能细节与前因后果。
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import date, datetime

import version as _version

_CHANGELOG = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")
_DATAFILE = os.path.join(os.path.dirname(__file__), "release_notes_data.py")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 部署环境权威来源：随代码发布的版本通知数据。即使部署环境没有 CHANGELOG.md 或
# git，接口也能直接展示最新版本内容；开发期若 CHANGELOG 已含更新版本则优先实时解析。
try:
    from release_notes_data import NOTES as _EMBEDDED_NOTES
except Exception:  # pragma: no cover - 生成文件缺失时回退到 CHANGELOG / 自动兜底
    _EMBEDDED_NOTES = []

_VER_RE = re.compile(r"^##\s+(V\d+\.\d+(?:\.\d+)?)\s*(.*)$")
_DATE_RE = re.compile(r"发布日期\D*?(\d{4}-\d{2}-\d{2})")
_FIELD_RE = re.compile(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+?)\s*$")
_SECTION_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_CHANGE_RE = re.compile(r"^【([^】]+)】\s*(.+)$")
_SPLIT_RE = re.compile(r"[、,，/|｜;；]+")

CHANGE_TYPES = ("新增", "优化", "修复", "删除", "重构", "下线", "发布")
REQUIRED_FIELDS = ("发布日期", "变更类型", "涉及模块", "变更摘要")
REQUIRED_SECTIONS = ("本次优化与更改的功能 / 模块", "影响范围", "验证")
TODO_MARKERS = ("TODO", "待补充", "待填写", "占位", "<请", "XXX")

POINT_LIMIT = 6           # 每个版本最多展示的总结要点数
POINT_CHARS = 120         # 单条要点最大字数


def _phase_of(fields: dict) -> dict:
    """改造期次解析（完整归档字段，供发版期次校验使用，不在通知页展示）。"""
    from roadmap import parse_phase
    return parse_phase(fields.get("改造期次", ""))


def _split_list(value: str) -> list[str]:
    return [x.strip() for x in _SPLIT_RE.split(value or "") if x.strip()]


def _clean_line(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text or "")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def _short(text: str, limit: int = POINT_CHARS) -> str:
    t = _clean_line(text)
    return t[:limit] + ("…" if len(t) > limit else "")


def _parse_change(text: str) -> dict:
    m = _CHANGE_RE.match(text)
    if not m:
        return {"type": "变更", "module": "", "title": _clean_line(text), "detail": ""}
    kind, rest = m.group(1).strip(), _clean_line(m.group(2))
    head, _, detail = rest.partition("：")
    if not detail:
        head, _, detail = rest.partition(":")
    if not detail:
        head, detail = rest, ""
    module = ""
    if " / " in head:
        module, head = head.split(" / ", 1)
    return {"type": kind, "module": module.strip(), "title": head.strip(), "detail": detail.strip()}


def _parse_body(body: str) -> dict:
    lines = body.splitlines()
    fields: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    all_bullets: list[str] = []
    cur_section = ""

    for line in lines:
        fm = _FIELD_RE.match(line)
        if fm:
            fields.setdefault(fm.group(1).strip(), fm.group(2).strip())
            cur_section = fm.group(1).strip()
            sections.setdefault(cur_section, [])
            continue
        sm = _SECTION_RE.match(line)
        if sm:
            cur_section = sm.group(1).strip()
            sections.setdefault(cur_section, [])
            continue
        bm = _BULLET_RE.match(line)
        if bm:
            text = bm.group(1).strip()
            all_bullets.append(text)
            sections.setdefault(cur_section, []).append(text)

    def bullets_of(*names):
        out = []
        for key, vals in sections.items():
            if any(n in key for n in names):
                out.extend(vals)
        return out

    structured = [b for b in bullets_of("本次优化", "更改的功能") if _CHANGE_RE.match(b)]
    changes = [_parse_change(b) for b in structured]
    impact = [_clean_line(x) for x in bullets_of("影响范围")]
    verification = [_clean_line(x) for x in bullets_of("验证", "验收证据")]
    if not changes:
        changes = [{"type": "变更", "module": "", "title": _clean_line(x), "detail": ""}
                   for x in all_bullets[:6]]

    # V4.43：优先使用人工整理的「更新要点」；没有则按模块聚合改动标题，丢弃细节说明。
    key_points = [_short(x) for x in bullets_of("更新要点") if _clean_line(x)]

    date_value = None
    dm = re.search(r"\d{4}-\d{2}-\d{2}", fields.get("发布日期", "")) or _DATE_RE.search(body)
    if dm:
        date_value = dm.group(0)

    modules = _split_list(fields.get("涉及模块", ""))
    change_types = [x for x in _split_list(fields.get("变更类型", "")) if x]
    summary = _clean_line(fields.get("变更摘要", ""))
    phase = _phase_of(fields)
    return {
        "date": date_value,
        "summary": summary,
        "modules": modules,
        "change_types": change_types,
        "changes": changes,
        "impact": impact,
        "verification": verification,
        "has_structured": bool(summary and modules and change_types and structured),
        "key_points": key_points,
        "phase_text": _clean_line(fields.get("改造期次", "")),
        "phase_index": phase["index"],
        "issue_ids": phase["issues"],
        "body": body,
        "has_placeholder": any(m in body for m in TODO_MARKERS),
    }


def _vkey(v: str):
    parts = [int(x) for x in re.findall(r"\d+", v)]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def parse_changelog(path: str | None = None) -> list[dict]:
    """纯解析 CHANGELOG，不做任何自动补齐（供发版校验使用，避免掩盖漏写）。"""
    try:
        with open(path or _CHANGELOG, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return []

    notes: list[dict] = []
    cur = None
    buf: list[str] = []

    def flush():
        if cur is None:
            return
        body = "\n".join(buf).strip()
        item = {"version": cur["version"], "title": cur["title"]}
        item.update(_parse_body(body))
        notes.append(item)

    for line in lines:
        m = _VER_RE.match(line)
        if m:
            flush()
            cur = {"version": m.group(1), "title": m.group(2).strip()}
            buf = []
            continue
        if cur is None:
            continue
        buf.append(line)
    flush()
    notes.sort(key=lambda n: _vkey(n["version"]), reverse=True)
    return notes


def latest_note() -> dict | None:
    """发版校验使用：CHANGELOG 里最新一条（不含自动兜底条目）。"""
    notes = parse_changelog()
    return notes[0] if notes else None


# ---------------------------------------------------------------------------
# 自动同步：系统版本升级但 CHANGELOG 漏写时，仍然生成对应版本的通知
# ---------------------------------------------------------------------------
_AUTO_MODULE_RULES = (
    ("frontend/src/pages/ReleaseNotes.tsx", "新版通知"),
    ("backend/release_notes.py", "新版通知"),
    ("backend/version.py", "系统版本"),
    ("frontend/src/pages/", "前端页面"),
    ("frontend/src/", "前端"),
    ("backend/", "后端"),
    ("scripts/", "发版流程"),
    ("docs/", "文档"),
)


def _auto_modules(files: list[str]) -> list[str]:
    mods: list[str] = []
    for f in files:
        for prefix, label in _AUTO_MODULE_RULES:
            if f.startswith(prefix):
                if label not in mods:
                    mods.append(label)
                break
    return mods[:6]


def _git(args: list[str], timeout: float = 1.2) -> str:
    try:
        return subprocess.run(["git", "-C", _ROOT] + args, capture_output=True,
                              text=True, check=False, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def auto_note(tag: str | None = None) -> dict:
    """按当前系统版本生成兜底通知；只陈述可核对的事实，不编造功能细节。"""
    tag = tag or _version.release_tag()
    subject = _git(["log", "-1", "--pretty=%s"])
    files = [x for x in _git(["show", "--pretty=format:", "--name-only", "HEAD"]).splitlines() if x]
    mods = _auto_modules(files)
    points = []
    if mods:
        points.append(f"本次改动涉及 {('、'.join(mods))} 等 {len(mods)} 个模块，共 {len(files)} 个文件。")
    if subject:
        points.append(f"最近一次提交：{_short(subject, 80)}")
    points.append("该条通知由系统按当前运行版本自动生成，请补写 CHANGELOG 的「更新要点」以完善说明。")
    return {
        "version": tag,
        "title": "版本更新",
        "date": date.today().isoformat(),
        "summary": f"系统已更新至 {tag}，版本通知按运行版本自动同步。",
        "modules": mods or ["系统版本"],
        "change_types": ["发布"],
        "changes": [],
        "impact": [],
        "verification": [],
        "has_structured": False,
        "key_points": points,
        "phase_text": "",
        "phase_index": None,
        "issue_ids": [],
        "body": "",
        "has_placeholder": False,
        "auto_generated": True,
    }


def _fallback_points(n: dict) -> list[str]:
    """历史版本无「更新要点」时，按模块聚合改动标题，不展示 detail / 前因后果。"""
    groups: dict[str, list[str]] = {}
    for c in n.get("changes") or []:
        title = (c.get("title") or "").strip()
        if not title:
            continue
        mod = (c.get("module") or "本次更新").strip()
        bucket = groups.setdefault(mod, [])
        if title not in bucket:
            bucket.append(title)
    points = []
    for mod, titles in groups.items():
        text = "、".join(titles[:3]) + ("等" if len(titles) > 3 else "")
        points.append(_short(f"{mod}：{text}"))
        if len(points) >= POINT_LIMIT:
            break
    if not points and n.get("summary"):
        points = [_short(n["summary"])]
    return points


def public_note(n: dict) -> dict:
    """精简为「版本号 + 总结式更新内容」，不下发完整记录与无关模块。"""
    points = n.get("key_points") or _fallback_points(n)
    return {
        "version": n.get("version") or "",
        "title": n.get("title") or "",
        "date": n.get("date"),
        "summary": _short(n.get("summary") or "", 180),
        "points": [p for p in points if p][:POINT_LIMIT],
        "change_types": n.get("change_types") or [],
        "modules": n.get("modules") or [],
        "auto_generated": bool(n.get("auto_generated")),
    }


# ---------------------------------------------------------------------------
# 缓存：按 CHANGELOG + 内置数据文件的签名失效；也提供显式失效入口
# ---------------------------------------------------------------------------
_sig = None
_cache = None


def _file_sig():
    sigs = []
    for path in (_CHANGELOG, _DATAFILE):
        try:
            st = os.stat(path)
            sigs.append((st.st_mtime_ns, st.st_size, st.st_ino))
        except Exception:
            sigs.append(None)
    return tuple(sigs)


def invalidate_cache() -> None:
    global _cache, _sig
    _cache, _sig = None, None


def _collect_notes():
    """合并内置发布数据（部署环境权威来源）与 CHANGELOG 实时解析（开发期优先）。"""
    tag = _version.release_tag()
    notes = {n["version"]: dict(n) for n in _EMBEDDED_NOTES}
    data_versions = list(notes.keys())
    data_latest = max(data_versions, key=_vkey) if data_versions else None
    try:
        parsed = parse_changelog()
    except Exception:
        parsed = []
    if parsed:
        cl_latest = parsed[0]["version"]
        # 仅当 CHANGELOG 的最新版本不落后于内置数据时，整体采用实时解析，
        # 避免部署环境里陈旧的 CHANGELOG 覆盖掉已随代码发布的新版本。
        if data_latest is None or _vkey(cl_latest) >= _vkey(data_latest):
            notes = {n["version"]: public_note(n) for n in parsed}
    merged = sorted(notes.values(), key=lambda n: _vkey(n["version"]), reverse=True)
    return merged, tag


def get_release_notes() -> dict:
    """返回「最新在前」的版本通知；保证包含当前系统版本对应的通知。

    权威来源为随代码发布的 `release_notes_data.py`（即使部署环境没有
    CHANGELOG.md 或 git 也能展示最新内容）；开发期若 CHANGELOG 已包含更新的
    版本段落，则优先使用其实时解析结果。当前系统版本在任一来源缺失时，
    仍由 `auto_note()` 生成一条明确标注「自动同步」的兜底通知。
    """
    global _cache, _sig
    sig = _file_sig()
    if _cache is not None and sig == _sig:
        return _cache

    merged, tag = _collect_notes()
    auto_generated = not any(n["version"] == tag for n in merged)
    if auto_generated:
        fallback = public_note(auto_note(tag))
        merged = [fallback] + merged
        merged.sort(key=lambda n: _vkey(n["version"]), reverse=True)

    notes = merged
    _cache = {
        "latest": notes[0]["version"] if notes else None,
        "app_version": tag,
        "version": _version.APP_VERSION,
        "notes": notes,
        "current": notes[0] if notes else None,
        "total": len(notes),
        "auto_generated": auto_generated,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
    }
    _sig = sig
    return _cache


if __name__ == "__main__":
    import json
    data = get_release_notes()
    print(json.dumps({k: v for k, v in data.items() if k != "notes"},
                     ensure_ascii=False, indent=2))
    for n in data["notes"][:3]:
        print(json.dumps(n, ensure_ascii=False, indent=2))
