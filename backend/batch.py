"""
V1.1 批量提效：CSV 解析 + 异步批量生成任务 + 进度落库。

设计要点：
- 任务在后台 asyncio 任务中执行，进度写入 jobs 表，前端轮询 GET /api/jobs/{id}；
- 逐条隔离失败：单条异常只标记该条 failed，不中断整批；
- 单条落库即提交，任务中断也能保留已完成部分（可续跑）；
- 并发受全局信号量限制（默认 2 个任务并行），避免打满模型配额与 SQLite 写锁。
"""
import asyncio, csv, io, json
from datetime import datetime, timezone
from typing import List, Dict

from database import SessionLocal
from models import Job, Campaign
from services import analyze_landing_page, generate_campaign_materials

MAX_PARALLEL_JOBS = 2
_sem = asyncio.Semaphore(MAX_PARALLEL_JOBS)

CSV_HEADERS = ["campaign_name", "landing_text", "platforms", "languages", "material_types", "extra_prompt"]


def _split_multi(v: str) -> List[str]:
    if not v:
        return []
    for sep in ["|", ";", "/"]:
        if sep in v:
            return [x.strip() for x in v.split(sep) if x.strip()]
    return [v.strip()] if v.strip() else []


def parse_csv(raw: str) -> List[Dict]:
    """解析批量导入 CSV。兼容：有表头 / 无表头；多值用 | ; / 分隔。"""
    text = (raw or "").strip().lstrip("\ufeff")
    if not text:
        return []
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return []

    first = [c.strip().lower() for c in rows[0]]
    has_header = any(h in first for h in ("campaign_name", "landing_text", "platforms", "languages", "material_types"))
    if has_header:
        idx = {h: i for i, h in enumerate(first)}
        body = rows[1:]
    else:
        # 无表头：campaign_name, landing_text, platforms, languages, types, extra
        idx = {h: i for i, h in enumerate(CSV_HEADERS)}
        body = rows

    def cell(r, key):
        i = idx.get(key)
        return (r[i].strip() if i is not None and i < len(r) else "")

    items = []
    for r in body:
        landing = cell(r, "landing_text")
        name = cell(r, "campaign_name")
        if not landing and len(r) == 1:
            landing = r[0].strip()
        if not landing:
            continue
        if not name:
            name = landing[:24]
        items.append({
            "campaign_name": name,
            "landing_text": landing,
            "platforms": _split_multi(cell(r, "platforms")),
            "languages": _split_multi(cell(r, "languages")),
            "material_types": _split_multi(cell(r, "material_types")),
            "extra_prompt": cell(r, "extra_prompt"),
        })
    return items


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADERS)
    w.writerow(["SuperSave 首发", "SuperSave 自动比价省钱购物 App，覆盖欧美与拉美", "Facebook|Google", "en|es",
                "image|copy", "强调省钱"])
    w.writerow(["FitTrack 首发", "FitTrack 健身打卡 App，AI 定制训练计划", "Unity|AppLovin", "en|pt",
                "video|copy|keyword", "强调AI定制"])
    return buf.getvalue()


def _now():
    return datetime.now(timezone.utc)


async def run_job(job_id: int):
    """后台执行批量任务：逐条分析 + 生成。"""
    async with _sem:
        db = SessionLocal()
        try:
            job = db.query(Job).filter_by(id=job_id).first()
            if not job:
                return
            job.status = "running"
            job.started_at = _now()
            db.commit()

            payload = job.payload or {}
            items = payload.get("items", [])
            defaults = payload.get("defaults", {})
            results = []
            done = failed = 0

            for i, item in enumerate(items):
                db.refresh(job)
                if job.cancel_requested:
                    job.status = "canceled"
                    job.finished_at = _now()
                    job.result = results
                    db.commit()
                    return

                platforms = item.get("platforms") or defaults.get("platforms") or ["Facebook"]
                langs = item.get("languages") or defaults.get("languages") or ["en"]
                types = item.get("material_types") or defaults.get("material_types") or ["copy"]
                extra = item.get("extra_prompt") or defaults.get("extra_prompt") or ""

                try:
                    fw = await analyze_landing_page(db, None, item.get("landing_text", ""))
                    campaign = Campaign(name=item.get("campaign_name") or fw.product,
                                        framework_id=fw.id, platforms=platforms, status="draft",
                                        owner_id=(job.payload or {}).get("owner_id"))
                    db.add(campaign)
                    db.commit()   # 先落库，生成素材期间不持有写事务
                    db.refresh(campaign)
                    mats = await generate_campaign_materials(db, fw, campaign, platforms, types, langs, extra)
                    db.commit()
                    done += 1
                    results.append({
                        "index": i, "name": campaign.name, "campaign_id": campaign.id,
                        "framework_id": fw.id, "materials": len(mats), "ok": True, "error": None,
                    })
                except Exception as e:
                    db.rollback()
                    failed += 1
                    results.append({
                        "index": i, "name": item.get("campaign_name"), "campaign_id": None,
                        "framework_id": None, "materials": 0, "ok": False, "error": str(e)[:300],
                    })
                job = db.query(Job).filter_by(id=job_id).first()
                job.done, job.failed, job.result = done, failed, results
                db.commit()

            job = db.query(Job).filter_by(id=job_id).first()
            job.status = "success" if failed == 0 else ("partial" if done else "failed")
            job.finished_at = _now()
            db.commit()
        except Exception as e:
            db.rollback()
            j = db.query(Job).filter_by(id=job_id).first()
            if j:
                j.status = "failed"
                j.error = str(e)[:500]
                j.finished_at = _now()
                db.commit()
        finally:
            db.close()
