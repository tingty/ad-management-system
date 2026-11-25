# -*- coding: utf-8 -*-
"""V4.135 · P3 广告主报表查询层（纯读，零表结构变更）。

设计红线（对齐《广告主数据模块功能开发文档》5.4 / 第七章保障一）：
- 报表口径默认订单最终口径：所有聚合读 ``v_api_order_final`` 视图（净额、取消单标记），
  KPI 的"订单数"是视图行数（一个订单一行），不是明细条数。
- 表头 / 字段名 / 顺序 / 单位 / 格式 / 枚举翻译全部读 ``api_field_label`` 配置，
  后端只返回 column_key → 原始值的行数据 + 配置，前端不硬编码中文名。
- 明细下钻链路：订单明细（api_unified_fact）→ 商品子表（api_fact_item）/
  扩展层（api_fact_ext）→ 原始 JSON（api_source_record），并标注每个字段来自哪个
  上游字段、经过什么转换（api_field_map）。
- 权限隔离：所有查询按 ApiConnection.owner_id 过滤，只看当前用户自己的连接数据。
- 诚实的口径：CJ 接口不返回花费 / 曝光 / 点击，报表只有佣金收入视角，
  不计算 ROAS / ROI / CTR / CVR（在 payload 里显式声明 unavailable_metrics）。

本模块不写库、不加列、不建表；既有视图 / 种子配置由 migrations.py 负责。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import ApiConnection

# 维度排行的合法维度白名单（防止拼接注入；值即 api_unified_fact 的列 / 视图聚合来源）
DIMENSIONS = {
    "advertiser_name": "广告主名称",
    "campaign_name": "品牌名称",
    "event_name": "事件名称",
    "action_status": "订单状态",
}
DEFAULT_DIMENSION = "advertiser_name"

# 报表明确不提供的指标（上游无花费/曝光/点击数据），前端据此标注"不可用"
UNAVAILABLE_METRICS = ["roas", "roi", "ctr", "cvr", "spend", "impression", "click"]


def _num(v: Any) -> float:
    """Decimal / None / str → float，保证 JSON 可序列化且金额不再带 Decimal 类型。"""
    if v is None:
        return 0.0
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return 0.0


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _owned_ids(db: Session, owner_id: int) -> list[int]:
    return list(db.execute(
        text("SELECT id FROM api_connection WHERE owner_id=:o"),
        {"o": owner_id},
    ).scalars().all())


def _label_rows(db: Session, scope: str) -> list[dict]:
    rows = db.execute(
        text("""SELECT column_key, label, unit, format, enum_map_json, sort_no, visible
                FROM api_field_label WHERE scope=:s
                ORDER BY sort_no, id"""),
        {"s": scope},
    ).all()
    out = []
    for r in rows:
        out.append({
            "column_key": r[0], "label": r[1], "unit": r[2], "format": r[3],
            "enum_map": r[4] if isinstance(r[4], dict) else ({} if r[4] in (None, "") else _parse_json(r[4])),
            "sort_no": r[5], "visible": bool(r[6]),
        })
    return out


def _parse_json(raw: Any) -> dict:
    import json
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def field_labels(db: Session, scope: str = "fact") -> dict:
    """表头配置：报表 / 明细 / 下钻统一调用，前端不硬编码任何中文字段名。"""
    scope = scope if scope in ("fact", "order_final", "item") else "fact"
    rows = _label_rows(db, scope)
    return {
        "scope": scope,
        "columns": [c for c in rows if c["visible"]],
        "all": rows,
        "unavailable_metrics": list(UNAVAILABLE_METRICS),
    }


# ---------------------------------------------------------------------------
# 筛选条件（KPI / 趋势 / 维度排行共用的订单最终口径）
# ---------------------------------------------------------------------------
def _order_where(ids: list[int], *, connection_id: Optional[int] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None,
                 advertiser_name: Optional[str] = None, campaign_name: Optional[str] = None,
                 event_name: Optional[str] = None, action_status: Optional[str] = None,
                 alias: str = "v") -> tuple[str, dict]:
    """基于订单最终视图构造 WHERE；所有筛选按 owner 的 connection_id 收口。"""
    clauses = [f"{alias}.connection_id IN :ids"]
    params: dict[str, Any] = {"ids": ids or [-1]}
    if connection_id:
        clauses.append(f"{alias}.connection_id = :cid")
        params["cid"] = connection_id
    if date_from:
        clauses.append(f"{alias}.first_event_date >= :df")
        params["df"] = date_from
    if date_to:
        clauses.append(f"{alias}.first_event_date <= :dt")
        params["dt"] = date_to
    # 视图只聚合净额字段，维度字段从事实表回查（见 _dim_subquery）；这里维度筛选交给调用方。
    return " AND ".join(clauses), params


def kpi(db: Session, owner_id: int, *, connection_id: Optional[int] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None) -> dict:
    """概览 KPI：全部读订单最终视图 v_api_order_final（净额 + 取消单标记）。"""
    ids = _owned_ids(db, owner_id)
    where, params = _order_where(
        ids, connection_id=connection_id, date_from=date_from, date_to=date_to)
    sql = text(f"""SELECT
            COALESCE(SUM(v.net_sale_usd), 0)       AS net_sale_usd,
            COALESCE(SUM(v.net_commission_usd), 0) AS net_commission_usd,
            COUNT(*)                               AS order_count,
            COALESCE(SUM(v.is_void), 0)            AS void_count,
            COALESCE(SUM(v.detail_count), 0)       AS detail_count
        FROM v_api_order_final v WHERE {where}""").bindparams(
        __import__("sqlalchemy").bindparam("ids", expanding=True))
    row = db.execute(sql, params).mappings().first()
    order_count = int(row["order_count"] or 0)
    void_count = int(row["void_count"] or 0)
    net_sale = _num(row["net_sale_usd"])
    effective = order_count - void_count
    return {
        "net_sale_usd": net_sale,
        "net_commission_usd": _num(row["net_commission_usd"]),
        "order_count": order_count,
        "void_count": void_count,
        "detail_count": int(row["detail_count"] or 0),
        # 平均客单价 = 净销售额 / 有效订单数；无有效订单时为 0，不产生除零
        "avg_order_value_usd": round(net_sale / effective, 2) if effective > 0 else 0.0,
        "source_view": "v_api_order_final",
        "unavailable_metrics": list(UNAVAILABLE_METRICS),
    }


def trend(db: Session, owner_id: int, *, connection_id: Optional[int] = None,
          date_from: Optional[str] = None, date_to: Optional[str] = None,
          dimension: Optional[str] = None, dimension_value: Optional[str] = None) -> dict:
    """按事件日期的销售 / 佣金趋势（订单最终口径），可叠加维度筛选。

    视图只存净额，维度筛选通过 EXISTS 子查询回查事实表，保持订单级口径不变。
    """
    ids = _owned_ids(db, owner_id)
    where, params = _order_where(
        ids, connection_id=connection_id, date_from=date_from, date_to=date_to)
    extra = ""
    if dimension in DIMENSIONS and dimension_value:
        extra = (f" AND EXISTS (SELECT 1 FROM api_unified_fact d "
                 f"WHERE d.template_id=v.template_id AND d.connection_id=v.connection_id "
                 f"AND d.order_id=v.order_id AND d.{dimension}=:dimval)")
        params["dimval"] = dimension_value
    sql = text(f"""SELECT v.first_event_date AS event_date,
            ROUND(SUM(v.net_sale_usd), 6)       AS net_sale_usd,
            ROUND(SUM(v.net_commission_usd), 6) AS net_commission_usd,
            COUNT(*)                            AS order_count
        FROM v_api_order_final v
        WHERE {where} AND v.first_event_date IS NOT NULL {extra}
        GROUP BY v.first_event_date
        ORDER BY v.first_event_date""").bindparams(
        __import__("sqlalchemy").bindparam("ids", expanding=True))
    rows = db.execute(sql, params).mappings().all()
    points = [{
        "event_date": _iso(r["event_date"]),
        "net_sale_usd": _num(r["net_sale_usd"]),
        "net_commission_usd": _num(r["net_commission_usd"]),
        "order_count": int(r["order_count"] or 0),
    } for r in rows]
    return {
        "points": points,
        "metric_labels": {
            "net_sale_usd": "净销售金额", "net_commission_usd": "净佣金金额",
        },
        "total": len(points),
    }


def rankings(db: Session, owner_id: int, *, dimension: str = DEFAULT_DIMENSION,
             connection_id: Optional[int] = None, date_from: Optional[str] = None,
             date_to: Optional[str] = None, limit: int = 20) -> dict:
    """维度排行：广告主 / 品牌 / 事件 / 订单状态的金额与订单数排行。

    维度值在事实表上；为避免重复计算修正单，先按 (模板,连接,订单) 取一条维度代表值
    （MIN），再与订单最终视图按订单 join 聚合净额 —— 口径与 KPI 完全一致。
    """
    if dimension not in DIMENSIONS:
        dimension = DEFAULT_DIMENSION
    ids = _owned_ids(db, owner_id)
    where, params = _order_where(
        ids, connection_id=connection_id, date_from=date_from, date_to=date_to)
    params["lim"] = max(1, min(int(limit or 20), 100))
    # 维度代表值：每个订单取一个，避免原始单+修正单两行导致排行金额翻倍
    sql = text(f"""SELECT d.{dimension} AS name,
            ROUND(SUM(v.net_sale_usd), 6)       AS net_sale_usd,
            ROUND(SUM(v.net_commission_usd), 6) AS net_commission_usd,
            COUNT(*)                            AS order_count
        FROM v_api_order_final v
        JOIN (
            SELECT template_id, connection_id, order_id, MIN({dimension}) AS {dimension}
            FROM api_unified_fact
            WHERE connection_id IN :ids AND {dimension} IS NOT NULL AND {dimension} <> ''
            GROUP BY template_id, connection_id, order_id
        ) d ON d.template_id=v.template_id AND d.connection_id=v.connection_id
            AND d.order_id=v.order_id
        WHERE {where}
        GROUP BY d.{dimension}
        ORDER BY net_commission_usd DESC, order_count DESC
        LIMIT :lim""").bindparams(
        __import__("sqlalchemy").bindparam("ids", expanding=True))
    rows = db.execute(sql, params).mappings().all()
    items = [{
        "name": r["name"] or "—",
        "net_sale_usd": _num(r["net_sale_usd"]),
        "net_commission_usd": _num(r["net_commission_usd"]),
        "order_count": int(r["order_count"] or 0),
    } for r in rows]
    return {
        "dimension": dimension,
        "dimension_label": DIMENSIONS[dimension],
        "items": items,
        "metric_labels": {"net_sale_usd": "净销售金额", "net_commission_usd": "净佣金金额"},
    }


import re as _re

# 明细只额外取这几个技术列（用于下钻 / 链接 / 权限），其余展示列全部从 api_field_label 配置推导，
# 不在代码里硬编码业务列名——既保证表头配置驱动，也让 rename_column 审计不误报业务列。
_DETAIL_TECH_COLUMNS = ["id", "template_id", "connection_id", "original"]
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _detail_columns(db: Session) -> tuple[list[str], list[dict]]:
    """展示列 = 可见的 api_field_label；查询列 = 展示列 + 技术列。列名经过标识符白名单校验。"""
    visible = [c for c in field_labels(db, "fact")["columns"] if _IDENT_RE.match(c["column_key"])]
    biz = [c["column_key"] for c in visible]
    query_cols = list(dict.fromkeys(_DETAIL_TECH_COLUMNS + biz))
    return query_cols, visible


def details(db: Session, owner_id: int, *, connection_id: Optional[int] = None,
            date_from: Optional[str] = None, date_to: Optional[str] = None,
            advertiser_name: Optional[str] = None, campaign_name: Optional[str] = None,
            event_name: Optional[str] = None, action_status: Optional[str] = None,
            keyword: Optional[str] = None, page: int = 1, page_size: int = 20) -> dict:
    """佣金明细列表（明细粒度）：行数据 + 动态表头配置 + 分页。"""
    ids = _owned_ids(db, owner_id)
    clauses = ["f.connection_id IN :ids"]
    params: dict[str, Any] = {"ids": ids or [-1]}
    if connection_id:
        clauses.append("f.connection_id = :cid"); params["cid"] = connection_id
    if date_from:
        clauses.append("f.event_date >= :df"); params["df"] = date_from
    if date_to:
        clauses.append("f.event_date <= :dt"); params["dt"] = date_to
    for col, val in (("advertiser_name", advertiser_name), ("campaign_name", campaign_name),
                     ("event_name", event_name), ("action_status", action_status)):
        if val:
            clauses.append(f"f.{col} = :{col}"); params[col] = val
    if keyword:
        clauses.append("(f.order_id LIKE :kw OR f.commission_id LIKE :kw OR f.advertiser_name LIKE :kw)")
        params["kw"] = f"%{keyword.strip()[:64]}%"
    where = " AND ".join(clauses)

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    offset = (page - 1) * page_size
    total = int(db.execute(
        text(f"SELECT COUNT(*) FROM api_unified_fact f WHERE {where}").bindparams(
            __import__("sqlalchemy").bindparam("ids", expanding=True)),
        params,
    ).scalar() or 0)

    query_cols, visible_cols = _detail_columns(db)
    cols = ", ".join(f"f.{c}" for c in query_cols)
    rows = db.execute(
        text(f"SELECT {cols} FROM api_unified_fact f WHERE {where} "
             f"ORDER BY f.event_date DESC, f.id DESC LIMIT :lim OFFSET :off").bindparams(
            __import__("sqlalchemy").bindparam("ids", expanding=True)),
        {**params, "lim": page_size, "off": offset},
    ).mappings().all()

    def _row(r):
        out = {}
        for c in query_cols:
            v = r[c]
            if isinstance(v, Decimal):
                v = _num(v)
            elif isinstance(v, (datetime, date)):
                v = _iso(v)
            out[c] = v
        return out

    return {
        "rows": [_row(r) for r in rows],
        "columns": visible_cols,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "source_table": "api_unified_fact",
    }


def drilldown(db: Session, owner_id: int, fact_id: int) -> dict:
    """明细行下钻：事实行 → 商品子表 / 扩展层 → 原始 JSON + 字段映射规则。"""
    ids = _owned_ids(db, owner_id)
    fact = db.execute(
        text("""SELECT f.* FROM api_unified_fact f
                WHERE f.id=:fid AND f.connection_id IN :ids""").bindparams(
            __import__("sqlalchemy").bindparam("ids", expanding=True)),
        {"fid": fact_id, "ids": ids or [-1]},
    ).mappings().first()
    if not fact:
        return {"found": False}

    def _serialize(mapping):
        out = {}
        for k, v in dict(mapping).items():
            if isinstance(v, Decimal):
                v = _num(v)
            elif isinstance(v, (datetime, date)):
                v = _iso(v)
            out[k] = v
        return out

    items = db.execute(
        text("SELECT sku, quantity, unit_price_usd, commission_usd, ext_json "
             "FROM api_fact_item WHERE fact_id=:fid ORDER BY id"), {"fid": fact_id},
    ).mappings().all()
    ext = db.execute(
        text("SELECT data_json FROM api_fact_ext WHERE fact_id=:fid ORDER BY id LIMIT 1"),
        {"fid": fact_id},
    ).scalar()
    src = None
    if fact.get("source_record_id"):
        raw = db.execute(
            text("SELECT id, external_id, payload_json, payload_sha256, first_seen, last_seen "
                 "FROM api_source_record WHERE id=:sid"), {"sid": fact["source_record_id"]},
        ).mappings().first()
        if raw:
            src = _serialize(raw)
    maps = []
    if fact.get("template_id"):
        rows = db.execute(
            text("""SELECT source_path, target_field, transform, note, enabled
                    FROM api_field_map WHERE template_id=:t AND enabled=1
                    ORDER BY id"""), {"t": fact["template_id"]},
        ).all()
        maps = [{"source_path": r[0], "target_field": r[1], "transform": r[2],
                 "note": r[3] or ""} for r in rows]

    return {
        "found": True,
        "fact": _serialize(fact),
        "columns": field_labels(db, "fact")["columns"],
        "items": [_serialize(r) for r in items],
        "ext": ext if isinstance(ext, dict) else (_parse_json(ext) if ext else {}),
        "source": src,
        "field_maps": maps,
        "chain": ["api_unified_fact", "api_fact_item / api_fact_ext", "api_source_record"],
    }
