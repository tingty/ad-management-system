"""V4.42 / F09：落地页事实证据链、分区采集与「空证据 / 过期优惠」阻断。

说明书 F09 的原始问题：抓取后只把正文前 4000 字符送进模型，长页面里 4001 字符之后
的价格 / 退货 / 订阅条款会丢失；抓取失败或空页面仍继续分析；卖点无法回溯到原文。

本模块提供可被确定性验证的纯函数：

- `split_sections()`：按标题 / 列表 / 段落把正文切成带字符区间的区块；
- `key_clauses()`：定位价格、退货、订阅、试用、运费、保证、优惠有效期等条款；
- `select_evidence_budget()`：**不再截前 4000 字符**，改为「首尾窗口 + 关键条款区块」
  的预算内采样，并如实返回 coverage（哪些字符区间真的进了提示词）；
- `build_evidence_index()`：每条区块生成可引用的 evidence_id / 原文 / 来源 / 位置 / 核验状态；
- `evidence_gate()`：空页、抓取失败、薄内容、过期优惠 → `needs_input` 阻断，不调用模型；
- `build_evidence_pack()`：整合以上结果，供 services.build_landing_prompt 使用。

事实边界：这里只做「原文证据」的采集与阻断，不做事实正确性判定；
`verified` 表示「有原文可引用」，不代表商业真实性，价格 / 效果仍须人工复核。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

MAX_SOURCE_CHARS = 200_000
DEFAULT_BUDGET = 16_000
HEAD_WINDOW = 4_000
TAIL_WINDOW = 4_000
SECTION_MIN_CHARS = 24

CLAUSE_PATTERNS: dict[str, str] = {
    "price": r"(?i)\b(price|cost|\$\s?\d|usd|€|£|¥|pricing|from\s+\d+[\.,]\d+)",
    "refund": r"(?i)\b(refund|return policy|money.?back|cancel(lation)? policy|returns?)\b",
    "subscription": r"(?i)\b(subscription|billed|renew(al|s|ed)?|recurring|per month|/mo|monthly|annual(ly)?|per year)\b",
    "trial": r"(?i)\b(free trial|trial period|\d+\s*day trial|try free|no credit card)\b",
    "shipping": r"(?i)\b(shipping|delivery|free ship|dispatch|lead time)\b",
    "guarantee": r"(?i)\b(guarantee|warranty|certified|compliant|GDPR|SOC ?2)\b",
    "offer_window": r"(?i)\b(valid (until|through|from)|ends?\s+(on|at)?|expires?|offer ends|promo code|deadline)\b",
}

_DATE_RE = re.compile(
    r"(?i)\b(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})\b|"
    r"\b(20\d{2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def split_sections(text: str, html: str = "") -> list[dict]:
    """把正文切为带 [start,end) 字符区间的区块。

    优先用 HTML 的 h1-h3 / section / li 分段并映射回纯文本；没有 HTML 时按空行 / 换行分段。
    无论哪种方式都保留原始字符位置，模型引用的 evidence_id 可以跳回原文。
    """
    src = (text or "")[:MAX_SOURCE_CHARS]
    if not src.strip():
        return []
    headings: list[tuple[int, str]] = []
    if html:
        for m in re.finditer(r"(?is)<h([1-3])[^>]*>(.*?)</h\1>", html):
            label = _clean(re.sub(r"<[^>]+>", " ", m.group(2)))
            if label:
                headings.append((m.start(), label))
    parts: list[tuple[int, int, str]] = []
    if src.count("\n") >= 2:
        pos = 0
        for line in src.splitlines(keepends=True):
            n = len(line)
            if line.strip():
                parts.append((pos, pos + n, line.strip()))
            pos += n
    else:
        # 单段长文：按句切，避免整页只有一个区块导致预算采样退化为前 4000 字符
        pos = 0
        for m in re.finditer(r"[^.!?。！？]+[.!?。！？]?\s*", src):
            seg = m.group(0)
            if seg.strip():
                parts.append((pos + m.start(), pos + m.end(), seg.strip()))
        pos = 0
    sections: list[dict] = []
    for i, (a, b, body) in enumerate(parts, 1):
        if len(body) < SECTION_MIN_CHARS and sections:
            prev = sections[-1]
            if b - prev["char_start"] <= 800:
                prev["char_end"] = b
                prev["text"] = (prev["text"] + " " + body).strip()
                prev["chars"] = len(prev["text"])
                continue
        heading = ""
        for hp, label in headings:
            if hp <= a:
                heading = label
            else:
                break
        sections.append({
            "section_id": f"S{i:03d}",
            "heading": heading[:120],
            "text": body[:2000],
            "char_start": a, "char_end": b, "chars": len(body),
        })
    return sections


def _clause_hits(text: str) -> list[dict]:
    hits: list[dict] = []
    for kind, pattern in CLAUSE_PATTERNS.items():
        for m in re.finditer(pattern, text):
            a = max(0, m.start() - 90)
            b = min(len(text), m.end() + 150)
            hits.append({"kind": kind, "quote": _clean(text[a:b])[:280],
                         "char_start": m.start(), "char_end": m.end()})
            if len([h for h in hits if h["kind"] == kind]) >= 6:
                break
    return hits


def key_clauses(text: str) -> list[dict]:
    """定位关键商业条款；每个条款带原文片段与字符位置（T11 可据此断言 4001 字符后不丢）。"""
    return sorted(_clause_hits((text or "")[:MAX_SOURCE_CHARS]),
                  key=lambda x: x["char_start"])


def expired_offers(text: str, now: datetime | None = None) -> list[dict]:
    """找出「明确写了结束日期且已过期」的优惠，避免过期承诺被继续沿用（T12）。"""
    now = now or datetime.now(timezone.utc)
    src = (text or "")[:MAX_SOURCE_CHARS]
    out: list[dict] = []
    for line in re.split(r"[\n.!?。！？]", src):
        if not re.search(CLAUSE_PATTERNS["offer_window"], line):
            continue
        for m in _DATE_RE.finditer(line):
            try:
                if m.group(1):
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    y, mo, d = int(m.group(4)), _MONTHS[m.group(5).lower()[:3]], int(m.group(6))
                dt = datetime(y, mo, d, tzinfo=timezone.utc)
            except (ValueError, KeyError, TypeError):
                continue
            if dt < now:
                out.append({"expires_on": dt.date().isoformat(),
                            "quote": _clean(line)[:200]})
            break
    return out


def select_evidence_budget(text: str, sections: list[dict],
                           budget: int = DEFAULT_BUDGET) -> dict:
    """在字符预算内做「首尾窗口 + 关键条款区块」采样，取代 `text[:4000]`。

    返回 `budgeted_text`（带 [E###] 标记的分段正文）与 `coverage`（实际送入的字符区间），
    T11 据此验证第 4001 字符之后的订阅条款确实进入了模型输入。
    """
    src = (text or "")[:MAX_SOURCE_CHARS]
    n = len(src)
    if n == 0:
        return {"budgeted_text": "", "coverage": [], "dropped_chars": 0,
                "budget": budget, "clauses": [], "source_chars": 0}
    clauses = key_clauses(src)
    windows: list[tuple[int, int, str]] = [
        (0, min(n, HEAD_WINDOW), "head"),
        (max(0, n - TAIL_WINDOW), n, "tail"),
    ]
    for c in clauses:
        a = max(0, c["char_start"] - 260)
        b = min(n, c["char_end"] + 320)
        windows.append((a, b, c["kind"]))
    # 合并重叠 / 相邻窗口，再按起点排序
    windows.sort()
    merged: list[list] = []
    for a, b, tag in windows:
        if merged and a <= merged[-1][1] + 80:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2].add(tag)
        else:
            merged.append([a, b, {tag}])
    # 预算分配：始终保留首尾窗口，其余按关键条款优先填充
    must_idx = [i for i, m in enumerate(merged) if "head" in m[2] or "tail" in m[2]]
    extra_idx = [i for i in range(len(merged)) if i not in set(must_idx)]
    must = [merged[i] for i in must_idx]
    extra = [merged[i] for i in extra_idx]
    used = sum(b - a for a, b, _ in must)
    picked = list(must)
    for m in extra:
        size = m[1] - m[0]
        if used + size <= budget:
            picked.append(m)
            used += size
    picked.sort()
    chunks: list[str] = []
    coverage: list[dict] = []
    for i, (a, b, tags) in enumerate(picked, 1):
        body = _clean(src[a:b])
        if not body:
            continue
        eid = f"E{i:03d}"
        chunks.append(f"[{eid}] ({a}-{b}) {body}")
        coverage.append({"evidence_id": eid, "char_start": a, "char_end": b,
                         "tags": sorted(tags)})
    return {
        "budgeted_text": "\n".join(chunks),
        "coverage": coverage,
        "dropped_chars": max(0, n - sum(x["char_end"] - x["char_start"]
                                        for x in coverage)),
        "budget": budget,
        "clauses": clauses,
        "source_chars": n,
        "note": "首尾窗口 + 关键条款区块采样；未覆盖区间见 dropped_chars，不宣称全文已读",
    }


def build_evidence_index(text: str, sections: list[dict], source_url: str = "",
                         fetched_at: str = "") -> list[dict]:
    """每条采集区块生成可引用证据。verified 只表示「有原文可引用」，不是商业真实性背书。"""
    clause_positions = {c["char_start"] for c in key_clauses(text)}
    out: list[dict] = []
    for s in sections:
        kinds = sorted({c["kind"] for c in _clause_hits(s["text"])})
        has_clause = any(abs(s["char_start"] - p) < 2000 for p in clause_positions)
        out.append({
            "evidence_id": f"EV_{s['section_id']}",
            "quote": s["text"][:400],
            "source_url": source_url,
            "section": s["heading"] or s["section_id"],
            "char_start": s["char_start"], "char_end": s["char_end"],
            "fetched_at": fetched_at,
            "clause_kinds": kinds,
            "verified": bool(s["text"]),
            "verification": "original_text" if s["text"] else "empty",
            "applicable_scope": "page_text",
            "legacy_unverified": False,
            "has_key_clause": has_clause,
        })
    return out


def evidence_gate(page: dict, text: str, *, now: datetime | None = None) -> dict:
    """返回是否允许进入模型。空页 / 抓取失败 / 薄内容 / 过期优惠一律 needs_input。"""
    page = page or {}
    body = (text or "").strip()
    quality = page.get("fetch_quality") or ("manual_text" if body else "not_fetched")
    reasons: list[str] = []
    if len(body) < 120:
        reasons.append(f"页面正文为空或过短（{len(body)} 字符），无可用事实证据")
    if quality == "fetch_failed":
        reasons.append("落地页抓取失败，不能从 URL 推断产品事实")
    if quality == "thin_content" and len(body) < 200:
        reasons.append("抓取质量标记为 thin_content 且未补充足够正文")
    expired = expired_offers(body, now=now)
    if expired:
        reasons.append(f"检测到 {len(expired)} 条已过期优惠，不能沿用（最早过期日 "
                       f"{min(x['expires_on'] for x in expired)}）")
    return {
        "allowed": not reasons,
        "status": "ok" if not reasons else "needs_input",
        "reasons": reasons,
        "fetch_quality": quality,
        "source_chars": len(body),
        "expired_offers": expired,
    }


def build_evidence_pack(page: dict, text: str, *, budget: int = DEFAULT_BUDGET,
                        now: datetime | None = None) -> dict:
    """整合分区 / 证据 / 预算采样 / 阻断门，供 services 直接使用。"""
    page = page or {}
    src = (text or "")[:MAX_SOURCE_CHARS]
    sections = split_sections(src, page.get("html") or "")
    sampled = select_evidence_budget(src, sections, budget=budget)
    gate = evidence_gate(page, src, now=now)
    final_url = page.get("final_url") or page.get("input_url") or ""
    fetched_at = datetime.now(timezone.utc).isoformat()
    index = build_evidence_index(src, sections, final_url, fetched_at)
    return {
        "gate": gate,
        "budgeted_text": sampled["budgeted_text"],
        "coverage": sampled["coverage"],
        "dropped_chars": sampled["dropped_chars"],
        "budget": sampled["budget"],
        "source_chars": sampled["source_chars"],
        "clauses": sampled["clauses"],
        "sections": sections[:24],
        "evidence": index[:24],
        "evidence_ids": [x["evidence_id"] for x in index[:24]],
        "section_count": len(sections),
        "final_url": final_url,
        "fetched_at": fetched_at,
        "legacy_unverified": not bool(index),
        "note": "证据来自页面原文；已验证事实 / 营销假设 / 缺口在分析结构中分离，"
                "竞品须独立研究附来源，不从 URL 猜产品事实",
    }


def evidence_contract(pack: dict) -> str:
    """写进落地页分析提示词的证据边界条款。"""
    return (
        "证据使用规则（必须遵守）：\n"
        "1. 只把下方带 [E###] 标记的正文片段当作已验证事实来源；每条价格、优惠、退货、"
        "订阅、试用或效果承诺都必须在对应字段的 evidence_ids 里引用片段编号。\n"
        "2. 把「已验证事实(facts)」「营销假设(assumptions)」「资料缺口(gaps)」分开输出；"
        "缺资料时写进 gaps 并留空相应字段，绝不从域名、URL 或行业常识推断产品事实。\n"
        "3. 竞品只能来自正文里明确出现且有证据编号的名字；不得推断全球排名、市场份额或"
        "未出现的竞品，独立竞品研究应另附来源。\n"
        "4. 已过期或标注了结束日期且早于今天的优惠不得作为当前承诺；"
        "发现过期条款请写进 gaps 并说明。\n"
        f"5. 本次采样覆盖 {len(pack.get('coverage') or [])} 个片段，"
        f"未覆盖 {pack.get('dropped_chars', 0)} 字符；不要在未覆盖区间编造事实。"
    )
