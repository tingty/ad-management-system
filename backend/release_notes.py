"""
版本发布公告：单一数据源 = 仓库根目录的 CHANGELOG.md。

V4.37 起，每个版本都按统一结构发布，用户在「新版通知」里能按「涉及模块 / 变更类型」
筛选，并直接看到本次优化与更改的功能、影响范围与验证结果：

    ## V4.38 版本标题
    **发布日期**：YYYY-MM-DD
    **变更类型**：新增 / 优化 / 修复 / 删除
    **涉及模块**：模块A、模块B
    **变更摘要**：一句话说明本版做了什么

    **本次优化与更改的功能 / 模块**
    - 【优化】模块A / 功能名：具体改动说明
    - 【删除】模块B：具体改动说明

    **影响范围**
    - 前端 / 后端 / 数据 / 兼容性说明

    **验证**
    - 具体的验证项与结果

历史版本（V1.1–V4.36）仍保留原样：解析不到结构化字段时自动降级为
「摘要要点 + 完整发版记录」，不会丢失任何内容。

解析规则：
- 以 `## V<数字>.<数字>(.<数字>)?` 开头的行作为一条版本的起始。
- 起始行之后直到下一条 `## ` 之前的内容为该版本详情正文（保留原始 Markdown）。
- `**字段**：值` 提取结构化字段；`**章节**` 下的 `- ` 列表按章节归类。
- 返回结果按版本号降序（最新在前），带 CHANGELOG.md mtime 缓存。
"""
import os
import re

_CHANGELOG = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")

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

_mtime = -1.0
_cache = None  # type: ignore


def _split_list(value: str) -> list[str]:
    return [x.strip() for x in _SPLIT_RE.split(value or "") if x.strip()]


def _clean_line(text: str) -> str:
    """去掉行内 Markdown 标记，用于卡片中的紧凑展示。"""
    text = re.sub(r"`([^`]+)`", r"\1", text or "")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def _parse_change(text: str) -> dict:
    """把 `【优化】模块 / 功能：说明` 拆成结构化条目。"""
    m = _CHANGE_RE.match(text)
    if not m:
        return {"type": "变更", "module": "", "title": _clean_line(text), "detail": ""}
    kind, rest = m.group(1).strip(), _clean_line(m.group(2))
    # 「模块 / 功能：说明」或「模块：说明」
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
        # 历史版本降级：从正文里取前几条要点，保证卡片不至于空白
        changes = [{"type": "变更", "module": "", "title": _clean_line(x), "detail": ""}
                   for x in all_bullets[:6]]

    date = None
    dm = re.search(r"\d{4}-\d{2}-\d{2}", fields.get("发布日期", "")) or _DATE_RE.search(body)
    if dm:
        date = dm.group(0)

    modules = _split_list(fields.get("涉及模块", ""))
    change_types = [x for x in _split_list(fields.get("变更类型", "")) if x]
    summary = _clean_line(fields.get("变更摘要", ""))
    return {
        "date": date,
        "summary": summary,
        "modules": modules,
        "change_types": change_types,
        "changes": changes,
        "impact": impact,
        "verification": verification,
        "has_structured": bool(summary and modules and change_types and structured),
    }


def _parse(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return [], None

    notes = []
    cur = None
    buf = []

    def flush():
        if cur is not None:
            body = "\n".join(buf).strip()
            item = {"version": cur["version"], "title": cur["title"], "body": body}
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

    def _vkey(v: str):
        parts = [int(x) for x in re.findall(r"\d+", v)]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    notes.sort(key=lambda n: _vkey(n["version"]), reverse=True)
    return notes, (notes[0]["version"] if notes else None)


def _aggregate(notes: list) -> dict:
    modules, types = [], []
    for n in notes:
        for m in n["modules"]:
            if m not in modules:
                modules.append(m)
        for t in n["change_types"]:
            if t not in types:
                types.append(t)
    types.sort(key=lambda t: (CHANGE_TYPES.index(t) if t in CHANGE_TYPES else 99, t))
    return {
        "modules": modules,
        "change_types": types,
        "total": len(notes),
        "structured_count": sum(1 for n in notes if n["has_structured"]),
    }


def get_release_notes() -> dict:
    """返回 {latest, notes, modules, change_types, total, structured_count}，带 mtime 缓存。"""
    global _mtime, _cache
    try:
        st = os.stat(_CHANGELOG)
    except Exception:
        return {"latest": None, "notes": [], "modules": [], "change_types": [],
                "total": 0, "structured_count": 0}
    if _cache is None or st.st_mtime != _mtime:
        notes, latest = _parse(_CHANGELOG)
        _cache = {"latest": latest, "notes": notes, **_aggregate(notes)}
        _mtime = st.st_mtime
    return _cache


def latest_note() -> dict | None:
    """供发版前校验脚本使用：返回最新一条版本记录。"""
    return (get_release_notes()["notes"] or [None])[0]


if __name__ == "__main__":
    import json
    data = get_release_notes()
    print(json.dumps({k: v for k, v in data.items() if k != "notes"},
                     ensure_ascii=False, indent=2))
    print(json.dumps(data["notes"][0], ensure_ascii=False, indent=2)[:2200])
