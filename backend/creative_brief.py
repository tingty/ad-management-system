"""V4.101 / P0：文案 / 图片 / 视频共用的创意框架与用户确认 brief。

设计目标
--------
1. 把海外效果广告常用高转化框架（AIDA / PAS / BAB / HSO / 4P / 对比证明 /
   场景代入 / 社会认同 / 稀缺紧迫）沉淀为统一数据契约，不再各自硬编码；
2. 用户输入的原始提示词统一经 `normalize_brief()` 补全、校验、生成可读预览，
   **只有 confirmed=true 的 brief 才允许进入生成流程**；
3. 本模块只产出「表达策略」，不是事实依据：任何数字 / 折扣 / 评分 / 用户数
   仍必须过既有证据门；画面文字仍由三道防线管理，brief 不得绕过。

本模块不依赖 FastAPI / DB，可被 routers、media_ad、image_prompt_rule、
视频规划与出片链路安全复用。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from material_prompt_manage import LAYER_ORDER  # 六层心理链条，单一事实源

RULE_VERSION = "1"

# ---------------------------------------------------------------------------
# 一、框架注册表
# ---------------------------------------------------------------------------
FRAMEWORKS: list[dict[str, Any]] = [
    {
        "key": "aida", "label": "AIDA · 注意→兴趣→欲望→行动",
        "desc": "最通用的效果广告框架：先抢注意，再用利益建立兴趣，放大拥有后的欲望，最后低风险收口。",
        "beats": ["注意钩子", "兴趣利益", "欲望放大", "行动收口"],
        "layers": ["desire", "proof", "decision", "cta"],
        "visual_hook": "首屏结果前置或强反差构图，让受众一眼看到「变化」",
        "tone": "直接、结果导向、节奏快",
        "cta_role": "明确下一步且降低风险（了解更多 / 立即体验）",
        "requires_evidence": False,
    },
    {
        "key": "pas", "label": "PAS · 痛点→放大→解决",
        "desc": "先让受众认出自己的痛点，放大不解决的代价，再给出产品作为解法。适合功能型与效率型产品。",
        "beats": ["痛点识别", "代价放大", "方案登场", "行动收口"],
        "layers": ["pain", "desire", "attribution", "cta"],
        "visual_hook": "前后并置或受阻场景，痛点先于产品出现",
        "tone": "克制但有压迫感，转折要干净",
        "cta_role": "从痛点回到可行动的解法",
        "requires_evidence": False,
    },
    {
        "key": "bab", "label": "BAB · 现状→理想→桥梁",
        "desc": "从用户熟悉的现状出发，展示理想状态，再把产品定义为跨越落差的桥梁。适合生活方式与升级类商品。",
        "beats": ["现状锚定", "理想状态", "产品桥梁", "行动收口"],
        "layers": ["pain", "desire", "attribution", "decision"],
        "visual_hook": "同一场景的两种状态对照，产品出现在转折处",
        "tone": "有画面感、生活化、不过度承诺",
        "cta_role": "邀请进入理想状态",
        "requires_evidence": False,
    },
    {
        "key": "hso", "label": "HSO · 钩子→故事→优惠",
        "desc": "前 3 秒定生死：强钩子开场，微叙事建立代入，再给出明确利益/优惠。优惠必须有证据支持。",
        "beats": ["3秒钩子", "微叙事", "利益/优惠", "行动收口"],
        "layers": ["pain", "desire", "decision", "cta"],
        "visual_hook": "开场即动作或反差，不用空镜铺垫",
        "tone": "短促、有冲击力、口语化",
        "cta_role": "利益驱动的立即行动",
        "requires_evidence": True,
    },
    {
        "key": "4p", "label": "4P · 承诺→画面→证明→推动",
        "desc": "Promise-Picture-Proof-Push：先给承诺，再让受众看见结果，用证据坐实，最后推动行动。",
        "beats": ["结果承诺", "结果画面", "可信证明", "行动推动"],
        "layers": ["desire", "proof", "attribution", "cta"],
        "visual_hook": "结果可视化：让利益在画面里被看见",
        "tone": "自信、证据感强",
        "cta_role": "证据之后的顺势推动",
        "requires_evidence": True,
    },
    {
        "key": "contrast_proof", "label": "对比证明 · 差异→验证→结论",
        "desc": "把核心差异做成可观察的对比，再用真实演示验证，最后给出不带夸张的结论。",
        "beats": ["差异设定", "同条件对比", "真实验证", "结论收口"],
        "layers": ["pain", "proof", "attribution", "decision"],
        "visual_hook": "同机位 / 同光线的前后对照",
        "tone": "客观、可验证、少形容词",
        "cta_role": "以结论引导进一步了解",
        "requires_evidence": True,
    },
    {
        "key": "scene", "label": "场景代入 · 时刻→动作→融入",
        "desc": "用真实使用时刻切入，让产品自然融入动作链，降低广告感，适合社媒信息流。",
        "beats": ["真实时刻", "连续动作", "产品融入", "自然收口"],
        "layers": ["desire", "attribution", "decision", "cta"],
        "visual_hook": "第一视角或手持跟随，像真实生活切片",
        "tone": "自然、可信、轻叙述",
        "cta_role": "低干扰的轻 CTA",
        "requires_evidence": False,
    },
    {
        "key": "social_proof", "label": "社会认同 · 群体→口碑→归因",
        "desc": "用真实使用场景中的群体信号与口碑建立信任，再把信任归因到产品能力。不得虚构评价或数量。",
        "beats": ["群体信号", "真实口碑", "能力归因", "行动收口"],
        "layers": ["pain", "proof", "attribution", "cta"],
        "visual_hook": "多人真实使用场景，禁止伪造评价截图",
        "tone": "可信、克制、去夸张",
        "cta_role": "跟随可信群体的低风险行动",
        "requires_evidence": True,
    },
    {
        "key": "scarcity", "label": "稀缺紧迫 · 时机→窗口→行动",
        "desc": "用真实存在的时机窗口推动决策。限时 / 限量 / 价格必须能在页面证据中定位，否则自动降级。",
        "beats": ["时机识别", "窗口展示", "代价提示", "立即行动"],
        "layers": ["desire", "decision", "cta"],
        "visual_hook": "时间或数量线索只作为构图氛围，不绘制文字",
        "tone": "紧凑、明确、不恐吓",
        "cta_role": "窗口期内的立即行动",
        "requires_evidence": True,
    },
]

FRAMEWORK_BY_KEY = {f["key"]: f for f in FRAMEWORKS}
DEFAULT_FRAMEWORK = "aida"

BRIEF_FIELDS = (
    "raw_input", "framework", "product", "audience", "hook", "pain", "desire",
    "proof", "attribution", "decision", "cta", "visual_hook", "beat", "tone",
    "sound_design", "avoid", "layers", "warnings", "confirmed", "brief_hash",
    "prompt_text",
)

_NUMBER_RE = re.compile(r"\d|％|%|折|off|限时|限量|免费|销量|用户数|评分|第一|最佳|top\s*\d", re.I)
_QUOTED_RE = re.compile(r"[\"“”「」']")


def framework_of(key: str = "") -> dict[str, Any]:
    """未知框架一律回退 AIDA，避免生成链路因前端传值异常中断。"""
    return FRAMEWORK_BY_KEY.get((key or "").strip() or DEFAULT_FRAMEWORK,
                                FRAMEWORK_BY_KEY[DEFAULT_FRAMEWORK])


def framework_options() -> list[dict[str, Any]]:
    """供前端下拉直接渲染，不暴露内部 beats 之外的实现细节。"""
    return [
        {
            "key": f["key"], "label": f["label"], "desc": f["desc"],
            "beats": list(f["beats"]), "layers": list(f["layers"]),
            "requires_evidence": bool(f["requires_evidence"]),
        }
        for f in FRAMEWORKS
    ]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first(values: Any, limit: int = 3) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [_clean(x) for x in values if _clean(x)][:limit]


def _warnings(raw: str, fw: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if _NUMBER_RE.search(raw):
        out.append("输入含数字 / 折扣 / 排名等强转化表述：必须能在页面证据中定位，否则生成时自动降级为场景化表达。")
    if _QUOTED_RE.search(raw):
        out.append("输入含引号文字：系统将按「不上屏」处理，转为旁白或播放层叠加候选，不交给模型画字。")
    if fw.get("requires_evidence"):
        out.append("所选框架依赖可信证据；若页面无对应事实，证据门会把证明段降级为真实功能演示。")
    return out


def render_brief_for_review(brief: dict[str, Any]) -> str:
    """生成给用户查阅 / 编辑 / 确认的自然语言版本。"""
    fw = framework_of(brief.get("framework"))
    lines = [
        "【完善后的创意 brief · %s】" % fw["label"],
        "目标产品：%s" % (brief.get("product") or "产品"),
        "目标受众：%s" % (brief.get("audience") or "页面分析结论中的目标人群"),
        "一句话钩子：%s" % (brief.get("hook") or ""),
        "痛点识别：%s" % (brief.get("pain") or ""),
        "渴望结果：%s" % (brief.get("desire") or ""),
        "可信证据：%s（仅引用页面证据链，未核实不写数字）" % (brief.get("proof") or ""),
        "能力归因：%s" % (brief.get("attribution") or ""),
        "决策降本：%s" % (brief.get("decision") or ""),
        "行动收口：%s（作为旁白或播放层叠加，不绘制到画面）" % (brief.get("cta") or ""),
        "视觉钩子：%s" % (brief.get("visual_hook") or ""),
        "叙事节奏：%s" % (brief.get("beat") or ""),
        "语气 / 镜头：%s" % (brief.get("tone") or ""),
        "音频纪律：%s" % (brief.get("sound_design") or ""),
        "禁止事项：%s" % (brief.get("avoid") or ""),
    ]
    if brief.get("warnings"):
        lines.append("风险提示：" + "；".join(brief["warnings"]))
    lines.append("确认状态：%s" % ("已确认，可进入生成" if brief.get("confirmed") else "未确认，不会进入生成"))
    return "\n".join(lines)


def normalize_brief(raw: Any = None, analysis: Optional[dict] = None,
                    framework: str = "", layers: Optional[list[str]] = None,
                    confirmed: bool = False) -> dict[str, Any]:
    """把用户原始输入补全为结构化 brief。

    - raw 可为字符串或 dict；dict 中可带具体字段覆盖自动补全结果；
    - analysis 仅用于补产品 / 受众 / 卖点提示，不作为新增事实来源；
    - 任何 brief 都不得绕过证据门与零文字契约。
    """
    analysis = analysis or {}
    if isinstance(raw, dict):
        src = dict(raw)
        raw_input = _clean(src.get("raw_input") or src.get("user_input") or src.get("raw") or "")
        fw_key = _clean(src.get("framework") or framework) or DEFAULT_FRAMEWORK
    else:
        src = {}
        raw_input = _clean(raw)
        fw_key = _clean(framework) or DEFAULT_FRAMEWORK

    fw = framework_of(fw_key)
    product = _clean(src.get("product") or analysis.get("product") or analysis.get("title")) or "产品"
    audience = _clean(src.get("audience") or analysis.get("audience"))
    strengths = _first(analysis.get("advantages") or analysis.get("sellingPoints") or [])

    brief: dict[str, Any] = {
        "raw_input": raw_input,
        "framework": fw["key"],
        "product": product,
        "audience": audience,
        "hook": _clean(src.get("hook")) or (
            "用%s的可观察结果或反差场景在前 3 秒抓住注意" % product),
        "pain": _clean(src.get("pain")) or (
            "围绕「%s」的真实痛点展开，不引入页面未说明的事实" % (audience or "目标受众")),
        "desire": _clean(src.get("desire")) or (
            "把可验证的核心利益翻译成具体理想结果%s" % (
                "（如：%s）" % "、".join(strengths[:2]) if strengths else "")),
        "proof": _clean(src.get("proof")) or (
            "仅引用页面证据链中可定位的事实；无证据时用真实功能演示，不写数字"),
        "attribution": _clean(src.get("attribution")) or (
            "把结果归因到产品真实具备的能力，不夸大适用范围"),
        "decision": _clean(src.get("decision")) or (
            "用卖点清单 / 适用场景压缩决策成本，不虚构价格或优惠"),
        "cta": _clean(src.get("cta")) or "了解更多",
        "visual_hook": _clean(src.get("visual_hook")) or fw["visual_hook"],
        "beat": " → ".join(fw["beats"]),
        "tone": _clean(src.get("tone")) or fw["tone"],
        "sound_design": _clean(src.get("sound_design")) or (
            "静音浏览时也应理解主动作；旁白只复述已核实事实"),
        "avoid": _clean(src.get("avoid")) or (
            "禁止虚构价格 / 折扣 / 评分 / 用户数 / 倒计时；画面零文字；CTA 交播放层叠加"),
        "layers": list(layers or src.get("layers") or fw["layers"]),
        "warnings": _warnings(raw_input, fw),
        "confirmed": bool(src.get("confirmed", confirmed)),
    }
    brief["layers"] = [x for x in brief["layers"] if x in LAYER_ORDER] or list(fw["layers"])
    payload = {k: v for k, v in brief.items() if k != "brief_hash"}
    brief["brief_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    brief["prompt_text"] = render_brief_for_review(brief)
    return brief


def _confirmed(brief: Optional[dict]) -> Optional[dict]:
    """未确认 brief 一律不进入生成；兼容前端直接传 prompt_text 的旧形态。"""
    if not brief:
        return None
    if not isinstance(brief, dict):
        brief = {"raw_input": _clean(brief)}
    if not brief.get("confirmed"):
        return None
    return brief if brief.get("prompt_text") else normalize_brief(brief, confirmed=True)


def build_copy_brief_block(brief: Optional[dict], platform: str = "") -> str:
    """文案系统提示词附加块：表达策略，不是事实依据。"""
    b = _confirmed(brief)
    if not b:
        return ""
    fw = framework_of(b.get("framework"))
    lines = [
        "【用户确认的创意表达策略 · 非事实依据 · brief=%s】" % b.get("brief_hash"),
        "采用框架：%s；叙事顺序：%s。" % (fw["label"], b.get("beat")),
    ]
    if b.get("variation"):
        lines.append("换一批变体：第 %s 版；换一条不同的钩子和表达角度，不要复述上一版。" % b["variation"])
    lines += [
        "钩子：%s" % b.get("hook"),
        "痛点 → 渴望：%s → %s" % (b.get("pain"), b.get("desire")),
        "证据表达：%s" % b.get("proof"),
        "能力归因 / 决策降本：%s / %s" % (b.get("attribution"), b.get("decision")),
        "CTA：%s" % b.get("cta"),
        "语气：%s" % b.get("tone"),
    ]
    if platform:
        lines.append("投放平台：%s；CTA 措辞须符合该平台候选值。" % platform)
    lines.append(
        "纪律：以上只调整钩子、顺序与措辞；不得据此编造数字、折扣、评分、用户数、倒计时或背书，"
        "所有事实仍以落地页证据为准；不要输出解释文字。"
    )
    return "\n".join(lines)


def build_image_brief_block(brief: Optional[dict], platform: str = "") -> str:
    """图片系统提示词附加块：视觉化表达策略，CTA 仅作为构图意图。"""
    b = _confirmed(brief)
    if not b:
        return ""
    fw = framework_of(b.get("framework"))
    lines = [
        "【用户确认的视觉表达策略 · 非事实依据 · brief=%s】" % b.get("brief_hash"),
        "视觉框架：%s；画面叙事：%s。" % (fw["label"], b.get("beat")),
        "视觉钩子：%s" % b.get("visual_hook"),
        "痛点场景：%s" % b.get("pain"),
        "渴望结果（用画面呈现，不写字）：%s" % b.get("desire"),
        "可信证据画面：%s" % b.get("proof"),
        "构图语气：%s" % b.get("tone"),
        "CTA 只作为右下 / 底部叠加位的构图意图，不要在画面里绘制文字或按钮。",
    ]
    if platform:
        lines.append("遵循 %s 平台素材规格与版位要求。" % platform)
    lines.append("纪律：不得据此编造商品事实、价格、评分或用户数；画面仍保持零文字。")
    return "\n".join(lines)


def build_video_brief_block(brief: Optional[dict], platform: str = "") -> str:
    """视频系统提示词附加块：导演指令，hook/cta 不作为上屏文字。"""
    b = _confirmed(brief)
    if not b:
        return ""
    fw = framework_of(b.get("framework"))
    lines = [
        "【用户确认的导演策略 · 非事实依据 · brief=%s】" % b.get("brief_hash"),
        "视频框架：%s；五段节奏：%s。" % (fw["label"], b.get("beat")),
        "开场钩子指令（用动作 / 反差表达，不画字）：%s" % b.get("hook"),
        "痛点放大：%s" % b.get("pain"),
        "方案演示：%s" % b.get("desire"),
        "证据镜头：%s" % b.get("proof"),
        "收口动作（仅作为动作 / 叠加位，不画字）：%s" % b.get("cta"),
        "镜头语气：%s；音频：%s" % (b.get("tone"), b.get("sound_design")),
    ]
    if platform:
        lines.append("遵循 %s 平台素材规格与静音浏览场景。" % platform)
    lines.append("纪律：以上只指导镜头、节奏与旁白；数字与承诺必须过证据门，画面文字仍由三道防线管理。")
    return "\n".join(lines)
