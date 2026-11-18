"""V4.93：品牌 / 文案黄金词典（品牌名与单词正确性的唯一事实源）。

背景：视频大模型把「画字」当成生成像素，不认识字母与品牌名，必然出现品牌名次错误、
单词拼错、缺笔画。V4.90 的批准清单把落地页 facts / sellingPoints 整句也当成可上屏文字，
等于允许模型自由"写"这些句子，是错字高发的根源。

本模块的定位：**把"允许出现在画面上的品牌名 / 产品名 / CTA / 单词"收敛成一份可追溯的
黄金词典**，作为唯一事实源。任何上屏文字必须逐字来自这份词典；词典没有的字一律不允许
上屏（阶段一策略：视频默认零文字，由播放层叠加文字，画面不出现任何品牌字样）。

设计约束：
- 纯函数；不调用模型、不访问数据库、不依赖 ffmpeg / OCR；
- 不改表结构：词典随分析结果即时编译，快照写入任务 meta 便于追溯；
- 品牌名/产品名只取自「已确认来源」：用户输入(brand) 优先，其次落地页 analysis 的
  product / title；绝不接受从 facts / sellingPoints 里猜出来的品牌；
- 提供 enforce_onscreen()：对任何"打算上屏"的文字逐字比对，未命中即返回阻断结论。

阶段边界：阶段一只做源头词典 + 零文字 + 严格白名单；播放层叠加与成片 OCR 属后续阶段。
"""
from __future__ import annotations

import re

LEXICON_VERSION = "1.0.0"
MAX_BRAND_LEN = 60
MAX_TERM_LEN = 80

# 已确认来源的字段名：只有这些字段里的短字符串才允许进入品牌 / 产品 / CTA 词典。
_CONFIRMED_BRAND_KEYS = ("brand", "brandName", "brand_name", "advertiser")
_CONFIRMED_PRODUCT_KEYS = ("product", "productName", "product_name")
_CONFIRMED_CTA_KEYS = ("cta", "ctaText", "cta_text")


def _clean(value) -> str:
    s = str(value or "").replace("\u3000", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _unwrap(analysis: dict | None) -> dict:
    if not isinstance(analysis, dict):
        return {}
    inner = analysis.get("analysis")
    return inner if isinstance(inner, dict) else analysis


def _pick(data: dict, keys) -> str:
    for k in keys:
        v = _clean(data.get(k))
        if v and len(v) <= MAX_BRAND_LEN:
            return v
    return ""


def build_lexicon(analysis: dict | None = None,
                  plan: dict | None = None,
                  brief: dict | None = None) -> dict:
    """从落地页分析与分镜编译黄金词典。

    只接受已确认来源（用户 brand / analysis.product / title / brief.cta）。
    facts / sellingPoints / advantages 一律不进入词典，避免整句卖点被模型当品牌画出来。
    """
    a = _unwrap(analysis)
    b = brief if isinstance(brief, dict) else (a.get("brief") if isinstance(a.get("brief"), dict) else {})
    p = plan if isinstance(plan, dict) else {}

    brand = _pick(a, _CONFIRMED_BRAND_KEYS) or _pick(b, _CONFIRMED_BRAND_KEYS)
    product = _pick(a, _CONFIRMED_PRODUCT_KEYS) or _pick(b, _CONFIRMED_PRODUCT_KEYS)
    if not product and isinstance(analysis, dict):
        product = _clean(analysis.get("title"))
        if len(product) > MAX_BRAND_LEN:
            product = ""
    cta = _pick(p, _CONFIRMED_CTA_KEYS) or _pick(b, _CONFIRMED_CTA_KEYS)

    # 简报层显式列出的上屏词：可作为词典补充（brief 来自落地页分析，属已确认层）。
    # V4.93 关键：**绝不采纳 plan 里的 approved_texts / onscreen_texts** —— 那是"待校验的
    # 上屏声明"，可能来自模型或前端。若让它填充词典，错拼品牌名会自我认证成合法词。
    # 校验基准只能由被信任的来源建立，再由 enforce_onscreen() 去校验 plan 声明。
    explicit: list[str] = []
    for source in (b.get("onscreen_texts"), b.get("approved_texts")):
        if isinstance(source, (list, tuple, set)):
            values = list(source)
        else:
            values = [source]
        for v in values:
            s = _clean(v)
            if s and len(s) <= MAX_TERM_LEN and s not in explicit:
                explicit.append(s)

    # 词典正文：品牌 / 产品 / CTA / 显式上屏词，去重保序。
    entries: list[str] = []
    for s in (brand, product, cta, *explicit):
        if s and s not in entries:
            entries.append(s)

    sources = {
        "brand": "confirmed" if brand else "unconfirmed",
        "product": "confirmed" if product else "unconfirmed",
        "cta": "confirmed" if cta else "unconfirmed",
    }
    return {
        "version": LEXICON_VERSION,
        "brand": brand,
        "product": product,
        "cta": cta,
        "entries": entries,
        "explicit_onscreen": explicit,
        "sources": sources,
        "has_brand": bool(brand),
        "note": (
            "黄金词典：品牌名 / 产品名 / CTA 只取自已确认来源；facts 与卖点整句不进入词典。"
            + ("" if brand else " 未取得已确认品牌名，画面禁止出现任何品牌字样。")
        ),
    }


def enforce_onscreen(texts, lexicon: dict | None) -> dict:
    """对打算上屏的文字逐字比对词典，返回阻断结论。

    阶段一策略：没有任何文字被"默认允许"上屏——即使字符串在词典里，也只是
    "允许但需受控"，而 approved_only 才会真正放行。这里负责识别"词典外 + 高风险
    品牌近似字"，供 text_guard 汇总为 generation_blocked。
    """
    lex = lexicon if isinstance(lexicon, dict) else {}
    entries = [str(x) for x in (lex.get("entries") or []) if str(x).strip()]
    raw = list(texts) if isinstance(texts, (list, tuple, set)) else ([texts] if texts is not None else [])
    violations: list[dict] = []
    for item in raw:
        s = _clean(item)
        if not s:
            continue
        exact = s in entries
        # 与词典项高度相似但不完全一致：品牌名 / 单词错拼的典型特征。
        # 大小写不敏感（ASCII 品牌名 Novax vs NovaX 必须判为错拼，不能被当新词放行）。
        import difflib
        near = ""
        casefold_hit = ""
        if not exact:
            hit = difflib.get_close_matches(s, entries, n=1, cutoff=0.82)
            near = hit[0] if hit else ""
            folded = s.casefold()
            for e in entries:
                if e.casefold() == folded and e != s:
                    casefold_hit = e
                    break
        risk = "exact" if exact else ("case_miss" if casefold_hit else
                                      ("near_miss" if near else "unknown"))
        violations.append({
            "text": s[:120],
            "in_lexicon": exact,
            "near_lexicon": near or casefold_hit,
            "risk": risk,
        })
    outside = [v for v in violations if not v["in_lexicon"]]
    return {
        "status": "needs_revision" if outside else "ok",
        "lexicon_version": lex.get("version", ""),
        "checked": len(violations),
        "outside_count": len(outside),
        "violations": violations,
        "note": (
            "存在词典外上屏文字；品牌名 / 单词必须逐字来自已确认词典，"
            "缺字、近似字、错拼一律阻断出片。" if outside else
            "全部上屏文字命中黄金词典。"
        ),
    }


def render_lexicon_block(lexicon: dict | None) -> str:
    """把黄金词典编译进出片提示词，阻断模型自由写品牌名 / 单词。"""
    lex = lexicon if isinstance(lexicon, dict) else {}
    brand = lex.get("brand") or ""
    product = lex.get("product") or ""
    cta = lex.get("cta") or ""
    entries = [str(x) for x in (lex.get("entries") or []) if str(x).strip()]
    lines = [
        "[品牌黄金词典] 唯一事实源；画面文字不得超出本词典。",
        f"已确认品牌名：{brand or '（无已确认品牌名 —— 画面禁止出现任何品牌字样）'}",
        f"已确认产品名：{product or '（无）'}",
        f"已确认 CTA 文案：{cta or '（无）'}",
    ]
    if entries:
        lines.append("允许逐字出现的文字：" + " | ".join(entries[:12]))
    lines.extend([
        "严禁：拼写 / 生成品牌名、产品名、英文单词、Logo 字样、水印、端卡；"
        "不得猜测近似拼写、不得补字/缺字、不得手写字母。",
        "品牌标识只能以无字图形或主体外观表达；如需可读品牌字样，交给播放层叠加，画面本身不出字。",
        "无需上屏的字段（字幕 / CTA / VO）仅用于内部节奏与旁白，不绘制到画面。",
    ])
    return "\n".join(lines)
