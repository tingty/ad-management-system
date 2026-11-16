#!/usr/bin/env python3
"""V4.82 验收：文档 D0 / N01 / A06 / A07 / N03 在**视频链路**成立（零费用、模拟）。

用法：python3 scripts/check_video_claims.py
覆盖：
1. 证据契约进分镜 / 出片提示词；
2. 原文没有的数字（评分、用户数）被拦截并保守修复；
3. 原文有数字但丢掉限定（up to / 护理模式 / 测试条件）被拦截；
4. 镜头时间码不误判为广告承诺；
5. 图生视频缺参考图直接拦截；
6. 任务入队前拦截，不产生供应商任务号 / 费用。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp(prefix="v482_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(TMP, 'claims.db')}"

from database import Base, engine, SessionLocal  # noqa: E402
from models import User  # noqa: E402
from evidence import build_evidence_pack  # noqa: E402
from video_claims import (audit_video_plan, repair_video_plan,
                          video_evidence_context, video_asset_gate)  # noqa: E402
import routers  # noqa: E402
from schemas import CWVideoGenerateRequest  # noqa: E402

RESULTS: list[dict] = []
SRC = ("Battery degradation reduced by up to 20% in Battery Care mode under "
       "laboratory conditions. Results may vary.")


def record(name: str, ok: bool, detail: str):
    RESULTS.append({"case": name, "ok": bool(ok), "detail": detail})
    print(("  ✅ " if ok else "  ❌ ") + f"{name} — {detail}")


def analysis_with_evidence() -> dict:
    pack = build_evidence_pack({"final_url": "https://shop.example.com/p",
                                "fetch_quality": "ok", "html": ""}, SRC)
    return {
        "product": "床头充电站", "title": "床头充电站",
        "facts": ["电池老化最多降低 20%（护理模式 / 实验室条件）"],
        "evidence_index": pack["evidence"],
        "evidence_snapshot_id": pack["evidence_snapshot_id"],
        "evidence_chain": [],
    }


def plan_with(*, text: str, visual: str = "产品真实使用场景", cta: str = "了解更多",
              mode: str = "text_to_video") -> dict:
    return {
        "mode": mode, "duration_sec": 15, "aspect": "9:16", "hook": "认识这款产品",
        "cta": cta,
        "shots": [{"idx": 1, "t": "0-3s", "shot": "text_to_video",
                   "visual": visual, "text": text, "vo": text}],
    }


def main():
    a = analysis_with_evidence()

    print("[1] 证据契约进入分镜 / 出片提示词")
    ctx = video_evidence_context(a)
    record("A01 契约含快照与唯一编号", "evs_" in ctx and "E001" in ctx,
           ctx[:110].replace("\n", " / "))
    record("A01 契约含限定规则", "最多" in ctx and "测试条件" in ctx,
           "已注入最多/测试条件约束")
    no_ctx = video_evidence_context({"product": "X"})
    record("A01 无快照禁止量化承诺", "禁止出现数字" in no_ctx, no_ctx[:70])

    print("\n[2] 分镜文案审计（A06 / A07）")
    bad = plan_with(text="★★★★★ 4.8 · 100K+ users")
    audit = audit_video_plan(bad, a)
    nums = [v for v in audit["violations"] if v["type"] == "unsupported_number"]
    record("A06 虚构评分 / 用户数被拦截", audit["status"] == "needs_revision" and bool(nums),
           f"violations={len(audit['violations'])} unsupported={len(nums)}")
    loss = plan_with(text="电池老化降低20%")
    a2 = audit_video_plan(loss, a)
    quals = [v for v in a2["violations"] if v["type"] == "missing_qualifier"]
    record("A07 短句丢限定被拦截", a2["status"] == "needs_revision" and bool(quals),
           str(quals[0].get("missing") if quals else "无 violation"))
    timed = plan_with(text="真实使用场景", visual="0-3s 钩子；3-8s 功能演示")
    record("A07 时间码不误判为承诺", audit_video_plan(timed, a)["status"] == "ok",
           f"status={audit_video_plan(timed, a)['status']}")

    print("\n[3] 保守修复与提交拦截")
    fixed, final, removed = repair_video_plan(bad, a, "床头充电站")
    record("A06 修复后不再含无出处数字", final["status"] == "ok" and removed > 0
           and "4.8" not in str(fixed) and "100K" not in str(fixed),
           f"removed={removed} status={final['status']}")
    fixed2, final2, _ = repair_video_plan(loss, a, "床头充电站")
    record("A07 修复后不放大承诺", final2["status"] == "ok",
           f"text={fixed2['shots'][0]['text']}")
    src = open(os.path.join(ROOT, "backend", "routers.py"), encoding="utf-8").read()
    record("N01 兜底模板无虚构评分", "100K+ users" not in src,
           "旧模板虚构数字已删除")

    print("\n[4] 商品素材门（N03 / A08）")
    g1 = video_asset_gate(plan_with(text="真实场景"), "")
    record("N03 纯文生视频标草案", g1["status"] == "no_product_asset"
           and g1["delivery_grade"] == "draft" and not g1["deliverable"], g1["status"])
    g2 = video_asset_gate(plan_with(text="真实场景", mode="image_to_video"), "")
    record("N03 图生视频缺图拦截", g2["status"] == "asset_missing", g2["note"][:50])
    g3 = video_asset_gate(plan_with(text="真实场景", mode="image_to_video"), "/files/a.png")
    record("N03 有参考图仍按草案", g3["status"] == "reference_provided"
           and g3["delivery_grade"] == "draft", g3["status"])

    print("\n[5] 提交入口拦截（不产生供应商费用）")
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user = db.query(User).first()
    if not user:
        user = User(username="qa", email="qa@v482.local", display_name="QA",
                    role="admin", password_hash="x", salt="x")
        db.add(user); db.commit(); db.refresh(user)

    def req_with(plan, ref=""):
        return CWVideoGenerateRequest(
            analysis=a, platform="TikTok", plan=plan, reference_image=ref,
            options={"duration": 15, "aspect": "9:16"})

    built_bad = routers._cw_video_request_build(req_with(bad), db)
    record("A06 构建阶段即判违规", built_bad["claim_audit"]["status"] == "needs_revision",
           f"status={built_bad['claim_audit']['status']}")
    record("A01 出片 prompt 带证据契约", "唯一可引用编号" in built_bad["prompt"],
           "prompt 含证据快照约束")
    try:
        asyncio.run(routers.api_cw_video_create_job(
            req_with(bad), db=db, user=user, idempotency_key="v482-bad",
            draft_id="", batch_id=""))
        record("A06 违规分镜不入队", False, "未拦截")
    except Exception as e:
        record("A06 违规分镜不入队", getattr(e, "status_code", 0) == 422,
               f"{type(e).__name__}: {str(e)[:80]}")
    try:
        asyncio.run(routers.api_cw_video_create_job(
            req_with(fixed2, "/files/a.png"), db=db, user=user,
            idempotency_key="v482-ok", draft_id="", batch_id=""))
        record("A06 修复后可入队", True, "已创建视频任务（本地库，无供应商调用）")
    except Exception as e:
        record("A06 修复后可入队", False, f"{type(e).__name__}: {e}")
    db.close()

    ok = sum(1 for x in RESULTS if x["ok"])
    print(f"\n结果：{ok}/{len(RESULTS)} 通过")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
