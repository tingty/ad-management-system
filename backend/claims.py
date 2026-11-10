"""V4.44 / N01：证据 → 广告承诺（claim）的强引用、限定保护与生成后校验。

验收文档指出：V4.43 只是「有证据字段」，但
1. `[E###]` 采样编号与 `EV_S###` 分区索引并存且无强映射；
2. `_normalize_landing()` 接受不存在的证据编号；
3. `_analysis_context()` 没把 facts / evidence_chain 传给文案模型；
4. 语义保护只比较「超长压缩前后」，短文案首次生成丢掉 `up to / 最多 / 护理模式` 等
   限定条件时没有任何拦截。

本模块提供纯函数，全部可在无模型、无数据库的回归脚本中验证：

- `EvidenceSnapshot`：从 `evidence_index`（唯一 `[E###]` 命名空间）构建不可变快照；
- `validate_evidence_refs()`：不存在的证据 ID 直接拒绝，且要求 claim 的引用能定位到原文；
- `check_claim_qualifiers()`：量化承诺必须保留原文的限定 / 计费周期 / 测试条件 / 适用范围；
- `audit_copy_fields()`：**每次**生成与编辑后都校验，与文案是否超长无关；
- `claim_contract()`：把上述规则写进文案模型提示词。

重要边界：`review_status = locatable_not_reviewed` 只表示「能在原文定位」，
不代表价格 / 效果 / 合规的商业真实性已被审核，二者分开（文档 N01）。
"""
from __future__ import annotations

import hashlib
import json
import re

CLAIM_RULES_VERSION = "1.0"

#: 必须随量化承诺一起保留的限定类别。命中即视为「不得扩大」的硬约束。
HARD_QUALIFIERS = ("upper_bound", "condition", "billing_cycle", "test_condition", "scope")
ADVISORY_QUALIFIERS = ("compatibility", "bundle")

QUALIFIER_RULES: dict[str, str] = {
    "upper_bound": r"up\s*to|as\s+(?:much|many|low)\s+as|at\s+most|maximum|max\.?\s*\d|"
                   r"最多|至多|最高|上限|不超过|不高于|不低于|至少|起售|起价|\d+\s*折",
    "condition": r"conditions?\s+apply|terms?\s+apply|subject\s+to|only\s+(?:if|for|when)|"
                 r"while\s+supplies\s+last|需|仅限|仅适用于|另需|除外|不含|不适用|有条件|满足条件",
    "billing_cycle": r"per\s+month|/\s*mo\b|billed\s+annually|per\s+year|recurring|"
                     r"renew(?:al|s)?|first\s+year|after\s+\d+\s+months?|按月|按年|每月|每年|"
                     r"首年|续费|自动续订|下一个计费周期|\d+\s*个月|\d+\s*天试用",
    "test_condition": r"battery\s+care|care\s+mode|lab(?:oratory)?\s+(?:test|condition)|"
                      r"tested\s+(?:under|with|in)|results?\s+may\s+vary|depending\s+on|"
                      r"护理模式|测试条件|实验室|实测|结果可能|因人而异|视.*而定|在特定条件下",
    # 有效期（valid until / 有效期至）属于时间条件，不并入适用范围，
    # 否则同窗口内的其它条款会误伤与数字无关的广告短句。
    "scope": r"selected\s+(?:regions?|countries?|models?|plans?)|"
             r"applicable\s+to|available\s+(?:in|for|on)|仅限|适用于|适用地区|指定型号|"
             r"部分地区|指定套餐|活动期间",
    "compatibility": r"compatible\s+with|works\s+with|requires?|supports?|兼容|支持|需搭配|"
                     r"适配|仅支持|需要.*系统",
    "bundle": r"sold\s+separately|accessor(?:y|ies)\s+(?:not\s+)?included|in\s+the\s+box|"
              r"另售|需另购|配件.*另|包装内含|套装含",
}

_COMPILED = {k: re.compile(v, re.I) for k, v in QUALIFIER_RULES.items()}

# 量化承诺：数字 + 百分比 / 倍 / 时长 / 金额 / 容量单位
_NUM_RE = re.compile(
    # 中文语境下数字紧跟汉字，不能用 (?<!\w)（Unicode 中文也算 \w）
    r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:%|％|倍|折|小时|h\b|天|分钟|元|美元|\$|€|£|"
    r"mAh|W\b|w\b|GB|TB|Mbps|kg|cm|mm|x\b)?",
    re.I)
_EID_RE = re.compile(r"^E\d{3}$")


def qualifier_hits(text: str) -> dict[str, list[str]]:
    """返回文本里出现的所有限定类别 → 命中片段（去重、每个类别最多 3 条）。"""
    s = str(text or "")
    out: dict[str, list[str]] = {}
    for kind, rx in _COMPILED.items():
        hits = []
        for m in rx.finditer(s):
            frag = m.group(0).strip()
            if frag and frag not in hits:
                hits.append(frag)
            if len(hits) >= 3:
                break
        if hits:
            out[kind] = hits
    return out


def numeric_tokens(text: str) -> list[str]:
    """提取量化承诺里的数字 token，用于把广告短句回连到原文窗口。"""
    return [re.sub(r"\s+", "", m.group(0)).lower()
            for m in _NUM_RE.finditer(str(text or "")) if m.group(0).strip()]


class EvidenceSnapshot:
    """一次落地页采集的不可变证据视图；对外只暴露 `[E###]`。"""

    def __init__(self, index: list[dict] | None = None, *, snapshot_id: str = "",
                 source_url: str = "", fetched_at: str = ""):
        self.entries: dict[str, dict] = {}
        for row in index or []:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("evidence_id") or "").strip()
            if _EID_RE.match(eid):
                self.entries[eid] = dict(row)
        self.source_url = source_url
        self.fetched_at = fetched_at
        self.snapshot_id = snapshot_id or self._digest()

    def _digest(self) -> str:
        payload = json.dumps(
            [[k, v.get("quote"), v.get("char_start"), v.get("char_end")]
             for k, v in sorted(self.entries.items())],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "evs_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_analysis(cls, analysis: dict) -> "EvidenceSnapshot":
        a = analysis if isinstance(analysis, dict) else {}
        return cls(a.get("evidence_index"), snapshot_id=a.get("evidence_snapshot_id") or "",
                   source_url=a.get("final_url") or a.get("url") or "",
                   fetched_at=a.get("evidence_fetched_at") or "")

    @property
    def valid_ids(self) -> set[str]:
        return set(self.entries)

    @property
    def available(self) -> bool:
        return bool(self.entries)

    def quote_of(self, eid: str) -> str:
        return str((self.entries.get(eid) or {}).get("quote") or "")

    def source_text(self) -> str:
        """把可定位原文拼成限定词校验的语料（不依赖完整页面正文）。"""
        return "\n".join(self.quote_of(k) for k in sorted(self.entries))

    def to_dict(self) -> dict:
        return {"snapshot_id": self.snapshot_id, "evidence_ids": sorted(self.entries),
                "count": len(self.entries), "source_url": self.source_url,
                "fetched_at": self.fetched_at,
                "review_status": "locatable_not_reviewed"}


def validate_evidence_refs(ids, snapshot: EvidenceSnapshot,
                           *, claim: str = "") -> dict:
    """不存在的证据编号直接拒绝；存在但无原文可定位同样拒绝。"""
    raw = [str(x or "").strip() for x in (ids if isinstance(ids, list) else [ids])]
    raw = [x for x in raw if x]
    invalid = [x for x in raw if x not in snapshot.valid_ids]
    unlocatable = [x for x in raw if x in snapshot.valid_ids and not snapshot.quote_of(x)]
    return {
        "ok": bool(raw) and not invalid and not unlocatable and snapshot.available,
        "claim": str(claim or "")[:240],
        "ids": raw, "invalid_ids": invalid, "unlocatable_ids": unlocatable,
        "reason": ("未引用任何证据编号" if not raw else
                   f"证据编号不存在：{', '.join(invalid)}" if invalid else
                   f"证据编号无原文可定位：{', '.join(unlocatable)}" if unlocatable else
                   "证据快照为空" if not snapshot.available else ""),
    }


def validate_evidence_chain(chain, snapshot: EvidenceSnapshot,
                            *, strict_refs: bool = False) -> dict:
    """逐条校验模型输出的事实→证据引用；返回可写进接口结果的审计结构。

    默认只把「引用了不存在的 / 不可定位的编号」判为违规；模型输出的纯描述性事实
    未带编号时不算违规（`strict_refs=True` 时才要求每条 claim 必须有引用）。
    """
    items = []
    for row in chain or []:
        if isinstance(row, dict):
            claim, ids = row.get("claim", ""), row.get("evidence_ids") or []
            rejected = bool(row.get("rejected"))
        else:
            claim, ids, rejected = str(row or ""), [], False
        checked = validate_evidence_refs(ids, snapshot, claim=claim)
        if not ids and not rejected and not strict_refs:
            checked = {**checked, "ok": True, "reason": ""}
        items.append({**checked, "rejected": rejected,
                      "kind": (row.get("kind") if isinstance(row, dict) else "fact") or "fact"})
    invalid = [x for x in items if not x["ok"]]
    return {"checked": len(items), "invalid": len(invalid), "items": items,
            "status": "ok" if not invalid else "needs_revision",
            "note": "引用不存在的 [E###] 编号一律不进入下游文案依据"}


def check_claim_qualifiers(source_text: str, claim_text: str) -> dict:
    """量化承诺必须保留原文的限定类别；对**短句首次生成**同样生效。

    做法：从广告文案提取数字 token → 回连原文中包含该数字的窗口 → 取窗口内出现的
    硬限定类别 → 要求文案自身也包含这些类别。例如原文「最多降低 20%，护理模式下、
    实验室条件」被写成「电池老化降低 20%」时，`upper_bound` / `test_condition` 缺失，
    判定 needs_revision，而不是等超长压缩才检查。
    """
    src, claim = str(source_text or ""), str(claim_text or "")
    nums = numeric_tokens(claim)
    claim_digits = {m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?", claim)}
    if not nums or not claim_digits or not src.strip():
        return {"ok": True, "checked": False, "numbers": nums, "required": [],
                "missing": [], "reason": "文案无量化承诺或原文为空，无需限定比对"}
    required: set[str] = set()
    # 只用与文案数字相同的原文片段做限定比对，避免整页其它条款误伤
    for m in re.finditer(r"\d+(?:\.\d+)?", src):
        if m.group(0) not in claim_digits:
            continue
        window = src[max(0, m.start() - 120): min(len(src), m.end() + 160)]
        required |= {k for k in qualifier_hits(window) if k in HARD_QUALIFIERS}
    present = set(qualifier_hits(claim))
    missing = sorted(required - present)
    return {"ok": not missing, "checked": True, "numbers": nums,
            "required": sorted(required), "missing": missing,
            "reason": ("缺少原文限定：" + "、".join(missing)) if missing else ""}


def audit_copy_fields(fields: dict, analysis: dict) -> dict:
    """每次文案生成 / 编辑之后都执行；与字数、是否压缩无关。"""
    a = analysis if isinstance(analysis, dict) else {}
    snap = EvidenceSnapshot.from_analysis(a)
    src = snap.source_text()
    if not snap.available:
        return {
            "status": "legacy_unverified", "rules_version": CLAIM_RULES_VERSION,
            "snapshot": snap.to_dict(), "checked": 0, "violations": [],
            "note": "本次分析没有可定位的证据快照（旧历史 / 抓取失败），"
                    "结论不得标为已通过新证据审核",
        }
    chain_audit = validate_evidence_chain(a.get("evidence_chain"), snap)
    violations: list[dict] = []
    checked = 0
    for key, value in (fields or {}).items():
        values = value if isinstance(value, list) else [value]
        for i, item in enumerate(values):
            text = str(item or "").strip()
            if not text:
                continue
            checked += 1
            q = check_claim_qualifiers(src, text)
            if not q["ok"]:
                violations.append({"field": key, "index": i if isinstance(value, list) else None,
                                   "text": text[:160], "type": "missing_qualifier",
                                   "missing": q["missing"], "reason": q["reason"]})
    for bad in chain_audit["items"]:
        if not bad["ok"]:
            violations.append({"field": "evidence_chain", "index": None,
                               "text": bad["claim"][:160], "type": "invalid_evidence_ref",
                               "invalid_ids": bad["invalid_ids"], "reason": bad["reason"]})
    return {
        "status": "needs_revision" if violations else "ok",
        "rules_version": CLAIM_RULES_VERSION,
        "snapshot": snap.to_dict(),
        "checked": checked,
        "chain": chain_audit,
        "violations": violations,
        "note": "已定位原文 ≠ 商业真实性已审核；量化承诺不得扩大上限、计费周期、"
                "测试条件与适用范围（文档 N01 / A06 / A07）",
    }


def claim_contract(snapshot: EvidenceSnapshot) -> str:
    """写进文案模型提示词的证据契约（唯一 [E###] 命名空间 + 限定保护）。"""
    ids = ", ".join(sorted(snapshot.valid_ids)[:24]) or "（本次无可用证据编号）"
    return (
        "【证据与承诺契约 · 强制】\n"
        f"1. 本次证据快照 {snapshot.snapshot_id}，唯一可引用编号为 {ids}；"
        "引用任何其它编号（含不存在的 E###、EV_S###）都会被程序拒绝。\n"
        "2. 每条含数字、价格、效果、试用、退货、订阅或兼容性的承诺，必须能由所引用编号的"
        "原文片段直接支持；只能写进 facts 的内容不得写成 assumptions。\n"
        "3. 原文中的「最多 / up to / 上限 / 至少」「计费周期与续费」「护理模式 / 实验室 / "
        "测试条件 / 结果可能不同」「指定地区 / 型号 / 套餐」「需另购 / 仅适用于」等限定"
        "必须原样保留，不得在短句里扩大为无条件承诺。\n"
        "4. 证据状态只表示『可定位原文』，不代表价格真实性、效果或合规已被审核；"
        "无证据时写进 gaps，不要从 URL、域名或行业常识推断。\n"
    )
