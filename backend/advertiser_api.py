"""V4.124 · 广告主数据模块：API 模板与连接层。

设计依据：docs/广告主数据模块功能开发文档_20261124.html（唯一维护文档）。

职责边界（P0）：
  1. 预置标准模板：把「接口怎么调」沉淀为只读模板（CJ publisherCommissions）。
  2. 连接实例：用户只填 API Token / CID / Endpoint，其余继承模板。
  3. 测试连接：真实调用上游 API（1 天窗口，只读 count），不落任何凭据到日志。

不做（留后续版本）：
  - 定时拉取与落库（P1/P2）、统一事实表映射（P1）、报表（P3）。

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
        "name": "CJ 联盟 · 发布者佣金明细",
        "vendor": "CJ Affiliate",
        "description": "读取 publisherCommissions 返回的每条 PublisherCommission（一个订单的一笔佣金明细，含原始单与修正单）。",
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
# P0 只请求 count / maxCommissionId / payloadComplete，用最小字段验证凭据与 CID 是否正确。
_TEST_QUERY = """
query PublisherCommissions($forPublishers: [String!]!, $sinceEventDate: String, $beforeEventDate: String) {
  publisherCommissions(forPublishers: $forPublishers,
                       sinceEventDate: $sinceEventDate,
                       beforeEventDate: $beforeEventDate) {
    count
    limit
    maxCommissionId
    payloadComplete
  }
}
"""


def _safe_error(text: str) -> str:
    """脱敏上游错误：去掉可能回显的 token 片段与换行，限制长度。"""
    s = re.sub(r"Bearer\s+\S+", "Bearer ***", text or "", flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:300]


def build_test_payload(cid: str, since_event_date: str, before_event_date: str) -> dict:
    return {
        "query": _TEST_QUERY,
        "variables": {
            "forPublishers": [cid],
            "sinceEventDate": since_event_date,
            "beforeEventDate": before_event_date,
        },
    }


async def test_connection(*, template_code: str, endpoint: str, token: str, cid: str,
                          since_event_date: str, before_event_date: str,
                          timeout_sec: float = 20.0) -> dict:
    """真实调用上游 API 验证凭据与 CID。返回结构化结果，任何异常归为 ok=False。

    绝不把 token 写进 result / detail / 日志；只回传脱敏错误摘要。
    """
    tpl = template_by_code(template_code)
    if not tpl:
        return {"ok": False, "error": "未知模板，无法测试连接", "count": 0, "http_code": 0}
    if not token or not cid:
        return {"ok": False, "error": "API Token 与 CID 均为必填", "count": 0, "http_code": 0}
    url = (endpoint or tpl["default_endpoint"]).strip()
    if not url.startswith("https://") and not url.startswith("http://"):
        return {"ok": False, "error": "Endpoint 必须是 http(s) 地址", "count": 0, "http_code": 0}

    payload = build_test_payload(cid, since_event_date, before_event_date)
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=False) as c:
            r = await c.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as e:
        return {"ok": False, "error": "网络请求失败：" + _safe_error(str(e)), "count": 0, "http_code": 0}

    code = r.status_code
    if code == 401 or code == 403:
        return {"ok": False, "error": f"认证失败（HTTP {code}）：请检查 Token 是否有效", "count": 0, "http_code": code}
    if code >= 400:
        return {"ok": False, "error": f"上游返回 HTTP {code}：{_safe_error(r.text)}", "count": 0, "http_code": code}
    try:
        body = r.json()
    except Exception:
        return {"ok": False, "error": "上游返回不是 JSON", "count": 0, "http_code": code}
    errors = body.get("errors")
    if errors:
        msg = errors[0].get("message", "") if isinstance(errors, list) and errors else str(errors)
        return {"ok": False, "error": "GraphQL 错误：" + _safe_error(msg), "count": 0, "http_code": code}
    data = (body.get("data") or {}).get(tpl["query_name"]) or {}
    return {
        "ok": True,
        "error": "",
        "count": int(data.get("count") or 0),
        "http_code": code,
        "payload_complete": bool(data.get("payloadComplete")),
        "max_commission_id": data.get("maxCommissionId") or "",
    }
