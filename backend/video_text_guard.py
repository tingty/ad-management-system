"""V4.90：视频文字 / 文案预检与保守修复。

V4.82 已经用 `video_claims` 管住数字、限定与证据；V4.88 又默认禁止把分镜里的
字幕 / CTA / Logo 绘制进画面。但模型出片仍可能在画面里自行“写”字，且分镜文案
本身也可能出现截断、乱码、重复标点、不可读长句或未经批准的上屏文案。

本模块只做确定性纯函数，不调用模型、不碰数据库：

- `audit_video_text()`：从 plan/options 中抽取所有可能进入视频的文字，检查文本形态、
  可读性、批准清单与效果化例外，返回可追溯审查报告；
- `repair_video_text()`：只做保守修正（归一化、补全前缀、去掉截断符号、按批准清单纠偏），
  修不掉就标记 `generation_blocked`，绝不把问题文字交给厂商；
- `render_video_text_guard_block()`：把审查结论编译进出片提示词。默认仍是严格无字；
  只有 plan/options 显式给出 `text_policy=approved_only` + `approved_texts` 时，
  才允许批准清单中的文字逐字出现。

边界：`text_effect` / `text_treatment` / `motion_graphics` 只放宽可读性硬门，
不绕过证据、限定、完整性和批准清单检查。
"""
from __future__ import annotations

import copy
import difflib
import re

TEXT_GUARD_VERSION = "1.0.0"
DEFAULT_TEXT_POLICY = "none"

_PLAN_TEXT_KEYS = (
    "hook", "cta", "headline", "subtitle", "caption", "endcard",
    "cta_text", "title_text", "brand_text", "logo_text", "badge", "label",
)
_SHOT_ONSCREEN_KEYS = (
    "text", "subtitle", "caption", "overlay", "endcard", "title", "cta",
    "cta_text", "title_text", "brand_text", "logo_text", "badge", "label",
)
_SHOT_AUDIO_KEYS = ("vo", "narration", "voiceover")
_VISIBLE_PLAN_KEYS = {
    "subtitle", "caption", "endcard", "cta_text", "title_text",
    "brand_text", "logo_text", "badge", "label",
}

_GARBLED_RE = re.compile(r"Ã|Â|â€|ï¿½|\ufffd|[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")
_TRUNC_RE = re.compile(r"(?:\.\.\.|…|[、，,:：\-—_])$")
_REPEAT_RE = re.compile(r"([!！?？。.、,，;；])\1{2,}")
_QUOTE_RE = re.compile(r"([\"“「『《])([^\"”」』》]{1,120})([\"”」』》])")
_UNPAIRED_RIGHT = set("”」』》)]}")
_UNPAIRED_LEFT = set("“「『《([{")

_APPROVED_POLICY_WORDS = {
    "approved", "approved_only", "allowlist", "whitelist", "explicit",
    "visible", "on", "true", "yes", "1",
}


def _unwrap(analysis: dict | None) -> dict:
    if not isinstance(analysis, dict):
        return {}
    inner = analysis.get("analysis")
    return inner if isinstance(inner, dict) else analysis


def _normalize(text) -> str:
    """去零宽字符 + 合并空白；保留中文全角标点，不擅自改写文案风格。"""
    s = str(text or "").replace("\u3000", " ")
    s = _ZERO_WIDTH_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,，。.!！?？;；:：])", r"\1", s)
    return s


def _effect_flag(node) -> bool:
    if not isinstance(node, dict):
        return False
    raw = node.get("text_effect") or node.get("text_treatment") or node.get("effect_text")
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    return bool(s) and s not in {"false", "none", "no", "0", "off"}


def _text_policy(plan: dict | None, options: dict | None) -> str:
    p = plan if isinstance(plan, dict) else {}
    o = options if isinstance(options, dict) else {}
    raw = p.get("text_policy") or o.get("text_policy") or DEFAULT_TEXT_POLICY
    return "approved_only" if str(raw).strip().lower() in _APPROVED_POLICY_WORDS else "none"


def _repair_corpus(plan: dict | None, analysis: dict | None,
                   options: dict | None) -> list[str]:
    """仅用于截断补全的"文本语料"，不是上屏批准清单。

    V4.90 把 facts / sellingPoints 整句当成批准文案，V4.93 起这些句子只能用来
    把"真实任务..."补成完整句，绝不代表模型可以把整句画到画面上。
    """
    p = plan if isinstance(plan, dict) else {}
    o = options if isinstance(options, dict) else {}
    a = _unwrap(analysis)
    b = a.get("brief") if isinstance(a.get("brief"), dict) else {}
    raw_sources = [
        a.get("facts"), a.get("advantages"), a.get("sellingPoints"),
        b.get("sellingPoints"), b.get("core_promise"), b.get("promise"),
        p.get("approved_texts"), o.get("approved_texts"), a.get("approved_texts"),
    ]
    out: list[str] = []
    for source in raw_sources:
        if isinstance(source, (list, tuple, set)):
            values = list(source)
        else:
            values = [source]
        for value in values:
            s = _normalize(value)
            if s and s not in out and len(s) <= 100:
                out.append(s)
    return out


def _approved_texts(plan: dict | None, analysis: dict | None,
                    options: dict | None, lexicon: dict | None = None) -> list[str]:
    """上屏批准清单（V4.93 收紧）：只认黄金词典 / 显式上屏词，不再从 facts 兜底。

    未传 lexicon 时退回 plan/options 显式声明的批准清单，保持 V4.90 调用兼容；
    传入 lexicon 时以词典 entries 为唯一允许上屏文字，facts 整句不再自动获批。
    """
    p = plan if isinstance(plan, dict) else {}
    o = options if isinstance(options, dict) else {}
    out: list[str] = []

    def add_all(source):
        if isinstance(source, (list, tuple, set)):
            values = list(source)
        else:
            values = [source]
        for value in values:
            s = _normalize(value)
            if s and s not in out and len(s) <= 100:
                out.append(s)

    if isinstance(lexicon, dict):
        # V4.93：黄金词典是唯一权威来源。绝不采纳 plan/options 里的 approved_texts 声明——
        # 那是被校验对象，若允许自我批准，错拼品牌名（Novax）会被真正的词典放过。
        add_all(lexicon.get("entries"))
    else:
        # 兼容旧调用：无词典时用显式声明（不含 facts 整句）。
        add_all(p.get("approved_texts"))
        add_all(p.get("text_allowlist"))
        add_all(o.get("approved_texts"))
        add_all((analysis or {}).get("approved_texts") if isinstance(analysis, dict) else None)
    return out


def _get_field(obj, path: str):
    cur = obj
    for part in str(path or "").split("."):
        if isinstance(cur, list) and part.isdigit():
            i = int(part)
            if i < 0 or i >= len(cur):
                return None
            cur = cur[i]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _set_field(obj, path: str, value) -> bool:
    parts = str(path or "").split(".")
    if not parts:
        return False
    cur = obj
    for part in parts[:-1]:
        if isinstance(cur, list) and part.isdigit():
            i = int(part)
            if i < 0 or i >= len(cur):
                return False
            cur = cur[i]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return False
    last = parts[-1]
    if isinstance(cur, list) and last.isdigit():
        i = int(last)
        if 0 <= i < len(cur):
            cur[i] = value
            return True
        return False
    if isinstance(cur, dict):
        cur[last] = value
        return True
    return False


def _collect_candidates(plan: dict | None, options: dict | None) -> list[dict]:
    p = plan if isinstance(plan, dict) else {}
    o = options if isinstance(options, dict) else {}
    out: list[dict] = []

    def add(field: str, value, kind: str, effect: bool = False, quote: str = ""):
        if value is None:
            return
        text = str(value)
        if not text.strip():
            return
        out.append({
            "field": field, "text": text, "kind": kind,
            "effect": bool(effect), "quote": quote,
        })

    plan_effect = _effect_flag(p)
    for key in _PLAN_TEXT_KEYS:
        if key in p:
            kind = "onscreen" if key in _VISIBLE_PLAN_KEYS else "planning"
            add(key, p.get(key), kind,
                plan_effect or _effect_flag({k: v for k, v in p.items()
                                             if k == f"{key}_effect" or k == f"{key}_treatment"}))

    for i, shot in enumerate(p.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        effect = _effect_flag(shot) or str(shot.get("shot") or "").strip().lower() == "motion_graphics"
        for key in _SHOT_ONSCREEN_KEYS:
            if key in shot:
                add(f"shots.{i}.{key}", shot.get(key), "onscreen", effect)
        for key in _SHOT_AUDIO_KEYS:
            if key in shot:
                add(f"shots.{i}.{key}", shot.get(key), "audio", effect)
        visual = str(shot.get("visual") or "")
        for m in _QUOTE_RE.finditer(visual):
            add(f"shots.{i}.visual", m.group(2), "quoted", effect, quote=m.group(0))

    hint = str(o.get("prompt_hint") or "")
    for m in _QUOTE_RE.finditer(hint):
        add("options.prompt_hint", m.group(2), "quoted", False, quote=m.group(0))
    return out


def _balanced(text: str) -> bool:
    for left, right in (("“", "”"), ("「", "」"), ("『", "』"), ("《", "》")):
        if text.count(left) != text.count(right):
            return False
    if text.count('"') % 2:
        return False
    stack: list[str] = []
    for ch in text:
        if ch in _UNPAIRED_LEFT:
            stack.append(ch)
        elif ch in _UNPAIRED_RIGHT:
            if not stack:
                return False
            stack.pop()
    return not stack


def _length_score(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(re.sub(r"[\u4e00-\u9fff\s]", "", text))
    return cjk * 2 + other


def _check_candidate(candidate: dict, policy: str, approved: list[str],
                     corpus: list[str] | None = None) -> list[dict]:
    text = _normalize(candidate["text"])
    if not text:
        return []
    issues: list[dict] = []

    def add(kind: str, severity: str, reason: str, suggested: str = "", repairable: bool = False):
        issues.append({
            "type": kind, "severity": severity, "reason": reason,
            "suggested": suggested, "repairable": repairable,
        })

    if _GARBLED_RE.search(text):
        add("garbled_text", "block", "文字含乱码 / 控制字符，模型无法稳定复现")
        return issues

    truncated = bool(_TRUNC_RE.search(text))
    if truncated:
        base = re.sub(r"(?:\.\.\.|…|[、，,:：\-—_])$", "", text).strip()
        suggested = ""
        for item in (approved + (corpus or [])):
            if len(base) >= 2 and base in item and len(item) <= 100:
                suggested = item
                break
        add("truncated_text", "block", "文字以省略号 / 半截标点结尾，疑似被截断",
            suggested or base, bool(base))

    repeat = _REPEAT_RE.search(text)
    if repeat:
        fixed = _REPEAT_RE.sub(r"\1", text)
        add("unreadable_repetition", "block", "连续重复标点，画面中不可读",
            fixed, fixed != text)

    if not _balanced(text):
        fixed = text.strip()
        while fixed and fixed[-1] in _UNPAIRED_RIGHT:
            fixed = fixed[:-1].rstrip()
        while fixed and fixed[0] in _UNPAIRED_LEFT:
            fixed = fixed[1:].lstrip()
        add("unbalanced_marks", "block", "引号 / 括号不成对，容易被生成成半截字",
            fixed, bool(fixed) and fixed != text)

    score = _length_score(text)
    if score > 72:
        if candidate.get("effect"):
            add("long_text_effect", "warn", "文字较长，但已标记为效果化处理，仅提示人工抽检")
        else:
            add("too_long", "block", f"文字过长（强度 {score}），缩到安全区后通常无法看清")

    if policy == "approved_only" and candidate.get("kind") in {"onscreen", "quoted"}:
        if text not in approved:
            close = difflib.get_close_matches(text, approved, n=1, cutoff=0.92)
            if close:
                add("unapproved_text", "block", "上屏文字与批准文案高度接近但不完全一致",
                    close[0], True)
            else:
                add("unapproved_text", "block",
                    "上屏文字不在 approved_texts / 已确认事实清单中")
    return issues


def audit_video_text(plan: dict | None, analysis: dict | None = None,
                     options: dict | None = None,
                     lexicon: dict | None = None) -> dict:
    """审查视频中所有可能进入画面的文字；返回结构化报告，不修改输入。"""
    p = plan if isinstance(plan, dict) else {}
    o = options if isinstance(options, dict) else {}
    policy = _text_policy(p, o)
    approved = _approved_texts(p, analysis, o, lexicon)
    corpus = _repair_corpus(p, analysis, o)
    candidates = _collect_candidates(p, o)
    violations: list[dict] = []

    # V4.93：黄金词典校验——品牌名 / 单词错拼（大小写在内的近似字）必须在提交前暴露。
    # 只对"打算上屏"的文字生效：默认 none 策略画面本应无字，任何上屏候选都要经得起词典核对。
    lex_entries = [str(x) for x in ((lexicon or {}).get("entries") or []) if str(x).strip()] if isinstance(lexicon, dict) else []
    for c in candidates:
        for issue in _check_candidate(c, policy, approved, corpus):
            violations.append({
                "field": c["field"],
                "kind": c["kind"],
                "text": _normalize(c["text"])[:200],
                "quote": c.get("quote", ""),
                "effect": bool(c.get("effect")),
                **issue,
            })
        # 词典近似错拼：只针对 onscreen，避免把 VO / 策划草稿的口语误判为错字。
        if lex_entries and c.get("kind") == "onscreen":
            from brand_lexicon import enforce_onscreen as _enforce
            chk = _enforce([c["text"]], lexicon)
            for v in chk.get("violations") or []:
                if v.get("risk") in ("case_miss", "near_miss"):
                    violations.append({
                        "field": c["field"], "kind": c["kind"],
                        "text": v["text"][:200], "quote": c.get("quote", ""),
                        "effect": bool(c.get("effect")),
                        "type": "brand_spelling_mismatch", "severity": "block",
                        "reason": f"上屏文字疑似品牌名 / 单词错拼，应为「{v['near_lexicon']}」",
                        "suggested": v["near_lexicon"], "repairable": True,
                    })

    blocking = [v for v in violations if v.get("severity") == "block"]
    warnings = [v for v in violations if v.get("severity") == "warn"]
    return {
        "status": "needs_revision" if blocking else "ok",
        "rules_version": TEXT_GUARD_VERSION,
        "text_policy": policy,
        "checked": len(candidates),
        "approved_texts": approved[:20],
        "lexicon_enforced": bool(isinstance(lexicon, dict) and lexicon.get("entries")),
        "violations": violations,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "note": (
            "视频文字未通过预检：截断 / 乱码 / 不可读 / 未批准文字必须在提交厂商前修正。"
            if blocking else
            ("已启用批准文案白名单；只有清单内文字允许逐字出现，效果化处理仍需人工抽检。"
             if policy == "approved_only" and approved else
             "默认无上屏文字；分镜字幕 / CTA 仅作策划与 VO 参考，不绘制进画面。")
        ),
    }


def repair_video_text(plan: dict | None, analysis: dict | None = None,
                      options: dict | None = None,
                      lexicon: dict | None = None) -> tuple[dict, dict, int]:
    """保守修复：能确定的错误直接改；改不掉的保留原样并标记禁止提交。"""
    p = copy.deepcopy(plan or {})
    report = audit_video_text(p, analysis, options, lexicon)
    done = 0
    handled_fields: set[str] = set()
    # 同一字段可能同时命中多条问题（如品牌错拼 = 未批准 + 近似错拼）。
    # 排序让"可修复"的排前，确保品牌错别字能被自动改成词典正确拼写，
    # 而不是被同字段那条不可修复的"未批准"抢先占位后直接阻断。
    ordered = sorted(
        report.get("violations") or [],
        key=lambda v: (str(v.get("field") or ""), not bool(v.get("repairable"))),
    )
    for v in ordered:
        field = str(v.get("field") or "")
        if field in handled_fields:
            continue
        handled_fields.add(field)
        if v.get("severity") != "block" or not v.get("repairable"):
            continue
        suggested = _normalize(v.get("suggested") or "")
        if not suggested:
            continue
        quote = str(v.get("quote") or "")
        if quote:
            current = str(_get_field(p, field) or "")
            if quote in current:
                _set_field(p, field, current.replace(quote, suggested, 1))
                done += 1
            continue
        current = _normalize(_get_field(p, field))
        if suggested != current and _set_field(p, field, suggested):
            done += 1

    final = audit_video_text(p, analysis, options, lexicon)
    p["text_guard"] = final
    p["text_repair_count"] = done
    p["generation_blocked"] = bool(p.get("generation_blocked")) or final["status"] == "needs_revision"
    return p, final, done


def render_video_text_guard_block(report: dict | None) -> str:
    """把审查结论编译进出片提示词，避免文字规则只停在报告里。"""
    r = report if isinstance(report, dict) else {}
    if not r:
        return ""
    policy = str(r.get("text_policy") or DEFAULT_TEXT_POLICY)
    approved = [str(x) for x in (r.get("approved_texts") or []) if str(x).strip()]
    lines: list[str] = []

    if r.get("status") == "needs_revision":
        bad = "；".join(
            f"{v.get('field')}:{v.get('type')}" for v in (r.get("violations") or [])[:3]
        )
        lines.append(f"【文字审查 · 未通过】{r.get('blocking_count', 0)} 处问题未修正（{bad}）；不得提交厂商出片。")
    if policy == "approved_only" and approved:
        lines.append("【文字审查 · 批准清单】画面只允许逐字出现：" + " | ".join(approved[:12]))
        lines.append("清单外的文字、字幕、数字、角标、按钮、假 UI 一律不得生成；不得改写、缩略、补字或截断批准文字。")
        lines.append("效果化文字：仅允许对被批准文字做动效 / 光效 / 景深处理；处理后仍必须可辨认，不能变成错字或缺字。")
    else:
        lines.append("【文字审查 · 无字】本次没有任何批准上屏文字；画面内禁止文字、字幕、字母、数字、端卡、水印与 Logo 图层。")
    lines.append("审查纪律：VO 只复述已核实事实；分镜字幕 / CTA 只作策划节奏，不自动上屏。")
    return "\n".join(lines)
