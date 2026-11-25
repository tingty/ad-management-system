# -*- coding: utf-8 -*-
"""V4.132 · P1-B 映射写入与幂等落库。

职责边界：
1. 覆盖检查：上游字段集合必须 ⊆ api_field_map 已登记集合（显式 __skip__ 也算登记）；
   未登记字段写入原始层并告警，不静默丢弃、不擅自改表结构。
2. 按映射分发：source_path → fact.* / item.* / ext.* / __skip__，transform 统一转换。
3. 幂等：source_record 用 (template_id, connection_id, external_id) 去重；fact 用
   (template_id, external_id) 去重；重跑/修正单覆盖更新并重建 items / ext 子表。
4. 派生：主表均价 = 销售金额 / 商品数量汇总（源路径由映射反查）；is_void 按订单净额归零重算。
5. replay_mapping()：改映射后从原始层重放，支持 dry_run 预览，幂等不重复插行。

不做：调度（P2）、报表数据接口（P3）、改数据库表结构与映射 seed（V4.130 已固化）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from migrations import CJ_TEMPLATE_ID
from models import ApiFactExt, ApiFactItem, ApiSourceRecord, ApiUnifiedFact

# V4.138 / P4：语义源路径从映射配置反查，避免把 CJ 字段名写死在业务代码。
# 目标字段 → 缺省源路径（兼容未登记该目标的旧模板）
_SEMANTIC_DEFAULTS = {
    "source_record.external_id": "commissionId",
    "fact.order_id": "orderId",
    "fact.sale_amount_usd": "saleAmountUsd",
    "item.quantity": "items[].quantity",
}


def semantic_source(db: Session, template_id: str, target: str) -> str:
    """从 api_field_map 反查某目标字段的上游源路径；未登记则回退缺省。"""
    row = db.execute(
        text("""SELECT source_path FROM api_field_map
                WHERE template_id=:t AND target_field=:g AND enabled=1
                ORDER BY id LIMIT 1"""),
        {"t": template_id, "g": target},
    ).first()
    return (row[0] if row else None) or _SEMANTIC_DEFAULTS.get(target, "")


# ---------------------------------------------------------------------------
# 字段取值与转换
# ---------------------------------------------------------------------------
def _get_path(record: dict, path: str) -> Any:
    """按 source_path 取值；items[].xxx 返回列表，其余按点号逐层取。"""
    if path.startswith("items[]."):
        key = path[len("items[]."):]
        return [item.get(key) for item in (record.get("items") or [])
                if isinstance(item, dict)]
    if path.startswith("verticalAttributes."):
        va = record.get("verticalAttributes")
        return va.get(path[len("verticalAttributes."):]) if isinstance(va, dict) else None
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _convert(value: Any, transform: str | None) -> Any:
    if value is None:
        return None
    try:
        if transform == "decimal":
            return Decimal(str(value))
        if transform == "cents_decimal":
            # PartnerStack：金额是美元分（整数），统一报表按美元展示，保留两位。
            return (Decimal(str(value)) / Decimal(100)).quantize(Decimal("0.01"))
        if transform == "epoch_ms_date":
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date()
        if transform == "epoch_ms_datetime":
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
        if transform == "utc_date":
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        if transform == "utc_datetime":
            text_value = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text_value)
            return dt.replace(tzinfo=None)
        if transform == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes")
        if transform == "skip":
            return None
    except (ValueError, TypeError, InvalidOperation):
        return None
    return value


def _observed_paths(record: dict) -> set[str]:
    """提取一条明细里实际出现的字段路径，用于覆盖检查（容器键本身不算字段）。"""
    paths: set[str] = set()
    for key, value in record.items():
        if key == "items" and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    paths.update(f"items[].{k}" for k in item)
        elif key == "verticalAttributes" and isinstance(value, dict):
            paths.update(f"verticalAttributes.{k}" for k in value)
        else:
            paths.add(key)
    return paths


def mapping_rows(db: Session, template_id: str = CJ_TEMPLATE_ID) -> list[tuple[str, str, str]]:
    rows = db.execute(
        text("""SELECT source_path, target_field, transform FROM api_field_map
                WHERE template_id=:t AND enabled=1 ORDER BY id"""),
        {"t": template_id},
    ).all()
    return [(r[0], r[1], r[2] or "direct") for r in rows]


def check_coverage(record: dict, db: Session,
                   template_id: str = CJ_TEMPLATE_ID) -> list[str]:
    """返回未登记字段路径；空列表表示全部已登记（含显式 skip）。"""
    registered = {row[0] for row in mapping_rows(db, template_id)}
    return sorted(_observed_paths(record) - registered)


# ---------------------------------------------------------------------------
# 按映射构造落库值
# ---------------------------------------------------------------------------
def _fact_values(record: dict, rows: Iterable[tuple[str, str, str]], *,
                 sale_source: str = "saleAmountUsd") -> dict:
    values: dict = {}
    rows = list(rows)
    quantities = [_convert(v, "decimal") for v in _get_path(record, "items[].quantity")]
    qty_total = sum((q for q in quantities if q is not None), Decimal(0))
    for source, target, transform in rows:
        if not target.startswith("fact.") or source.startswith("items[]"):
            continue
        column = target[len("fact."):]
        # is_void 必须按整单净额重算，不能在单条明细层判定
        if source == "__derived__is_void":
            continue
        if column == "unit_price_usd":
            sale = _convert(_get_path(record, sale_source), "decimal")
            values[column] = (sale / qty_total) if sale is not None and qty_total else None
            continue
        values[column] = _convert(_get_path(record, source), transform)
    return values


def _item_rows(record: dict, rows: Iterable[tuple[str, str, str]]) -> list[dict]:
    specs = [(src[len("items[]."):], tgt[len("item."):], transform)
             for src, tgt, transform in rows
             if src.startswith("items[].") and tgt.startswith("item.")]
    result: list[dict] = []
    for item in (record.get("items") or []):
        if not isinstance(item, dict):
            continue
        result.append({column: _convert(item.get(key), transform)
                       for key, column, transform in specs})
    return result


def _json_safe(value: Any) -> Any:
    """把转换后的值归一为 JSON 可序列化类型，避免真实明细落库失败。

    V4.139：_convert 的 utc_datetime / decimal 会产出 datetime / Decimal，
    SQLAlchemy JSON 列不认识这些类型。日期时间保留 ISO 字符串、Decimal 保留
    字符串精度，嵌套列表逐项归一；原始层 payload_json 仍是上游原文。
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _ext_data(record: dict, rows: Iterable[tuple[str, str, str]]) -> dict:
    data: dict = {}
    for source, target, transform in rows:
        if not target.startswith("ext."):
            continue
        value = _get_path(record, source)
        if isinstance(value, list):
            value = [_convert(v, transform) for v in value]
        else:
            value = _convert(value, transform)
        if value is not None:
            data[target[len("ext."):]] = _json_safe(value)
    return data


def _recalc_void(db: Session, records: list[dict], template_id: str, *,
                 order_source: str = "orderId") -> int:
    """按订单重算 is_void：净销售额与净佣金同时归零视为取消单。"""
    order_ids = {str(_get_path(r, order_source) or "") for r in records} - {""}
    if not order_ids:
        return 0
    facts = db.query(ApiUnifiedFact).filter(
        ApiUnifiedFact.template_id == template_id,
        ApiUnifiedFact.order_id.in_(list(order_ids)),
    ).all()
    groups: dict[str, list] = {}
    for fact in facts:
        groups.setdefault(fact.order_id or "", []).append(fact)
    changed = 0
    for group in groups.values():
        net_sale = sum((Decimal(str(f.sale_amount_usd or 0)) for f in group), Decimal(0))
        net_commission = sum((Decimal(str(f.commission_amount_usd or 0)) for f in group), Decimal(0))
        is_void = net_sale == 0 and net_commission == 0
        for fact in group:
            if fact.is_void != is_void:
                fact.is_void = is_void
                changed += 1
    return changed


# ---------------------------------------------------------------------------
# 幂等落库
# ---------------------------------------------------------------------------
def ingest_records(db: Session, *, records: list[dict], connection_id: int | None = None,
                   template_id: str = CJ_TEMPLATE_ID, run_id: int | None = None) -> dict:
    """把 PublisherCommission 明细幂等写入原始层 / 统一事实表 / items / ext。"""
    rows = mapping_rows(db, template_id)
    ext_source = semantic_source(db, template_id, "source_record.external_id")
    sale_source = semantic_source(db, template_id, "fact.sale_amount_usd")
    order_source = semantic_source(db, template_id, "fact.order_id")
    stats = {
        "fetched": len(records), "inserted": 0, "updated": 0,
        "unchanged": 0, "skipped": 0, "void_recalculated": 0, "warnings": [],
    }
    for record in records:
        if not isinstance(record, dict):
            stats["skipped"] += 1
            stats["warnings"].append("非对象明细已跳过")
            continue
        external_id = str(_get_path(record, ext_source) or "").strip()
        if not external_id:
            stats["skipped"] += 1
            stats["warnings"].append(f"缺少 {ext_source} 的明细已跳过")
            continue

        unknown = check_coverage(record, db, template_id)
        if unknown:
            stats["warnings"].append(f"{external_id}: 未登记字段 {', '.join(unknown)}（原始层已保留）")

        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        source = db.query(ApiSourceRecord).filter_by(
            template_id=template_id, connection_id=connection_id,
            external_id=external_id).first()
        # 必须先在更新哈希前判定是否变化，否则修正单会被误判为「未变」而跳过
        source_changed = source is None or source.payload_sha256 != sha
        if source is None:
            source = ApiSourceRecord(
                template_id=template_id, connection_id=connection_id,
                external_id=external_id, payload_json=record, payload_sha256=sha)
            db.add(source)
            db.flush()
        elif source.payload_sha256 != sha:
            source.payload_json = record
            source.payload_sha256 = sha
            source.last_seen = datetime.utcnow()

        fact = db.query(ApiUnifiedFact).filter_by(
            template_id=template_id, external_id=external_id).first()
        if not source_changed and fact is not None:
            stats["unchanged"] += 1
            continue

        values = _fact_values(record, rows, sale_source=sale_source)
        values.update({
            "source_record_id": source.id, "external_id": external_id,
            "template_id": template_id, "connection_id": connection_id, "run_id": run_id,
        })
        if fact is None:
            db.add(ApiUnifiedFact(**values))
            db.flush()
            stats["inserted"] += 1
        else:
            for key, value in values.items():
                setattr(fact, key, value)
            db.query(ApiFactItem).filter_by(fact_id=fact.id).delete()
            db.query(ApiFactExt).filter_by(fact_id=fact.id).delete()
            stats["updated"] += 1
        fact = db.query(ApiUnifiedFact).filter_by(
            template_id=template_id, external_id=external_id).first()
        for item_values in _item_rows(record, rows):
            db.add(ApiFactItem(fact_id=fact.id, **item_values))
        ext = _ext_data(record, rows)
        if ext:
            db.add(ApiFactExt(fact_id=fact.id, template_id=template_id, data_json=ext))

    db.flush()
    stats["void_recalculated"] = _recalc_void(db, records, template_id, order_source=order_source)
    db.commit()
    return stats


def recalc_all_voids(db: Session, *, template_id: str = CJ_TEMPLATE_ID,
                     connection_id: int | None = None) -> int:
    """P1-C：跨批次全量重算订单净额 / is_void。

    与 _recalc_void() 的差别：后者只看当批 records 涉及的 orderId，修正单若在后续
    批次才到达、且当批没有同样订单号，历史行会一直停留在旧判定。这里按
    (模板, 连接, 订单) 全量分组重算，供历史回填结束与手动修复调用。
    空 orderId 不参与合并（保持原值），与批内口径一致。
    """
    query = db.query(ApiUnifiedFact).filter(ApiUnifiedFact.template_id == template_id)
    if connection_id is not None:
        query = query.filter(ApiUnifiedFact.connection_id == connection_id)
    groups: dict[tuple, list] = {}
    for fact in query.all():
        if not fact.order_id:
            continue
        key = (fact.template_id, fact.connection_id, fact.order_id)
        groups.setdefault(key, []).append(fact)
    changed = 0
    for group in groups.values():
        net_sale = sum((Decimal(str(f.sale_amount_usd or 0)) for f in group), Decimal(0))
        net_commission = sum((Decimal(str(f.commission_amount_usd or 0)) for f in group), Decimal(0))
        is_void = net_sale == 0 and net_commission == 0
        for fact in group:
            if bool(fact.is_void) != is_void:
                fact.is_void = is_void
                changed += 1
    db.flush()
    return changed


def replay_mapping(db: Session, *, template_id: str = CJ_TEMPLATE_ID,
                   connection_id: int | None = None, dry_run: bool = True,
                   limit: int | None = None) -> dict:
    """保障二：改映射后从原始层重放。dry_run=True 只预览，不写库。"""
    query = db.query(ApiSourceRecord).filter_by(template_id=template_id)
    if connection_id is not None:
        query = query.filter_by(connection_id=connection_id)
    query = query.order_by(ApiSourceRecord.id)
    if limit:
        query = query.limit(limit)
    sources = query.all()
    records = [s.payload_json for s in sources if isinstance(s.payload_json, dict)]
    preview = {
        "sources": len(sources), "records": len(records),
        "coverage_warnings": sum(len(check_coverage(r, db, template_id)) for r in records),
        "mode": "dry_run" if dry_run else "apply",
    }
    if not dry_run:
        preview.update(ingest_records(
            db, records=records, connection_id=connection_id, template_id=template_id))
    return preview
