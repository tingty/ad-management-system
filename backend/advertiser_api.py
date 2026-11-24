"""V4.124 · 广告主数据模块：API 模板与连接层。

设计依据：docs/广告主数据模块功能开发文档_20261124.html（唯一维护文档）。

  职责边界（P0 / V4.129 起）：
  1. 预置标准模板：把「接口怎么调」沉淀为只读模板（CJ publisherCommissions → PublisherCommission 明细）。
  2. 连接实例：用户只填 API Token / CID / Endpoint，其余继承模板。
  3. 测试连接：真实调用上游 API（1 天窗口），请求 publisherCommissions.records，
     即逐条拉取官方 Object: PublisherCommission（订单佣金明细，含 items 与
     advertiser-supplied custom attributes），不落任何凭据到日志。

  不做（留后续版本）：
  - 明细幂等落库与统一事实表映射（P1-B）、自动调度执行（P2）、报表（P3）。

安全约定：
  - Token 加密入库（标准库实现：HMAC-SHA256 派生密钥 + CTR 流 + encrypt-then-MAC），
    密钥来自 AUTH_SECRET，容器重启后一致；不新增第三方依赖。
  - Token 不回显、不写日志、不进审计 detail；列表仅显示掩码。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from typing import Optional

import httpx

from auth import SECRET

# ---------------- Token 加解密（零新增依赖） ----------------
_TOKEN_KEY = hashlib.sha256(SECRET + b"|advertiser-api-token-v1").digest()


def _keystream(nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(_TOKEN_KEY, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_token(plain: str) -> str:
    if not plain:
        return ""
    raw = plain.encode("utf-8")
    nonce = os.urandom(16)
    cipher = bytes(a ^ b for a, b in zip(raw, _keystream(nonce, len(raw))))
    tag = hmac.new(_TOKEN_KEY, nonce + cipher, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + tag + cipher).decode().rstrip("=")


def decrypt_token(stored: str) -> str:
    if not stored:
        return ""
    try:
        pad = "=" * (-len(stored) % 4)
        blob = base64.urlsafe_b64decode(stored + pad)
        nonce, tag, cipher = blob[:16], blob[16:32], blob[32:]
        expect = hmac.new(_TOKEN_KEY, nonce + cipher, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expect):
            return ""
        return bytes(a ^ b for a, b in zip(cipher, _keystream(nonce, len(cipher)))).decode("utf-8")
    except Exception:
        return ""


def mask_token(plain: str) -> str:
    if not plain:
        return ""
    if len(plain) <= 8:
        return "*" * len(plain)
    return plain[:4] + "*" * (len(plain) - 8) + plain[-4:]


# ---------------- 预置模板（只读，模板规则随代码发布） ----------------
# 用户只填 Token / CID / Endpoint；查询骨架、分页、限流、字段映射由模板固化。
PRESET_TEMPLATES: list[dict] = [
    {
        "code": "cj_publisher_commissions",
        "name": "CJ联盟",
        "vendor": "CJ Affiliate",
        "description": "读取 publisherCommissions 返回的每条 PublisherCommission（一个订单的一笔佣金明细，含原始单与修正单）。",
        # V4.129：明确请求对象。官方 Schema 有两个 Object：PublisherCommissions（结果包装）
        # 与 PublisherCommission（逐条佣金明细）。本系统要的是后者——订单明细，不是统计报表。
        "record_object": "PublisherCommission",
        "record_object_desc": (
            "A record of a publisher commission event, potentially including items purchased "
            "and advertiser-supplied custom attributes."
        ),
        "method": "POST",
        "auth_type": "bearer",
        "default_endpoint": "https://commissions.api.cj.com/query",
        "required_fields": [
            {"key": "token", "label": "API Token", "type": "password", "required": True},
            {"key": "cid", "label": "发布者 CID", "type": "text", "required": True},
            {"key": "endpoint", "label": "Endpoint", "type": "text", "required": False},
        ],
        "query_name": "publisherCommissions",
        "pagination": "maxCommissionId → sinceCommissionId，直到 payloadComplete=true",
        "limits": "日期跨度≤31天；单次≤10000条；200次/5分钟",
        "framework_version": "advertiser-api/1.0",
        "status": "active",
    },
]


def template_by_code(code: str) -> Optional[dict]:
    for t in PRESET_TEMPLATES:
        if t["code"] == code:
            return t
    return None


# ---------------- CJ GraphQL 客户端 ----------------
# V4.129：明确请求对象为 PublisherCommission（订单佣金明细，不是统计报表）。
# 官方定义：A record of a publisher commission event, potentially including items
# purchased and advertiser-supplied custom attributes.
# 官方查询字段是 publisherCommissions，其返回包装 Object 是 PublisherCommissions；
# 真正的明细在 records: [PublisherCommission!]! 中，本模板显式请求 records。
PUBLISHER_COMMISSION_FIELDS = """
      aid
      actionStatus
      actionTrackerId
      actionTrackerName
      actionType
      advertiserId
      advertiserName
      clickDate
      clickReferringURL
      commissionId
      correctionReason
      country
      coupon
      eventDate
      initiatingBrowser
      initiatingDeviceName
      initiatingDeviceType
      isCrossDevice
      lockingDate
      lockingMethod
      orderId
      original
      originalActionId
      postingDate
      pubCommissionAmountPubCurrency
      pubCommissionAmountUsd
      publisherId
      publisherName
      reviewedStatus
      saleAmountPubCurrency
      saleAmountUsd
      shopperId
      source
      validationStatus
      websiteId
      websiteName
      items {
        quantity
        sku
        perItemSaleAmountPubCurrency
        perItemSaleAmountUsd
        totalCommissionPubCurrency
        totalCommissionUsd
      }
      verticalAttributes {
        brand
        campaignId
        campaignName
        itemId
        itemName
        custCountry
      }
""".lstrip("\n").rstrip("\n")

_DETAIL_QUERY = f"""
query PublisherCommission($forPublishers: [String!]!, $sinceEventDate: String, $beforeEventDate: String, $sinceCommissionId: String) {{
  publisherCommissions(forPublishers: $forPublishers,
                       sinceEventDate: $sinceEventDate,
                       beforeEventDate: $beforeEventDate,
                       sinceCommissionId: $sinceCommissionId) {{
    count
    limit
    maxCommissionId
    payloadComplete
    records {{
{PUBLISHER_COMMISSION_FIELDS}
    }}
  }}
}}
"""


def _safe_error(text: str) -> str:
    """脱敏上游错误：去掉可能回显的 token 片段与换行，限制长度。"""
    s = re.sub(r"Bearer\s+\S+", "Bearer ***", text or "", flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300]


def build_detail_payload(cid: str, since_event_date: str, before_event_date: str,
                         since_commission_id: str = "") -> dict:
    """构造 PublisherCommission 明细查询（含 records）；Token 不进入请求体。

    sinceCommissionId 是官方游标分页参数，P1-B 落库时可续页；测试连接不传。
    """
    variables = {
        "forPublishers": [cid],
        "sinceEventDate": since_event_date,
        "beforeEventDate": before_event_date,
    }
    if since_commission_id:
        variables["sinceCommissionId"] = since_commission_id
    return {"query": _DETAIL_QUERY, "variables": variables}


def build_test_payload(cid: str, since_event_date: str, before_event_date: str) -> dict:
    """兼容旧调用；V4.129 起「测试连接」本身就是一次 PublisherCommission 明细请求。"""
    return build_detail_payload(cid, since_event_date, before_event_date)


def _redact_text(text: str, token: str = "") -> str:
    """脱敏完整响应文本：只替换 Token 本体与 Bearer 片段，不截断内容。"""
    s = text or ""
    if token:
        s = s.replace(token, "***")
    return re.sub(r"Bearer\s+\S+", "Bearer ***", s, flags=re.I)


def _redact_record(record: dict, token: str = "") -> dict:
    """脱敏单条 PublisherCommission 明细（递归处理 items / verticalAttributes 中的字符串）。"""
    def walk(value):
        if isinstance(value, str):
            return _redact_text(value, token)
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value
    return walk(record) if isinstance(record, dict) else record


def _test_envelope(*, ok: bool, error: str, count: int, http_code: int,
                   url: str = "", payload: Optional[dict] = None,
                   response_text: str = "", response: Optional[dict] = None,
                   **extra) -> dict:
    """V4.128 / V4.129：所有返回路径共用同一契约，保证右侧滑窗永远有完整请求/响应可看。"""
    from datetime import datetime, timezone
    result = {
        "ok": bool(ok),
        "error": error or "",
        "count": int(count or 0),
        "http_code": int(http_code or 0),
        "request_url": url or "",
        "request_method": "POST",
        "request_body": payload or {},
        "response_text": response_text or "",
        "response": response,
        "tested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload_complete": False,
        "max_commission_id": "",
        # V4.129：明确请求对象与真正拉到的明细条数（count 仍保留官方包装层语义）
        "record_object": "PublisherCommission",
        "record_count": 0,
        "sample_records": [],
    }
    result.update(extra)
    return result


async def test_connection(*, template_code: str, endpoint: str, token: str, cid: str,
                          since_event_date: str, before_event_date: str,
                          timeout_sec: float = 20.0) -> dict:
    """真实调用上游 API，逐条拉取 PublisherCommission 订单佣金明细。异常归为 ok=False。

    V4.128：请求 URL / GraphQL 请求体 / 上游完整响应原文统一返回，供「测试」右侧滑窗查阅；
    V4.129：请求体显式包含 publisherCommissions.records（Object: PublisherCommission），
    返回 record_count / sample_records；Token 只用于 Authorization 头，绝不写入请求体、
    结果、响应文本或日志。
    """
    tpl = template_by_code(template_code)
    url = (endpoint or "").strip() or ((tpl or {}).get("default_endpoint") or "")
    if not tpl:
        return _test_envelope(ok=False, error="未知模板，无法测试连接", count=0, http_code=0, url=url)
    if not token or not cid:
        return _test_envelope(ok=False, error="API Token 与 CID 均为必填", count=0, http_code=0, url=url)
    if not url.startswith("https://") and not url.startswith("http://"):
        return _test_envelope(ok=False, error="Endpoint 必须是 http(s) 地址", count=0, http_code=0, url=url)

    payload = build_detail_payload(cid, since_event_date, before_event_date)
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as c:
            r = await c.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as e:
        return _test_envelope(
            ok=False, error="网络请求失败：" + _safe_error(_redact_text(str(e), token)), count=0,
            http_code=0, url=url, payload=payload, response_text=_redact_text(str(e), token))

    code = r.status_code
    response_text = _redact_text(r.text, token)
    if code == 401 or code == 403:
        return _test_envelope(
            ok=False, error=f"认证失败（HTTP {code}）：请检查 Token 是否有效", count=0,
            http_code=code, url=url, payload=payload, response_text=response_text)
    if code >= 400:
        return _test_envelope(
            ok=False, error=f"上游返回 HTTP {code}：{_safe_error(response_text)}", count=0,
            http_code=code, url=url, payload=payload, response_text=response_text)
    try:
        body = r.json()
    except Exception:
        return _test_envelope(
            ok=False, error="上游返回不是 JSON", count=0, http_code=code,
            url=url, payload=payload, response_text=response_text)
    errors = body.get("errors")
    if errors:
        msg = errors[0].get("message", "") if isinstance(errors, list) and errors else str(errors)
        return _test_envelope(
            ok=False, error="GraphQL 错误：" + _safe_error(_redact_text(msg, token)), count=0, http_code=code,
            url=url, payload=payload, response_text=response_text,
            response=_redact_record(body, token))
    data = (body.get("data") or {}).get(tpl["query_name"]) or {}
    records = [r for r in (data.get("records") or []) if isinstance(r, dict)]
    records = [_redact_record(r, token) for r in records]
    return _test_envelope(
        ok=True, error="", count=int(data.get("count") or 0), http_code=code,
        url=url, payload=payload, response_text=response_text,
        response=_redact_record(body, token),
        payload_complete=bool(data.get("payloadComplete")),
        max_commission_id=data.get("maxCommissionId") or "",
        record_object=(tpl.get("record_object") or "PublisherCommission"),
        record_count=len(records), sample_records=records[:3])
