"""V4.46 / D4–D6：媒体全覆盖计划、PromptBundle、多阶段持久编排与 A09–A20 回归。

所有后端断言均为纯函数 / 临时数据库，不调用模型、不连生产库、不发起真实付费调用。
四种状态分开记录：本文件只提供「代码已实现 + 模拟测试通过」；
真实模型验证 / 真实投放验证 / 人工视觉核验均为「未验证」，不得互相替代。

用例覆盖（文档 A09–A20）：
  A09  按资产角色编译提示词，软件真实 UI 不被全局 no UI 删除、不每张烘焙 CTA；
  A10  未知平台在创建计划时即拒绝；
  A11  覆盖计划只按已选平台计算（不静默扩展范围）；
  A12  超出单批 24 任务 / 40MP 自动拆子批，不截断版位；
  A13  计划版本失效（产品事实 / 目标地区变化）→ 下游拒绝（409）；
  A14  预算不足 / 成本上界未覆盖时不隐瞒缺口，确认被拒；
  A15  逐图质检：供应商失败纯背景模板 → draft / needs_revision，不计合格商品图；
  A16  同幂等键不同内容 → 409，不串任务；
  A17  刷新 / 关闭后按 plan_id 恢复完整状态；
  A18  重启后按子任务状态对账，不自动重发 unknown_outcome；
  A19  取消后停止派发新子任务，已结束计划不可再确认；
  A20  打包 manifest：media / concept / role / 缺失报告齐全且不谎报完成。
"""
import asyncio
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from database import SessionLocal
from migrations import ensure_schema
from models import GenerationJob, CreationPlan
from sqlalchemy.orm.attributes import flag_modified

from creation_plan_service import (
    create_plan, set_coverage, confirm_plan, attach_job, finalize,
    validate_plan_reference, qa_generation_result, build_manifest,
    plan_to_dict, next_stage, STAGES, TERMINAL,
)
from media_coverage import build_coverage_plan, merge_manifest
from prompt_compiler import compile_prompt_bundle, ASSET_ROLE_RENDER
from media_platforms import validate_platform, MediaRuleError, SPEC_VERIFIED_ON
import job_service as js
import routers

USER = SimpleNamespace(id=7, display_name="测试账号", username="tester")
OTHER = SimpleNamespace(id=8, display_name="另一账号", username="other")

ANALYSIS = {
    "url": "https://www.anker.com/charger",
    "brand": "Anker", "brand_status": "confirmed",
    "type": "ecommerce", "industry": "consumer electronics",
    "audience": "多设备通勤用户",
    "facts": ["Qi2 certified foldable charging station",
              "magnetic stand with soft night light"],
    "evidence_index": [
        {"evidence_id": "E001", "quote": "Qi2 certified foldable charging station",
         "char_start": 0, "char_end": 40},
        {"evidence_id": "E002", "quote": "magnetic stand with soft night light",
         "char_start": 41, "char_end": 80},
    ],
    "evidence_snapshot_id": "SNAP_abc123",
}


def fresh_db():
    ensure_schema()
    db = SessionLocal()
    db.query(GenerationJob).delete()
    db.query(CreationPlan).delete()
    db.commit()
    return db


def rec_for(analysis, plats, defaults=None):
    from creation_planner import build_recommendation
    return build_recommendation(analysis, plats, workspace_defaults=defaults or {})


class TestD4PromptBundle(unittest.TestCase):
    """A09：按资产角色编译 PromptBundle；软件真实 UI 不被全局 no UI 删除，不每张烘焙 CTA。"""

    def test_01_app_portrait_preserves_real_ui_no_cta(self):
        b = compile_prompt_bundle(
            {"promise": "快充", "claim_ids": ["E001"], "audience": "通勤族",
             "situation": "床头", "purchase_reason": "便利", "distinct_reason": "磁吸",
             "must_preserve_qualifiers": ["up to"], "forbidden_inferences": [],
             "concept_id": "C01"},
            {"subject": "Anker 充电站", "scene": "床头", "composition": "右主体左标题",
             "size": "1080x1920", "version": "pv1", "short_copy": "快充"},
            asset_role="app_portrait")
        # 软件真实 UI：不在画面上叠加文案，也不烘焙 CTA 按钮，但保留 Logo 角标
        self.assertFalse(b["render_spec"]["bake_text"], "真实 UI 上不得叠图内文案")
        self.assertFalse(b["render_spec"]["bake_cta"], "软件真实界面不烘焙 CTA 按钮")
        self.assertTrue(b["render_spec"]["bake_logo"], "品牌角标仍保留")
        # 不得出现「删除 / 移除界面」之类的全局 no UI 指令
        self.assertNotIn("删除界面", b["task"])
        self.assertNotIn("移除界面", b["task"])
        self.assertNotIn("remove the ui", b["task"].lower())
        self.assertNotIn("remove ui", b["system"].lower())

    def test_02_feed_image_bakes_cta_not_global_no_ui(self):
        b = compile_prompt_bundle(
            {"promise": "快充", "claim_ids": ["E001"], "audience": "通勤族",
             "situation": "床头", "purchase_reason": "便利", "distinct_reason": "磁吸",
             "must_preserve_qualifiers": [], "forbidden_inferences": [], "concept_id": "C01"},
            {"subject": "Anker 充电站", "scene": "床头", "composition": "右主体左标题",
             "size": "1080x1080", "version": "pv1", "short_copy": "快充"},
            asset_role="feed_image")
        self.assertTrue(b["render_spec"]["bake_cta"], "信息流主视觉允许 CTA，证明不是全局 no UI")
        self.assertTrue(b["render_spec"]["bake_text"])

    def test_03_role_render_table_is_not_uniform(self):
        # 角色渲染表必须显式区分 bake_cta / bake_text，而非统一 False（即非全局 no UI 一刀切）
        cta = {k: v["bake_cta"] for k, v in ASSET_ROLE_RENDER.items()}
        text_flags = {k: v["bake_text"] for k, v in ASSET_ROLE_RENDER.items()}
        self.assertNotEqual(cta, {k: False for k in cta}, "不得全部禁止 CTA")
        self.assertNotEqual(text_flags, {k: False for k in text_flags}, "不得全部禁止图内文案")
        # 软件真实界面（app_portrait）必须保留 UI：不叠文案、不烘焙 CTA
        self.assertFalse(ASSET_ROLE_RENDER["app_portrait"]["bake_text"])
        self.assertFalse(ASSET_ROLE_RENDER["app_portrait"]["bake_cta"])

    def test_04_bundle_is_traceable_and_hashable(self):
        b = compile_prompt_bundle(
            {"promise": "快充", "claim_ids": ["E001"], "audience": "通勤族",
             "situation": "床头", "purchase_reason": "便利", "distinct_reason": "磁吸",
             "must_preserve_qualifiers": [], "forbidden_inferences": [], "concept_id": "C01"},
            {"subject": "Anker 充电站", "scene": "床头", "composition": "右主体左标题",
             "size": "1080x1920", "version": "pv1", "short_copy": "快充"},
            asset_role="app_portrait")
        self.assertIn("bundle_hash", b["hashes"])
        self.assertEqual(len(b["hashes"]["full"]), 64)
        self.assertEqual(b["traceability"]["concept_id"], "C01")


class TestD4CoveragePlan(unittest.TestCase):
    """A11 / A12 / D4：只按已选范围、超限拆批不截断、成本上界诚实标注。"""

    def test_05_coverage_only_selected_platforms(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook", "TikTok", "Moloco"], {}, USER)
        full = plan.coverage_json["coverage"]["required_tasks"]
        plan2 = set_coverage(db, plan.plan_id, ["Facebook"], USER)
        cov = plan2.coverage_json["coverage"]
        self.assertEqual(cov["platforms"], ["Facebook"])
        self.assertLess(cov["required_tasks"], full, "只选 Facebook 应少于全选")
        self.assertTrue(all(t["platform"] == "Facebook"
                            for t in plan2.coverage_json["tasks"]))
        db.close()

    def test_06_batch_split_does_not_truncate(self):
        rec = rec_for(ANALYSIS, ["Facebook", "TikTok", "Moloco", "Google", "Unity", "AppLovin"],
                      {"concept_count": 3})
        cov = build_coverage_plan(rec, ["Facebook", "TikTok", "Moloco", "Google", "Unity", "AppLovin"],
                                  rec.get("structured_concepts"), rec.get("workspace_defaults"))
        rep = cov["coverage"]
        self.assertGreater(rep["required_tasks"], 24, "应超过单批上限")
        self.assertGreaterEqual(rep["sub_batch_count"], 2, "应拆为多个子批")
        self.assertFalse(rep["truncated"], "拆批不得截断版位")
        total_in_batches = sum(len(b) for b in cov["sub_batches"])
        self.assertEqual(total_in_batches, rep["required_tasks"], "父计划保留全部任务")
        # 每个概念都完整适配每个版位（不是轮换伪装全覆盖）：
        # (platform, placement, size, concept) 组合必须一一对应、无重复、无坍缩
        keys = {(t["platform"], t["placement_id"], t["size"], t["concept_index"])
                for t in cov["tasks"]}
        self.assertEqual(len(keys), rep["required_tasks"], "不得用轮换伪装每概念全覆盖")
        self.assertTrue(all(t["asset_role"] for t in cov["tasks"]), "每个任务都须有资产角色")

    def test_07_cost_upper_is_estimate_not_real_billing(self):
        rec = rec_for(ANALYSIS, ["Facebook"], {"concept_count": 1})
        cov = build_coverage_plan(rec, ["Facebook"], rec.get("structured_concepts"),
                                  rec.get("workspace_defaults"))
        est = cov["cost_estimate"]
        self.assertTrue(est["is_estimate"])
        self.assertEqual(est["currency"], "USD")
        self.assertGreater(est["cost_upper_usd"], 0)
        # 内部目录 SPEC_VERIFIED_ON 为空：诚实标注未知任务
        self.assertFalse(cov["coverage"]["spec_verified"])
        self.assertGreater(cov["report"]["unknown_spec"], 0)
        self.assertIn("未官方核验", cov["coverage"]["spec_verified_on"])

    def test_08_over_budget_is_flagged_not_hidden(self):
        rec = rec_for(ANALYSIS, ["Facebook", "TikTok", "Moloco", "Google", "Unity", "AppLovin"],
                      {"concept_count": 3, "budget_cap": 1.0})
        cov = build_coverage_plan(rec, ["Facebook", "TikTok", "Moloco", "Google", "Unity", "AppLovin"],
                                  rec.get("structured_concepts"), rec.get("workspace_defaults"))
        self.assertTrue(cov["cost_estimate"]["over_budget"], "预算低于成本上界须显式标出")
        self.assertIn("不会静默生成", cov["cost_estimate"]["note"])


class TestD5PlanReference(unittest.TestCase):
    """A10 / A13 / A14：未知平台拒绝、版本失效 409、预算缺口不隐瞒。"""

    def test_09_unknown_platform_rejected_at_create(self):
        db = fresh_db()
        with self.assertRaises(MediaRuleError):
            create_plan(db, ANALYSIS, ["NotAPlatform"], {}, USER)
        rec = rec_for(ANALYSIS, ["NotAPlatform"])
        self.assertEqual(rec["status"], "needs_input")
        self.assertTrue(any("未知媒体平台" in x for x in rec["blocking_reasons"]))
        db.close()

    def test_10_version_mismatch_blocks_downstream_409(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        with self.assertRaises(ValueError) as ctx:
            validate_plan_reference(db, plan.plan_id, "pv_wrong_version", "SNAP_abc123")
        self.assertEqual(str(ctx.exception), "plan_version_mismatch")
        db.close()

    def test_11_fact_rewrite_blocked_422(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        with self.assertRaises(ValueError) as ctx:
            validate_plan_reference(db, plan.plan_id, plan.plan_version, "SNAP_other")
        self.assertEqual(str(ctx.exception), "fact_rewrite_blocked")
        db.close()

    def test_12_unconfirmed_plan_rejected(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        with self.assertRaises(ValueError) as ctx:
            validate_plan_reference(db, plan.plan_id, plan.plan_version, "SNAP_abc123")
        self.assertEqual(str(ctx.exception), "plan_not_confirmed")
        db.close()

    def test_13_confirm_rejects_fee_below_cost_upper(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook", "TikTok", "Moloco"], {"budget_cap": 3.0}, USER)
        cost_upper = plan.coverage_json["cost_estimate"]["cost_upper_usd"]
        self.assertGreater(cost_upper, 0)
        with self.assertRaises(ValueError) as ctx:
            confirm_plan(db, plan.plan_id, fee_authorized_usd=0.1, user=USER)
        self.assertIn("成本上界", str(ctx.exception))
        # 授权额度达标后仍可确认
        cp = confirm_plan(db, plan.plan_id, fee_authorized_usd=cost_upper + 1.0, user=USER)
        self.assertTrue(cp.approval_token)
        db.close()

    def test_14_zero_fee_rejected(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        with self.assertRaises(ValueError) as ctx:
            confirm_plan(db, plan.plan_id, fee_authorized_usd=0, user=USER)
        self.assertIn("未授权费用上限", str(ctx.exception))
        db.close()


class TestD5Orchestration(unittest.TestCase):
    """A17 / 全链路：create → set_coverage → confirm → attach_job → finalize。"""

    def test_15_full_lifecycle_persists_recoverable_state(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook", "TikTok"], {}, USER)
        self.assertIn(plan.stage, ("recommendation_ready", "needs_input"))
        plan = set_coverage(db, plan.plan_id, ["Facebook"], USER)
        self.assertEqual(plan.coverage_json["coverage"]["platforms"], ["Facebook"])
        cp = confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        self.assertEqual(cp.stage, "platform_confirmed")
        self.assertTrue(cp.approval_token)
        aj = attach_job(db, plan.plan_id, "job_A1")
        self.assertEqual(aj.stage, "generating")
        self.assertIn("job_A1", aj.job_ids)

        # A17：模拟刷新 / 重启后，从新会话按 plan_id 取回完整状态
        fresh = SessionLocal()
        restored = get_plan_restored(fresh, plan.plan_id)
        self.assertEqual(restored["stage"], "generating")
        self.assertIn("job_A1", restored["job_ids"])
        self.assertTrue(restored["approval_token"])
        self.assertIn("coverage", restored)
        fresh.close()

        fp = finalize(db, plan.plan_id, [{
            "images": [{"file": "a.png", "status": "ok"}],
            "task_results": [{"task_index": 0, "status": "ok"},
                             {"task_index": 1, "status": "failed",
                              "reason": "supplier failed: pure gradient"}],
        }])
        self.assertIn(fp.status, ("partial_success", "failed"))
        self.assertIn("missing_report", fp.manifest_json)
        db.close()


def get_plan_restored(db, plan_id):
    from creation_plan_service import get_plan, plan_to_dict
    return plan_to_dict(get_plan(db, plan_id))


class TestD5QualityGate(unittest.TestCase):
    """A15：逐图质检，供应商失败纯背景模板 → draft / needs_revision，不计合格商品图。"""

    def test_16_failed_supplier_result_is_not_deliverable(self):
        plan_doc = {"recommendation": {"delivery_grade": "draft"},
                    "coverage": {"report": {"required": 3}}, "delivery_grade": "draft"}
        result = {"images": [{"file": "a.png", "status": "ok"}],
                  "task_results": [{"task_index": 0, "status": "ok"},
                                   {"task_index": 1, "status": "failed",
                                    "reason": "纯渐变模板"}]}
        qa = qa_generation_result(result, plan_doc)
        self.assertEqual(qa["failed"], 1)
        self.assertFalse(qa["deliverable"], "供应商失败纯背景不得计为可交付")
        self.assertEqual(qa["delivery_grade"], "draft")
        self.assertTrue(any(f["status"] == "needs_revision" for f in qa["findings"]))

    def test_17_all_ok_but_unverified_spec_still_draft(self):
        # SPEC_VERIFIED_ON 为空：即便图都生成，也只能草案
        plan_doc = {"recommendation": {"delivery_grade": "standard"},
                    "coverage": {"report": {"required": 2}}, "delivery_grade": "standard"}
        result = {"images": [{"file": "a.png", "status": "ok"}, {"file": "b.png", "status": "ok"}],
                  "task_results": [{"task_index": 0, "status": "ok"},
                                   {"task_index": 1, "status": "ok"}]}
        qa = qa_generation_result(result, plan_doc)
        self.assertEqual(qa["passed"], 2)
        self.assertFalse(qa["deliverable"], "规格未官方核验，不得显示完整可交付")
        self.assertEqual(qa["delivery_grade"], "draft")

    def test_18_manifest_aggregates_qa(self):
        plan_doc = {"recommendation": {"delivery_grade": "draft"},
                    "coverage": {"report": {"required": 4},
                                 "tasks": [{"task_index": i} for i in range(4)]},
                    "delivery_grade": "draft"}
        job_results = [{
            "images": [{"file": "a.png", "status": "ok"}, {"file": "b.png", "status": "ok"}],
            "task_results": [{"task_index": 0, "status": "ok"},
                             {"task_index": 1, "status": "failed", "reason": "x"}],
        }]
        m = build_manifest(plan_doc, job_results)
        self.assertEqual(m["item_count"], 2)
        self.assertEqual(len(m["missing_report"]), 1)
        self.assertIn("qa", m)


class TestD5Idempotency(unittest.TestCase):
    """A16：同幂等键不同内容 → 409，不串任务。"""

    def test_19_same_key_diff_payload_conflicts(self):
        db = fresh_db()
        js.create_job(db, _payload(1), USER, idempotency_key="k_d5",
                      kind="auto_creation", plan_id="cp_x", plan_version="pv1")
        with self.assertRaises(js.IdempotencyConflict) as ctx:
            js.create_job(db, _payload(2), USER, idempotency_key="k_d5",
                          kind="auto_creation", plan_id="cp_x", plan_version="pv1")
        self.assertNotEqual(ctx.exception.expected, ctx.exception.actual)
        db.close()

    def test_20_same_key_same_payload_returns_original(self):
        db = fresh_db()
        a, c1 = js.create_job(db, _payload(1), USER, idempotency_key="same_d5",
                               kind="auto_creation", plan_id="cp_x", plan_version="pv1")
        b, c2 = js.create_job(db, _payload(1), USER, idempotency_key="same_d5",
                               kind="auto_creation", plan_id="cp_x", plan_version="pv1")
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(a.job_id, b.job_id)

    def test_21_router_maps_idempotency_conflict_to_409(self):
        # 不直接跑 spawn：旧任务用服务层创建，路由在 create_job 内即抛 409，不会触达 spawn_job
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        js.create_job(db, _payload(1), USER,
                      idempotency_key="router_k", kind="auto_creation",
                      plan_id=plan.plan_id, plan_version=plan.plan_version)
        body = _gen_body(2, plan.plan_id, plan.plan_version, idempotency_key="router_k")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(routers.create_generation_job(body, db=db, user=USER))
        self.assertEqual(_status(ctx.exception), 409)
        db.close()

    def test_22_router_maps_version_mismatch_to_409(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        body = _gen_body(1, plan.plan_id, "pv_wrong", snapshot="SNAP_abc123")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(routers.create_generation_job(body, db=db, user=USER))
        self.assertEqual(_status(ctx.exception), 409)
        db.close()

    def test_23_router_maps_fact_rewrite_to_422(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        body = _gen_body(1, plan.plan_id, plan.plan_version, snapshot="SNAP_tampered")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(routers.create_generation_job(body, db=db, user=USER))
        self.assertEqual(_status(ctx.exception), 422)
        db.close()

    def test_24_router_maps_unconfirmed_plan_to_422(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        body = _gen_body(1, plan.plan_id, plan.plan_version, snapshot="SNAP_abc123")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(routers.create_generation_job(body, db=db, user=USER))
        self.assertEqual(_status(ctx.exception), 422)
        db.close()


class TestD5CancelRestart(unittest.TestCase):
    """A18 / A19：重启对账、取消停止派发、已结束计划不可再确认。"""

    def test_25_recover_interrupted_marks_unknown_not_canceled(self):
        db = fresh_db()
        job, _ = js.create_job(db, _payload(2, kind="auto_creation"), USER,
                               idempotency_key="rec_d5", kind="auto_creation")
        # 模拟「派发后结果未知」
        subs = [dict(x) for x in job.subtasks_json]
        subs[0]["status"] = "running"
        job.subtasks_json = subs
        flag_modified(job, "subtasks_json")
        job.status = "running"
        db.commit()
        n = js.recover_interrupted()
        self.assertGreaterEqual(n, 1)
        db.expire_all()
        row = db.query(GenerationJob).filter_by(job_id=job.job_id).first()
        self.assertEqual(row.status, "failed")
        statuses = [x["status"] for x in row.subtasks_json]
        self.assertIn("unknown_outcome", statuses)
        # 取消的任务不被 resurrect
        canceled, _ = js.create_job(db, _payload(1, kind="auto_creation"), OTHER,
                                     idempotency_key="cancel_d5", kind="auto_creation")
        canceled.status = "canceled"
        canceled.cancel_requested = True
        db.commit()
        n2 = js.recover_interrupted()
        db.expire_all()
        c = db.query(GenerationJob).filter_by(job_id=canceled.job_id).first()
        self.assertEqual(c.status, "canceled")
        db.close()

    def test_26_canceled_plan_cannot_be_reconfirmed(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        # 标记为已结束
        p = db.query(CreationPlan).filter_by(plan_id=plan.plan_id).first()
        p.stage = "canceled"
        db.commit()
        with self.assertRaises(ValueError) as ctx:
            confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        self.assertIn("已结束", str(ctx.exception))
        db.close()


class TestD6Manifest(unittest.TestCase):
    """A20：打包 manifest 含 media / concept / role / 缺失报告，不谎报完成。"""

    def test_27_manifest_lists_items_and_missing(self):
        plan = {"tasks": [{"task_index": i, "platform": "Facebook",
                           "asset_role": "feed_image", "concept_id": "C01"} for i in range(3)]}
        job_results = [{
            "images": [{"file": "a.png", "placement": "Feed", "size": "1080x1080",
                        "concept_id": "C01", "status": "ok"},
                       {"file": "b.png", "placement": "Feed", "size": "1080x1080",
                        "concept_id": "C01", "status": "ok"}],
            "task_results": [{"task_index": 0, "status": "ok"},
                             {"task_index": 1, "status": "ok"},
                             {"task_index": 2, "status": "failed",
                              "reason": "supplier failed: pure gradient"}],
        }]
        m = merge_manifest(plan, job_results)
        self.assertEqual(m["item_count"], 2)
        self.assertEqual(m["plan_required_tasks"], 3)
        self.assertEqual(len(m["missing_report"]), 1)
        self.assertFalse(m["complete"], "有失败项不得谎报 complete")
        self.assertIn("A15", m["incomplete_reason"])

    def test_28_manifest_complete_when_all_pass(self):
        plan = {"tasks": [{"task_index": i} for i in range(2)]}
        job_results = [{
            "images": [{"file": "a.png", "status": "ok"}, {"file": "b.png", "status": "ok"}],
            "task_results": [{"task_index": 0, "status": "ok"}, {"task_index": 1, "status": "ok"}],
        }]
        m = merge_manifest(plan, job_results)
        self.assertTrue(m["complete"])


class TestRouterStatusMapping(unittest.TestCase):
    """D6：灰度开关与边界错误映射。"""

    def test_29_feature_off_returns_503(self):
        db = fresh_db()
        old = routers.ENABLE_AUTO_CREATION_PLAN
        routers.ENABLE_AUTO_CREATION_PLAN = False
        try:
            with self.assertRaises(Exception) as ctx:
                routers.api_create_plan({"analysis": ANALYSIS, "platforms": ["Facebook"]},
                                        db=db, user=USER)
            self.assertEqual(_status(ctx.exception), 503)
        finally:
            routers.ENABLE_AUTO_CREATION_PLAN = old
        db.close()

    def test_30_unknown_platform_returns_422(self):
        db = fresh_db()
        with self.assertRaises(Exception) as ctx:
            routers.api_create_plan({"analysis": ANALYSIS, "platforms": ["NotAPlatform"]},
                                    db=db, user=USER)
        self.assertEqual(_status(ctx.exception), 422)
        db.close()

    def test_31_confirm_fee_below_cost_returns_422(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook", "TikTok", "Moloco"], {"budget_cap": 3.0}, USER)
        cost_upper = plan.coverage_json["cost_estimate"]["cost_upper_usd"]
        with self.assertRaises(Exception) as ctx:
            routers.api_plan_confirm(plan.plan_id, {"fee_authorized_usd": 0.1}, db=db, user=USER)
        self.assertEqual(_status(ctx.exception), 422)
        # 授权足额成功
        p = routers.api_plan_confirm(plan.plan_id, {"fee_authorized_usd": cost_upper + 1.0},
                                     db=db, user=USER)
        self.assertTrue(p["approval_token"])
        db.close()

    def test_32_get_plan_recovers_full_state(self):
        db = fresh_db()
        plan = create_plan(db, ANALYSIS, ["Facebook"], {}, USER)
        confirm_plan(db, plan.plan_id, fee_authorized_usd=10.0, user=USER)
        attach_job(db, plan.plan_id, "job_g1")
        p = routers.api_get_plan(plan.plan_id, db=db, _=USER)
        self.assertEqual(p["stage"], "generating")
        self.assertIn("job_g1", p["job_ids"])
        self.assertTrue(p["approval_token"])
        self.assertIn("coverage", p)
        db.close()


def _payload(count, plan_id=None, plan_version=None, kind="images"):
    return {
        "images_request": {
            "analysis": {"url": "https://shop.example.com/p", "language": "en",
                         "evidence_snapshot_id": "SNAP_abc123"},
            "platform": "Facebook", "lang": "en",
            "copy_fields": {"headline": "已确认标题"},
            "slots": [{"size": "1080x1080", "placement": "信息流 Feed",
                       "placement_id": "feed", "concept_index": 0} for _ in range(count)],
            "spec_version": "", "total_pixels": None,
        },
        "archive": {"history_id": None, "platform": "Facebook", "lang": "en"},
    }


def _gen_body(count, plan_id, plan_version, snapshot="SNAP_abc123", idempotency_key=None):
    body = _payload(count, plan_id, plan_version)
    body["plan_id"] = plan_id
    body["plan_version"] = plan_version
    body["images_request"]["analysis"]["evidence_snapshot_id"] = snapshot
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return body


def _status(exc):
    """从异常对象取得 HTTP 状态码（FastAPI HTTPException）。"""
    code = getattr(exc, "status_code", None)
    if code is not None:
        return code
    # 兼容某些测试框架包装
    return getattr(exc.exception, "status_code", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
