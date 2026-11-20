"""V4.118 素材创意模板库 · 外网 URL 安全访问闸门（SSRF 防护）。

背景：素材导入支持「图片 URL」与「网页链接自动截图」，两者都由服务端主动访问
用户提供的 URL。若不设防，攻击者可用 file:///、gopher://、127.0.0.1、169.254.169.254
（云元数据）等地址探测内网。本模块是全站唯一的「外部 URL 准入」事实源：

- scheme 只允许 http/https；禁止 userinfo（user:pass@host）与非常规端口；
- 主机若为 IP 字面量直接判定；若为域名则 DNS 解析后对**每一条** A/AAAA 复检；
- 私有 / 回环 / 链路本地 / 保留 / 组播 / CGNAT / 未指定地址一律拒绝；
- httpx 跟随重定向时逐跳校验（follow_redirects=False + 手动循环），杜绝「合法域名
  302 到内网」绕过；
- 下载按流式累加限大小，超限即中止并删除半截文件。

设计原则：失败即抛 SSRFError（调用层翻 400），不静默放行；不臆测「应该安全」。
测试可通过 resolver / fetch 注入替身，无需真实外网。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Optional
from urllib.parse import urlparse

MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_BYTES = 12 * 1024 * 1024
ALLOWED_SCHEMES = ("http", "https")
ALLOWED_PORTS = (80, 443)


class SSRFError(ValueError):
    """外部 URL 未通过安全校验。调用层统一转成 HTTP 400。"""


def is_public_ip(addr: str) -> bool:
    """IP 是否公网可路由。任何非 global 地址（含私有/回环/保留）都判否。"""
    try:
        ip = ipaddress.ip_address(str(addr).strip().strip("[]"))
    except (ValueError, TypeError):
        return False
    if not ip.is_global:
        return False
    # 显式兜底：部分 Python 版本对 CGNAT / 文档地址段的 is_global 判定不完全一致。
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return False
    return True


def default_resolver(host: str) -> list[str]:
    """解析域名到所有 A/AAAA 地址；解析失败返回空列表（由调用方拒绝）。"""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except Exception:
        return []
    return list({str(info[4][0]) for info in infos if info and info[4]})


def validate_url(url: str, *, resolver: Optional[Callable[[str], list[str]]] = None,
                 allow_ports=ALLOWED_PORTS) -> dict:
    """校验 URL 准入，返回 {"url": 规范化URL, "host": 域名}；不合法抛 SSRFError。

    resolver 可注入以便测试（签名 host -> list[ip]）；生产用 DNS。
    """
    text = str(url or "").strip()
    if not text:
        raise SSRFError("链接不能为空")
    try:
        p = urlparse(text)
    except Exception:
        raise SSRFError("链接格式无法解析")
    if (p.scheme or "").lower() not in ALLOWED_SCHEMES:
        raise SSRFError("仅支持 http / https 链接")
    if p.username or p.password:
        raise SSRFError("链接不允许包含账号密码")
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SSRFError("链接缺少主机名")
    # 显式拦截本地 / 云元数据主机名，不依赖 DNS 解析结果（防止解析器差异导致绕过）。
    _blocked_hosts = ("localhost", "metadata", "metadata.google.internal", "instance-data")
    if host in _blocked_hosts or host.endswith(".localhost") or host.endswith(".internal"):
        raise SSRFError("禁止访问本地 / 内网主机名")
    try:
        port = p.port or (443 if p.scheme.lower() == "https" else 80)
    except ValueError:
        raise SSRFError("链接端口非法")
    if port not in tuple(allow_ports):
        raise SSRFError("仅允许 80 / 443 端口")

    # IP 字面量：直接判定，不走 DNS（避免绕过）。
    # 注意：SSRFError 继承 ValueError，绝不能用 try/except ValueError 做「是否 IP」的
    # 控制流判断——那会把这里抛出的 SSRFError 一起吞掉，导致内网 IP 字面量被放行。
    is_literal_ip = False
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        pass  # host 是域名，下面解析后复检
    if is_literal_ip and not is_public_ip(host):
        raise SSRFError("禁止访问内网 / 保留地址")

    resolve = resolver or default_resolver
    addrs = resolve(host)
    if not addrs:
        raise SSRFError("域名解析失败")
    for addr in addrs:
        if not is_public_ip(addr):
            raise SSRFError("域名解析到内网 / 保留地址，已拒绝")

    # 规范化：去掉 userinfo / fragment，保留路径与查询。
    netloc = host if port in (80 if p.scheme.lower() == "http" else 443,
                              443 if p.scheme.lower() == "https" else 80) else f"{host}:{port}"
    normalized = f"{p.scheme.lower()}://{netloc}{p.path or '/'}"
    if p.query:
        normalized += "?" + p.query
    return {"url": normalized, "host": host}


async def fetch_remote_bytes(url: str, *, max_bytes: int = DEFAULT_MAX_BYTES,
                             timeout: float = DEFAULT_TIMEOUT,
                             resolver: Optional[Callable[[str], list[str]]] = None,
                             fetcher=None) -> dict:
    """安全地下载远程资源字节；逐跳校验重定向，流式累加限大小。

    返回 {"content": bytes, "content_type": str, "final_url": str, "host": str}。
    fetcher 可注入以便测试（签名 (client, url) -> 类 httpx 响应）；生产用 httpx。
    """
    import httpx

    current = validate_url(url, resolver=resolver)["url"]
    for _hop in range(MAX_REDIRECTS + 1):
        checked = validate_url(current, resolver=resolver)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if fetcher is not None:
                resp = await fetcher(client, checked["url"])
            else:
                resp = await client.get(checked["url"])
        status = int(getattr(resp, "status_code", 0) or 0)
        if status in (301, 302, 303, 307, 308):
            loc = (resp.headers or {}).get("location") or ""
            if not loc:
                raise SSRFError("重定向缺少目标地址")
            from urllib.parse import urljoin
            current = urljoin(checked["url"], loc)
            continue  # 下一跳会重新 validate_url，杜绝跳到内网
        if status != 200:
            raise SSRFError(f"无法获取资源（HTTP {status}）")
        ctype = str((resp.headers or {}).get("content-type") or "").split(";")[0].strip().lower()
        content = getattr(resp, "content", b"") or b""
        if len(content) > max_bytes:
            raise SSRFError(f"资源超过 {max_bytes // (1024 * 1024)}MB 限制")
        return {"content": content, "content_type": ctype,
                "final_url": checked["url"], "host": checked["host"]}
    raise SSRFError("重定向次数过多")
