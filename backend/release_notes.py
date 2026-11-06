"""
版本发布公告：单一数据源 = 仓库根目录的 CHANGELOG.md。

每次发版只需在 CHANGELOG.md 追加一个 `## Vx.y 标题` 段落（可选 `**发布日期**：YYYY-MM-DD`），
本模块解析后通过 `/api/system/release-notes` 暴露给前端「新版通知」，无需额外维护一份数据。

解析规则：
- 以 `## V<数字>.<数字>(.<数字>)?` 开头的行作为一条版本的起始（版本号 + 标题）。
- 起始行之后直到下一条 `## ` 之前的内容为该版本的详情正文（保留原始 Markdown）。
- 正文中若出现 `发布日期：YYYY-MM-DD`（**发布日期** 或 发布日期:）则提取为 date 字段。
- 返回结果按「最新在前」排序。
"""
import os
import re

_CHANGELOG = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")

_VER_RE = re.compile(r"^##\s+(V\d+\.\d+(?:\.\d+)?)\s*(.*)$")
# 兼容「发布日期：」「发布日期:」「发布日期-」等多种分隔符
_DATE_RE = re.compile(r"发布日期\D*?(\d{4}-\d{2}-\d{2})")

_mtime = -1.0
_cache = None  # type: ignore


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
            cur["body"] = "\n".join(buf).strip()
            notes.append(cur)

    for line in lines:
        m = _VER_RE.match(line)
        if m:
            flush()
            cur = {"version": m.group(1), "title": m.group(2).strip(), "date": None, "body": ""}
            buf = []
            continue
        if cur is None:
            continue
        dm = _DATE_RE.search(line)
        if dm and cur["date"] is None:
            cur["date"] = dm.group(1)
        buf.append(line)

    flush()

    def _vkey(v: str):
        # V4.29 -> (4,29,0)；V4.10 -> (4,10,0)，保证按版本号而非文件顺序排序
        parts = [int(x) for x in re.findall(r"\d+", v)]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

    notes.sort(key=lambda n: _vkey(n["version"]), reverse=True)  # 最新在前
    latest = notes[0]["version"] if notes else None
    return notes, latest


def get_release_notes() -> dict:
    """返回 {latest, notes:[{version,title,date,body}]}，带 mtime 缓存。"""
    global _mtime, _cache
    try:
        st = os.stat(_CHANGELOG)
    except Exception:
        return {"latest": None, "notes": []}
    if _cache is None or st.st_mtime != _mtime:
        notes, latest = _parse(_CHANGELOG)
        _cache = {"latest": latest, "notes": notes}
        _mtime = st.st_mtime
    return _cache


if __name__ == "__main__":
    import json
    print(json.dumps(get_release_notes(), ensure_ascii=False, indent=2)[:1500])
