"""V4.96 创意工作台：图片创意规划统一提示词规则。

把「用户勾选的多条创意路线」与「补充创意指令」合并成**唯一一份**确定性规则块，
供文生图提示词消费。设计原则：

1. 唯一实现：规则只在后端生成，前端只传结构化数据（routes + supplement），
   不各自拼提示词，避免前后端漂移。
2. 主干 + 修饰：第一勾选路线为主干（决定画面主体与情绪），其余勾选路线只做
   构图 / 情绪 / 场景修饰；每条路线各出一组图，规则文本一致。
3. 补充指令优先级最高，但仅限视觉表达（构图 / 光线 / 色调 / 场景 / 镜头语言），
   不得据此编造商品事实、价格、评分或效果数据（V4.96 确认：只做硬约束，不接审查模型）。
4. 零文字兜底：规则自带「画面不绘制任何文字」硬约束，并与 V4.88 图片零文字契约
   叠加（契约块在提示词中最后出现，作为最终兜底）。
5. 可追溯：rule_hash 随 config_id 与资产 meta 归档，规则变更可比对。
"""

import hashlib
import re

from creative_brief import build_image_brief_block

RULE_VERSION = "2"
MAX_ROUTES = 10
MAX_SUPPLEMENT = 500


def _clean(value, limit: int) -> str:
    """清洗为单行文本并限长，避免换行破坏提示词结构。"""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _clean_route(raw: dict, idx: int) -> dict:
    route = raw if isinstance(raw, dict) else {}
    tags = []
    for t in (route.get("tags") or []):
        tag = _clean(t, 24)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 4:
            break
    key = _clean(route.get("key"), 4) or chr(65 + idx)
    return {
        "key": key,
        "name": _clean(route.get("name"), 60) or "未命名路线",
        "angle": _clean(route.get("angle"), 120),
        "description": _clean(route.get("description"), 200),
        "tags": tags,
        "framework": _clean(route.get("framework"), 24),
        "framework_label": _clean(route.get("framework_label"), 60),
        "hook": _clean(route.get("hook"), 160),
        "proof": _clean(route.get("proof"), 160),
        "visual_hook": _clean(route.get("visual_hook"), 160),
        "cta_role": _clean(route.get("cta_role"), 120),
    }


def build_image_prompt_rule(*, routes=None, supplement: str = "", platform: str = "",
                            overlay_mode: str = "pure", brief: dict | None = None) -> dict:
    """把所选路线 + 补充指令构建成一条统一规则。

    返回 dict：version / routes / route_keys / supplement / rule_text / rule_hash。
    无路线且无补充指令时 rule_text 为空（调用方应跳过注入，保持旧行为）。
    """
    items = [_clean_route(r, i) for i, r in enumerate(list(routes or [])[:MAX_ROUTES])]
    items = [r for r in items if r["name"] or r["angle"] or r["description"] or r["tags"]]
    supp = _clean(supplement, MAX_SUPPLEMENT)
    plat = _clean(platform, 40)
    mode = _clean(overlay_mode, 20) or "pure"
    brief_block = build_image_brief_block(brief, plat) if brief else ""

    if not items and not supp and not brief_block:
        return {"version": RULE_VERSION, "routes": [], "route_keys": [],
                "supplement": "", "rule_text": "", "rule_hash": "", "brief_hash": ""}

    lines: list[str] = ["[CreativePlanRule v%s] 本次出图的唯一创意规则（已合并所选创意规划与补充指令，按优先级执行）：" % RULE_VERSION]
    if items:
        head = items[0]
        lines.append("主干路线 %s「%s」：切入角度=%s；视觉表达=%s；标签=%s。" % (
            head["key"], head["name"], head["angle"] or "未指定",
            head["description"] or "未指定", "、".join(head["tags"]) or "无"))
        lines.append("主干转化框架：%s；钩子=%s；证据表达=%s；视觉钩子=%s；收口意图=%s。" % (
            head["framework_label"] or head["framework"] or "AIDA",
            head["hook"] or "首屏结果或反差", head["proof"] or "真实功能演示，不写数字",
            head["visual_hook"] or "主体与场景形成可观察变化",
            head["cta_role"] or "叠加位收口，不绘制文字"))
        if len(items) > 1:
            others = []
            for r in items[1:]:
                others.append("%s「%s」(%s)" % (
                    r["key"], r["name"], r["angle"] or r["description"] or "视觉修饰"))
            lines.append("辅助路线（只做构图 / 情绪 / 场景修饰，不改主体）：" + "；".join(others) + "。")
    else:
        lines.append("主干路线：未勾选创意规划，仅按补充指令调整视觉表达。")

    if supp:
        lines.append("用户补充指令（仅调整视觉表达，优先级最高）：" + supp + "。")
    if brief_block:
        lines.append(brief_block)

    constraints = [
        "以主干路线决定画面主体与情绪基调，辅助路线只做修饰，禁止多主题拼贴或逐个路线各画一遍",
        "补充指令与路线冲突时以补充指令为准，但仅限构图 / 光线 / 色调 / 场景 / 镜头语言等视觉表达",
        "不得据此编造商品事实、价格、折扣、评分、用户数或效果数据，也不得改写已确认信息",
        "画面内不绘制任何文字（含品牌名、标语、按钮、字母与数字），文字由播放层 / 合成层另行处理",
    ]
    if plat:
        constraints.insert(3, "遵循 %s 平台素材规格与版位要求" % plat)
    lines.append("融合硬约束：" + "；".join("%d) %s" % (i, c) for i, c in enumerate(constraints, 1)) + "。")
    if mode != "pure":
        lines.append("叠加模式=%s：文字 / 按钮 / logo 由合成层绘制，生成画面仍保持零文字。" % mode)

    rule_text = "\n".join(lines)
    return {
        "version": RULE_VERSION,
        "routes": items,
        "route_keys": [r["key"] for r in items],
        "supplement": supp,
        "rule_text": rule_text,
        "rule_hash": hashlib.sha256(rule_text.encode("utf-8")).hexdigest()[:12],
        "overlay_mode": mode,
        "platform": plat,
        "brief_hash": str((brief or {}).get("brief_hash") or "") if brief_block else "",
    }


def render_image_prompt_rule(rule: dict | None) -> str:
    """把规则渲染成可拼进文生图提示词的独立块；空规则返回空串。"""
    text = str((rule or {}).get("rule_text") or "").strip()
    return text if text else ""
