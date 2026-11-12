"""V4.59 / B1：创意工作台专属抓取模块（P0#2：消除「只传 URL 不抓取」）。

复用素材创作链路的真实抓取与证据机制（services.fetch_page / build_evidence_pack /
evidence_contract / claim_contract），但把「降噪耳机演示数据」隔离成显式演示模式，
不再在解析失败时静默套用、也不再伪装成真实模型结论。

对外只暴露两个入口：
- `fetch_product(url)`：真实抓取一个产品/落地页，返回页面、证据包与可落库的快照字段；
  抓取失败（不可达 / 空页）时 `ok=False`，由调用方明确阻断，而不是编造数据。
- `demo_product()` / `demo_snapshot(url)`：仅「演示模式」开启时返回，明确标注
  `source="demo"`，让用户一眼看出这是样例而非真实分析结果。
"""
from __future__ import annotations

from typing import Any, Dict, List

from services import fetch_page, build_evidence_pack
from evidence import evidence_contract
from claims import EvidenceSnapshot, claim_contract


# 演示模式样例（隔离后仅演示模式使用，绝不伪装成真实抓取结论）
DEMO_PRODUCT: Dict[str, Any] = {
    "title": "产品分析（演示样例）",
    "summary": "这是一款面向城市年轻人的中高端无线降噪耳机，用户的关键动机是隔绝环境干扰，"
               "并在通勤和工作中获得沉浸体验。",
    "boxes": {
        "industry": "消费电子",
        "coreAudience": "城市效率人群",
        "purchaseMotivation": "专注与沉浸",
        "priceBand": "中高端",
    },
    "brief": {
        "promotionGoal": "提升购买转化",
        "targetAudience": ["18-35 岁", "城市通勤", "音乐爱好者", "效率人群"],
        "sellingPoints": ["自适应主动降噪", "40 小时超长续航", "沉浸式空间音频"],
    },
    "recommendedPlatforms": ["Meta", "Google"],
}


def demo_product() -> Dict[str, Any]:
    """返回演示样例的静态分析结果（深拷贝，避免被调用方改动污染）。"""
    import copy
    return copy.deepcopy(DEMO_PRODUCT)


def demo_snapshot(url: str) -> Dict[str, Any]:
    """演示模式的来源快照：明确标注 source=demo，绝不伪装成真实抓取。"""
    return {
        "source": "demo",
        "url": url or "",
        "final_url": url or "",
        "fetched_at": "",
        "fetch_quality": "demo",
        "snapshot_id": "",
        "title": "演示样例（降噪耳机）",
        "evidence_ids": [],
    }


async def fetch_product(url: str) -> Dict[str, Any]:
    """真实抓取一个 URL 并构造可落库的快照字段。

    返回：
        {
          "ok": bool,                 # False=抓取失败，调用方应明确阻断
          "page": dict,               # fetch_page 原始结果（含 html/text/质量等）
          "pack": dict | None,        # 证据包（ok 时为 build_evidence_pack 结果）
          "snapshot": dict,           # ProductSnapshot 所需字段
          "error": str,               # ok=False 时的原因
        }
    """
    page = await fetch_page(url)
    fetched = bool(page.get("fetched"))
    quality = page.get("fetch_quality") or "not_fetched"
    if not fetched or quality == "fetch_failed":
        return {
            "ok": False,
            "page": page,
            "pack": None,
            "snapshot": {
                "source": "fetch_failed",
                "url": url,
                "final_url": page.get("final_url") or url,
                "fetched_at": "",
                "fetch_quality": quality,
                "snapshot_id": "",
                "title": "",
                "evidence_ids": [],
            },
            "error": "fetch_failed",
        }

    pack = build_evidence_pack(page, page.get("text") or "")
    return {
        "ok": True,
        "page": page,
        "pack": pack,
        "snapshot": {
            "source": "real_fetch",
            "url": url,
            "final_url": page.get("final_url") or url,
            "fetched_at": pack.get("fetched_at") or "",
            "fetch_quality": quality,
            "snapshot_id": pack.get("evidence_snapshot_id") or "",
            "title": page.get("title") or "",
            "evidence_ids": pack.get("evidence_ids") or [],
        },
        "error": "",
    }


def evidence_prompt_part(url: str, page: Dict[str, Any], pack: Dict[str, Any]) -> str:
    """用与素材创作一致的「证据包 + 证据契约 + 声明契约」拼出带 [E###] 编号的页面内容段。

    复用 services.build_landing_prompt：它内部已经把 evidence_pack 的预算采样、
    首尾窗口与条款契约拼好了，CW 只需在其后追加自己的 JSON 输出指令即可。
    """
    from services import build_landing_prompt
    return build_landing_prompt(url, page.get("text") or "", page, evidence_pack=pack)


def is_demo_request(req_payload: Dict[str, Any]) -> bool:
    """便捷判断：是否显式开启演示模式（供调用方分支）。"""
    return bool(req_payload.get("demo_mode"))
