"""
轻量级 schema 自愈（SQLite / Postgres 通用）。
create_all 只建新表，不会给已存在的表加列；本模块扫描元数据与库内实际列差异，
自动 ALTER TABLE ADD COLUMN，避免「模型改了、演示库还是旧结构」导致的运行时错误。

V4.37：旧「素材管理」业务表（campaigns / materials / frameworks / angles /
platform_specs / jobs / review_records 等）已从模型层移除，历史库中的这些表
保持原样不再迁移（数据保留但不被系统使用）。

V4.127（广告主数据 P1-A）：在此之上叠加「保障三 · 版本化列迁移」——
  - 结构变更写成版本函数，执行记录落 schema_migrations，可重复执行不重复应用；
  - v_api_order_final 视图由本模块统一创建 / 重建；
  - rename_column() 一次同步四处：物理列 → api_field_map.target_field → 视图 → 代码引用审计；
  - api_field_label 种子配置在此落地（保障一：报表展示名不硬编码）。
"""
import json
import os
import re
from pathlib import Path

from sqlalchemy import inspect, text
from database import engine, Base, SessionLocal
import models  # noqa: F401  注册全部表到 Base.metadata，create_all 才能建新表


# ---------------------------------------------------------------------------
# 订单最终视图：按 (模板, 连接, 订单) 聚合净额与取消单。报表默认查此视图。
# 不使用 actionStatus=REVERSED（CJ 官方枚举无此值）；正负相抵净额归零即取消单。
# ---------------------------------------------------------------------------
ORDER_VIEW_NAME = "v_api_order_final"
ORDER_VIEW_SQL = f"""
CREATE VIEW IF NOT EXISTS {ORDER_VIEW_NAME} AS
SELECT
    f.template_id,
    f.connection_id,
    f.order_id,
    ROUND(SUM(COALESCE(f.sale_amount_usd, 0)), 6)       AS net_sale_usd,
    ROUND(SUM(COALESCE(f.commission_amount_usd, 0)), 6) AS net_commission_usd,
    COUNT(*)                                            AS detail_count,
    CASE WHEN ROUND(SUM(COALESCE(f.sale_amount_usd, 0)), 6) = 0
          AND ROUND(SUM(COALESCE(f.commission_amount_usd, 0)), 6) = 0
         THEN 1 ELSE 0 END                              AS is_void,
    MIN(f.event_date)                                   AS first_event_date,
    MAX(f.event_date)                                   AS last_event_date,
    MAX(f.updated_at)                                   AS last_updated_at
FROM api_unified_fact f
GROUP BY f.template_id, f.connection_id, f.order_id
"""


# ---------------------------------------------------------------------------
# 保障一：20 个业务字段的展示名配置（唯一权威种子）。
# scope=order_final 的少量行供订单视图报表使用；fact 为明细表默认。
# ---------------------------------------------------------------------------
FIELD_LABEL_SEED = [
    # column_key, label, unit, format, sort_no, visible, enum_map
    ("commission_id",          "ID / 佣金ID",      None,  "text",     1, True,  None),
    ("advertiser_name",        "广告主名称",        None,  "text",     2, True,  None),
    ("order_id",               "订单号",            None,  "text",     3, True,  None),
    ("event_date",             "日期（事件日期）",  None,  "date",     4, True,  None),
    ("campaign_name",          "品牌名称",          None,  "text",     5, True,  None),
    ("action_status",          "订单状态",          None,  "enum",     6, True,
     {"new": "新建", "extended": "延长", "locked": "锁定", "closed": "关闭"}),
    ("event_name",             "事件名称",          None,  "text",     7, True,  None),
    ("sale_amount_usd",        "销售金额",          "USD", "decimal2", 8, True,  None),
    ("commission_amount_usd",  "佣金金额",          "USD", "decimal2", 9, True,  None),
    ("unit_price_usd",         "单价",              "USD", "decimal2", 10, True, None),
    ("validation_status",      "审核状态",          None,  "enum",     11, True,
     {"PENDING": "待审核", "ACCEPTED": "已接受", "DECLINED": "已拒绝", "AUTOMATED": "自动通过"}),
    ("is_void",                "合并后是否为取消单", None, "bool",     12, True,
     {"0": "否", "1": "是"}),
    ("ad_id",                  "广告ID",            None,  "text",     13, True,  None),
    ("click_date",             "点击日期",          None,  "datetime", 14, True,  None),
    ("correction_reason",      "纠正原因",          None,  "enum",     15, True,
     {"INVALID_CREDIT_CARD": "无效信用卡", "RETURNED_MERCHANDISE": "退货",
      "DUPLICATED_ORDER": "重复订单", "CANT_SHIP_OR_SOLD_OUT": "无法发货或售罄",
      "UNQUALIFIED_LEAD": "不合格线索", "QUALIFIED_LEAD": "合格线索",
      "OTHER_REASON": "其他原因"}),
    ("country",                "交易国家",          None,  "text",     16, True,  None),
    ("coupon",                 "优惠码ID",          None,  "text",     17, True,  None),
    ("posting_date",           "推送时间",          None,  "datetime", 18, True,  None),
    ("publisher_id",           "渠道商ID",          None,  "text",     19, True,  None),
    ("publisher_name",         "渠道商名称",        None,  "text",     20, True,  None),
]

ORDER_LABEL_SEED = [
    ("net_sale_usd",        "净销售金额",   "USD", "decimal2", 1, True, None),
    ("net_commission_usd",  "净佣金金额",   "USD", "decimal2", 2, True, None),
    ("detail_count",        "佣金明细条数", None,  "int",      3, True, None),
    ("is_void",             "取消单",       None,  "bool",     4, True, {"0": "否", "1": "是"}),
    ("first_event_date",    "首次事件日期", None,  "date",     5, True, None),
    ("last_event_date",     "末次事件日期", None,  "date",     6, True, None),
]


# ---------------------------------------------------------------------------
# V4.130：CJ 模板字段映射种子（api_field_map 的唯一权威配置）。
# source_path 与 GraphQL Object: PublisherCommission 字段一一对应；
# 目标分 fact（统一事实表）/ item（商品子表）/ source_record（原始层幂等键）/
# ext（扩展层 data_json 键）/ __skip__（显式忽略，原始层仍保留）。
# 请求字段必须全部登记，P1-B 落库前按此做「未登记即告警」覆盖检查。
# ---------------------------------------------------------------------------
CJ_TEMPLATE_ID = "cj_publisher_commissions"
CJ_FIELD_MAP_SEED = [
    # ---- 12 个核心确认字段（含同源/派生）----
    ("commissionId",                    "fact.commission_id",                  "direct",      "ID / 幂等键"),
    ("commissionId",                    "source_record.external_id",           "direct",      "原始层幂等键"),
    ("advertiserName",                  "fact.advertiser_name",                "direct",      "广告主名称"),
    ("advertiserName",                  "fact.campaign_name",                  "direct",      "Q3：品牌名称同取顶层 advertiserName"),
    ("orderId",                         "fact.order_id",                       "direct",      "订单号 / 合并键"),
    ("eventDate",                       "fact.event_date",                     "utc_date",    "Q2：事件日期 UTC→业务日期"),
    ("actionStatus",                    "fact.action_status",                  "enum_map",    "订单状态（官方小写枚举）"),
    ("actionTrackerName",               "fact.event_name",                     "direct",      "Q4：事件名称"),
    ("saleAmountUsd",                   "fact.sale_amount_usd",                "decimal",     "销售金额"),
    ("pubCommissionAmountUsd",          "fact.commission_amount_usd",          "decimal",     "发布者佣金金额"),
    ("saleAmountUsd",                   "fact.unit_price_usd",                 "derived",     "主表均价 = sale / qty_internal（中间量，不落列）"),
    ("validationStatus",                "fact.validation_status",              "enum_map",    "审核状态"),
    ("__derived__is_void",              "fact.is_void",                        "derived",     "按订单合并净额归零判定取消单；官方无 REVERSED 枚举"),
    # ---- V4.127 提升可见的 6 个新增业务字段 ----
    ("aid",                             "fact.ad_id",                          "direct",      "广告 ID（可空）"),
    ("clickDate",                       "fact.click_date",                     "utc_datetime", "点击日期（可空）"),
    ("correctionReason",                "fact.correction_reason",              "enum_map",    "纠正原因"),
    ("country",                         "fact.country",                        "direct",      "交易国家"),
    ("coupon",                          "fact.coupon",                         "direct",      "优惠码 ID"),
    ("publisherId",                     "fact.publisher_id",                   "direct",      "渠道商 CID（与连接校验）"),
    ("publisherName",                   "fact.publisher_name",                 "direct",      "渠道商名称"),
    # ---- 合并 / 对账技术列 ----
    ("original",                        "fact.original",                       "bool",        "原始单 true / 修正单 false"),
    ("originalActionId",                "fact.original_action_id",             "direct",      "原始与修正的关联键"),
    ("postingDate",                     "fact.posting_date",                   "utc_datetime", "对账保留；增量水位按 eventDate"),
    # ---- 商品子表 ----
    ("items[].sku",                     "item.sku",                            "direct",      "商品 SKU"),
    ("items[].quantity",                "item.quantity",                       "direct",      "数量（增量可负，不进统一表）"),
    ("items[].perItemSaleAmountUsd",    "item.unit_price_usd",                 "direct",      "子表精确单价（USD），多 SKU 以此为准"),
    ("items[].totalCommissionUsd",      "item.commission_usd",                 "decimal",     "子表佣金（USD）"),
    # ---- 有请求但无统一列：落扩展层，零丢失 ----
    ("actionTrackerId",                 "ext.action_tracker_id",               "direct",      "广告主定义的动作 ID"),
    ("advertiserId",                    "ext.advertiser_id",                   "direct",      "广告主 CID"),
    ("initiatingBrowser",               "ext.initiating_browser",              "direct",      "发起浏览器"),
    ("initiatingDeviceName",            "ext.initiating_device_name",          "direct",      "发起设备名"),
    ("initiatingDeviceType",            "ext.initiating_device_type",          "direct",      "发起设备类型"),
    ("isCrossDevice",                   "ext.is_cross_device",                 "bool",        "跨设备归因"),
    ("lockingDate",                     "ext.locking_date",                    "utc_datetime", "锁定日期"),
    ("lockingMethod",                   "ext.locking_method",                  "direct",      "锁定方式"),
    ("pubCommissionAmountPubCurrency",  "ext.pub_commission_amount_pub_currency", "decimal",  "发布者币种佣金"),
    ("reviewedStatus",                  "ext.reviewed_status",                 "direct",      "广告主复核状态"),
    ("saleAmountPubCurrency",           "ext.sale_amount_pub_currency",        "decimal",     "发布者币种销售额"),
    ("shopperId",                       "ext.shopper_id",                      "direct",      "购物者 ID（发布者可见）"),
    ("source",                          "ext.source",                          "direct",      "交易来源"),
    ("websiteId",                       "ext.website_id",                      "direct",      "网站 ID"),
    ("websiteName",                     "ext.website_name",                    "direct",      "网站名称"),
    ("verticalAttributes.brand",        "ext.vertical_brand",                  "direct",      "广告主自定义属性 · 品牌"),
    ("verticalAttributes.campaignId",   "ext.vertical_campaign_id",            "direct",      "广告主自定义属性 · 活动 ID"),
    ("verticalAttributes.itemId",       "ext.vertical_item_id",                "direct",      "广告主自定义属性 · 商品 ID"),
    ("verticalAttributes.itemName",     "ext.vertical_item_name",              "direct",      "广告主自定义属性 · 商品名"),
    ("verticalAttributes.custCountry",  "ext.vertical_cust_country",           "direct",      "广告主自定义属性 · 客户国家"),
    ("items[].perItemSaleAmountPubCurrency", "ext.item_per_item_sale_pub_currency", "decimal", "子表发布者币种单价"),
    ("items[].totalCommissionPubCurrency",   "ext.item_total_commission_pub_currency", "decimal", "子表发布者币种佣金"),
    # ---- 显式忽略（原始层仍保留，不参与统一表/扩展层）----
    ("actionType",                      "__skip__",                            "skip",        "本轮口径不使用"),
    ("clickReferringURL",               "__skip__",                            "skip",        "非必需，避免解析开销"),
    ("verticalAttributes.campaignName", "__skip__",                            "skip",        "Q3 后品牌名取顶层 advertiserName，避免同源歧义"),
    ("situations",                      "__skip__",                            "skip",        "解析慢，首版不取"),
    ("situationDetails",                "__skip__",                            "skip",        "解析慢，首版不取"),
]


def _current_order_view_sql(conn) -> str:
    """优先用库中持久化的视图定义（改名后已同步），否则用代码内默认定义。"""
    row = conn.execute(
        text("SELECT sql FROM schema_view_def WHERE name=:n"), {"n": ORDER_VIEW_NAME}
    ).first()
    return row[0] if row else ORDER_VIEW_SQL


def _sync_order_view(conn) -> None:
    """重建订单视图：列改名或口径调整后调用，保证视图与事实表列一致。"""
    conn.execute(text(f"DROP VIEW IF EXISTS {ORDER_VIEW_NAME}"))
    conn.execute(text(_current_order_view_sql(conn)))


def _seed_field_labels(conn) -> int:
    """幂等写入展示名配置。已存在的行不改（用户可在管理端覆盖），只补缺失行。"""
    added = 0
    for scope, rows in (("fact", FIELD_LABEL_SEED), ("order_final", ORDER_LABEL_SEED)):
        for column_key, label, unit, fmt, sort_no, visible, enum_map in rows:
            exists = conn.execute(
                text("SELECT 1 FROM api_field_label WHERE scope=:s AND column_key=:k"),
                {"s": scope, "k": column_key},
            ).first()
            if exists:
                continue
            conn.execute(
                text("""INSERT INTO api_field_label
                        (scope, column_key, label, unit, format, enum_map_json, sort_no, visible)
                        VALUES (:s, :k, :l, :u, :f, :e, :n, :v)"""),
                {"s": scope, "k": column_key, "l": label, "u": unit, "f": fmt,
                 "e": json.dumps(enum_map, ensure_ascii=False) if enum_map else None,
                 "n": sort_no, "v": 1 if visible else 0},
            )
            added += 1
    return added


# ---------------------------------------------------------------------------
# 保障三：版本化迁移。每个版本函数只做一次，执行记录落 schema_migrations。
# ---------------------------------------------------------------------------
def _migrate_v4127_1(conn) -> str:
    """V4.127.1：统一数据存储骨架（表由 create_all 建；这里建视图 + 种子配置）。"""
    conn.execute(
        text("INSERT OR IGNORE INTO schema_view_def(name, sql, updated_at) VALUES (:n, :s, CURRENT_TIMESTAMP)"),
        {"n": ORDER_VIEW_NAME, "s": ORDER_VIEW_SQL},
    )
    _sync_order_view(conn)
    labels = _seed_field_labels(conn)
    return f"订单视图 {ORDER_VIEW_NAME} 已就绪；展示名配置新增 {labels} 行"


def _migrate_v4128_1(conn) -> str:
    """V4.128.1：核对轻量 ADD COLUMN 已补齐测试详情字段，并留下版本记录。"""
    have = {c["name"] for c in inspect(conn).get_columns("api_connection")}
    need = {"last_test_url", "last_test_request_body", "last_test_response_text"}
    missing = need - have
    if missing:
        raise RuntimeError("api_connection 缺少测试详情字段：" + ", ".join(sorted(missing)))
    return "api_connection 测试详情字段（请求链接 / 请求体 / 响应原文）已就绪"


def _migrate_v4130_1(conn) -> str:
    """V4.130.1：把 CJ 请求字段 ↔ 统一字段映射登记落库，作为 P1-B 覆盖检查的配置源。"""
    added = 0
    for source, target, transform, note in CJ_FIELD_MAP_SEED:
        exists = conn.execute(
            text("""SELECT 1 FROM api_field_map
                    WHERE template_id=:t AND source_path=:s AND target_field=:g AND version=1"""),
            {"t": CJ_TEMPLATE_ID, "s": source, "g": target},
        ).first()
        if exists:
            continue
        conn.execute(
            text("""INSERT INTO api_field_map
                    (template_id, source_path, target_field, transform, version, enabled, note)
                    VALUES (:t, :s, :g, :r, 1, 1, :n)"""),
            {"t": CJ_TEMPLATE_ID, "s": source, "g": target, "r": transform, "n": note},
        )
        added += 1
    return f"CJ 字段映射登记新增 {added} 行（含 fact / item / ext / __skip__）"


def _migrate_v4133_1(conn) -> str:
    """V4.133.1：新增列表时间列 config_updated_at / last_sync_at 并回填历史值。

    列由 ensure_schema 的 ADD COLUMN 补齐；这里核对存在性并为历史连接回填：
    配置更新时间取 updated_at（旧库里它随配置变更刷新，且未被本版回写前是唯一可用值），
    API 同步时间取 last_test_at（旧库只有测试才算请求，拉取是 V4.132 才新增的）。
    """
    cols = {c["name"] for c in inspect(conn).get_columns("api_connection")}
    need = {"config_updated_at", "last_sync_at"}
    missing = need - cols
    if missing:
        raise RuntimeError("api_connection 缺少列表时间列：" + ", ".join(sorted(missing)))
    conn.execute(text("""UPDATE api_connection
                         SET config_updated_at = COALESCE(updated_at, created_at)
                         WHERE config_updated_at IS NULL"""))
    conn.execute(text("""UPDATE api_connection
                         SET last_sync_at = last_test_at
                         WHERE last_sync_at IS NULL AND last_test_at IS NOT NULL"""))
    return "列表时间列已就绪：config_updated_at / last_sync_at（历史值已回填）"


def _migrate_v4134_1(conn) -> str:
    """V4.134.1：api_fetch_run 增加 run_mode（运行来源），历史记录一律视为手动。"""
    cols = {c["name"] for c in inspect(conn).get_columns("api_fetch_run")}
    if "run_mode" not in cols:
        raise RuntimeError("api_fetch_run 缺少 run_mode 列")
    conn.execute(text("""UPDATE api_fetch_run SET run_mode='manual'
                         WHERE run_mode IS NULL OR run_mode=''"""))
    return "运行记录来源标记已就绪：run_mode（历史记录回填为 manual）"


MIGRATIONS = [
    ("V4.127.1", "advertiser_unified_schema", _migrate_v4127_1),
    ("V4.128.1", "advertiser_test_detail", _migrate_v4128_1),
    ("V4.130.1", "advertiser_field_map_seed", _migrate_v4130_1),
    ("V4.133.1", "advertiser_list_timestamps", _migrate_v4133_1),
    ("V4.134.1", "advertiser_fetch_run_mode", _migrate_v4134_1),
]


def _run_versioned_migrations() -> list[str]:
    applied_log = []
    with engine.begin() as conn:
        applied = {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}
        for version, name, fn in MIGRATIONS:
            if version in applied:
                continue
            note = fn(conn) or ""
            conn.execute(
                text("INSERT INTO schema_migrations(version, name, applied_at, note) "
                     "VALUES (:v, :n, CURRENT_TIMESTAMP, :note)"),
                {"v": version, "n": name, "note": note},
            )
            applied_log.append(version)
    if applied_log:
        print("[migrate] schema versions applied:", ", ".join(applied_log))
    return applied_log


def ensure_schema() -> list[str]:
    """建表 + 补列 + 版本化迁移 + 视图同步（可重复执行）。"""
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    applied = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}"))
                applied.append(f"{table.name}.{col.name}")
    if applied:
        print("[migrate] added columns:", ", ".join(applied))
    _run_versioned_migrations()
    return applied


# ---------------------------------------------------------------------------
# rename_column：物理列改名 + 三处数据层同步 + 一处代码引用审计（保障三）。
# 语义变更才用；只改「叫法」优先改 api_field_label，不动物理列。
# ---------------------------------------------------------------------------
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CODE_DIRS = ("backend", "frontend/src")
_CODE_EXT = (".py", ".ts", ".tsx")
# 这些文件里的旧名是「迁移历史 / 测试断言」本身，不算待同步的业务引用
_IGNORE_FILES = ("migrations.py", "test_advertiser_schema_v4127.py", "models.py")


def audit_column_references(old: str) -> list[str]:
    """扫描写入代码 / 报表查询中仍使用旧列名的位置；返回 file:line:content。"""
    root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for d in _CODE_DIRS:
        for path in (root / d).rglob("*"):
            if path.suffix not in _CODE_EXT or path.name in _IGNORE_FILES:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            # 只认「列引用」形态：obj.column / ["column"] / 'column' / "column"，
            # 避免 english 文案里出现同名单词造成误报。
            pattern = re.compile(
                rf"\.{re.escape(old)}\b|[\"']{re.escape(old)}[\"']|\[\s*[\"']{re.escape(old)}[\"']\s*\]"
            )
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(root)}:{i}:{line.strip()[:160]}")
    return hits


def rename_column(old: str, new: str, table: str = "api_unified_fact", force: bool = False) -> dict:
    """一次同步四处：① 物理列 ② 映射表 ③ 视图 ④ 代码引用审计。

    默认 strategy：发现代码层仍有旧名引用就抛错（不再写库前先由人工改代码）；
    确认引用已全部处理或本就是历史文本时传 force=True 完成迁移。
    调用前必须已完成数据库备份（scripts/rollback.py backup-db）。
    """
    if not _IDENT.match(old) or not _IDENT.match(new) or not _IDENT.match(table):
        raise ValueError("列名/表名不合法，只允许字母、数字、下划线且不能以数字开头")
    refs = audit_column_references(old)
    if refs and not force:
        raise RuntimeError("以下代码仍引用旧列名，请先同步后再迁移（或确认后 force=True）：\n" + "\n".join(refs[:20]))

    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        if old not in cols:
            raise RuntimeError(f"{table} 中不存在列 {old}")
        if new in cols:
            raise RuntimeError(f"{table} 中已存在列 {new}，拒绝覆盖")
        conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"))
        conn.execute(
            text("UPDATE api_field_map SET target_field = :new, updated_at = CURRENT_TIMESTAMP "
                 "WHERE target_field = :old"),
            {"old": f"fact.{old}", "new": f"fact.{new}"},
        )
        conn.execute(
            text("UPDATE api_field_label SET column_key = :new, updated_at = CURRENT_TIMESTAMP "
                 "WHERE scope = 'fact' AND column_key = :old"),
            {"old": old, "new": new},
        )
        # 视图定义同步：把持久化的 SQL 中旧列名整体替换为新列名（词边界精确匹配）
        view_sql = _current_order_view_sql(conn)
        new_sql = re.sub(rf"\b{re.escape(old)}\b", new, view_sql)
        conn.execute(
            text("INSERT INTO schema_view_def(name, sql, updated_at) VALUES (:n, :s, CURRENT_TIMESTAMP) "
                 "ON CONFLICT(name) DO UPDATE SET sql=excluded.sql, updated_at=CURRENT_TIMESTAMP"),
            {"n": ORDER_VIEW_NAME, "s": new_sql},
        )
        _sync_order_view(conn)
        conn.execute(
            text("INSERT INTO schema_migrations(version, name, applied_at, note) "
                 "VALUES (:v, :n, CURRENT_TIMESTAMP, :note)"),
            {"v": f"rename-{old}-to-{new}"[:32], "n": "rename_column",
             "note": f"{table}.{old} → {new}；映射/标签/视图已同步；代码引用 {len(refs)} 处"},
        )
    return {"table": table, "old": old, "new": new, "code_refs": refs}


def verify_schema() -> dict:
    """一致性校验：视图、事实表 20 字段、展示名种子是否齐全。"""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with SessionLocal() as db:
        fact_cols = {c["name"] for c in insp.get_columns("api_unified_fact")}
        labels = db.execute(text("SELECT column_key FROM api_field_label WHERE scope='fact'")).scalars().all()
        versions = db.execute(text("SELECT version FROM schema_migrations")).scalars().all()
        map_count = db.execute(
            text("SELECT COUNT(*) FROM api_field_map WHERE template_id=:t AND enabled=1"),
            {"t": CJ_TEMPLATE_ID},
        ).scalar()
    return {
        "tables_ok": all(t in tables for t in (
            "api_source_record", "api_unified_fact", "api_fact_item", "api_fact_ext",
            "api_field_map", "api_field_label", "schema_migrations", "schema_view_def",
            "api_fetch_task", "api_fetch_run")),
        "view_ok": ORDER_VIEW_NAME in set(insp.get_view_names()) or ORDER_VIEW_NAME in tables,
        "business_fields": len([c for c in fact_cols if c not in {
            "id", "source_record_id", "external_id", "template_id", "connection_id",
            "run_id", "original", "original_action_id", "created_at", "updated_at"}]),
        "label_count": len(set(labels)),
        "map_count": int(map_count or 0),
        "versions": list(versions),
    }
