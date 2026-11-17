"""V4.88：内部提示词契约（不改界面、不改流程）。

来源：《全球主流媒体图片与视频推广提示词体系及品牌级验收规范》1.0。
本模块只做确定性编译，不调用模型、不碰数据库：

- 把文档的行业 / 人群 / 素材类型词表映射成内部 ID，不替换现有 profile；
- 集中维护 GLOBAL-VISUAL-1、图片 / 视频无字主模板、负向约束；
- 生成可追溯的 PromptContract 快照，写入图片资产与视频任务元数据。

纪律：文档的阈值（覆盖率、评分、时间分配）是内部制作建议，不冒充平台官方硬规则。
无字策略默认用于“纯图片”和所有视频出片提示词；原有文字 / 按钮 / Logo 选项仍保留，
但在无字策略下只作为策划、排版或 VO 参考，不绘制进生成画面。
"""
from __future__ import annotations

import hashlib
import json
import re

CONTRACT_SCHEMA_VERSION = "1.0.0"
GLOBAL_VISUAL_ID = "GLOBAL-VISUAL-1"
QUALITY_PROFILE = "BRAND-QA-1"

INDUSTRIES = {
    "I00": {"label": "待分类 / 未覆盖品类", "internal_profile": "general"},
    "I01": {"label": "家居日用", "internal_profile": "ecommerce"},
    "I02": {"label": "服饰配件", "internal_profile": "ecommerce"},
    "I03": {"label": "美妆个护", "internal_profile": "ecommerce"},
    "I04": {"label": "食品饮品", "internal_profile": "ecommerce"},
    "I05": {"label": "宠物用品", "internal_profile": "ecommerce"},
    "I06": {"label": "数码家电", "internal_profile": "ecommerce"},
    "I07": {"label": "移动应用", "internal_profile": "app_game"},
    "I08": {"label": "数字订阅", "internal_profile": "subscription"},
    "I09": {"label": "游戏娱乐", "internal_profile": "app_game"},
    "I10": {"label": "B2B 与 SaaS", "internal_profile": "b2b_service"},
    "I11": {"label": "成人教育", "internal_profile": "education"},
    "I12": {"label": "旅游及本地服务", "internal_profile": "travel_local"},
}

INDUSTRY_BY_PROFILE = {
    "ecommerce": "I01", "subscription": "I08", "app_game": "I07",
    "b2b_service": "I10", "travel_local": "I12", "education": "I11",
    "finance": "I00", "general": "I00",
}

AUDIENCES = {
    "A00": "待确认（不按外貌 / 敏感属性推断）",
    "A01": "时间紧张者", "A02": "家庭与空间管理者", "A03": "专业或通勤使用者",
    "A04": "审美与身份表达者", "A05": "谨慎品质比较者", "A06": "体验与兴趣探索者",
    "A07": "已有品类经验者", "A08": "成长与效率导向者", "A09": "已了解产品的犹豫者",
    "A10": "核心玩家与爱好者",
}

CREATIVE_TYPES = {
    "T01": "生活方式情境", "T02": "功能演示", "T03": "材质与工艺", "T04": "视觉隐喻",
    "T05": "有依据的差异", "T06": "创作者视角", "T07": "内容与玩法证明",
    "T08": "场景化静物", "T09": "细节答疑", "T10": "续用与关系",
}

GLOBAL_VISUAL_CONTRACT = (
    "[GLOBAL-VISUAL-1 · 不可由行业模板覆盖]\n"
    "1. 画面内不出现文字、数字、字母、字幕、价格、折扣、星级、认证印章、水印、角标、"
    "Logo 叠加或伪造交互；不绘制按钮、下载框、播放键、箭头引导与假 UI。平台渲染的 CTA "
    "与账户文字不属于生成画面。\n"
    "2. 不用蒙版、半透明层、渐变遮罩、大色块、暗角或人工虚化铺底遮盖背景；不白底拼贴、"
    "不留白等文案、不边框、不拷贝拉伸。允许真实光影与合理景深，不允许用失焦填尺寸。\n"
    "3. 真实场景从画布一边延伸至另一边；主体轮廓清楚，有前中后景和可信接触点。主体位于"
    "实际媒体安全区，边缘继续铺真实环境。\n"
    "4. 不为了满版增加无关道具或重复商品，不为未来文案预留大片空位。若真实标签、界面或"
    "法定说明无法在无字条件下准确表达，返回 needs_review，不篡改产品来通过检测。"
)

IMAGE_MASTER_PURE = (
    "[图片无字主模板]\n"
    "按目标画布比例直接构图，不先做方图再裁切；产品与人物、环境、光线和材质保持一致，"
    "不添加不存在的配件、接口、功能或品牌标识。通过一个真实可见动作和一个可观察细节表达"
    "单一已核实价值。场景延伸至四边，背景有真实空间层次。完成商业摄影级画面，保留自然"
    "细节与可信材质，不用塑料皮肤、过度锐化、过饱和或不合理镜面反射。"
)

VIDEO_MASTER_PURE = (
    "[视频无字主模板]\n"
    "首帧直接出现产品参与的可理解动作，不以空景、Logo 或泛化惊奇镜头开场；中段展示真实"
    "使用动作与可信细节，动作因果清楚，不瞬移、不变形；结尾回到自然使用结果或下一步动作，"
    "以场景和动作收束。镜头间按动作与视线匹配切换，身份、产品结构、光线和人物关系稳定；"
    "不用炫目转场掩盖问题，不慢放、循环或补静帧冒充完整时长。静音浏览时也应理解主动作；"
    "如需声音，只使用已核实的简短画外音或自然环境音。输出真实可播放文件，不以分镜脚本、"
    "外链或静帧序列冒充成片。"
)

NEGATIVE_PROMPT = (
    "text, letters, numbers, captions, subtitles, price tags, ratings, badges, watermark, "
    "overlay logo, CTA, button, fake UI, blank white background, dominant solid-color background, "
    "large empty copy space, opaque panel, translucent mask, gradient overlay, blurred padding, "
    "borders, collage, distorted product, extra parts, warped hands, impossible shadows, "
    "duplicated objects, temporal flicker, identity drift, changing product geometry, morphing, "
    "object teleportation, impossible motion, frozen loop, fake before-and-after, jumpy exposure, "
    "abrupt audio cut, unwanted subtitles"
)

BASELINE_OVERLAY_CONSTRAINTS = (
    "[叠加模式底线约束]\n"
    "保留现有图内文案 / Logo / 按钮策略，但画面必须由真实满版场景构成；不得绘制假 UI、"
    "伪造按钮或不可能的界面，不得用蒙版、半透明色块或模糊铺底遮盖生成缺陷，不得篡改真实"
    "商品外观。文字由现有排版层按安全区添加，生成底图本身不自行发明文字。"
)

_AUDIENCE_KEYWORDS = {
    "A01": (r"通勤|早晨|赶时间|多任务|时间紧|busy|commut|time.sav",),
    "A02": (r"家庭|居家|收纳|宠物看护|family|home|storage|pet",),
    "A03": (r"办公|专业|工作|出差|business|office|work|commut",),
    "A04": (r"穿搭|风格|审美|创作|身份|style|fashion|creative",),
    "A05": (r"品质|材质|细节|对比|认证|quality|material|detail|compare",),
    "A06": (r"周末|休闲|新体验|探索|adventure|weekend|explor",),
    "A07": (r"更换|升级|配件|已有|replacement|upgrade|accessor",),
    "A08": (r"学习|效率|制作|分析|协作|productive|learn|workflow",),
    "A09": (r"再营销|犹豫|评估|决策|retarget|consider|evaluat",),
    "A10": (r"玩家|玩法|策略|技巧|gamer|gameplay|strateg",),
}

_CREATIVE_TYPE_KEYWORDS = {
    "T02": (r"功能|演示|操作|连接|使用动作|demo|function|how.to",),
    "T03": (r"材质|工艺|微距|纹理|反射|macro|material|texture",),
    "T04": (r"隐喻|概念|象征|比喻|metaphor|concept",),
    "T05": (r"差异|对比|同条件|before|after|compare|difference",),
    "T06": (r"创作者|手持|第一视角|UGC|creator|handheld",),
    "T07": (r"玩法|录屏|内容证明|gameplay|screen.record|content",),
    "T08": (r"静物|场景化|陈列|still.life|product.scene",),
    "T09": (r"答疑|细节回应|结构|尺度|开合|faq|detail",),
    "T10": (r"续用|关系|重复使用|服务过程|routine|repeat.use",),
}

_INDUSTRY_KEYWORDS = {
    "I01": (r"家居|收纳|厨具|清洁|家具|home|storage|furniture",),
    "I02": (r"服饰|鞋|包|饰品|apparel|shoes|bag|fashion",),
    "I03": (r"美妆|护肤|彩妆|洗护|beauty|skincare|cosmetic",),
    "I04": (r"食品|饮品|咖啡|零食|food|drink|coffee|snack",),
    "I05": (r"宠物|围栏|牵引|pet|dog|cat",),
    "I06": (r"数码|家电|耳机|设备|electronics|device|appliance",),
    "I07": (r"应用|app|工具|utility|mobile app",),
    "I08": (r"订阅|会员|影音|内容会员|subscription|membership",),
    "I09": (r"游戏|休闲|策略|竞技|game|gaming",),
    "I10": (r"b2b|saas|crm|企业服务|协作|enterprise|analytics",),
    "I11": (r"教育|课程|培训|学习|education|course|training",),
    "I12": (r"旅游|酒店|本地服务|家政|维修|travel|hotel|local service",),
}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _unwrap(analysis: dict) -> dict:
    a = analysis if isinstance(analysis, dict) else {}
    inner = a.get("analysis")
    return inner if isinstance(inner, dict) else a


def _haystack(analysis: dict, brief: dict | None, route: dict | None) -> str:
    a = _unwrap(analysis)
    b = brief if isinstance(brief, dict) else {}
    r = route if isinstance(route, dict) else {}
    parts = [
        a.get("industry"), a.get("type"), a.get("industry_profile"),
        a.get("audience"), a.get("coreAudience"), a.get("purchaseMotivation"),
        b.get("targetAudience"), b.get("promotionGoal"), b.get("sellingPoints"),
        b.get("scene"), b.get("setting"), b.get("composition"),
        r.get("name"), r.get("description"), r.get("angle"), r.get("tags"),
    ]
    return " ".join(_clean(x) for x in parts if x is not None)


def classify_industry(analysis: dict | None = None, profile_key: str = "") -> dict:
    """文档 I 类 ↔ 现有 internal profile 的保守映射，不新增用户下拉。"""
    a = _unwrap(analysis)
    key = _clean(profile_key or a.get("industry_profile") or a.get("profile_key"))
    ident = INDUSTRY_BY_PROFILE.get(key)
    text = _haystack(analysis, a.get("brief") or {}, None).lower()
    if not ident:
        ident = next((iid for iid, pats in _INDUSTRY_KEYWORDS.items()
                      if any(re.search(p, text, re.I) for p in pats)), "I00")
    row = INDUSTRIES[ident]
    return {"id": ident, "label": row["label"], "internal_profile": row["internal_profile"]}


def classify_audience(analysis: dict | None = None) -> dict:
    """只按任务 / 情境 / 动机关键词推断，不用年龄、性别、健康等敏感属性。"""
    text = _haystack(analysis, (_unwrap(analysis).get("brief") or {}), None).lower()
    ident = next((aid for aid, pats in _AUDIENCE_KEYWORDS.items()
                  if any(re.search(p, text, re.I) for p in pats)), "A00")
    return {"id": ident, "label": AUDIENCES[ident]}


def classify_creative_type(route: dict | None = None, brief: dict | None = None) -> dict:
    text = _haystack({}, brief, route).lower()
    ident = next((tid for tid, pats in _CREATIVE_TYPE_KEYWORDS.items()
                  if any(re.search(p, text, re.I) for p in pats)), "T01")
    return {"id": ident, "label": CREATIVE_TYPES[ident]}


def _facts(analysis: dict) -> list[str]:
    a = _unwrap(analysis)
    raw = list(a.get("facts") or a.get("advantages") or a.get("sellingPoints") or [])
    return [_clean(x)[:160] for x in raw if _clean(x)][:8]


def _evidence_ids(analysis: dict) -> list[str]:
    a = _unwrap(analysis)
    out: list[str] = []
    for row in a.get("evidence_chain") or []:
        if isinstance(row, dict) and not row.get("rejected"):
            for eid in row.get("evidence_ids") or []:
                eid = _clean(eid)
                if eid and eid not in out:
                    out.append(eid)
    return out[:12]


def _placement(spec: dict | None, analysis: dict | None) -> dict:
    s = spec if isinstance(spec, dict) else {}
    a = _unwrap(analysis)
    return {
        "platform": _clean(s.get("platform")) or _clean(a.get("platform")),
        "ad_product": _clean(s.get("ad_product")),
        "placement_id": _clean(s.get("placement_id")),
        "target_size": _clean(s.get("target_size")),
        "target_aspect": _clean(s.get("target_aspect")),
        "format": _clean(s.get("format")),
        "max_bytes": s.get("max_bytes"),
        "duration": s.get("duration"),
        "spec_version": _clean(s.get("spec_version")),
        "verification": _clean(s.get("verification")),
        "source_url": _clean(s.get("source_url")),
    }


def _video_contract(plan: dict, analysis: dict) -> dict:
    p = plan if isinstance(plan, dict) else {}
    shots = []
    for i, shot in enumerate(p.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        shots.append({
            "start": _clean(shot.get("t") or "").split("-")[0].strip() or None,
            "end": _clean(shot.get("t") or "").split("-")[-1].strip() or None,
            "visual_action": _clean(shot.get("visual")),
            "camera": _clean(shot.get("camera")),
            "lighting": _clean(shot.get("lighting")),
            "transition": _clean(shot.get("motion")),
            "audio": _clean(shot.get("vo")),
            "must_preserve": _evidence_ids(analysis)[:6],
            "failure_checks": ["no_text", "no_button", "identity_continuity", "actual_duration"],
        })
    return {
        "requested_duration": p.get("duration_sec"),
        "submitted_duration": p.get("duration_sec"),
        "measured_duration": None,
        "frame_rate": None,
        "audio_mode": _clean(p.get("voiceover") or (p.get("options") or {}).get("voiceover")),
        "scene_order": [_clean(s.get("visual_action")) for s in shots if s.get("visual_action")],
        "shots": shots,
    }


def build_prompt_contract(*, media_type: str, analysis: dict | None = None,
                          brief: dict | None = None, profile_key: str = "",
                          route: dict | None = None, plan: dict | None = None,
                          placement: dict | None = None,
                          overlay_mode: str = "pure") -> dict:
    """把现有分析 / 简报 / 版位 / 分镜编译成文档要求的结构化提示词源记录。"""
    media = "video" if _clean(media_type).lower() == "video" else "image"
    a = _unwrap(analysis)
    b = brief if isinstance(brief, dict) else {}
    ind = classify_industry(analysis, profile_key)
    aud = classify_audience(analysis)
    ctp = classify_creative_type(route, b)
    facts = _facts(analysis)
    eids = _evidence_ids(analysis)
    product = _clean(b.get("subject") or a.get("product") or (analysis or {}).get("title") or "产品")
    promise = _clean(b.get("core_promise") or b.get("promise") or (facts[0] if facts else ""))
    subject = _clean(b.get("subject") or product)
    scene = _clean(b.get("setting") or b.get("scene") or "真实使用场景")
    proof = _clean(b.get("evidence") or (facts[0] if facts else ""))
    audience_job = _clean(b.get("audience_scenario") or b.get("targetAudience")
                          or a.get("coreAudience") or aud["label"])
    composition = _clean(b.get("composition") or "满版真实场景，主体位于实际媒体安全区")
    lighting = _clean(b.get("lighting_material") or "待确认：自然光方向与真实材质，不凭空生成品牌规范")
    no_text = media == "video" or _clean(overlay_mode) == "pure"
    digest_src = {
        "m": media, "i": ind["id"], "a": aud["id"], "t": ctp["id"],
        "p": product, "v": promise, "f": facts, "e": eids,
        "pl": _placement(placement, analysis), "nt": no_text,
    }
    digest = hashlib.sha256(json.dumps(
        digest_src, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    contract = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "prompt_id": f"{'VID' if media == 'video' else 'IMG'}-{ind['id']}-{aud['id']}-{ctp['id']}-{digest}",
        "media_type": media,
        "industry": ind,
        "audience": aud,
        "creative_type": ctp,
        "objective": _clean(b.get("promotionGoal") or a.get("purchaseMotivation") or "单一产品价值"),
        "product": product,
        "product_facts": [{"claim": x, "source_id": eids[i] if i < len(eids) else None}
                          for i, x in enumerate(facts)],
        "evidence_ids": eids,
        "audience_job": audience_job,
        "visual_promise": promise,
        "scene": scene,
        "subject": subject,
        "proof": proof,
        "composition": composition,
        "lighting_material": lighting,
        "placement": _placement(placement, analysis),
        "constraints_ref": GLOBAL_VISUAL_ID,
        "negative_prompt": NEGATIVE_PROMPT,
        "quality_profile": QUALITY_PROFILE,
        "evidence_status": "verified" if eids else "unverified",
        "overlay_mode": _clean(overlay_mode) or "pure",
        "no_text_policy": no_text,
    }
    if media == "video":
        contract["video"] = _video_contract(plan, analysis)
    return contract


def _header(contract: dict) -> str:
    return (f"[PromptContract] prompt_id={contract.get('prompt_id', '')} "
            f"schema={contract.get('schema_version', '')} "
            f"constraints={contract.get('constraints_ref', '')} "
            f"evidence={contract.get('evidence_status', '')}")


def _compiled_line(contract: dict) -> str:
    pl = contract.get("placement") or {}
    place = " / ".join(str(pl.get(k) or "") for k in ("platform", "ad_product", "target_aspect", "target_size", "spec_version") if pl.get(k))
    return (
        "编译事实：主体【{subject}】；受众任务【{aud}】；场景【{scene}】；"
        "单一价值【{promise}】；证据【{eids}】；版位【{place}】。"
    ).format(
        subject=contract.get("subject") or "产品",
        aud=contract.get("audience_job") or "真实任务",
        scene=contract.get("scene") or "真实使用场景",
        promise=contract.get("visual_promise") or "页面已明示的价值",
        eids="、".join(contract.get("evidence_ids") or []) or "无可定位原文（不生成量化承诺）",
        place=place or "未标注（不猜规格）",
    )


def render_image_contract_block(contract: dict) -> str:
    """图片提示词尾部追加块：纯图片走无字主模板，叠加模式只追加底线。"""
    head = _header(contract)
    if contract.get("no_text_policy"):
        return "\n".join([
            head,
            _compiled_line(contract),
            GLOBAL_VISUAL_CONTRACT,
            IMAGE_MASTER_PURE,
            "负向约束：" + NEGATIVE_PROMPT,
            "覆盖规则：若上文出现留白、文案区、按钮或 Logo 要求，以本契约为准并删除该要求；冲突无法消解时返回 needs_review。",
        ])
    return "\n".join([
        head,
        _compiled_line(contract),
        BASELINE_OVERLAY_CONSTRAINTS,
        "规格纪律：目标尺寸与比例只来自广告位规则，不从提示词猜测；不得用纯色边或模糊铺底填尺寸。",
    ])


def render_video_contract_block(contract: dict) -> str:
    """视频出片提示词尾部追加块；字幕 / CTA / Logo 字段不再绘制进画面。"""
    pl = contract.get("placement") or {}
    spec_line = "；".join(
        f"{k}={pl[k]}" for k in ("platform", "ad_product", "target_aspect", "target_size", "duration", "spec_version", "verification") if pl.get(k)
    ) or "规格未标注（不猜）"
    return "\n".join([
        _header(contract),
        _compiled_line(contract),
        GLOBAL_VISUAL_CONTRACT,
        VIDEO_MASTER_PURE,
        "字段纪律：分镜中的字幕 / CTA / 品牌 Logo 字段只用于内部节奏、VO 与策划追溯，不绘制到画面；不生成文字端卡、按钮或伪界面。",
        "音频纪律：画外音只能复述已核实事实并保留限定；无 VO 时静音也应能理解主动作；不模仿未授权声音。",
        "规格注入：" + spec_line,
        "负向约束：" + NEGATIVE_PROMPT,
    ])
