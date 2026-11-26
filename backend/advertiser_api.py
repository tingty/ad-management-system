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
        # V4.138 / P4：协议能力显式声明（值与历史硬编码一致，行为零变化）
        "protocol": {
            "style": "graphql", "http_method": "POST", "auth": "bearer", "cid_in": "body",
            "records_path": "data.publisherCommissions.records",
            "count_path": "data.publisherCommissions.count",
            "cursor_path": "data.publisherCommissions.maxCommissionId",
            "complete_path": "data.publisherCommissions.payloadComplete",
            "cursor_param": "sinceCommissionId",
            "external_id_path": "commissionId",
        },
    },
    {
        # V4.138 / P4：第二渠道模板，验证"加模板 + 加映射不改代码"。
        # 真实结构来源：Awin Publisher API /publishers/{publisherId}/transactions/
        # 差异点（对比 CJ）：REST GET、Token 走 query、CID 走 URL path、顶层数组、
        # 幂等键是 id、日期参数名 startDate/endDate、无游标（按窗口分片）。
        "code": "awin_publisher_transactions",
        "name": "Awin联盟",
        "vendor": "Awin",
        "description": "读取 Awin Publisher API 的逐笔交易（transactions），含 saleAmount / commissionAmount / orderRef 等佣金明细字段。",
        "record_object": "Transaction",
        "record_object_desc": "Awin publisher transaction: a commission event with sale and commission amounts.",
        "method": "GET",
        "auth_type": "query_param",
        "default_endpoint": "https://api.awin.com",
        "required_fields": [
            {"key": "token", "label": "API Access Token", "type": "password", "required": True},
            {"key": "cid", "label": "发布者 ID（publisherId）", "type": "text", "required": True},
            {"key": "endpoint", "label": "Endpoint", "type": "text", "required": False},
        ],
        "query_name": "transactions",
        "pagination": "无游标；按 startDate/endDate 窗口分片，单次跨度≤31天",
        "limits": "日期跨度≤31天；顶层数组返回；需在 Awin 后台生成 Access Token",
        "framework_version": "advertiser-api/1.0",
        "status": "active",
        "protocol": {
            "style": "rest", "http_method": "GET", "auth": "query_param", "cid_in": "path",
            "token_param": "accessToken",
            "path_template": "publishers/{cid}/transactions/",
            "records_path": "",  # 顶层数组
            "count_path": "",
            "cursor_path": "",  # 无游标：单窗口即完成
            "complete_path": "",
            "date_params": {"since": "startDate", "before": "endDate"},
            "external_id_path": "id",
        },
    },
    {
        # V4.144：模板名称即 partnerstack，严格按官方 Partner API 文档建模板。
        # 官方参考：GET https://api.partnerstack.com/api/v2/rewards
        #   - 唯一「必要信息」= Partner API Key：Authorization: Bearer <key>；
        #   - 全部 query 参数都是可选筛选（company_key / group_key / customer_key /
        #     keywords / payment_status / currency / creation_source / reward_key /
        #     invoiceable / drip_key / min_created / max_created / limit / order_by /
        #     starting_after / ending_before），无任何必填 CID 或 publisherId；
        #   - 响应 { data: { items: [...], has_more, total }, message, status }。
        # 因此本模板不再沿用 CJ / Awin 的「Token + CID + Endpoint」三元字段要求：
        # 只声明 token，一个 CID 输入框都不渲染，请求也不带文档未确认的参数。
        "code": "partnerstack",
        "name": "PartnerStack",
        "vendor": "PartnerStack",
        "description": "读取 Partner API 的逐笔 Reward（佣金）明细，含公司、客户、交易、金额与审核/支付状态。",
        "record_object": "Reward",
        "record_object_desc": "Reward is what you earn from companies on PartnerStack.",
        "method": "GET",
        "auth_type": "bearer",
        "default_endpoint": "https://api.partnerstack.com/api",
        "required_fields": [
            {"key": "token", "label": "Partner API Key", "type": "password", "required": True},
        ],
        "query_name": "rewards",
        "pagination": "starting_after=本页最后一条 key；data.has_more=true 继续翻页",
        "limits": "limit 1–250（模板固定 250）；min_created/max_created 为毫秒 epoch；Partner API Key 需从 Partner 后台 Settings → API 生成",
        "framework_version": "advertiser-api/1.0",
        "status": "active",
        "protocol": {
            "style": "rest", "http_method": "GET", "auth": "bearer", "cid_in": "none",
            "endpoint_path": "v2/rewards",
            "records_path": "data.items",
            "count_path": "data.total",
            "cursor_path": "",
            "complete_path": "data.has_more",
            "complete_invert": True,
            "cursor_from_last": True,
            "cursor_param": "starting_after",
            "external_id_path": "key",
            "date_params": {"since": "min_created", "before": "max_created"},
            "date_value_format": "epoch_ms",
            "extra_params": {"limit": 250, "order_by": "-created_at"},
        },
    },
    {
        # V4.150：Rakuten Advertising 流量商佣金流水模板。
        # 官方资料：
        #   - https://developers.rakutenadvertising.com/guides/access_tokens
        #   - https://developers.rakutenadvertising.com/documentation/en-US/affiliate_apis
        #     GET /events/1.0/transactions
        # 关键口径：Commissioning Lists API 是「动态佣金规则/SKU 名单」，不是已产生佣金；
        # Advanced Reports 主要是付款历史/付款明细，且还需 Web Security Token；
        # 本模板选 Events transactions，因为它是官方唯一明确返回逐笔
        # etransaction_id / order_id / sku_number / sale_amount / commissions 的佣金流水接口。
        "code": "rakuten_advertising",
        "name": "Rakuten Advertising",
        "vendor": "Rakuten Advertising",
        "description": "读取 Events API transactions 逐笔佣金流水（订单/商品、销售额、佣金、币种与处理时间）。",
        "record_object": "Transaction",
        "record_object_desc": "Rakuten Events transaction: a commission event with order, SKU, sale amount and commission.",
        "method": "GET",
        "auth_type": "bearer",
        "default_endpoint": "https://api.linksynergy.com",
        "required_fields": [
            {
                "key": "token",
                "label": "API Access Token（或 oauth:token-key|account-id）",
                "type": "password",
                "required": True,
            },
        ],
        "query_name": "transactions",
        "pagination": "page/limit 分页；本页条数小于 limit 即结束",
        "limits": "Token 端点 100 次/分钟；Events 默认 limit=100（本模板固定 300）；token-key 生成的 access_token 有效期 3600 秒",
        "framework_version": "advertiser-api/1.0",
        "status": "active",
        "protocol": {
            "style": "rest", "http_method": "GET", "auth": "bearer", "cid_in": "none",
            "endpoint_path": "events/1.0/transactions",
            "records_path": "",
            "record_wrappers": ["transactions", "events", "results", "data"],
            "single_record": True,
            # 实测同一 etransaction_id 会各返回一条 is_event=N 与 is_event=Y，
            # 佣金金额完全相同；Y 是 Event 视角，计入会重复计算佣金。报表只取 N。
            "record_filter": {"field": "is_event", "equals": "N"},
            "count_path": "",
            "cursor_path": "",
            "complete_path": "",
            "complete_when_short": True,
            "page_size": 300,
            "page_param": "page",
            "external_id_path": "etransaction_id",
            "date_params": {
                "since": "process_date_start", "before": "process_date_end",
            },
            "date_value_format": "rakuten_datetime",
            "extra_params": {"limit": 300, "page": 1},
            # 通用凭据交换：用户可直接填 access token；若填 oauth:token-key|account-id，
            # 则在每次调用前按模板声明自动换取新的 access token。token-key 是 Base64(client_id:client_secret)。
            "credential": {
                "mode": "prefix_exchange",
                "prefix": "oauth:",
                "delimiter": "|",
                "parts": ["token_key", "account_id"],
                "endpoint": "https://api.linksynergy.com/token",
                "method": "POST",
                "auth": "bearer",
                "bearer_part": "token_key",
                "content_type": "application/x-www-form-urlencoded",
                "body": {"scope": "{account_id}"},
                "token_path": "access_token",
            },
        },
    },
]


def template_by_code(code: str) -> Optional[dict]:
    for t in PRESET_TEMPLATES:
        if t["code"] == code:
            return t
    return None


def requires_cid(template_code: str) -> bool:
    """V4.144：模板未声明 cid 字段即视为不需要 CID。

    CJ / Awin 显式声明 cid(required=True) 继续强制；PartnerStack 按官方
    Partner API 文档只声明 token，因此不存在任何必填的发布者 ID。
    """
    tpl = template_by_code(template_code or "") or {}
    for field in tpl.get("required_fields") or []:
        if field.get("key") == "cid":
            return bool(field.get("required", True))
    return False


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


def _redact_text(text: str, token: str = "", secrets: Optional[list[str]] = None) -> str:
    """脱敏完整响应文本：替换 Token / 组合凭据片段与 Bearer 片段，不截断内容。"""
    s = text or ""
    values = [token] + list(secrets or [])
    for value in values:
        if value:
            s = s.replace(value, "***")
    return re.sub(r"Bearer\s+\S+", "Bearer ***", s, flags=re.I)


def _redact_record(record: dict, token: str = "", secrets: Optional[list[str]] = None) -> dict:
    """脱敏单条明细（递归处理容器中的字符串）。"""
    def walk(value):
        if isinstance(value, str):
            return _redact_text(value, token, secrets)
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value
    return walk(record) if isinstance(record, dict) else record


def _expand_credential_template(value: Any, parts: dict) -> Any:
    """把 {part_name} 占位符替换为用户输入的凭据片段（配置驱动，不含渠道字段）。"""
    if not isinstance(value, str):
        return value
    out = value
    for key, item in parts.items():
        out = out.replace("{" + key + "}", str(item))
    return out


async def resolve_credential(template_code: str, token: str, *,
                             timeout_sec: float = 20.0) -> tuple[str, list[str], str]:
    """按模板声明处理凭据，返回 (实际请求 token, 需脱敏片段, 凭据说明)。

    默认直接把输入当作 access token，历史渠道行为零变化。模板声明 credential 且
    输入带约定前缀时，按官方 token endpoint 自动换取 access token；Rakuten 的
    token-key = Base64(client_id:client_secret)，scope = account-id。
    """
    import advertiser_protocol

    raw = (token or "").strip()
    proto = advertiser_protocol.protocol_of(template_code)
    cfg = proto.get("credential") or {}
    if not cfg or not raw.startswith(str(cfg.get("prefix") or "")):
        return raw, ([raw] if raw else []), ""

    prefix = str(cfg.get("prefix") or "")
    delimiter = str(cfg.get("delimiter") or "|")
    names = [str(x) for x in (cfg.get("parts") or [])]
    pieces = raw[len(prefix):].split(delimiter)
    if not names or len(pieces) != len(names):
        raise ValueError("组合凭据格式错误：应为 " + prefix + delimiter.join(names))
    parts = {name: piece.strip() for name, piece in zip(names, pieces)}
    if any(not value for value in parts.values()):
        raise ValueError("组合凭据含空字段：" + delimiter.join(names))

    endpoint = str(cfg.get("endpoint") or "")
    if not endpoint.startswith("https://"):
        raise ValueError("凭据交换地址必须是 HTTPS")
    headers = {"Content-Type": str(cfg.get("content_type")
                                    or "application/x-www-form-urlencoded")}
    if cfg.get("auth") == "bearer":
        bearer_part = str(cfg.get("bearer_part") or "")
        headers["Authorization"] = "Bearer " + parts.get(bearer_part, "")
    body = {key: _expand_credential_template(value, parts)
            for key, value in dict(cfg.get("body") or {}).items()}

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as c:
            r = await c.request(str(cfg.get("method") or "POST").upper(),
                                endpoint, data=body, headers=headers)
    except httpx.HTTPError as exc:
        raise RuntimeError("凭据交换网络失败：" + _safe_error(str(exc))) from exc
    if r.status_code >= 400:
        raise RuntimeError(f"凭据交换失败（HTTP {r.status_code}）："
                           + _safe_error(_redact_text(r.text, parts.get("token_key", ""))))
    try:
        payload = r.json()
    except Exception as exc:
        raise RuntimeError("凭据交换返回不是 JSON") from exc
    token_path = str(cfg.get("token_path") or "access_token")
    access = payload.get(token_path) if isinstance(payload, dict) else None
    access = str(access or "").strip()
    if not access:
        raise RuntimeError("凭据交换成功但未返回 " + token_path)
    secrets = [access] + [v for v in parts.values() if v]
    note = "access_token 由模板凭据交换获得；有效期按上游 expires_in 为准"
    return access, secrets, note


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
        "hint": "",
    }
    result.update(extra)
    return result


async def test_connection(*, template_code: str, endpoint: str, token: str, cid: str,
                          since_event_date: str, before_event_date: str,
                          timeout_sec: float = 20.0, full_records: bool = False,
                          since_commission_id: str = "") -> dict:
    """真实调用上游 API，逐条拉取 PublisherCommission 订单佣金明细。异常归为 ok=False。

    V4.128：请求 URL / GraphQL 请求体 / 上游完整响应原文统一返回，供「测试」右侧滑窗查阅；
    V4.129：请求体显式包含 publisherCommissions.records（Object: PublisherCommission），
    返回 record_count / sample_records；Token 只用于 Authorization 头，绝不写入请求体、
    结果、响应文本或日志。
    """
    # V4.138 / P4：请求构造 / 响应解析全部下沉到协议层，业务代码不再写死某一家。
    import advertiser_protocol

    tpl = template_by_code(template_code)
    url = (endpoint or "").strip() or ((tpl or {}).get("default_endpoint") or "")

    # V4.131：所有返回路径都带上实际查询窗口，滑窗可据此判断"为什么没有明细"
    def _env(**kwargs) -> dict:
        kwargs.setdefault("window_since", since_event_date)
        kwargs.setdefault("window_before", before_event_date)
        return _test_envelope(**kwargs)

    if not tpl:
        return _env(ok=False, error="未知模板，无法测试连接", count=0, http_code=0, url=url)
    if not token:
        return _env(ok=False, error="API Token 必填", count=0, http_code=0, url=url)
    if requires_cid(template_code) and not cid:
        return _env(ok=False, error="该模板要求的发布者 ID 必填", count=0, http_code=0, url=url)

    # V4.150：模板可按声明完成凭据交换；普通 Token 直接透传，既有渠道零变化。
    try:
        effective_token, secrets, credential_note = await resolve_credential(
            template_code, token, timeout_sec=timeout_sec)
    except Exception as exc:
        return _env(ok=False, error=_safe_error(str(exc)), count=0, http_code=0, url=url,
                    hint="组合凭据格式或凭据交换失败；请检查 token-key / account-id。")

    req = advertiser_protocol.build_request(
        template_code=template_code, endpoint=endpoint, token=effective_token, cid=cid,
        since_event_date=since_event_date, before_event_date=before_event_date,
        since_commission_id=since_commission_id)
    url = req["url"]
    if not url.startswith("https://") and not url.startswith("http://"):
        return _env(ok=False, error="Endpoint 必须是 http(s) 地址", count=0, http_code=0, url=url)

    payload = req["json_body"] or {}
    display_url = _redact_text(advertiser_protocol.request_display(
        method=req["method"], url=url, params=req["params"]), effective_token, secrets)
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as c:
            # V4.138：CJ(GraphQL POST) 保留 .post() 调用形态，兼容既有 mock 与契约；
            # REST 协议才用 .request()。业务语义完全相同，只是调用入口不同。
            if req["method"] == "POST" and not req["params"]:
                r = await c.post(url, json=req["json_body"], headers=req["headers"])
            else:
                r = await c.request(
                    req["method"], url, json=req["json_body"],
                    params=req["params"] or None, headers=req["headers"])
    except httpx.HTTPError as e:
        text = _redact_text(str(e), effective_token, secrets)
        return _env(
            ok=False, error="网络请求失败：" + _safe_error(text), count=0,
            http_code=0, url=url, payload=payload, response_text=text)

    code = r.status_code
    response_text = _redact_text(r.text, effective_token, secrets)
    if code == 401 or code == 403:
        return _env(
            ok=False, error=(f"认证失败（HTTP {code}）：access token 无效或已过期；"
                             "请重新生成，或改用 oauth:token-key|account-id 自动换取"),
            count=0, http_code=code, url=url, payload=payload, response_text=response_text)
    if code >= 400:
        return _env(
            ok=False, error=f"上游返回 HTTP {code}：{_safe_error(response_text)}", count=0,
            http_code=code, url=url, payload=payload, response_text=response_text)
    try:
        body = r.json()
    except Exception:
        return _env(
            ok=False, error="上游返回不是 JSON", count=0, http_code=code,
            url=url, payload=payload, response_text=response_text)
    # GraphQL 错误顶层 errors；REST 协议（如 Awin）无此包装，跳过
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        msg = errors[0].get("message", "") if isinstance(errors, list) and errors else str(errors)
        return _env(
            ok=False, error="GraphQL 错误：" + _safe_error(_redact_text(msg, effective_token, secrets)),
            count=0, http_code=code,
            url=url, payload=payload, response_text=response_text,
            response=_redact_record(body, effective_token, secrets))

    parsed = advertiser_protocol.parse_response(template_code=template_code, body=body)
    records = [_redact_record(r, effective_token, secrets) for r in parsed["records"]]
    result = _env(
        ok=True, error="", count=parsed["count"], http_code=code,
        url=display_url, request_method=req["method"], payload=payload,
        response_text=response_text, response=_redact_record(body, effective_token, secrets),
        payload_complete=parsed["complete"], max_commission_id=parsed["cursor"],
        record_object=(tpl.get("record_object") or "PublisherCommission"),
        record_count=len(records), sample_records=records[:10],
        credential_note=credential_note)
    if not records:
        if (tpl.get("protocol") or {}).get("style", "graphql") == "rest":
            result["hint"] = (
                f"查询窗口 {since_event_date} ~ {before_event_date} 内没有 "
                f"{tpl.get('record_object') or '明细'} 数据；可能是正常的空窗口，"
                "建议在测试抽屉调整日期窗口后重新测试。")
        else:
            # V4.131 原文案，保持 CJ 既有契约与测试兼容
            result["hint"] = (
                f"查询窗口 {since_event_date} ~ {before_event_date} 内没有 PublisherCommission 明细；"
                "这是正常的空窗口，不是统计报表。CJ 佣金记录通常延迟 1–3 天，"
                "建议在测试抽屉把开始日期往前调（如近 7 天）后重新测试。")
    # V4.132：落库链路需要完整明细；默认测试请求不返回，避免把大响应体透给前端
    if full_records:
        result["all_records"] = records
    return result
