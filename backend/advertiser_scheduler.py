# -*- coding: utf-8 -*-
"""V4.134 · 广告主数据 P2 自动调度 + P1-C 历史回填。

设计依据：docs/广告主数据模块功能开发文档_20261124.html 第四章 / 9.1。
沿用现有表（ApiFetchTask / ApiFetchRun / SystemState），不新增调度框架、不改既有表：

  1. execute_run()  单窗口拉取：游标翻页 → 按 api_field_map 幂等落库 → 运行记录；
  2. backfill()     历史回填：从起始日按 ≤31 天分片，逐片调用 execute_run，
                    结束后全量重算订单净额 / is_void（P1-C 的跨批次缺口）；
  3. run_due()      按 connection.schedule_json 的频率 / 小时 / 回溯窗口调度，
                    SystemState 记录水位与锁，重启后不重复跑、失败不静默；
  4. start/stop     FastAPI startup 后台协程，与 model_health 启停对称。

安全与限流：Token 只在内存解密后放进 Authorization 头，不写库、不写日志、不入运行记录；
CJ 限制 200 次 / 5 分钟，翻页之间留间隔（测试可把间隔置 0）。
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

import advertiser_api
import advertiser_ingest
from database import SessionLocal
from models import ApiConnection, ApiFetchRun, ApiFetchTask, SystemState
from timeutil import beijing_naive_now  # V4.137：用户配置的调度小时按北京时间解释

WINDOW_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SLICE_DAYS = 31            # CJ 硬限制：单次日期跨度 ≤31 天
SLICE_STEP_DAYS = 30       # 步长 = 31 - 1 天重叠，保证加重叠后仍不超过硬限制
MAX_PAGES = 100            # 单窗口翻页上限，防止游标异常导致死循环
PAGE_DELAY_SEC = 1.6       # 200 次 / 5 分钟 ≈ 1.5 秒一次，留余量
OVERLAP_DAYS = 1           # 相邻分片重叠一天，边界数据由幂等去重吸收
LOCK_TTL_MINUTES = 15      # 抢占锁过期时间，进程异常退出后自动释放

_scheduler_task: "asyncio.Task | None" = None
_run_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# 配置与工具
# ---------------------------------------------------------------------------
def scheduler_enabled() -> bool:
    """全局开关：出问题时置 0 即停调度，已落库数据不受影响。"""
    return os.getenv("ADVERTISER_FETCH_ENABLED", "1").strip().lower() not in (
        "0", "false", "no", "off")


def auto_backfill_enabled() -> bool:
    """首次启用调度时是否自动做历史回填（默认开，与任务配置的首次回填天数一致）。"""
    return os.getenv("ADVERTISER_FETCH_AUTO_BACKFILL", "1").strip().lower() not in (
        "0", "false", "no", "off")


def page_delay() -> float:
    """独立函数便于测试置 0，不改动生产限流值。"""
    return PAGE_DELAY_SEC


def schedule_of(conn: ApiConnection) -> dict:
    """与 routers._normalize_schedule 同口径的白名单规范化（此处独立避免循环导入）。"""
    raw = conn.schedule_json if isinstance(conn.schedule_json, dict) else {}

    def _integer(key: str, default: int, lo: int, hi: int) -> int:
        try:
            n = int(raw.get(key, default))
        except (TypeError, ValueError):
            n = default
        return max(lo, min(hi, n))

    frequency = raw.get("frequency")
    return {
        "enabled": bool(raw.get("enabled", False)),
        "frequency": frequency if frequency in ("daily", "6h") else "daily",
        "hour": _integer("hour", 2, 0, 23),
        "lookback_days": _integer("lookback_days", 7, 1, 90),
        "backfill_days": _integer("backfill_days", 90, 1, 365),
    }


def _window_text(moment: datetime) -> str:
    return moment.strftime(WINDOW_FORMAT)


def _window_datetime(text: str) -> datetime:
    return datetime.strptime(text, WINDOW_FORMAT)


def _next_run(frequency: str, hour: int, now: datetime) -> datetime:
    if frequency == "6h":
        return now + timedelta(hours=6)
    nxt = now + timedelta(days=1)
    return nxt.replace(hour=hour, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# 运行记录读写
# ---------------------------------------------------------------------------
def upsert_task(db: Session, conn: ApiConnection, schedule: Optional[dict] = None) -> ApiFetchTask:
    """把连接上的任务设置同步到 api_fetch_task（一个连接一条默认定期任务）。"""
    sch = schedule or schedule_of(conn)
    task = db.query(ApiFetchTask).filter_by(connection_id=conn.id).first()
    if task is None:
        task = ApiFetchTask(connection_id=conn.id, name="定期拉取")
        db.add(task)
        db.flush()
    task.enabled = bool(sch["enabled"])
    task.frequency = sch["frequency"]
    task.hour = int(sch["hour"])
    task.lookback_days = int(sch["lookback_days"])
    task.backfill_days = int(sch["backfill_days"])
    if task.enabled and task.status == "error":
        task.status = "idle"
    if task.enabled and task.next_run_at is None:
        task.next_run_at = _next_run(task.frequency, task.hour, beijing_naive_now())
    db.flush()
    return task


def _state_value(db: Session, key: str) -> str:
    row = db.query(SystemState).filter_by(key=key).first()
    return (row.value or "") if row else ""


def _set_state(db: Session, key: str, value: str) -> None:
    row = db.query(SystemState).filter_by(key=key).first()
    if row is None:
        row = SystemState(key=key, value="")
        db.add(row)
        db.flush()
    row.value = value
    db.flush()


def _claim(conn_id: int, now: datetime) -> bool:
    """跨进程抢占：仅当锁不存在或已过期时写入新过期时间，返回是否抢到。"""
    db = SessionLocal()
    try:
        key = f"adv_fetch_lock_{conn_id}"
        if db.query(SystemState).filter_by(key=key).first() is None:
            db.add(SystemState(key=key, value=""))
            db.commit()
        lock_until = (now + timedelta(minutes=LOCK_TTL_MINUTES)).isoformat()
        n = (db.query(SystemState)
             .filter(SystemState.key == key,
                     or_(SystemState.value.is_(None), SystemState.value == "",
                         SystemState.value < now.isoformat()))
             .update({"value": lock_until}, synchronize_session=False))
        db.commit()
        return n == 1
    finally:
        db.close()


def _due(db: Session, conn: ApiConnection, sch: dict, now: datetime) -> bool:
    """按频率判断是否到期；配置的小时按北京时间解释，拉取窗口本身仍按 UTC 计算。"""
    raw = _state_value(db, f"adv_fetch_last_{conn.id}")
    if not raw:
        return True if sch["frequency"] == "6h" else now.hour >= sch["hour"]
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if sch["frequency"] == "6h":
        return (now - last) >= timedelta(hours=6)
    if last.date() == now.date():
        return False
    return now.hour >= sch["hour"]


def _has_success_run(db: Session, conn_id: int) -> bool:
    return db.query(ApiFetchRun.id).filter_by(
        connection_id=conn_id, status="success").first() is not None


# ---------------------------------------------------------------------------
# 单窗口拉取（游标翻页 + 幂等落库 + 运行记录）
# ---------------------------------------------------------------------------
async def fetch_window(db: Session, conn: ApiConnection, *, since: str, before: str,
                       run: Optional[ApiFetchRun] = None) -> dict:
    """拉一个窗口的全部 PublisherCommission 明细并落库，返回汇总统计。"""
    token = advertiser_api.decrypt_token(conn.token_enc or "")
    if not token:
        raise RuntimeError("Token 解密失败，请重新填写")
    stats = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0,
             "skipped": 0, "warnings": [], "pages": 0, "cursor": "",
             "max_commission_id": "", "payload_complete": True}
    cursor = ""
    while stats["pages"] < MAX_PAGES:
        result = await advertiser_api.test_connection(
            template_code=conn.template_code or "", endpoint=conn.endpoint or "",
            token=token, cid=conn.cid or "", since_event_date=since,
            before_event_date=before, since_commission_id=cursor, full_records=True)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "上游请求失败")[:300])
        stats["pages"] += 1
        batch = advertiser_ingest.ingest_records(
            db, records=result.get("all_records") or [],
            connection_id=conn.id, run_id=run.id if run else None)
        for key in ("fetched", "inserted", "updated", "unchanged", "skipped"):
            stats[key] += int(batch.get(key) or 0)
        stats["warnings"].extend(batch.get("warnings") or [])
        max_id = str(result.get("max_commission_id") or "")
        complete = bool(result.get("payload_complete"))
        stats["max_commission_id"] = max_id
        stats["payload_complete"] = complete
        if complete or not max_id or max_id == cursor:
            break
        cursor = max_id
        await asyncio.sleep(page_delay())
    stats["cursor"] = cursor
    return stats


async def execute_run(db: Session, conn: ApiConnection, *, mode: str,
                      since: str, before: str,
                      task_id: Optional[int] = None) -> dict:
    """执行一个窗口并写 ApiFetchRun；失败不静默，状态与错误摘要都留痕。"""
    run = ApiFetchRun(
        connection_id=conn.id, task_id=task_id, status="running", run_mode=mode,
        window_from=_window_datetime(since), window_to=_window_datetime(before),
        started_at=datetime.utcnow(), cursor_json={"mode": mode, "pages": 0})
    db.add(run)
    conn.last_sync_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    try:
        stats = await fetch_window(db, conn, since=since, before=before, run=run)
        run.status = "success"
        run.fetched_count = stats["fetched"]
        run.inserted_count = stats["inserted"]
        run.updated_count = stats["updated"]
        run.cursor_json = {
            "mode": mode, "pages": stats["pages"], "cursor": stats["cursor"],
            "max_commission_id": stats["max_commission_id"],
            "payload_complete": stats["payload_complete"],
            "warnings": stats["warnings"][:20],
        }
        result = {"run_id": run.id, "ok": True, "window_since": since,
                  "window_before": before, **stats}
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
        run.cursor_json = {"mode": mode, "pages": 0}
        result = {"run_id": run.id, "ok": False, "error": run.error,
                  "window_since": since, "window_before": before}
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()
    return result


# ---------------------------------------------------------------------------
# P1-C 历史回填
# ---------------------------------------------------------------------------
async def backfill(db: Session, conn: ApiConnection, *, days: Optional[int] = None,
                   task_id: Optional[int] = None) -> dict:
    """从起始日按 ≤31 天分片回填，最后跨批次重算取消单。重复执行幂等。"""
    sch = schedule_of(conn)
    try:
        total_days = int(days or sch["backfill_days"])
    except (TypeError, ValueError):
        total_days = 90
    total_days = max(1, min(total_days, 365))
    end = datetime.utcnow()
    start = end - timedelta(days=total_days)

    slices: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=SLICE_STEP_DAYS), end)
        piece_start = cursor if not slices else max(start, cursor - timedelta(days=OVERLAP_DAYS))
        slices.append((piece_start, nxt))
        cursor = nxt

    summary = {"connection_id": conn.id, "days": total_days, "slices": len(slices),
               "ok": True, "fetched": 0, "inserted": 0, "updated": 0,
               "void_recalculated": 0, "runs": [], "errors": []}
    for piece_start, piece_end in slices:
        res = await execute_run(
            db, conn, mode="backfill", task_id=task_id,
            since=_window_text(piece_start), before=_window_text(piece_end))
        summary["runs"].append({"run_id": res["run_id"], "ok": res["ok"],
                                "window_since": res["window_since"],
                                "window_before": res["window_before"]})
        if res["ok"]:
            summary["fetched"] += int(res.get("fetched") or 0)
            summary["inserted"] += int(res.get("inserted") or 0)
            summary["updated"] += int(res.get("updated") or 0)
        else:
            summary["ok"] = False
            summary["errors"].append(res.get("error") or "分片拉取失败")
    summary["void_recalculated"] = advertiser_ingest.recalc_all_voids(
        db, connection_id=conn.id)
    _set_state(db, f"adv_backfill_{conn.id}", end.isoformat())
    db.commit()
    return summary


# ---------------------------------------------------------------------------
# P2 调度
# ---------------------------------------------------------------------------
async def run_due(reason: str = "scheduler") -> dict:
    """扫描启用定期任务的连接，到期的执行窗口拉取（首次运行先回填历史）。"""
    async with _run_lock:
        db = SessionLocal()
        summary = {"reason": reason, "checked": 0, "ran": 0, "runs": []}
        try:
            now = beijing_naive_now()
            conns = (db.query(ApiConnection)
                     .filter(ApiConnection.status != "disabled")
                     .order_by(ApiConnection.id).all())
            for conn in conns:
                sch = schedule_of(conn)
                # 与「测试通过后才可启用任务」一致：未验证的凭据不自动打上游
                if not sch["enabled"] or not conn.last_test_ok:
                    continue
                summary["checked"] += 1
                if not _due(db, conn, sch, now) or not _claim(conn.id, now):
                    continue
                try:
                    task = upsert_task(db, conn, sch)
                    if auto_backfill_enabled() and not _has_success_run(db, conn.id):
                        bf = await backfill(
                            db, conn, days=sch["backfill_days"], task_id=task.id)
                        summary["runs"].append({"connection_id": conn.id,
                                                "mode": "backfill", **bf})
                    utc_now = datetime.utcnow()
                    res = await execute_run(
                        db, conn, mode="scheduled", task_id=task.id,
                        since=_window_text(utc_now - timedelta(days=sch["lookback_days"])),
                        before=_window_text(utc_now))
                    task.last_run_at = datetime.utcnow()
                    task.status = "idle" if res["ok"] else "error"
                    task.next_run_at = _next_run(sch["frequency"], sch["hour"], beijing_naive_now())
                    _set_state(db, f"adv_fetch_last_{conn.id}", now.isoformat())
                    summary["ran"] += 1
                    summary["runs"].append({"connection_id": conn.id,
                                            "mode": "scheduled", **res})
                except Exception as exc:
                    summary["runs"].append({"connection_id": conn.id, "ok": False,
                                            "error": str(exc)[:300]})
                finally:
                    db.commit()
            return summary
        finally:
            db.close()


def scheduler_info() -> dict:
    """给前端 / 运维查看调度状态与任务概况。"""
    db = SessionLocal()
    try:
        tasks = db.query(ApiFetchTask).order_by(ApiFetchTask.id).all()
        return {
            "enabled": scheduler_enabled(),
            "auto_backfill": auto_backfill_enabled(),
            "loop_running": bool(_scheduler_task and not _scheduler_task.done()),
            "tasks": [{
                "id": t.id, "connection_id": t.connection_id, "name": t.name or "",
                "enabled": bool(t.enabled), "frequency": t.frequency or "daily",
                "hour": int(t.hour or 0), "lookback_days": int(t.lookback_days or 0),
                "backfill_days": int(t.backfill_days or 0), "status": t.status or "idle",
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            } for t in tasks],
        }
    finally:
        db.close()


async def _loop() -> None:
    await asyncio.sleep(8)   # 等 startup 的建表 / 补列 / 播种完成
    print("[advertiser_fetch] 定期拉取调度已启动")
    while True:
        try:
            if scheduler_enabled():
                result = await run_due()
                if result["ran"]:
                    print(f"[advertiser_fetch] 本轮执行 {result['ran']} 个任务")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[advertiser_fetch] 调度异常（下一轮重试）：{type(exc).__name__}: {exc}")
        await asyncio.sleep(60)


def start_scheduler() -> None:
    global _scheduler_task
    if not scheduler_enabled():
        print("[advertiser_fetch] 定期拉取已关闭（ADVERTISER_FETCH_ENABLED=0）")
        return
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_loop())


def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        _scheduler_task.cancel()
    _scheduler_task = None
