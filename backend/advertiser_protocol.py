# -*- coding: utf-8 -*-
"""V4.138 / P4 · 广告主数据：渠道协议适配层（验证"加模板+加映射不改代码"）。

设计目标：
  把各联盟 API 的差异全部下沉到「模板 protocol 配置」，业务代码只认协议能力，
  不再写死某一家。新增渠道 = 在 advertiser_api.PRESET_TEMPLATES 加一条 protocol
  + 在 migrations 加一份字段映射 seed，请求 / 拉取 / 落库 / 报表链路零改动。

协议能力（protocol 字段，全部可选；缺省 = CJ 行为，保证 V4.124–V4.137 完全兼容）：
  style            graphql | rest                默认 graphql
  http_method      POST / GET                    默认按 style（graphql→POST, rest→GET）
  auth             bearer | query_param         默认 bearer
  token_param      query_param 时的参数名        默认 accessToken
  cid_in           body | path | query | none    默认 body；none = 模板无 CID 概念（PartnerStack 按文档只填 API Key）
  path_template    rest 的 URL 路径模板          默认 ""
  records_path     明细数组在响应中的点分路径    默认 data.<query_name>.records
  count_path       总数路径                      默认 data.<query_name>.count
  cursor_path      游标路径                      默认 data.<query_name>.maxCommissionId
  complete_path    结束标志路径                  默认 data.<query_name>.payloadComplete
  external_id_path 幂等键在明细中的路径          默认 commissionId
  date_params      rest 日期参数名映射           默认 {"since":"startDate","before":"endDate"}
  date_value_format epoch_ms：日期字符串转毫秒时间戳（PartnerStack）
  endpoint_path    rest 固定路径后缀（PartnerStack v2/rewards）
  extra_params     rest 固定 query 参数（limit / order_by 等）
  cursor_from_last 游标不在响应元数据中，取最后一条记录的 external_id_path（PartnerStack）
  complete_invert  complete_path 为 has_more，结束标志需反转（PartnerStack）

不在本层处理：Token 加解密（advertiser_api）、字段映射与目标列（advertiser_ingest）、
调度与限流（advertiser_scheduler）、报表查询（advertiser_reports）。
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Optional

import advertiser_api


def _dig(obj: Any, path: str) -> Any:
    """按点分路径取值；空路径返回 None。仅支持 dict 逐层，数组路径交给调用方。"""
    if not path or not isinstance(obj, dict):
        return None
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _date_value(text: str, value_format: str) -> Any:
    """按协议把系统统一的 UTC 窗口字符串转成上游要求的日期值。"""
    value = str(text or "").strip()
    if value_format != "epoch_ms" or not value:
        return value
    try:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            moment = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return int(moment.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        # 已经是毫秒时间戳时原样透传；非法值由上游返回参数错误，便于排查。
        return value


def protocol_of(template_code: str) -> dict:
    """取模板协议配置；未知模板返回 CJ 缺省协议（向后兼容）。"""
    tpl = advertiser_api.template_by_code(template_code or "") or {}
    proto = dict(tpl.get("protocol") or {})
    proto.setdefault("style", "graphql")
    proto.setdefault("auth", "bearer")
    proto.setdefault("cid_in", "body")
    proto.setdefault("external_id_path", "commissionId")
    return proto


def default_paths(query_name: str) -> dict:
    """GraphQL 缺省响应路径（V4.129 CJ 契约），供协议未声明时回退。"""
    base = f"data.{query_name}"
    return {
        "records_path": f"{base}.records",
        "count_path": f"{base}.count",
        "cursor_path": f"{base}.maxCommissionId",
        "complete_path": f"{base}.payloadComplete",
    }


def build_request(*, template_code: str, endpoint: str, token: str, cid: str,
                  since_event_date: str, before_event_date: str,
                  since_commission_id: str = "") -> dict:
    """按模板协议构造一次请求，返回 method / url / headers / json_body / params。

    业务代码（test_connection / fetch_window）只消费这个契约，不关心是 GraphQL
    还是 REST，也不关心 Token 放在 Header 还是 Query。
    """
    tpl = advertiser_api.template_by_code(template_code or "") or {}
    proto = protocol_of(template_code)
    style = proto.get("style", "graphql")
    method = str(proto.get("http_method") or ("POST" if style == "graphql" else "GET")).upper()
    url = (endpoint or "").strip() or (tpl.get("default_endpoint") or "")
    suffix = str(proto.get("endpoint_path") or "").strip("/")
    if suffix and not url.rstrip("/").endswith(suffix):
        url = url.rstrip("/") + "/" + suffix

    headers: dict = {"Content-Type": "application/json"}
    json_body: Optional[dict] = None
    params: dict = dict(proto.get("extra_params") or {})

    # 认证方式下沉到协议：bearer 走 Header，query_param 走 URL 参数
    if proto.get("auth", "bearer") == "query_param":
        params[str(proto.get("token_param") or "accessToken")] = token
    else:
        headers["Authorization"] = f"Bearer {token}"

    # path 型 cid：把 {cid} 占位符替换进 URL 路径（如 Awin /publishers/{cid}/transactions/）
    if proto.get("cid_in") == "path" and proto.get("path_template"):
        suffix = str(proto["path_template"]).replace("{cid}", str(cid))
        url = url.rstrip("/") + "/" + suffix.lstrip("/")

    if style == "graphql":
        json_body = advertiser_api.build_detail_payload(
            cid, since_event_date, before_event_date, since_commission_id)
    else:
        names = dict(proto.get("date_params") or {"since": "startDate", "before": "endDate"})
        value_format = str(proto.get("date_value_format") or "")
        if names.get("since"):
            params[str(names["since"])] = _date_value(since_event_date, value_format)
        if names.get("before"):
            params[str(names["before"])] = _date_value(before_event_date, value_format)
        # V4.144：cid_in=none 表示模板按文档无 CID 概念，即使历史连接残留 cid
        # 也绝不注入任何发布者 ID 参数；path 型已在上方单独处理。
        if cid and proto.get("cid_in") in ("query", "body"):
            cid_param = str(proto.get("cid_param") or "publisherId")
            if cid_param:
                params[cid_param] = cid
        if since_commission_id and proto.get("cursor_param"):
            params[str(proto["cursor_param"])] = since_commission_id

    return {"method": method, "url": url, "headers": headers,
            "json_body": json_body, "params": params}


def parse_response(*, template_code: str, body: dict) -> dict:
    """按模板协议从上游响应中提取 records / count / cursor / complete。

    返回统一契约：records(list[dict]) / count(int) / cursor(str) / complete(bool)。
    """
    tpl = advertiser_api.template_by_code(template_code or "") or {}
    proto = protocol_of(template_code)
    style = proto.get("style", "graphql")
    paths = default_paths(str(tpl.get("query_name") or ""))
    for key in ("records_path", "count_path", "cursor_path", "complete_path"):
        if key in proto:
            paths[key] = proto[key]

    records_raw = _dig(body, paths.get("records_path") or "")
    if records_raw is None and style == "rest" and isinstance(body, list):
        records_raw = body  # 顶层数组型响应（如 Awin transactions）
    records = [r for r in (records_raw or []) if isinstance(r, dict)]
    count_raw = _dig(body, paths.get("count_path") or "")
    if count_raw is None:
        count_raw = len(records)
    cursor = _dig(body, paths.get("cursor_path") or "")
    raw_complete = _dig(body, paths.get("complete_path") or "")
    if raw_complete is None:
        complete = True
    else:
        complete = bool(raw_complete)
        if proto.get("complete_invert"):
            complete = not complete
    # PartnerStack 型游标：响应只给 has_more，游标取本页最后一条记录的 key。
    if not cursor and proto.get("cursor_from_last") and records:
        cursor = records[-1].get(str(proto.get("external_id_path") or "key")) or ""
    # rest 无游标协议：单窗口即完成（数据窗口由调度层分片保证）
    if style == "rest" and not paths.get("cursor_path") and not proto.get("cursor_from_last"):
        complete = True
        cursor = ""
    return {
        "records": records,
        "count": int(count_raw or 0),
        "cursor": str(cursor or ""),
        "complete": bool(complete) if complete is not None else True,
    }


def external_id_of(record: dict, template_code: str) -> str:
    """按协议取幂等键；缺省 commissionId。第二模板可声明 id / transactionId 等。"""
    proto = protocol_of(template_code)
    value = _dig(record, str(proto.get("external_id_path") or "commissionId"))
    return str(value or "").strip()


def request_display(*, method: str, url: str, params: dict) -> str:
    """给「测试」抽屉显示的完整请求 URL（含 query），与真实请求一致。"""
    if not params:
        return url
    from urllib.parse import urlencode
    sep = "&" if "?" in url else "?"
    return url + sep + urlencode(params)
