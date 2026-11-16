"""V4.82：把 D0（N01 / A06 / A07）的证据与限定保护接进**视频**链路。

V4.44 已经为广告文案与图片建立了 `[E###]` 单一证据命名空间、限定词保护和生成后审计，
但 V4.67 新增的创意工作台视频分镜走的是另一条路：分镜模型只收到“不要编造事实”的
口头约束，兜底模板里甚至直接写了 `★★★★★ 4.8 · 100K+ users`，出片提示词也只拼了
`sellingPoints`。结果是图片链路拦住的夸大承诺，视频链路可以原样送进厂商出片。

本模块只做纯函数，不调用模型、不碰数据库：

- `video_evidence_context()`：把事实 / 证据映射 / 限定契约写进分镜与出片提示词；
- `audit_video_plan()`：审计分镜里所有会进入画面的文案（含兜底模板），
  既检查限定丢失，也检查**原文根本没有的数字**；
- `repair_video_plan()`：发现违规时做一次保守修复（删掉无证据的量化表达），
  修不掉就标记 `generation_blocked`，绝不把问题留给厂商和最终用户。

边界：`locatable_not_reviewed` 仍只表示“能在原文定位”，不是商业真实性审核通过。
"""
from __future__ import annotations

import copy
import re

from claims import (EvidenceSnapshot, audit_copy_fields, check_claim_qualifiers,
                    claim_contract, numeric_tokens)

# 镜头时间码、比例与时长不是广告承诺，审计文案前先剔除，避免把 0-3s / 1080x1920
# 误判成"页面没有的数字"。
_TIME_RE = re.compile(r"\[?\d+(?:\.\d+)?\s*[-–—~至到]\s*\d+(?:\.\d+)?\s*s(?:ec(?:onds)?)?\]?", re.I)
_DUR_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:s|sec|seconds?|秒)\b", re.I)
_DIM_RE = re.compile(r"(?<!\d)\d{3,4}\s*[x×]\s*\d{3,4}(?!\d)", re.I)

_FALLBACK = {
    "hook": "看看它能解决什么",
    "cta": "了解更多",
    "text": "真实使用场景",
    "vo": "看看实际效果",
    "visual": "产品真实使用场景，动作自然连续，不出现第二个商品或虚构标识",
}


def _unwrap(analysis: dict) -> dict:
    if not isinstance(analysis, dict):
        return {}
    inner = analysis.get("analysis")
    return inner if isinstance(inner, dict) else analysis


def _clean_claim_text(text: str) -> str:
    s = str(text or "")
    for rx in (_TIME_RE, _DUR_RE, _DIM_RE):
        s = rx.sub(" ", s)
    return s


def video_evidence_context(analysis: dict, *, limit: int = 1400) -> str:
    """视频分镜 / 出片提示词里的证据契约。没有快照时给出禁止量化承诺的硬约束。"""
    a = _unwrap(analysis)
    snap = EvidenceSnapshot.from_analysis(a)
    if not snap.available:
        return ("【证据状态】本次无可定位原文快照。分镜与字幕禁止出现数字、价格、效果、"
                "试用、订阅或兼容性承诺；只描述页面已明示的中性使用场景。")
    bits = [claim_contract(snap)]
    facts = [str(x).strip()[:160] for x in (a.get("facts") or a.get("advantages")
                                            or a.get("sellingPoints") or [])
             if str(x or "").strip()][:8]
    if facts:
        bits.append("【页面已确认事实（只能从中挑选用语，不得加数字）】" + "；".join(facts))
    chain = []
    for row in (a.get("evidence_chain") or [])[:10]:
        if not isinstance(row, dict):
            continue
        claim = str(row.get("claim") or "").strip()[:120]
        ids = "、".join(str(x) for x in (row.get("evidence_ids") or []) if x)
        if claim and not row.get("rejected"):
            chain.append(f"- {claim}｜{ids or '（无引用）'}")
    if chain:
        bits.append("【事实 → 证据映射】\n" + "\n".join(chain))
    return "\n".join(bits)[:limit]


def _plan_fields(plan: dict) -> dict[str, str]:
    """抽出所有会进入画面的文案字段；key 用 `shots.#.<field>` 便于原路回写。"""
    p = plan if isinstance(plan, dict) else {}
    out: dict[str, str] = {}
    for key in ("hook", "cta"):
        if str(p.get(key) or "").strip():
            out[key] = str(p[key])
    for i, shot in enumerate(p.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        for key in ("visual", "text", "vo"):
            if str(shot.get(key) or "").strip():
                out[f"shots.{i}.{key}"] = str(shot[key])
    return out


def audit_video_plan(plan: dict, analysis: dict) -> dict:
    """分镜级承诺审计：原文定位 + 限定保留 + 数字必须有原文出处。"""
    a = _unwrap(analysis)
    fields = _plan_fields(plan)
    base = audit_copy_fields(fields, a)
    snap = EvidenceSnapshot.from_analysis(a)
    src_nums = set(numeric_tokens(snap.source_text()))
    violations = list(base.get("violations") or [])

    for key, text in fields.items():
        clean = _clean_claim_text(text)
        # 无快照时任何数字都无出处；有快照时只放行能在原文定位的数字
        unknown = [n for n in numeric_tokens(clean) if n not in src_nums]
        if unknown:
            violations.append({
                "field": key, "text": clean[:160], "type": "unsupported_number",
                "numbers": unknown[:6],
                "reason": "数字在本次页面原文中找不到："
                          + "、".join(unknown[:6]) + "（A06 / N01）",
            })
        q = check_claim_qualifiers(snap.source_text(), clean)
        if not q["ok"] and not any(
                v.get("field") == key and v.get("type") == "missing_qualifier"
                for v in violations):
            violations.append({
                "field": key, "text": clean[:160], "type": "missing_qualifier",
                "missing": q["missing"], "reason": q["reason"],
            })

    return {
        "status": "needs_revision" if violations else (base.get("status") or "ok"),
        "rules_version": base.get("rules_version", ""),
        "snapshot": snap.to_dict(),
        "checked": len(fields),
        "violations": violations,
        "note": ("分镜文案含缺少证据或限定的表述，修复前不提交厂商出片（A06 / A07 / N01）。"
                 if violations else
                 "已定位原文 ≠ 商业真实性已审核；数字与限定仍需人工抽检。"),
    }


def _safe_replacement(key: str, product: str) -> str:
    field = key.rsplit(".", 1)[-1]
    base = _FALLBACK.get(field, _FALLBACK["text"])
    return f"{product}{base}" if field == "hook" and product else base


def repair_video_plan(plan: dict, analysis: dict, product: str = "") -> tuple[dict, dict, int]:
    """保守修复一次：把违规文案换成不含数字的中性表达；修不掉就标记禁止提交。"""
    # 必须深拷贝：分镜的 shots 是嵌套 list/dict，浅拷贝修复会反过来改掉调用方的原始 plan，
    # 导致"修复前"的用例在后续断言里已经变成修复后的内容（回归脚本曾因此误判）。
    p = copy.deepcopy(plan or {})
    audit = audit_video_plan(p, analysis)
    violations = [v for v in audit["violations"] if v.get("field") in _plan_fields(p)]
    done = 0
    for v in violations:
        key = str(v.get("field") or "")
        bits = key.split(".")
        try:
            if len(bits) == 1:
                p[bits[0]] = _safe_replacement(key, product)
            elif len(bits) == 3 and bits[0] == "shots" and bits[2] in ("visual", "text", "vo"):
                shots = p.get("shots") or []
                i = int(bits[1])
                if 0 <= i < len(shots) and isinstance(shots[i], dict):
                    if bits[2] == "visual":
                        # 画面描述尽量保留其它句子，只删掉带违规数字的那句
                        kept = [s for s in re.split(r"[；;。]", str(shots[i].get("visual") or ""))
                                if s.strip() and not numeric_tokens(_clean_claim_text(s))]
                        shots[i]["visual"] = "；".join(kept)[:240] or _FALLBACK["visual"]
                    else:
                        shots[i][bits[2]] = _safe_replacement(key, product)
            else:
                continue
        except (ValueError, TypeError, IndexError):
            continue
        done += 1
    final = audit_video_plan(p, analysis)
    p["claim_audit"] = final
    p["claim_repair_count"] = done
    p["generation_blocked"] = final["status"] == "needs_revision"
    return p, final, done


def video_asset_gate(plan: dict, reference_image: str = "") -> dict:
    """N03 / A08：没有可信商品主体时诚实标草案，不把概念片包装成可投放商品广告。"""
    mode = str((plan or {}).get("mode") or "")
    has_ref = bool(str(reference_image or "").strip())
    if mode == "image_to_video" and not has_ref:
        return {
            "status": "asset_missing", "delivery_grade": "draft", "deliverable": False,
            "note": "分镜选择了图生视频但没有参考图；请上传官方商品图 / 真实界面后再出片。",
        }
    if has_ref:
        return {
            "status": "reference_provided", "delivery_grade": "draft",
            "deliverable": False,
            "note": "已附参考图，但未核验是否为官方 SKU / 授权素材；产出按草案处理。",
        }
    return {
        "status": "no_product_asset", "delivery_grade": "draft", "deliverable": False,
        "note": ("纯文生视频无法保证商品外观 / 真实 UI 一致，仅作概念草案；"
                 "如需可投放商品广告，请补充官方商品图或真实界面截图后改用图生视频。"),
    }
