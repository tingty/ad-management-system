"""
V4.34 大模型连通性健康：每日自动测试 + 状态/log 落库 + 后台调度。

设计要点
--------
1. 每天对所有「已保存」的 ModelConfig 跑一次真实 API 连通测试（调用 llm_catalog.test_llm_connection，
   与页面「保存并测试」完全同一条链路），把结果写回：
     last_test_ok        成功 / 失败（NULL = 尚未测试）
     last_test_at        最后测试时间
     last_test_http_code 服务器返回的 HTTP code（网络层失败为 0）
     last_test_error     失败 log：HTTP code + 服务器返回的错误信息 + 中文诊断
     last_test_latency_ms 成功延迟
2. 每天只跑一次：用 system_state 表的日期戳做跨进程/多 worker 去重（原子条件 UPDATE 抢占）。
   支持 LLM_DAILY_TEST_HOUR 指定本地小时（默认 3 点）；进程当天已过该小时且当天未跑过则启动后补跑。
3. 无新增依赖：FastAPI startup 里 asyncio.create_task 起后台协程，shutdown 时取消。
4. 手动兜底：POST /api/settings/models/test-all、POST /api/settings/models/{id}/test 复用同一套写回逻辑。
"""
import asyncio
import os
from datetime import datetime

from database import SessionLocal
from models import ModelConfig, SystemState, utcnow
from llm_catalog import test_llm_connection, _resolve_protocol

DAILY_DATE_KEY = "llm_daily_test_date"   # value = YYYY-MM-DD
DAILY_AT_KEY = "llm_daily_test_at"      # value = ISO 时间串
_HOUR_DEFAULT = 3
_run_lock = asyncio.Lock()
_scheduler_task: "asyncio.Task | None" = None


def daily_enabled() -> bool:
    return os.getenv("LLM_DAILY_TEST_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def daily_hour() -> int:
    try:
        h = int(os.getenv("LLM_DAILY_TEST_HOUR", str(_HOUR_DEFAULT)))
        return h if 0 <= h <= 23 else _HOUR_DEFAULT
    except (TypeError, ValueError):
        return _HOUR_DEFAULT


def _cfg_request(cfg: ModelConfig) -> dict:
    """把一条落库配置还原为 test_llm_connection 所需的请求体（含图像/视频协议与 endpoint/params）。

    params 整包透传，使视频模型配置里的 endpoint/body_shape/async_header 等开关
    （如阿里云百炼 MaaS 的 dashscope_maas 契约）在「测试已保存配置 / 每日健康测试」时生效。
    """
    params = cfg.params if isinstance(cfg.params, dict) else {}
    return {
        "provider": cfg.provider,
        "protocol": _resolve_protocol(cfg.provider),
        "api_key": cfg.api_key,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "endpoint": params.get("endpoint"),
        "params": params,
    }


def _build_error_log(res: dict) -> str:
    """失败 log：以 HTTP code 与服务器原始错误信息为主，附错误类型与中文诊断。"""
    code = res.get("http_status") or 0
    lines = [f"HTTP Code: {code if code else 'N/A（未获得 HTTP 响应，多为网络层失败 / 超时 / 地址不可达）'}"]
    if res.get("error_type"):
        lines.append(f"错误类型: {res['error_type']}")
    server = (res.get("raw") or res.get("error") or "").strip()
    if server:
        lines.append(f"服务器返回的错误信息: {server[:600]}")
    if res.get("message"):
        lines.append(f"诊断: {res['message']}")
    if res.get("hint_url"):
        lines.append(f"参考文档: {res['hint_url']}")
    return "\n".join(lines)[:1600]


async def test_one(db, cfg: ModelConfig) -> dict:
    """测试单条配置并把状态写回 ORM 对象（由调用方 commit）。"""
    try:
        res = await test_llm_connection(_cfg_request(cfg))
    except Exception as e:  # 兜底：任何异常都不应让每日任务整体崩掉
        res = {"ok": False, "http_status": 0, "error_type": "unknown",
               "message": f"测试过程异常：{type(e).__name__}: {e}", "raw": str(e)}
    cfg.last_test_ok = bool(res.get("ok"))
    cfg.last_test_at = utcnow()
    cfg.last_test_http_code = int(res.get("http_status") or 0)
    cfg.last_test_latency_ms = res.get("latency_ms")
    cfg.last_test_error = None if cfg.last_test_ok else _build_error_log(res)
    return res


async def run_all(reason: str = "manual") -> dict:
    """对全部已保存配置逐一连通测试并落库；返回汇总与逐条结果。"""
    async with _run_lock:
        db = SessionLocal()
        try:
            cfgs = db.query(ModelConfig).order_by(ModelConfig.id).all()
            items = []
            for cfg in cfgs:
                res = await test_one(db, cfg)
                items.append({
                    "id": cfg.id,
                    "name": cfg.name,
                    "ok": bool(res.get("ok")),
                    "http_status": int(res.get("http_status") or 0),
                    "latency_ms": res.get("latency_ms"),
                    "error": cfg.last_test_error,
                    "message": res.get("message"),
                })
            db.commit()
            ok_n = sum(1 for i in items if i["ok"])
            print(f"[model_health] {reason} 连通测试完成：{ok_n}/{len(items)} 成功")
            return {
                "reason": reason,
                "total": len(items),
                "ok": ok_n,
                "failed": len(items) - ok_n,
                "tested_at": datetime.now().isoformat(timespec="seconds"),
                "results": items,
            }
        finally:
            db.close()


def _get_or_create_state(db, key: str) -> SystemState:
    row = db.query(SystemState).filter_by(key=key).first()
    if row is None:
        row = SystemState(key=key, value="")
        db.add(row)
        db.commit()
        db.refresh(row)
    elif row.value is None:
        # 避免 SQL 的 `value != today` 在 NULL 上恒为 unknown，导致当天永远抢不到锁
        row.value = ""
        db.commit()
    return row


def _set_state(db, key: str, value: str) -> None:
    row = _get_or_create_state(db, key)
    row.value = value
    db.commit()


def _claim_today(today: str) -> bool:
    """原子抢占「今天由我执行」：仅当已存日期 != today 时才更新，返回是否抢到。"""
    db = SessionLocal()
    try:
        _get_or_create_state(db, DAILY_DATE_KEY)
        n = (db.query(SystemState)
               .filter(SystemState.key == DAILY_DATE_KEY,
                       SystemState.value != today)
               .update({"value": today}, synchronize_session=False))
        db.commit()
        return n == 1
    finally:
        db.close()


def _should_run_today() -> bool:
    db = SessionLocal()
    try:
        row = db.query(SystemState).filter_by(key=DAILY_DATE_KEY).first()
        today = datetime.now().strftime("%Y-%m-%d")
        if row and (row.value or "") == today:
            return False
        # 到点才跑；若进程在目标小时之后才启动，则立即补跑当天那一次
        return datetime.now().hour >= daily_hour()
    finally:
        db.close()


def health_info() -> dict:
    db = SessionLocal()
    try:
        d = db.query(SystemState).filter_by(key=DAILY_DATE_KEY).first()
        at = db.query(SystemState).filter_by(key=DAILY_AT_KEY).first()
        return {
            "enabled": daily_enabled(),
            "hour": daily_hour(),
            "last_daily_date": (d.value if d else None) or None,
            "last_daily_at": (at.value if at else None) or None,
            "total_configs": db.query(ModelConfig).count(),
        }
    finally:
        db.close()


async def _daily_loop() -> None:
    # 等启动流程（建表/补列/播种）跑完
    await asyncio.sleep(10)
    print(f"[model_health] 每日连通测试调度已启动（每天 {daily_hour():02d}:00 之后执行一次）")
    while True:
        try:
            if _should_run_today():
                today = datetime.now().strftime("%Y-%m-%d")
                if _claim_today(today):
                    await run_all(reason="daily")
                    db = SessionLocal()
                    try:
                        _set_state(db, DAILY_AT_KEY, datetime.now().astimezone().isoformat(timespec="seconds"))
                    finally:
                        db.close()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[model_health] 每日调度异常（已忽略，下一轮重试）：{type(e).__name__}: {e}")
        await asyncio.sleep(60)


def start_daily_scheduler() -> None:
    """由 FastAPI startup 调用：启动后台协程并保持引用，避免被 GC。"""
    global _scheduler_task
    if not daily_enabled():
        print("[model_health] 每日连通测试已关闭（LLM_DAILY_TEST_ENABLED=0）")
        return
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_daily_loop())


def stop_daily_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        _scheduler_task.cancel()
    _scheduler_task = None
