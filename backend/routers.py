from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Response
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import os, time, re, json

from database import get_db
from models import (ModelConfig, User, AuditLog, LoginLog, PromptConfig, SystemState,
                    CreationHistory, GenerationJob, CreativeAsset, CreativeAnalysis, CreativePlan, CwLibrary, utcnow)
from schemas import (ModelConfigIn, ModelConfigOut, ModelTestIn,
                     LoginRequest, UserOut, UserCreate, UserUpdate,
                     PromptOut, PromptUpdate, PromptDefaultIn,
                     LandingAnalysisRequest, LandingAnalysis, MediaCopyRequest, MediaImageRequest,
                     CreativeAnalysisRequest, CreativeAnalysisResult,
                     CreativePlanRequest, CreativePlanResult, CreativeRoute,
                     CWAnalyzeRequest, CWAnalysisResult, CWRoutesRequest, CWRoute, CWRoutesResult,
                     ProductSnapshot, CwLibraryOut, CwLibraryCreate,
                     CWVideoPlanRequest, CWVideoPlanResult, CWVideoGenerateRequest, CWVideoGenerateResult,
                     CWVideoAsset, ModelInfo)
from services import PROMPT_REGISTRY, analyze_landing_concise
from llm_catalog import test_llm_connection, _resolve_protocol
from providers import get_llm_with_info, finalize_invocation, parse_json, get_video, _active_config, StoryboardVideo
from presets import creative_presets_payload
from prompt_catalog import (library_dimensions, library_entries,
                            get_practice, target_key_for_kind, KINDS, FUNC_TYPES,
                            USAGE_TYPES, BEST_PRACTICES)
from media_platforms import (list_media_platforms, validate_platform,
                             validate_task_matrix, media_rules_payload,
                             canonical_platform,
                             MediaRuleError, SPEC_VERSION, MEDIA_RULES)
from media_ad import generate_media_copy, generate_media_images
from industry_profiles import resolve_profile
from creation_plan_service import (
    create_plan, set_coverage, confirm_plan, attach_job, finalize,
    get_plan, plan_to_dict,
)
from version import ENABLE_AUTO_CREATION_PLAN
from image_capabilities import public_capabilities
import job_service
from auth import (current_user, require_roles, verify_password, hash_password, create_token,
                  user_dict, ROLE_LABELS, CAN_EDIT, CAN_REVIEW, ROLES, decode_token)
from creation_history import (
    history_to_dict, derive_title, site_name_of, safe_image_path,
    media_type_of, image_files_of, copy_as_text, build_files_zip,
    build_history_zip, cleanup_orphan_files,
)
from fetchers import (fetch_product, demo_product, demo_snapshot,
                      evidence_prompt_part)

router = APIRouter(prefix="/api")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

@router.post("/landing-analysis", response_model=LandingAnalysis)
async def landing_analysis(req: LandingAnalysisRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*CAN_EDIT))):
    """素材创作：落地页分析。调用已配置的「分析 / 文案」大模型推理，产出 8 个必要字段，
    并回传实际调用了哪个模型（provider/model/role/fallback），便于持续跟踪各模型优劣势。结果不落库。"""
    url, text = (req.url or "").strip(), (req.text or "").strip()
    if not url and not text:
        raise HTTPException(400, "请提供落地页 URL 或正文")
    result = await analyze_landing_concise(db, url or None, text or None)
    # V4.42 / F09 / T12：空页、抓取失败、薄内容或过期优惠在调用模型前明确阻断，
    # 不返回一份「看起来能用但没有事实证据」的分析结果。
    if result.get("gate_status") == "needs_input":
        raise HTTPException(422, detail={
            "message": "落地页证据不足，已在调用模型前阻断分析（needs_input）",
            "errors": result.get("blocked_reasons") or [],
            "evidence_gate": "needs_input",
            "fetch_quality": result.get("fetch_quality") or "",
            "expired_offers": result.get("evidence_expired_offers") or [],
            "hint": "请补充落地页正文 / 检查网址可达性 / 移除过期优惠后重试；系统不会从 URL 猜测产品事实。",
        })
    return LandingAnalysis(**result)

# ----------------------------- 素材创作：营销推广的媒体平台设置 -----------------------------
@router.get("/media-platforms")
async def api_media_platforms(_: User = Depends(require_roles(*CAN_EDIT))):
    """营销推广媒体平台规格：数量 / 规格 / 尺寸 / 常规方案 / 字数红线。

    V4.40 / F08：每个版位额外返回 `ad_product` / `asset_role` / `os`，平台返回
    `spec_version` / `spec_source` / `spec_verified_on` / `rules`，供任务矩阵与导出标注。
    """
    return list_media_platforms()


@router.get("/media-rules")
async def api_media_rules(_: User = Depends(require_roles(*ROLES))):
    """V4.40 / F08：版本化媒体规则（强制 / 政策 / 建议）、限制与各平台允许尺寸。"""
    return media_rules_payload()


def _rule_error(exc: MediaRuleError) -> HTTPException:
    """把规则拒绝整理成接口可读的明确错误（不吞掉任何一条原因）。"""
    return HTTPException(422, detail={
        "message": "媒体规则校验未通过，已在调用模型前拦截",
        "errors": exc.errors,
        "spec_version": SPEC_VERSION,
    })


@router.get("/industry-profiles")
def api_industry_profiles(_: User = Depends(require_roles(*ROLES))):
    """V4.39：行业 / 品类画像列表，供「素材创作」局部调整。

    主干链路对所有行业一致；画像只调整价值维度、必须保留的语义、证据类型与视觉主体。
    """
    from industry_profiles import list_profiles, INDUSTRY_PROFILES, GENERIC_PATTERNS
    return {
        "profiles": list_profiles(),
        "total": len(INDUSTRY_PROFILES),
        "generic_rules": [label for _pat, label in GENERIC_PATTERNS],
        "note": "电商购买 / 订阅转化只是两个画像；未命中时使用 general，不猜产品事实。",
    }

@router.post("/media-campaign/copy")
async def api_media_campaign_copy(req: MediaCopyRequest, db: Session = Depends(get_db),
                                  user: User = Depends(require_roles(*CAN_EDIT))):
    """基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案，并标注本次调用的模型。

    文案必须结合落地页分析结论（行业/类型/优势/竞品/受众/推广途径），生成后立即返回，前端展示并允许编辑。
    """
    # V4.40 / F08：未知平台显式拒绝，不静默套用其它平台 schema
    try:
        platform = validate_platform(req.platform)
    except MediaRuleError as e:
        raise _rule_error(e)
    result = await generate_media_copy(db, req.analysis.model_dump(), platform, req.lang,
                                       ad_product=req.ad_product,
                                       style_opts=req.style_opts or {})
    return result

@router.post("/media-campaign/images")
async def api_media_campaign_images(req: MediaImageRequest, db: Session = Depends(get_db),
                                    user: User = Depends(require_roles(*CAN_EDIT))):
    """基于「任务矩阵 + 勾选的创意文案组合」生成推广图片素材。

    V4.38：copy_variants 按用户勾选文案拼出，未传时兼容旧行为。
    V4.40 / F07 + F08：slots 为前端确认过的任务矩阵；服务端在调用模型前按版本化规则
    重新解析尺寸、限制任务数与总像素、标注广告产品，并回传逐张状态（F11）。
    """
    slots = [s.model_dump() for s in req.slots]
    variants = [v.model_dump() for v in req.copy_variants]
    analysis = req.analysis.model_dump()
    profile = resolve_profile(analysis, key=analysis.get("industry_profile") or "")
    try:
        checked = validate_task_matrix(req.platform, slots,
                                       total_pixels=req.total_pixels,
                                       variant_count=len(variants),
                                       profile=profile)
    except MediaRuleError as e:
        raise _rule_error(e)
    if req.spec_version and req.spec_version != SPEC_VERSION:
        # 不静默升级/降级规则：客户端规则过期时明确提示刷新页面
        raise HTTPException(422, detail={
            "message": "媒体规则版本不一致，请刷新页面后重新生成",
            "errors": [f"客户端 {req.spec_version}，服务端 {SPEC_VERSION}"],
            "spec_version": SPEC_VERSION,
        })
    result = await generate_media_images(db, analysis, checked["meta"]["platform"], req.lang,
                                         req.copy_fields, req.style_opts, checked["slots"],
                                         req.logo or "", copy_variants=variants,
                                         rules_meta=checked["meta"],
                                         overlay_mode=req.overlay_mode)
    return result


# ===========================================================================
# V4.42 / F06 + F12：供应商尺寸能力、服务端持久任务与不可变资产
# ===========================================================================

# ===========================================================================
# V4.50 创意工作台：全球创意分析（参考素材 → LLM 归类创意风格/类型 → 可复用提示词模板）
# ===========================================================================
_CREATIVE_ANALYSIS_SYS = (
    "你是全球效果广告创意研究专家，长期跟踪 Meta、Google、Unity、Adsterra 等大媒体上"
    "最具创意、最具吸引力、流量效应与转化效果最好的广告素材。"
    "用户会给你若干参考素材（落地页 / 广告 / 竞品创意的链接或文本）。"
    "请从中总结、归类出可复用的「创意类型 / 风格」，并给出可直接用于文生图 / 文生视频的提示词模板。"
    "只返回 JSON，结构如下："
    "{\"title\": \"分析主题\","
    " \"summary\": \"对参考素材的整体洞察（为何有效、可借鉴点）\","
    " \"categories\": ["
    "   {\"name\": \"创意类型名\", \"description\": \"定义与适用场景\","
    "    \"traits\": [\"关键特征1\"],"
    "    \"examples\": [\"示例场景1\"],"
    "    \"image_prompt\": \"可直接用于文生图的提示词模板（含构图/色调/情绪/主体/文案占位）\","
    "    \"video_prompt\": \"可直接用于文生视频的提示词模板（含镜头/节奏/转场/时长建议）；若无法给出可留空\"}"
    " ]}"
    "要求：categories 不超过 8 条；image_prompt 必须具体、可直接调用模型；"
    "不要编造数据；如参考信息不足，可在 summary 中说明并给出通用建议。"
)


def _ca_to_dict(r: "CreativeAnalysis") -> dict:
    return {
        "id": r.id,
        "owner_id": r.owner_id,
        "owner_name": r.owner_name,
        "title": r.title,
        "inputs": r.inputs_json or {},
        "result": r.result_json or {},
        "model_info": r.model_info or {},
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


@router.post("/creative-analysis", response_model=CreativeAnalysisResult)
async def api_creative_analysis(req: CreativeAnalysisRequest, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·全球创意分析：参考素材 → 大模型归类创意风格/类型 → 可复用提示词模板；结果落库。"""
    urls = [str(u).strip() for u in (req.urls or []) if str(u).strip()]
    text = (req.text or "").strip()
    if not urls and not text:
        raise HTTPException(400, "请提供参考素材链接或文本")
    llm, info = get_llm_with_info(db, "analysis")
    user_prompt = json.dumps({"reference_urls": urls, "reference_text": text}, ensure_ascii=False)
    try:
        resp = await llm.chat(_CREATIVE_ANALYSIS_SYS, user_prompt)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    cats = []
    for c in (parsed.get("categories") or [])[:8]:
        if isinstance(c, dict):
            cats.append({
                "name": str(c.get("name") or "").strip(),
                "description": str(c.get("description") or "").strip(),
                "traits": [str(t) for t in (c.get("traits") or []) if str(t).strip()][:8],
                "examples": [str(e) for e in (c.get("examples") or []) if str(e).strip()][:6],
                "image_prompt": str(c.get("image_prompt") or "").strip(),
                "video_prompt": str(c.get("video_prompt") or "").strip(),
            })
    result = {
        "title": (req.title or parsed.get("title") or "全球创意分析"),
        "summary": str(parsed.get("summary") or "").strip(),
        "categories": cats,
        "model_info": info,
        "source": info.get("source", "local"),
    }
    rec = CreativeAnalysis(owner_id=user.id, owner_name=user.username,
                          title=result["title"], inputs_json={"urls": urls, "text": text},
                          result_json=result, model_info=info)
    db.add(rec); db.commit(); db.refresh(rec)
    result["id"] = rec.id
    return CreativeAnalysisResult(**result)


@router.get("/creative-analysis")
def list_creative_analysis(limit: int = 50, offset: int = 0, db: Session = Depends(get_db),
                           _: User = Depends(require_roles(*CAN_EDIT))):
    q = db.query(CreativeAnalysis).order_by(CreativeAnalysis.id.desc())
    lim = max(1, min(int(limit or 50), 200)); off = max(0, int(offset or 0))
    rows = q.offset(off).limit(lim).all()
    return {"items": [_ca_to_dict(r) for r in rows], "total": q.count(), "limit": lim, "offset": off}


@router.get("/creative-analysis/{cid}")
def get_creative_analysis(cid: int, db: Session = Depends(get_db),
                          _: User = Depends(require_roles(*CAN_EDIT))):
    r = db.query(CreativeAnalysis).filter_by(id=cid).first()
    if not r:
        raise HTTPException(404, "分析记录不存在")
    return _ca_to_dict(r)


# ----------------------------- V4.52 创意工作台：创意策略 / 路线规划 -----------------------------
_CREATIVE_PLAN_SYS = (
    "你是资深的出海效果广告创意策略师，长期跟踪 Meta、Google、Unity、Adsterra 等大媒体的高转化素材。"
    "基于给定的「产品分析结论」与「目标媒体平台」，为每一个平台规划一条创意路线。"
    "每条路线需包含：创意概念（concept）、切入角度（angle）、视觉风格（visual_style）、"
    "文案方向（copy_direction），以及一句可直接用于文生图的创意方向 / 提示词（image_prompt）。"
    "只返回 JSON，结构如下："
    "{\"title\": \"本次创意策略主题\","
    " \"routes\": ["
    "   {\"platform\": \"平台名\", \"concept\": \"创意概念\", \"angle\": \"切入角度\","
    "    \"visual_style\": \"视觉风格\", \"copy_direction\": \"文案方向\","
    "    \"image_prompt\": \"可直接用于文生图的创意方向 / 提示词\", \"notes\": \"补充说明\"}"
    " ]}"
    "要求：routes 数量须与给定平台数量一致（每个平台一条，platform 字段严格等于给定平台名）；"
    "image_prompt 必须具体、可直接调用模型；不要编造数据；如产品信息不足可在 notes 中说明。"
)


def _cp_to_dict(r: "CreativePlan") -> dict:
    return {
        "id": r.id,
        "owner_id": r.owner_id,
        "owner_name": r.owner_name,
        "title": r.title,
        "analysis": r.analysis_json or {},
        "platforms": r.platforms or [],
        "gen_image": r.gen_image,
        "gen_video": r.gen_video,
        "routes": r.routes_json or [],
        "status": r.status,
        "asset_count": r.asset_count,
        "history_id": r.history_id,
        "model_info": r.model_info or {},
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
    }


@router.post("/creative-plan", response_model=CreativePlanResult)
async def api_creative_plan(req: CreativePlanRequest, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·创意策略：产品分析 + 所选媒体平台 → 大模型规划每平台创意路线；结果落库。"""
    platforms = [str(p).strip() for p in (req.platforms or []) if str(p).strip()]
    analysis = req.analysis or {}
    if not platforms:
        raise HTTPException(400, "请至少选择一个媒体平台")
    if not analysis:
        raise HTTPException(400, "缺少产品分析结论（请先完成产品分析）")
    llm, info = get_llm_with_info(db, "analysis")
    user_prompt = json.dumps({"analysis": analysis, "platforms": platforms}, ensure_ascii=False)
    try:
        resp = await llm.chat(_CREATIVE_PLAN_SYS, user_prompt)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    # 归一化每条路线，并补齐缺失平台（保证与所选平台一一对应）
    route_map = {}
    for r in (parsed.get("routes") or []):
        if isinstance(r, dict) and str(r.get("platform") or "").strip():
            route_map[str(r.get("platform")).strip()] = {
                "platform": str(r.get("platform")).strip(),
                "concept": str(r.get("concept") or "").strip(),
                "angle": str(r.get("angle") or "").strip(),
                "visual_style": str(r.get("visual_style") or "").strip(),
                "copy_direction": str(r.get("copy_direction") or "").strip(),
                "image_prompt": str(r.get("image_prompt") or "").strip(),
                "notes": str(r.get("notes") or "").strip(),
            }
    routes = [route_map.get(p, {"platform": p}) for p in platforms]
    result = {
        "title": (req.title or parsed.get("title") or "创意策略规划"),
        "platforms": platforms,
        "gen_image": req.gen_image,
        "gen_video": req.gen_video,
        "routes": routes,
        "status": "draft",
        "model_info": info,
        "source": info.get("source", "local"),
    }
    rec = CreativePlan(owner_id=user.id, owner_name=user.username,
                      title=result["title"], analysis_json=analysis,
                      platforms=platforms, gen_image=req.gen_image, gen_video=req.gen_video,
                      routes_json=routes, status="draft", model_info=info)
    db.add(rec); db.commit(); db.refresh(rec)
    result["id"] = rec.id
    return CreativePlanResult(**result)


@router.get("/creative-plan")
def list_creative_plan(limit: int = 50, offset: int = 0, db: Session = Depends(get_db),
                       _: User = Depends(require_roles(*CAN_EDIT))):
    q = db.query(CreativePlan).order_by(CreativePlan.id.desc())
    lim = max(1, min(int(limit or 50), 200)); off = max(0, int(offset or 0))
    rows = q.offset(off).limit(lim).all()
    return {"items": [_cp_to_dict(r) for r in rows], "total": q.count(), "limit": lim, "offset": off}


@router.get("/creative-plan/{pid}")
def get_creative_plan(pid: int, db: Session = Depends(get_db),
                     _: User = Depends(require_roles(*CAN_EDIT))):
    r = db.query(CreativePlan).filter_by(id=pid).first()
    if not r:
        raise HTTPException(404, "创意策略记录不存在")
    return _cp_to_dict(r)


@router.patch("/creative-plan/{pid}")
def patch_creative_plan(pid: int, payload: dict, db: Session = Depends(get_db),
                        _: User = Depends(require_roles(*CAN_EDIT))):
    r = db.query(CreativePlan).filter_by(id=pid).first()
    if not r:
        raise HTTPException(404, "创意策略记录不存在")
    allowed = {"status", "asset_count", "history_id", "routes_json", "title"}
    for k, v in (payload or {}).items():
        if k in allowed:
            setattr(r, k, v)
    db.commit(); db.refresh(r)
    return _cp_to_dict(r)


# ----------------------------- V4.53 创意工作台：设计对齐的「产品分析」+「3 条创意路线」 -----------------------------
_CW_ANALYZE_SYS = (
    "你是资深的出海效果广告创意策略师。用户会给你一个产品链接或产品描述，以及目标媒体平台列表。"
    "请提炼产品定位与项目简报，只返回 JSON："
    "{\"title\": \"产品名\","
    " \"summary\": \"一句话产品定位描述（面向谁、解决什么、核心价值）\","
    " \"boxes\": {\"industry\": \"行业\", \"coreAudience\": \"核心人群\", \"purchaseMotivation\": \"购买动机\", \"priceBand\": \"价格带\"},"
    " \"brief\": {\"promotionGoal\": \"推广目标\", \"targetAudience\": [\"受众标签1\",\"受众标签2\"], \"sellingPoints\": [\"核心卖点1\",\"核心卖点2\",\"核心卖点3\"]},"
    " \"recommendedPlatforms\": [\"平台名\"]}"
    "要求：字段必须具体、贴合产品；recommendedPlatforms 从给定平台中选出最匹配的 1-3 个；"
    "不要编造数据；信息不足时给出合理默认。"
)

_CW_ROUTES_SYS = (
    "你是资深的出海效果广告创意策略师。基于产品分析结论、项目简报与目标媒体平台，"
    "规划 3 条差异化的创意概念路线（概念级，不逐平台拆分）。只返回 JSON："
    "{\"title\": \"本次创意路线主题\","
    " \"routes\": ["
    "   {\"key\": \"A\", \"name\": \"路线名\", \"description\": \"路线说明（切入方式与表达）\", \"tags\": [\"标签1\",\"标签2\"], \"angle\": \"切入角度\"},"
    "   {\"key\": \"B\", ...},"
    "   {\"key\": \"C\", ...}"
    " ]}"
    "要求：routes 恰为 3 条；key 依次为 A/B/C；每条路线要有清晰差异（如转化导向 / 生活方式 / 场景叙事）；"
    "tags 2-3 个；不要编造数据。"
)

# V4.66 创意工作台·视频素材创作区：对话式分镜策划
_CW_VIDEO_PLAN_SYS = (
    "你是资深的出海效果广告视频创意导演。用户会给你：① 产品分析结论（定位/受众/卖点/平台打法）；"
    "② 目标媒体平台；③ 参考图（可选，图生视频用）；④ 多轮对话（用户对提示词、创作构想、分镜方案的微调）；"
    "⑤ 已有的分镜方案（微调时带入，你需要增量修订而非重写）。\n"
    "你要始终围绕「媒体平台推广、吸引流量、完成转化」的目标，确保视频：贴合产品定位、精准捕捉信息、"
    "表达产品核心卖点与转化路径，严禁使用静态推拉运镜冒充真实动态。\n"
    "请只返回 JSON："
    "{\"reply\": \"给用户的自然语言回复（建议 / 已做的调整 / 下一步），中文，≤120字\","
    " \"plan\": {"
    "   \"mode\": \"text_to_video | image_to_video\","
    "   \"duration_sec\": 15,"
    "   \"aspect\": \"9:16 | 1:1 | 16:9\","
    "   \"voiceover\": \"none | narration | tts\","
    "   \"hook\": \"前3秒钩子文案（抓注意力）\","
    "   \"cta\": \"结尾行动号召文案\","
    "   \"shots\": ["
    "     {\"idx\": 1, \"t\": \"0-3s\", \"shot\": \"镜头方式(image_to_video|source_video|motion_graphics|scene_3d|text_to_video)\","
    "      \"visual\": \"画面描述（动作/主体/场景，必须可动态呈现）\", \"text\": \"叠加字幕\", \"vo\": \"旁白文案\","
    "      \"camera\": \"运镜（如手持跟随/推近/环绕）\", \"motion\": \"主体运动/转场\"},"
    "     {\"idx\": 2, ...}, {\"idx\": 3, ...}, {\"idx\": 4, ...}"
    "   ],"
    "   \"deliverables\": [\"15s 主片\", \"6s 剪辑版\", \"首帧封面图\"],"
    "   \"note\": \"制作须知（合规/节奏/音乐方向）\""
    " }}"
    "要求：shots 默认 4 镜覆盖 15 秒（0-3s 钩子 → 3-8s 真实功能 → 8-12s 可信支撑 → 12-15s 品牌收口）；"
    "每镜 visual 必须描述真实可生成的动态画面，不能只是静态图；可按对话微调节奏/卖点/时长；"
    "不要编造产品未提及的事实；信息不足时给合理默认。"
)


def _build_cw_result(title, summary, boxes, brief, rec_plat, *,
                     analysis_meta=None, snapshot, info, db, user, platforms):
    """V4.59 / B1 + B2：由 boxes/brief 构造「生成统一来源 analysis」、来源快照、并落库为创意方案草稿。

    `analysis` 字段对齐媒体生成链路 media_ad 读取的键，兼容历史恢复；
    `snapshot` 一并写入 analysis_json，保证历史记录可还原来源。
    """
    analysis_meta = analysis_meta or {}
    # 平台名归一：规范平台名已统一为 Meta；"Facebook"/"fb"/"instagram"/"ig" 为兼容别名，
    # 避免 recommendedPlatforms / channels 携带已弃用别名，导致后续 mediaCopy / 出图 422。
    _seen = set()
    rec_plat = [p for p in (canonical_platform(x) for x in (rec_plat or []))
                if p and not (p in _seen or _seen.add(p))]
    analysis = {
        "title": title,
        "summary": summary,
        "product": title,
        "brand": "",
        "industry": boxes.get("industry") or "",
        "type": boxes.get("industry") or "",
        "audience": ("、".join(brief.get("targetAudience") or []) or boxes.get("coreAudience") or "").strip(),
        "advantages": brief.get("sellingPoints") or [],
        "competitors": [],
        "channels": rec_plat,
        "language": "en",
        "industry_profile": "",
        "purchaseMotivation": boxes.get("purchaseMotivation") or "",
        "priceBand": boxes.get("priceBand") or "",
        "coreAudience": boxes.get("coreAudience") or "",
        "promotionGoal": brief.get("promotionGoal") or "",
        "targetAudience": brief.get("targetAudience") or [],
        "sellingPoints": brief.get("sellingPoints") or [],
        "recommendedPlatforms": rec_plat,
        "boxes": boxes,
        "brief": brief,
        "snapshot": snapshot.model_dump(),
        "url": analysis_meta.get("url") or "",
        "final_url": analysis_meta.get("final_url") or "",
    }
    result = {
        "title": title, "summary": summary, "boxes": boxes, "brief": brief,
        "recommendedPlatforms": rec_plat, "analysis": analysis,
        "snapshot": snapshot, "model_info": info, "source": snapshot.source,
    }
    rec = CreativePlan(owner_id=user.id, owner_name=user.username, title=title,
                       analysis_json={"summary": summary, "boxes": boxes, "brief": brief,
                                      "recommendedPlatforms": rec_plat, "analysis": analysis,
                                      "snapshot": snapshot.model_dump()},
                       platforms=platforms, gen_image=True, gen_video=False,
                       routes_json=[], status="draft", model_info=info)
    db.add(rec); db.commit(); db.refresh(rec)
    result["id"] = rec.id
    # V4.61 / B4：把真实抓取 / 手动文本的产品快照沉淀进素材库（演示样例不沉淀）。
    # 去重键为 source_plan_id：一个创意方案只对应一条产品条目，重复分析不会刷屏。
    if snapshot.source in ("real_fetch", "pasted") and title:
        _upsert_cw_library(db, user, "product", title,
                           url=analysis_meta.get("url") or "",
                           meta={"snapshot_id": snapshot.snapshot_id,
                                 "evidence_ids": snapshot.evidence_ids,
                                 "summary": summary, "brand": analysis.get("brand") or "",
                                 "platform": (platforms or [None])[0] or ""},
                           source_plan_id=rec.id)
    return result


def _upsert_cw_library(db: Session, user: User, kind: str, title: str, *,
                       file: str | None = None, url: str | None = None,
                       meta: dict | None = None, source_plan_id: int | None = None) -> CwLibrary:
    """B4 素材沉淀库 upsert：按 kind 去重，避免重复素材刷屏。

    - product → (owner_id, source_plan_id)
    - reference → (owner_id, file)
    - brand → (owner_id, title)
    """
    q = db.query(CwLibrary).filter(CwLibrary.owner_id == user.id, CwLibrary.kind == kind)
    if kind == "product":
        if source_plan_id:
            q = q.filter(CwLibrary.source_plan_id == source_plan_id)
    elif kind == "reference":
        q = q.filter(CwLibrary.file == (file or ""))
    elif kind == "brand":
        q = q.filter(CwLibrary.title == (title or ""))
    existing = q.first()
    if existing:
        existing.title = title or existing.title
        existing.file = file if file is not None else existing.file
        existing.url = url if url is not None else existing.url
        existing.meta_json = meta
        existing.updated_at = utcnow()
    else:
        existing = CwLibrary(owner_id=user.id, owner_name=user.username, kind=kind,
                             title=title, file=file, url=url, meta_json=meta,
                             source_plan_id=source_plan_id)
        db.add(existing)
    db.commit(); db.refresh(existing)
    return existing


def _cw_library_to_dict(row: CwLibrary) -> dict:
    return {"id": row.id, "owner_id": row.owner_id, "owner_name": row.owner_name,
            "kind": row.kind, "title": row.title or "", "file": row.file, "url": row.url,
            "meta_json": row.meta_json, "source_plan_id": row.source_plan_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.post("/cw/analyze", response_model=CWAnalysisResult)
async def api_cw_analyze(req: CWAnalyzeRequest, db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·产品分析：产品链接/文本 + 平台 → 大模型产出定位 + 4 分析盒 + 项目简报；落库为创意方案草稿。

    V4.59 / B1（P0#2：消除「只传 URL 不抓取」）：
    - demo_mode=True  → 仅返回显式「降噪耳机」演示样例，标注 source=demo（不再静默套用/伪装成真实结论）。
    - url 有值        → 服务端真实抓取落地页，用带 [E###] 证据包的页面内容驱动模型（source=real_fetch）；
                        抓取失败且无文本时明确 422 阻断，绝不编造。
    - 仅 text 有值    → 基于用户粘贴文本分析（source=pasted），不猜测 URL 外的产品事实。
    """
    url = (req.url or "").strip()
    text = (req.text or "").strip()
    platforms = [str(p).strip() for p in (req.platforms or []) if str(p).strip()]
    if not url and not text:
        raise HTTPException(400, "请提供产品链接或描述")

    # ---- ① 演示模式：显式样例，不调用模型、不伪装成真实抓取 ----
    if req.demo_mode:
        demo = demo_product()
        title = str(demo.get("title") or "").strip()
        summary = str(demo.get("summary") or "").strip()
        boxes = demo.get("boxes") or {}
        brief = demo.get("brief") or {}
        rec_plat = [str(p).strip() for p in (demo.get("recommendedPlatforms") or []) if str(p).strip()]
        snapshot = ProductSnapshot(**demo_snapshot(url))
        info = {"source": "demo", "provider": "demo", "model": "demo",
                "fallback": False, "config_id": None, "request_id": "", "error_type": "", "retries": 0}
        result = _build_cw_result(title, summary, boxes, brief, rec_plat,
                                 analysis_meta=None, snapshot=snapshot, info=info, db=db,
                                 user=user, platforms=platforms)
        return CWAnalysisResult(**result)

    # ---- ② URL：服务端真实抓取 + 证据包驱动 ----
    if url:
        fetch = await fetch_product(url)
        if not fetch["ok"]:
            # 抓取失败且无文本：明确阻断，不再静默套用演示数据
            raise HTTPException(422, detail={
                "message": "产品链接抓取失败，已在调用模型前阻断分析（needs_input）",
                "errors": ["链接不可达或返回空页；请检查网址可达性，或开启「演示模式」，或直接粘贴产品描述文本"],
                "fetch_quality": fetch["page"].get("fetch_quality") or "fetch_failed",
                "final_url": fetch["page"].get("final_url") or url,
                "hint": "系统不会从 URL 猜测产品事实；请补充正文或开启演示模式后重试。",
            })
        page = fetch["page"]
        pack = fetch["pack"]
        snapshot = ProductSnapshot(**fetch["snapshot"])
        evidence_text = evidence_prompt_part(url, page, pack)
        user_prompt = (
            json.dumps({"url": url, "platforms": platforms}, ensure_ascii=False)
            + "\n\n" + evidence_text
            + "\n\n请严格基于上方带 [E###] 编号的页面真实内容输出产品分析 JSON；"
              "不得从 URL / 域名推断页面未出现的事实，缺资料时留空。"
        )
        llm, info = get_llm_with_info(db, "analysis")
        try:
            resp = await llm.chat(_CW_ANALYZE_SYS, user_prompt)
            parsed = parse_json(resp) or {}
            info = finalize_invocation(info, llm, bool(parsed))
        except Exception:
            parsed, info = {}, finalize_invocation(info, llm, False)
        boxes = parsed.get("boxes") or {}
        brief = parsed.get("brief") or {}
        title = str(parsed.get("title") or "").strip() or (page.get("title") or url)[:40]
        summary = str(parsed.get("summary") or "").strip()
        rec_plat = [str(p).strip() for p in (parsed.get("recommendedPlatforms") or []) if str(p).strip()]
        # 真实抓取成功但模型未返回有效结构：用页面元信息（标题/H1）兜底，仍属真实抓取，不伪装为耳机样例
        if not (boxes or brief or summary):
            boxes = {"industry": "", "coreAudience": "", "purchaseMotivation": "", "priceBand": ""}
            brief = {"promotionGoal": "", "targetAudience": [], "sellingPoints": []}
            summary = (page.get("title") or (page.get("h1") or [""])[0] or url)[:120]
            rec_plat = platforms[:3] or ["Meta", "Google"]
            title = title or "产品分析"
        result = _build_cw_result(title, summary, boxes, brief, rec_plat,
                                 analysis_meta={"url": url, "final_url": page.get("final_url") or url},
                                 snapshot=snapshot, info=info, db=db,
                                 user=user, platforms=platforms)
        return CWAnalysisResult(**result)

    # ---- ③ 仅文本：基于用户粘贴描述分析（source=pasted） ----
    llm, info = get_llm_with_info(db, "analysis")
    user_prompt = json.dumps({"text": text, "platforms": platforms}, ensure_ascii=False)
    try:
        resp = await llm.chat(_CW_ANALYZE_SYS, user_prompt)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    boxes = parsed.get("boxes") or {}
    brief = parsed.get("brief") or {}
    title = str(parsed.get("title") or "").strip() or text[:40]
    summary = str(parsed.get("summary") or "").strip()
    rec_plat = [str(p).strip() for p in (parsed.get("recommendedPlatforms") or []) if str(p).strip()]
    # 文本模式解析失败：以用户文本首段兜底，标注 source=pasted（不伪装为真实抓取）
    if not (boxes or brief or summary):
        boxes = {"industry": "", "coreAudience": "", "purchaseMotivation": "", "priceBand": ""}
        brief = {"promotionGoal": "", "targetAudience": [], "sellingPoints": []}
        summary = text[:120]
        rec_plat = platforms[:3] or ["Meta", "Google"]
        title = title or "产品分析"
    snapshot = ProductSnapshot(source="pasted", url="", final_url="",
                               fetched_at="", fetch_quality="manual_text",
                               snapshot_id="", title="", evidence_ids=[])
    result = _build_cw_result(title, summary, boxes, brief, rec_plat,
                             analysis_meta={"url": "", "final_url": ""},
                             snapshot=snapshot, info=info, db=db,
                             user=user, platforms=platforms)
    return CWAnalysisResult(**result)


@router.post("/cw/routes", response_model=CWRoutesResult)
async def api_cw_routes(req: CWRoutesRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·创意路线：产品分析 + 简报 + 平台 → 大模型规划 3 条创意概念路线；写回创意方案。"""
    plan_id = req.plan_id
    platforms = [str(p).strip() for p in (req.platforms or []) if str(p).strip()]
    analysis = req.analysis or {}
    brief = req.brief or {}
    llm, info = get_llm_with_info(db, "analysis")
    user_prompt = json.dumps({"analysis": analysis, "brief": brief, "platforms": platforms}, ensure_ascii=False)
    try:
        resp = await llm.chat(_CW_ROUTES_SYS, user_prompt)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    routes = []
    for r in (parsed.get("routes") or [])[:3]:
        if isinstance(r, dict):
            routes.append({
                "key": str(r.get("key") or "").strip(),
                "name": str(r.get("name") or "").strip(),
                "description": str(r.get("description") or "").strip(),
                "tags": [str(t).strip() for t in (r.get("tags") or []) if str(t).strip()][:4],
                "angle": str(r.get("angle") or "").strip(),
                "selected": True,
            })
    keys = ["A", "B", "C"]
    for i, r in enumerate(routes):
        if not r["key"]:
            r["key"] = keys[i] if i < 3 else chr(65 + i)
    # Mock / 解析失败兜底
    if not routes:
        routes = [
            {"key": "A", "name": "痛点对比实验", "description": "用强烈视觉对比演示使用前后差异，前三秒制造悬念。",
             "tags": ["转化导向", "产品演示"], "angle": "前后对比", "selected": True},
            {"key": "B", "name": "专注力超能力", "description": "将产品塑造成工作与生活中的效率装备。",
             "tags": ["生活方式", "情绪价值"], "angle": "效率叙事", "selected": True},
            {"key": "C", "name": "续航自由出发", "description": "通过连续场景证明续航，强化产品信任。",
             "tags": ["场景叙事", "功能利益"], "angle": "场景证明", "selected": True},
        ]
    result = {"title": str(parsed.get("title") or "创意路线规划").strip(),
              "routes": routes, "model_info": info, "source": info.get("source", "local")}
    if plan_id:
        r0 = db.query(CreativePlan).filter_by(id=plan_id).first()
        if r0:
            r0.routes_json = routes
            r0.status = "draft"
            db.commit(); db.refresh(r0)
            result["id"] = r0.id
    return CWRoutesResult(**result)


# ----------------------------- V4.66 创意工作台 · 视频素材创作区（对话式分镜 + 生成） -----------------------------
def _mini_model_info(info: dict) -> ModelInfo:
    """从调用快照构造 ModelInfo（仅含非敏感字段）。"""
    return ModelInfo(**{k: info.get(k) for k in
                        ("provider", "model", "role", "fallback", "config_id", "source", "request_id", "error_type", "retries")})


@router.post("/cw-video/plan", response_model=CWVideoPlanResult)
async def api_cw_video_plan(req: CWVideoPlanRequest, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·视频素材创作区：对话式分镜策划（多轮微调提示词 / 构想 / 方案）。

    把产品分析 + 平台 + 参考图 + 对话历史 + 当前方案交给大模型，产出/微调一份 VIDEO_JSON v2
    风格的分镜方案；返回的 plan 可直接喂给 /cw-video/generate 实际生成。无视频模型也可在此规划。
    """
    analysis = req.analysis or {}
    platform = (req.platform or "").strip()
    lang = str((req.options or {}).get("lang") or "zh")
    convo = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}: {m.content}"
        for m in (req.messages or []) if m.content and m.content.strip()
    )
    payload = {
        "analysis": analysis,
        "platform": platform,
        "reference_image": req.reference_image or "",
        "options": req.options or {},
        "current_plan": req.current_plan or None,
        "conversation": convo,
        "language": lang,
    }
    llm, info = get_llm_with_info(db, "analysis")
    try:
        resp = await llm.chat(_CW_VIDEO_PLAN_SYS, json.dumps(payload, ensure_ascii=False))
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    plan = parsed.get("plan") or {}
    reply = str(parsed.get("reply") or "").strip()

    # 兜底：未返回有效分镜时，给一份基于分析的 15 秒四镜默认模板（可在对话框继续微调）
    if not plan.get("shots"):
        a = (analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else analysis) or {}
        product = a.get("product") or analysis.get("title") or "产品"
        plan = {
            "mode": "text_to_video",
            "duration_sec": 15,
            "aspect": "9:16",
            "voiceover": (req.options or {}).get("voiceover", "none"),
            "hook": f"{product}：真正解决你的痛点",
            "cta": "立即下载 / 了解更多",
            "shots": [
                {"idx": 1, "t": "0-3s", "shot": "text_to_video", "visual": f"{product} 使用场景中的人物特写，情绪从困惑转为惊喜", "text": "还在为这件事烦恼？", "vo": "还在为这件事烦恼？", "camera": "手持跟随推近", "motion": "主体入画"},
                {"idx": 2, "t": "3-8s", "shot": "text_to_video", "visual": f"{product} 核心功能两步演示，屏幕录制＋手指引导", "text": "三步完成", "vo": "Three steps, done.", "camera": "俯拍＋特写", "motion": "功能演示循环"},
                {"idx": 3, "t": "8-12s", "shot": "text_to_video", "visual": "评分 / 用户好评 / 数据角标弹出", "text": "★★★★★ 4.8 · 100K+ users", "vo": "Loved by millions.", "camera": "定格推近", "motion": "角标弹入"},
                {"idx": 4, "t": "12-15s", "shot": "text_to_video", "visual": f"{product} Logo ＋ 下载按钮动画 ＋ 端卡", "text": "立即下载", "vo": "Get it now.", "camera": "拉远收尾", "motion": "Logo 定格"},
            ],
            "deliverables": ["15s 主片", "6s 剪辑版", "首帧封面图"],
            "note": "未配置 / 未返回视频分镜，已生成通用模板；在对话框继续微调（更具体的卖点 / 节奏 / 平台打法）。",
        }
        if not reply:
            reply = "已基于产品分析生成一份默认 15 秒四镜分镜；告诉我你想强调的卖点或平台打法，我帮你微调。"

    # 把平台 / 选项 / 参考图回填进 plan，便于前端展示与生成复用
    plan["platform"] = platform
    plan["options"] = req.options or {}
    plan["reference_image"] = req.reference_image or ""
    return CWVideoPlanResult(reply=reply, plan=plan,
                             model_info=_mini_model_info(info), source=info.get("source", "local"))


@router.post("/cw-video/generate", response_model=CWVideoGenerateResult)
async def api_cw_video_generate(req: CWVideoGenerateRequest, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·视频素材创作区：按分镜方案调用真实视频模型（可灵 / 通用 /video/generations）生成视频。

    - 配置了 video 用途模型 → 直连生成（可灵走原生异步 API，其余走通用 /video/generations）；
    - 未配置 → 安全回退「可执行分镜脚本」，绝不阻断主流程。
    返回的 storyboard 始终包含分镜 JSON（展示 + 可下载），videos 为实际成片（如有）。
    """
    plan = req.plan or {}
    analysis = req.analysis or {}
    platform = (req.platform or "").strip()
    options = req.options or {}
    a = (analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else analysis) or {}
    product = a.get("product") or analysis.get("title") or "Product"
    brief = analysis.get("brief") or {}

    # 从分镜方案构造一段可供文生/图生视频模型消费的提示词
    shots = plan.get("shots") or []
    seg_lines = []
    for s in shots:
        seg = f"[{s.get('t') or ''}] {s.get('visual') or ''}"
        if s.get("text"): seg += f"（字幕：{s['text']}）"
        if s.get("vo"): seg += f"（旁白：{s['vo']}）"
        seg_lines.append(seg)
    aspect = str(plan.get("aspect") or options.get("aspect") or "9:16")
    duration = int(plan.get("duration_sec") or options.get("duration") or 15)
    prompt_parts = [f"产品：{product}"]
    if brief.get("promotionGoal"): prompt_parts.append(f"推广目标：{brief.get('promotionGoal')}")
    if brief.get("sellingPoints"): prompt_parts.append("核心卖点：" + "、".join(brief["sellingPoints"][:3]))
    prompt_parts.append(f"时长：{duration} 秒；比例：{aspect}")
    if seg_lines: prompt_parts.append("分镜：" + "；".join(seg_lines))
    if options.get("prompt_hint"): prompt_parts.append("补充要求：" + str(options["prompt_hint"]))
    prompt = "\n".join(prompt_parts)

    meta = {
        "product": product,
        "headline": plan.get("hook") or product,
        "cta": plan.get("cta") or "立即下载",
        "spec": "1080x1920" if aspect == "9:16" else ("1080x1080" if aspect == "1:1" else "1920x1080"),
        "lang": str(options.get("lang") or "en"),
        "duration": duration,
        "aspect": aspect,
    }
    # 图生视频：把参考图作为 image 带入（Kling / 通用模型据端点决定是否消费）
    if str(plan.get("mode") or options.get("mode") or "") == "image_to_video" and req.reference_image:
        meta["image"] = req.reference_image
        meta["mode"] = "image_to_video"

    cfg = _active_config(db, "video")
    if cfg and cfg.api_key and cfg.base_url and cfg.model:
        provider = get_video(db)
        m_info = ModelInfo(provider=("kling" if (cfg.provider or "") == "keling" else "model"),
                           model=cfg.model, role="video", fallback=False, config_id=cfg.id, source="llm")
    else:
        provider = StoryboardVideo()
        m_info = ModelInfo(provider="storyboard", model="", role="video", fallback=True, source="local")

    filename = f"cw_video_{user.id}_{int(time.time())}.mp4"
    try:
        res = await provider.generate(prompt, platform, filename, meta)
    except Exception as e:
        res = await StoryboardVideo().generate(prompt, platform, filename, meta)
        res["note"] = f"视频生成异常（{str(e)[:80]}），已回退分镜脚本。"

    # 若 provider 内部回退到分镜，则同步修正 model_info 标注
    if res.get("provider") == "storyboard":
        m_info = ModelInfo(provider="storyboard", model="", role="video", fallback=True, source="local")

    videos: list = []
    note = res.get("note") or ""
    if res.get("file_path"):
        rel = os.path.basename(res["file_path"])
        videos.append(CWVideoAsset(type="video", url=f"/files/{rel}", caption=product, duration_sec=duration))
    elif res.get("url"):
        videos.append(CWVideoAsset(type="video", url=res["url"], caption=product, duration_sec=duration))
    else:
        note = note or "未配置视频模型，已输出可执行分镜脚本（在设置页配置 video 用途的模型后可直连生成）。"

    # 始终回传分镜方案（展示 + 可下载 JSON）
    storyboard = dict(plan)
    storyboard["platform"] = platform
    storyboard["options"] = options
    storyboard["reference_image"] = req.reference_image or ""
    storyboard.setdefault("duration_sec", duration)
    storyboard.setdefault("aspect", aspect)
    storyboard.setdefault("shots", [])
    return CWVideoGenerateResult(
        provider=res.get("provider", "storyboard"),
        model=(cfg.model if (cfg and cfg.model) else ""),
        videos=videos, storyboard=storyboard,
        model_info=m_info, note=note, source=m_info.source,
    )


# ----------------------------- V4.61 / B4：创意工作台「素材沉淀库」接口 -----------------------------
@router.get("/cw/library", response_model=list[CwLibraryOut])
async def list_cw_library(kind: Optional[str] = None, limit: int = 50, offset: int = 0,
                          db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT))):
    """当前用户自己的素材库条目（参考图 / 产品 / 品牌），按最近更新倒序。"""
    q = db.query(CwLibrary).filter(CwLibrary.owner_id == user.id)
    if kind:
        q = q.filter(CwLibrary.kind == kind)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    rows = q.order_by(CwLibrary.updated_at.desc()).offset(off).limit(lim).all()
    return [_cw_library_to_dict(r) for r in rows]


@router.post("/cw/library", response_model=CwLibraryOut)
async def add_cw_library(body: CwLibraryCreate, db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*CAN_EDIT))):
    """沉淀 / 手动新增一条素材库条目；按 kind 去重 upsert（product→方案、reference→文件、brand→标题）。"""
    kind = (body.kind or "").strip().lower()
    if kind not in ("reference", "product", "brand"):
        raise HTTPException(400, "kind 仅支持 reference / product / brand")
    if kind == "reference" and not body.file:
        raise HTTPException(400, "参考图条目必须携带 file（/files/<name>）")
    if kind == "product" and not (body.title or body.url):
        raise HTTPException(400, "产品条目需至少提供 title 或 url")
    row = _upsert_cw_library(db, user, kind, body.title or "",
                             file=body.file, url=body.url, meta=body.meta,
                             source_plan_id=body.source_plan_id)
    return _cw_library_to_dict(row)


@router.delete("/cw/library/{id}")
async def delete_cw_library(id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """删除自己的素材库条目；若该文件未被其他条目引用，则一并删除磁盘文件（孤立清理）。"""
    row = db.query(CwLibrary).filter(CwLibrary.id == id, CwLibrary.owner_id == user.id).first()
    if not row:
        raise HTTPException(404, "素材不存在或无权删除")
    f = row.file
    if f:
        others = db.query(CwLibrary).filter(CwLibrary.file == f, CwLibrary.id != id).first()
        if not others:
            disk = os.path.join(UPLOAD_DIR, os.path.basename(f))
            if os.path.exists(disk):
                try:
                    os.remove(disk)
                except OSError:
                    pass
    db.delete(row); db.commit()
    return {"ok": True}


@router.get("/image-capabilities")
async def api_image_capabilities(_: User = Depends(require_roles(*CAN_EDIT))):
    """F06：下发各文生图供应商的尺寸候选 / 能力声明与核验日期（未核验不冒充已支持）。"""
    return public_capabilities()


@router.post("/generation-jobs", status_code=202)
async def create_generation_job(body: dict, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(*CAN_EDIT))):
    """F12：创建持久任务，立即返回 job_id；生成与归档由服务端完成。

    同一个 `idempotency_key` 重复提交只返回原任务，不重复调用模型、不重复归档。
    浏览器断开 / 刷新后可用 `GET /api/generation-jobs/{job_id}` 恢复结果与状态。

    V4.46 / D5：若携带 `plan_id`，须与持久计划的冻结版本、分析原文一致；
    客户端不得提交任意改写的事实绕过计划（否则 422 拒绝）。
    """
    from pydantic import ValidationError
    plan_id = str(body.get("plan_id") or "").strip() or None
    plan_version = str(body.get("plan_version") or "").strip() or None
    kind = "auto_creation" if plan_id else str(body.get("kind") or "images")
    if plan_id:
        plan = get_plan(db, plan_id)
        if not plan:
            raise HTTPException(422, detail={"message": "关联的创作计划不存在", "plan_id": plan_id})
        if plan_version and plan.plan_version and plan_version != plan.plan_version:
            raise HTTPException(409, detail={
                "message": "计划版本已失效（产品事实 / 目标地区变化），请重新确认",
                "plan_id": plan_id, "frozen": plan.plan_version, "given": plan_version})
        incoming_analysis = (body.get("images_request") or {}).get("analysis") or {}
        base_snap = (plan.analysis_json or {}).get("evidence_snapshot_id") or ""
        req_snap = incoming_analysis.get("evidence_snapshot_id") or ""
        if base_snap and req_snap and base_snap != req_snap:
            raise HTTPException(422, detail={
                "message": "生成请求的分析原文与计划不一致，已阻止改写事实绕过计划",
                "plan_id": plan_id})
        if not plan.approval_token:
            raise HTTPException(422, detail={"message": "计划尚未确认（未冻结版本 / 未授权费用），不能生成"})
    try:
        job, created = job_service.create_job(
            db, body, user, idempotency_key=str(body.get("idempotency_key") or "").strip(),
            kind=kind, plan_id=plan_id, plan_version=plan_version)
    except ValidationError as e:
        raise HTTPException(422, detail={
            "message": "生成任务入参不合法，已在排队前拒绝",
            "errors": [f"{'.'.join(str(x) for x in er.get('loc', []))}: {er.get('msg')}"
                       for er in e.errors()[:8]],
        })
    except job_service.IdempotencyConflict as e:
        # V4.44 / N05 / A16：同一幂等键换了请求内容，必须 409，不能返回旧任务
        raise HTTPException(409, detail={
            "message": str(e),
            "job_id": e.job_id,
            "expected_payload_hash": e.expected,
            "actual_payload_hash": e.actual,
            "hint": "请更换 idempotency_key，或先查询原任务结果；系统不会串用其它请求的任务。",
        })
    except Exception as e:
        raise HTTPException(422, detail={"message": "生成任务创建失败",
                                        "errors": [f"{type(e).__name__}: {str(e)[:180]}"]})
    if created and plan_id:
        try:
            attach_job(db, plan_id, job.job_id)
        except Exception:
            pass
    if created:
        job_service.spawn_job(job.job_id)
    return {**job_service.job_to_dict(job, include_result=False),
            "created": created,
            "plan_id": plan_id,
            "poll_url": f"/api/generation-jobs/{job.job_id}",
            "message": ("任务已创建并在服务端执行，可离开页面；刷新后按 job_id 恢复"
                        if created else "同一幂等键已存在，返回原任务（不重复生成）")}


@router.get("/generation-jobs")
def list_generation_jobs(history_id: int | None = None, limit: int = 50, offset: int = 0,
                         db: Session = Depends(get_db),
                         _: User = Depends(require_roles(*CAN_EDIT))):
    q = db.query(GenerationJob)
    if history_id is not None:
        q = q.filter(GenerationJob.history_id == history_id)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    rows = q.order_by(GenerationJob.id.desc()).offset(off).limit(lim).all()
    return {"items": [job_service.job_to_dict(r, include_result=False) for r in rows],
            "total": q.count(), "limit": lim, "offset": off}


@router.get("/generation-jobs/{job_id}")
def get_generation_job(job_id: str, db: Session = Depends(get_db),
                       _: User = Depends(require_roles(*CAN_EDIT))):
    """刷新 / 关闭浏览器后按 job_id 恢复：状态、逐项结果与归档信息都在这里。"""
    row = db.query(GenerationJob).filter_by(job_id=job_id).first()
    if not row:
        raise HTTPException(404, "生成任务不存在")
    return job_service.job_to_dict(row, include_result=True)


def _job_row(db: Session, job_id: str) -> GenerationJob:
    row = db.query(GenerationJob).filter_by(job_id=job_id).first()
    if not row:
        raise HTTPException(404, "生成任务不存在")
    return row


@router.post("/generation-jobs/{job_id}/cancel")
def cancel_generation_job(job_id: str, db: Session = Depends(get_db),
                          _: User = Depends(require_roles(*CAN_EDIT))):
    return job_service.cancel_job(db, _job_row(db, job_id))


@router.post("/generation-jobs/{job_id}/retry", status_code=202)
async def retry_generation_job(job_id: str, db: Session = Depends(get_db),
                               user: User = Depends(require_roles(*CAN_EDIT))):
    """只重试失败子任务：成功项不重复调用模型、不重复归档。"""
    origin = _job_row(db, job_id)
    job, message = job_service.retry_failed(db, origin, user)
    if job is None:
        raise HTTPException(409, detail={"message": message, "job_id": job_id})
    db.refresh(job)
    job_service.spawn_job(job.job_id)
    return {**job_service.job_to_dict(job, include_result=False),
            "created": True, "message": message}


@router.get("/creative-assets")
def list_creative_assets(history_id: int | None = None, job_id: str = "",
                         limit: int = 50, offset: int = 0,
                         db: Session = Depends(get_db),
                         _: User = Depends(require_roles(*CAN_EDIT))):
    """F12 / T16：不可变资产分页查询；历史超过 80 张仍能读取早期素材。"""
    return job_service.list_assets(db, history_id=history_id, job_id=job_id,
                                   limit=limit, offset=offset)


# ===========================================================================
# V4.36 推广图片查阅 / 下载 + 「素材历史」（分析 → 文案 → 图片 会话级落库）
# ===========================================================================

def _download_access(request: Request) -> dict:
    """浏览器 <a> 直链下载无法带 Authorization 头，token 走 query（auth_guard 已验签）。

    这里额外校验角色，避免只读账号通过直链拿到投放素材。
    """
    raw = request.headers.get("authorization")
    tok = raw[7:] if raw and raw.lower().startswith("bearer ") else (raw or "")
    tok = tok or request.query_params.get("token") or ""
    data = decode_token(tok)
    if not data:
        raise HTTPException(401, "未登录或登录已过期")
    if data.get("role") not in CAN_EDIT:
        raise HTTPException(403, "需要投放执行及以上角色")
    return data


@router.get("/media-files/download")
def download_media_file(request: Request, file: str = Query(..., description="uploads 下的纯文件名")):
    """单张推广图片下载。只接受纯文件名，杜绝 ../ 路径穿越。"""
    _download_access(request)
    path = safe_image_path(file)
    if not path:
        raise HTTPException(404, "图片不存在或文件名非法")
    return FileResponse(path, filename=os.path.basename(path),
                        media_type=media_type_of(path))


@router.get("/media-files/zip")
def zip_media_files(request: Request,
                    files: str = Query(..., description="逗号分隔的图片文件名"),
                    label: str = Query("推广图片", description="ZIP 内顶层目录名")):
    """一键打包全部 / 打包勾选的几张图片。"""
    _download_access(request)
    names = [x.strip() for x in (files or "").split(",") if x.strip()]
    if not names:
        raise HTTPException(400, "请提供要下载的图片")
    if len(names) > 200:
        raise HTTPException(400, "单次最多打包 200 张图片")
    folder = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", label)[:40].strip("_") or "推广图片"
    buf = build_files_zip(names, label=folder)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      f'attachment; filename="ad_images_{int(time.time())}.zip"'})


def _history_row(db, hid: int) -> CreationHistory:
    row = db.query(CreationHistory).filter_by(id=hid).first()
    if not row:
        raise HTTPException(404, "历史记录不存在")
    return row


@router.post("/creation-history")
def create_creation_history(body: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """创建一次「素材创作」会话：落地页分析完成时调用，后续文案 / 图片增量写回。"""
    analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else {}
    url = str(body.get("url") or analysis.get("url") or "").strip()
    platform = str(body.get("platform") or "").strip()
    row = CreationHistory(
        title=str(body.get("title") or "").strip() or derive_title(analysis, url, platform),
        url=url, site_name=site_name_of(url),
        platform=platform, lang=str(body.get("lang") or "").strip(),
        analysis_json=analysis or None,
        owner_id=user.id, owner_name=user.display_name or user.username,
        source_id=body.get("source_id") if isinstance(body.get("source_id"), int) else None,
        created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(row); db.commit(); db.refresh(row)
    return history_to_dict(row)


@router.get("/creation-history")
def list_creation_history(q: str = "", platform: str = "", limit: int = 50, offset: int = 0,
                          db: Session = Depends(get_db),
                          _: User = Depends(require_roles(*CAN_EDIT))):
    """历史列表（时间倒序）。q 匹配标题 / 网址 / 站点 / 平台 / 行业 / 类型 / 受众。"""
    query = db.query(CreationHistory)
    if platform:
        query = query.filter(CreationHistory.platform == platform)
    rows = query.order_by(CreationHistory.id.desc()).all()
    needle = (q or "").strip().lower()
    if needle:
        def hit(r) -> bool:
            a = r.analysis_json or {}
            hay = " ".join(str(x or "") for x in [
                r.title, r.url, r.site_name, r.platform, r.owner_name,
                a.get("industry"), a.get("type"), a.get("audience"), a.get("language"),
            ]).lower()
            return needle in hay
        rows = [r for r in rows if hit(r)]
    total = len(rows)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    return {"items": [history_to_dict(r) for r in rows[off:off + lim]],
            "total": total, "limit": lim, "offset": off}


@router.get("/creation-history/export")
def export_creation_history(request: Request, ids: str = Query(..., description="逗号分隔的历史 id"),
                            db: Session = Depends(get_db)):
    """批量打包所选历史（每条一个目录，含图片 / 文案 / 分析 / 生成信息）。"""
    _download_access(request)
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        raise HTTPException(400, "请提供有效的历史 id")
    rows = db.query(CreationHistory).filter(CreationHistory.id.in_(id_list))\
             .order_by(CreationHistory.id).all()
    if not rows:
        raise HTTPException(404, "未找到对应历史记录")
    buf = build_history_zip(rows, multi=True)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      f'attachment; filename="creation_history_batch_{len(rows)}.zip"'})


@router.delete("/creation-history")
def delete_creation_history(body: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """批量删除历史信息（物理删除、不可恢复），并清理不再被引用的图片文件。"""
    ids = body.get("ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "请提供要删除的历史 id 列表")
    ids = [int(x) for x in ids if str(x).strip().isdigit()]
    rows = db.query(CreationHistory).filter(CreationHistory.id.in_(ids)).all() if ids else []
    if not rows:
        raise HTTPException(404, "未找到对应历史记录")
    targets: set[str] = set()
    for r in rows:
        targets.update(image_files_of(r))
    found = [r.id for r in rows]
    # V4.42 / F12：显式保留 / 删除策略 —— 删除历史会话时同步删除其不可变资产记录，
    # 文件仍由 cleanup_orphan_files 按「是否被其它记录引用」安全回收。
    assets = db.query(CreativeAsset).filter(CreativeAsset.history_id.in_(found)).all()
    for a in assets:
        fn = os.path.basename(str(a.file or ""))
        if fn:
            targets.add(fn)
        db.delete(a)
    for r in rows:
        db.delete(r)
    db.commit()
    deleted_files = cleanup_orphan_files(db, targets)   # commit 之后再清磁盘，避免误删共享图片
    _audit(db, user, "history.delete", target="creation_history",
           detail={"ids": found, "deleted_files": deleted_files,
                   "deleted_assets": len(assets)})
    return {"ok": True, "deleted": len(found), "deleted_files": deleted_files,
            "deleted_assets": len(assets)}


@router.put("/creation-history/{hid}")
def update_creation_history(hid: int, body: dict, db: Session = Depends(get_db),
                            _: User = Depends(require_roles(*CAN_EDIT))):
    """增量写回：文案 / 图片 / 风格 / 平台 / 语言。images 默认追加（保留每次重新生成的产物）。"""
    row = _history_row(db, hid)
    if "analysis" in body and isinstance(body["analysis"], dict):
        row.analysis_json = body["analysis"]
    if "platform" in body:
        row.platform = str(body["platform"] or "").strip()
        row.title = derive_title(row.analysis_json, row.url, row.platform)
    if "lang" in body:
        row.lang = str(body["lang"] or "").strip()
    if "copy" in body:
        row.copy_json = body["copy"] or None
        row.has_copy = bool(body["copy"])
    if "style_opts" in body:
        row.style_opts_json = body["style_opts"] or {}
    if "image_model" in body:
        row.image_model_json = body["image_model"] or None
    if "note" in body:
        row.note = str(body["note"] or "")
    if "images" in body:
        fresh = body["images"] if isinstance(body["images"], list) else []
        old = row.images_json if isinstance(row.images_json, list) else []
        mode = body.get("images_mode") or "append"
        merged = ([] if mode == "replace" else list(old)) + fresh
        seen, uniq = set(), []
        for im in merged:
            if not isinstance(im, dict):
                continue
            key = str(im.get("file") or im.get("url") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            # 只存纯文件名，避免绝对路径随部署机变化失效；前端用 api.fileUrl() 还原
            item = dict(im)
            item["file"] = os.path.basename(str(item.get("file") or item.get("url") or ""))
            uniq.append(item)
        # V4.42 / F12：这里只是「最近 80 张的展示缓存」，不再是历史资产的唯一记录。
        # 完整不可变记录在 creative_assets 表，通过 GET /api/creative-assets?history_id=
        # 分页读取（T16：超过 80 张仍能查到早期素材）；不再静默丢弃元数据。
        row.images_json = uniq[-80:]
        row.image_count = len(uniq)
    row.updated_at = utcnow()
    db.commit(); db.refresh(row)
    return history_to_dict(row)


@router.get("/creation-history/{hid}")
def get_creation_history(hid: int, db: Session = Depends(get_db),
                         _: User = Depends(require_roles(*CAN_EDIT))):
    return history_to_dict(_history_row(db, hid))


@router.get("/creation-history/{hid}/export.zip")
def export_one_creation_history(request: Request, hid: int, db: Session = Depends(get_db)):
    """再下载整条历史：图片 + 广告文案 TXT/JSON + 落地页分析 + 生成信息。"""
    _download_access(request)
    row = _history_row(db, hid)
    buf = build_history_zip([row], multi=False)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      f'attachment; filename="creation_history_{hid}.zip"'})


@router.get("/creation-history/{hid}/copy.txt")
def export_creation_copy(request: Request, hid: int, db: Session = Depends(get_db)):
    """单独再下载广告文案（纯文本）。"""
    _download_access(request)
    row = _history_row(db, hid)
    if not row.copy_json:
        raise HTTPException(404, "该历史记录未生成广告文案")
    return PlainTextResponse(copy_as_text(row), headers={
        "Content-Disposition": f'attachment; filename="ad_copy_{hid}.txt"'})


@router.post("/assets/upload")
async def upload_asset(file: UploadFile = File(...),
                       user: User = Depends(require_roles(*CAN_EDIT))):
    """上传产品图 / Logo（透明底 PNG 或白底 JPG），用于合成到素材中。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "仅支持 PNG / JPG / WEBP")
    name = f"asset_{int(time.time() * 1000)}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"path": path, "url": f"/files/{name}", "name": file.filename}


@router.post("/assets/fetch-url")
async def fetch_asset_url(body: dict, user: User = Depends(require_roles(*CAN_EDIT))):
    """B3：把参考图 URL 下载到本地 uploads，返回 /files/<name>，供 style_opts.reference_image 使用。

    仅支持 http(s)；校验响应 content-type 为图片、限大小（12MB），避免把非图片 / 超大资源
    当作商品参考图塞进文生图链路。下载失败 / 非图片一律 400，不静默假装成功。
    """
    url = str((body or {}).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "仅支持 http(s) 链接")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise HTTPException(400, f"无法获取图片（HTTP {resp.status_code}）")
                ctype = (resp.headers.get("content-type") or "").lower()
                if not ctype.startswith("image/"):
                    raise HTTPException(400, f"链接内容不是图片（content-type={ctype or '未知'}）")
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                       "image/gif": ".gif"}.get(ctype, ".img")
                name = f"ref_{int(time.time() * 1000)}{ext}"
                path = os.path.join(UPLOAD_DIR, name)
                total = 0
                MAX = 12 * 1024 * 1024
                with open(path, "wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 64):
                        total += len(chunk)
                        if total > MAX:
                            f.close(); os.remove(path)
                            raise HTTPException(400, "图片超过 12MB 限制")
                        f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"下载参考图失败：{str(e)[:160]}")
    return {"path": path, "url": f"/files/{name}", "name": url}
@router.get("/settings/creative-presets")
def creative_presets():
    """返回「素材创作」三大提示词库：创意方向（D01-D20）/ 内容风格（S01-S26）/ 配色（C01-C16）。

    前端「素材提示词管理」与「素材创作」生成均从此处取数，便于后续在后台扩充。
    """
    return creative_presets_payload()


# ---------------------------------------------------------------------------
# 版本发布公告（新版通知）：单一数据源为仓库根目录 CHANGELOG.md
# ---------------------------------------------------------------------------
@router.get("/system/release-notes")
def release_notes(response: Response, _: User = Depends(require_roles(*ROLES))):
    """返回按系统版本自动同步的「总结式」版本更新内容（V4.43）。

    禁用缓存：系统更新后用户重新进入页面即可看到最新版本，不依赖整页刷新。
    """
    response.headers["Cache-Control"] = "no-store, max-age=0"
    from release_notes import get_release_notes
    return get_release_notes()

# ----------------------------- 设置：AI 模型配置 -----------------------------
def _normalize_usage(u) -> list:
    """usage 可能是单字符串或数组，统一为去重后的非空数组。"""
    if isinstance(u, str):
        return [u] if u else []
    if isinstance(u, (list, tuple)):
        return [str(x) for x in u if x]
    return []

def _deactivate_conflicting(db, usages: list, exclude_id: int | None = None):
    """同用途仅一个激活：仅停用「用途被新配置完全覆盖」的其它激活配置。

    例如新配置用途为 [analysis]，则只停用单用途的 analysis 配置；
    若某旧配置为 [analysis, copy]（多用途），因用途未被完全覆盖，保留其继续服务 copy。
    """
    if not usages:
        return
    uset = set(str(x) for x in usages)
    for o in db.query(ModelConfig).filter(ModelConfig.is_active == True).all():
        if exclude_id is not None and o.id == exclude_id:
            continue
        ou = o.usages if o.usages is not None else o.usage
        ou = set(str(x) for x in (ou if isinstance(ou, list) else ([ou] if ou else [])))
        if ou and ou <= uset:   # 旧配置的用途是新配置用途的子集 → 安全停用
            o.is_active = False


def _norm_model_key(provider: str, base_url: str, model: str):
    """同一「大模型配置」的身份键：接口协议（统一解析为协议串）+ 请求链接 + 模型版本。

    - provider 统一经 _resolve_protocol 解析（如 qwen-maas → openai），避免同一端点被
      不同 provider 串重复登记；
    - base_url 去掉首尾空白与结尾斜杠并按小写比较（兼容 http://x/v1 与 http://x/v1/）；
    - model 去空白、小写比较。
    """
    proto = (_resolve_protocol(provider or 'custom') or '').strip().lower()
    url = (base_url or '').strip().rstrip('/').lower()
    mdl = (model or '').strip().lower()
    return (proto, url, mdl)


def _dup_model_config(db, provider: str, base_url: str, model: str, exclude_id: int | None = None):
    """若已存在 (协议, 链接, 模型) 完全相同的配置则返回该记录，否则返回 None。

    exclude_id 用于编辑场景：排除正在编辑的自身，避免把自己判成重复。
    """
    target = _norm_model_key(provider, base_url, model)
    if not target[1] and not target[2]:
        return None  # 链接与模型均为空，无法构成有效配置，不判重
    q = db.query(ModelConfig)
    if exclude_id is not None:
        q = q.filter(ModelConfig.id != exclude_id)
    for m in q.all():
        if _norm_model_key(m.provider, m.base_url, m.model) == target:
            return m
    return None

@router.get("/settings/models", response_model=list[ModelConfigOut])
def list_models(db: Session = Depends(get_db)):
    rows = db.query(ModelConfig).order_by(ModelConfig.id).all()
    # V4.34：标注哪些配置是各用途「当前实际生效」的（测试成功优先），供设置页展示
    from providers import effective_config_ids
    try:
        in_use = effective_config_ids(db)
    except Exception:
        in_use = set()
    out = []
    for m in rows:
        o = ModelConfigOut.model_validate(m, from_attributes=True)
        o.in_use = m.id in in_use
        out.append(o)
    return out

@router.post("/settings/models", response_model=ModelConfigOut)
def create_model(req: ModelConfigIn, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles("admin"))):
    usages = _normalize_usage(req.usage)
    if not usages:
        raise HTTPException(400, "请至少选择一个用途")
    # 同一大模型配置只能添加一次：协议 + 请求链接 + 模型版本 完全相同即视为重复
    if _dup_model_config(db, req.provider, req.base_url, req.model):
        raise HTTPException(409, "已添加：检测到相同的大模型配置（接口协议 + 请求链接 + 模型版本 均一致），请勿重复添加。")
    if req.is_active:
        _deactivate_conflicting(db, usages)
    m = ModelConfig(
        name=req.name,
        usage=usages[0],
        usages=usages,
        provider=req.provider,
        api_key=req.api_key,
        base_url=req.base_url,
        model=req.model,
        params=req.params,
        is_active=req.is_active,
    )
    db.add(m); db.commit(); db.refresh(m)
    return m

@router.put("/settings/models/{mid}", response_model=ModelConfigOut)
def update_model(mid: int, req: ModelConfigIn, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles("admin"))):
    m = db.query(ModelConfig).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "配置不存在")
    usages = _normalize_usage(req.usage)
    if not usages:
        raise HTTPException(400, "请至少选择一个用途")
    # 编辑时同样防重复，但排除正在编辑的自身
    if _dup_model_config(db, req.provider, req.base_url, req.model, exclude_id=mid):
        raise HTTPException(409, "已添加：检测到相同的大模型配置（接口协议 + 请求链接 + 模型版本 均一致），请勿重复添加。")
    if req.is_active:
        _deactivate_conflicting(db, usages, exclude_id=mid)
    m.name = req.name
    m.usages = usages
    m.usage = usages[0]
    m.provider = req.provider
    m.api_key = req.api_key
    m.base_url = req.base_url
    m.model = req.model
    if req.params is not None:
        m.params = req.params
    m.is_active = req.is_active
    db.commit(); db.refresh(m)
    return m

@router.delete("/settings/models/{mid}")
def delete_model(mid: int, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles("admin"))):
    m = db.query(ModelConfig).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "配置不存在")
    db.delete(m); db.commit()
    return {"ok": True}

@router.get("/settings/models/presets")
def list_model_presets(usage: str = ""):
    """返回模型配置目录（不含任何密钥），供前端「添加大模型」选择。

    usage 缺省或 analysis/copy → 文本 LLM 目录；image → 文生图目录；video → 文生视频目录；
    all → 全部（含文本/图像/视频），前端下拉选择时一次性拉取。
    每个预设额外带出 extra_fields（厂商专属附加字段，如自定义端点）与 modality（text/image/video）。
    """
    from llm_catalog import get_presets, modality_of, _PROTOCOL_EXTRA, get_all_presets
    presets = get_all_presets() if (usage or "") == "all" else get_presets(usage or "")
    return [
        {
            "key": p["key"],
            "name": p["name"],
            "protocol": p["protocol"],
            "modality": modality_of(p["protocol"]),
            "mainstream": p.get("mainstream", False),
            "default_base_url": p["default_base_url"],
            "base_url_editable": p["base_url_editable"],
            "models": p["models"],
            "api_key_label": p["api_key_label"],
            "api_key_placeholder": p["api_key_placeholder"],
            "model_placeholder": p["model_placeholder"],
            "docs_url": p["docs_url"],
            "setup_guide": p["setup_guide"],
            "notes": p["notes"],
            "extra_fields": p.get("extra_fields") or _PROTOCOL_EXTRA.get(p["protocol"], []),
        }
        for p in presets
    ]


@router.post("/settings/models/test")
async def test_model(req: ModelTestIn):
    """协议感知连通测试：按 provider 查目录决定协议（OpenAI / Anthropic / Gemini / 文生图 / 文生视频），
    发起一次最小真实调用，返回 ok/延迟/回包，或结构化错误（error_type/message/hint_url）。"""
    result = await test_llm_connection({
        "provider": req.provider,
        "api_key": req.api_key,
        "base_url": req.base_url,
        "model": req.model,
        "protocol": req.protocol,
        "endpoint": req.endpoint,
    })
    return result


# ----------------------------- V4.34 连通性健康 -----------------------------
@router.get("/settings/models/health")
def model_health_info():
    """每日自动测试的运行信息（开关、执行小时、上次自动测试日期/时间、配置总数）。"""
    from model_health import health_info
    return health_info()


@router.post("/settings/models/test-all")
async def test_all_saved_models(admin: User = Depends(require_roles("admin"))):
    """手动触发：对全部已保存配置跑一次真实连通测试，写回成功/失败与失败 log。"""
    from model_health import run_all
    return await run_all(reason="manual")


@router.post("/settings/models/{mid}/test")
async def test_saved_model(mid: int, db: Session = Depends(get_db),
                           admin: User = Depends(require_roles("admin"))):
    """按 id 测试一条「已保存」配置（使用落库的 Key，不依赖前端回填），并写回测试状态。"""
    from model_health import test_one
    m = db.query(ModelConfig).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "配置不存在")
    res = await test_one(db, m)
    db.commit()
    db.refresh(m)
    out = ModelConfigOut.model_validate(m, from_attributes=True)
    try:
        from providers import effective_config_ids
        out.in_use = m.id in effective_config_ids(db)
    except Exception:
        pass
    return {**res, "config": out}


# ----------------------------- 素材提示词：统一目录 -----------------------------
def _prompt_reg(key: str):
    return next((p for p in PROMPT_REGISTRY if p["key"] == key), None)


@router.get("/settings/prompts", response_model=list[PromptOut])
def list_prompts(db: Session = Depends(get_db),
                 module: str = Query(None, description="按功能模块筛选"),
                 func_type: str = Query(None, description="按功能类型筛选"),
                 usage_type: str = Query(None, description="按使用类型筛选"),
                 _: User = Depends(require_roles(*ROLES))):
    """V4.35 / V4.37 统一提示词目录：一次输出「素材创作」涉及的全部提示词。

    8 条系统级提示词（5 条落地页分析 + 3 条广告推广文案/图片）+ 62 条预设片段；
    V4.37 已移除只服务于旧「素材管理」的 5 条失效提示词。
    未落库的用内置默认兜底展示（与运行时 get_prompt 行为一致）。
    菜单对 editor 可见，故读取放宽为所有已登录角色；写操作仍限 admin。
    """
    rows = {p.key: p for p in db.query(PromptConfig).all()}
    out = []
    for item in PROMPT_REGISTRY:
        if module and item.get("module") != module:
            continue
        if func_type and item.get("func_type") != func_type:
            continue
        if usage_type and item.get("usage_type") != usage_type:
            continue
        row = rows.get(item["key"])
        if row:
            out.append(row)
        else:
            out.append(PromptConfig(id=0, key=item["key"], name=item["name"], module=item["module"],
                                    category=item.get("category"),
                                    func_type=item.get("func_type"), usage_type=item.get("usage_type"),
                                    description=item["description"],
                                    content=item["content"], is_active=True, updated_at=None))
    return out


# ----------------------------- V4.35 素材提示词：分类 / 总结库 / 系统默认 -----------------------------

def _state_get(db, key: str) -> str:
    row = db.query(SystemState).filter_by(key=key).first()
    return (row.value or "").strip() if row else ""


def _state_set(db, key: str, value: str):
    row = db.query(SystemState).filter_by(key=key).first()
    if not row:
        row = SystemState(key=key, value="")
        db.add(row)
    row.value = value or ""


def _prompt_defaults(db) -> dict:
    """当前两类「直接影响最终结果」的提示词所选的总结库模板。

    customized=True 表示管理员在「提示词目录」里又手改过正文，前端会标注以免误认为
    当前生效内容仍等于总结库原模板。
    """
    out = {}
    for kind in KINDS:
        ident = _state_get(db, "prompt_default_" + kind["key"])
        practice = get_practice(kind["key"], ident) if ident else None
        reg = _prompt_reg(kind["target_key"])
        row = db.query(PromptConfig).filter_by(key=kind["target_key"]).first()
        baseline = practice["content"] if practice else (reg or {}).get("content", "")
        live = (row.content if row and row.content else baseline) or ""
        customized = bool(baseline and live.strip() != baseline.strip())
        out[kind["key"]] = {
            "kind": kind["key"],
            "label": kind["label"],
            "target_key": kind["target_key"],
            "id": ident or None,
            "name": practice["name"] if practice else "系统内置默认",
            "source": practice["source"] if practice else "内置提示词（可在目录中编辑）",
            "builtin": not bool(ident),
            "customized": customized,
        }
    return out


@router.get("/settings/prompt-taxonomy")
def prompt_taxonomy(db: Session = Depends(get_db),
                    _: User = Depends(require_roles(*ROLES))):
    """两套分类维度 + 各分类条目数，供「素材提示词」渲染筛选器与分类总览。"""
    counts: dict[str, int] = {}
    for item in PROMPT_REGISTRY:
        counts[item["func_type"]] = counts.get(item["func_type"], 0) + 1
    usage_counts: dict[str, int] = {}
    for item in PROMPT_REGISTRY:
        usage_counts[item["usage_type"]] = usage_counts.get(item["usage_type"], 0) + 1
    return {
        "func_types": [{**x, "count": counts.get(x["key"], 0)} for x in FUNC_TYPES],
        "usage_types": [{**x, "count": usage_counts.get(x["key"], 0)} for x in USAGE_TYPES],
        "total": len(PROMPT_REGISTRY),
    }


@router.get("/settings/prompt-library")
def prompt_library(kind: str = Query(None), type: str = Query(None),
                   style: str = Query(None), scene: str = Query(None),
                   audience: str = Query(None), q: str = Query(None),
                   db: Session = Depends(get_db),
                   _: User = Depends(require_roles(*ROLES))):
    """优秀提示词总结库：按 类型 / 风格 / 场景 / 覆盖对象 四维筛选（可叠加关键词）。"""
    items = library_entries(kind, type=type, style=style, scene=scene,
                            audience=audience, q=q)
    return {
        **library_dimensions(),
        "items": items,
        "total": len(items),
        "all_total": len(BEST_PRACTICES),
        "defaults": _prompt_defaults(db),
    }


@router.put("/settings/prompt-defaults")
def set_prompt_default(req: PromptDefaultIn, db: Session = Depends(get_db),
                       admin: User = Depends(require_roles("admin"))):
    """把总结库中一条优秀提示词设为系统默认。

    实现：把该模板正文写入对应系统提示词（media_copy_sys / media_image_sys），
    生成链路经 get_prompt 读取，因此**保存即生效**，无需重启。id 为空则恢复内置默认。
    """
    target_key = target_key_for_kind(req.kind)
    if not target_key:
        raise HTTPException(400, "未知的提示词类别（应为 ad_copy / ad_image）")
    reg = _prompt_reg(target_key)
    if not reg:
        raise HTTPException(500, "默认提示词目标未注册：" + target_key)

    if req.id:
        practice = get_practice(req.kind, req.id)
        if not practice:
            raise HTTPException(404, "总结库中不存在该提示词：" + req.id)
        content = practice["content"]
        label = practice["name"]
    else:
        content = reg["content"]
        label = "系统内置默认"

    row = db.query(PromptConfig).filter_by(key=target_key).first()
    if not row:
        row = PromptConfig(key=target_key, name=reg["name"], module=reg["module"],
                           category=reg.get("category"), func_type=reg.get("func_type"),
                           usage_type=reg.get("usage_type"), description=reg["description"])
        db.add(row)
    row.content = content
    row.is_active = True
    _state_set(db, "prompt_default_" + req.kind, req.id or "")
    db.commit()
    _audit(db, admin, "prompt.default", target_key, {"kind": req.kind, "id": req.id or "builtin"})
    return {"ok": True, "kind": req.kind, "target_key": target_key,
            "id": req.id or None, "name": label, "defaults": _prompt_defaults(db)}


@router.put("/settings/prompts/{key}", response_model=PromptOut)
def update_prompt(key: str, req: PromptUpdate, db: Session = Depends(get_db),
                  admin: User = Depends(require_roles("admin"))):
    """编辑提示词正文；保存即生效（下一次调用该模块时使用新提示词）。"""
    reg = _prompt_reg(key)
    if not reg:
        raise HTTPException(404, "提示词不存在")
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(400, "提示词内容不能为空")
    # 仅对「默认提示词本身含 MARKER 标记」的提示词强制保留 MARKER（如 site_analysis/angle/copy 等）；
    # 落地页分析等不含 MARKER 的提示词可自由编辑，不再被误拦截。
    if "MARKER" in reg["content"] and "MARKER" not in content:
        raise HTTPException(400, "提示词需保留结尾 MARKER 标记（Mock 兜底与日志定位依赖它），请勿删除")
    row = db.query(PromptConfig).filter_by(key=key).first()
    if not row:
        row = PromptConfig(key=key, name=reg["name"], module=reg["module"],
                           category=reg.get("category"), func_type=reg.get("func_type"),
                           usage_type=reg.get("usage_type"),
                           description=reg["description"], content=reg["content"])
        db.add(row)
    row.content = req.content
    if req.name is not None:
        row.name = req.name
    if req.description is not None:
        row.description = req.description
    if req.category is not None:
        row.category = req.category
    if req.func_type is not None:
        row.func_type = req.func_type
    if req.usage_type is not None:
        row.usage_type = req.usage_type
    if req.is_active is not None:
        row.is_active = req.is_active
    db.commit(); db.refresh(row)
    _audit(db, admin, "prompt.update", key, {"name": row.name, "chars": len(row.content)})
    return row


@router.post("/settings/prompts/{key}/reset", response_model=PromptOut)
def reset_prompt(key: str, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles("admin"))):
    """恢复为内置默认提示词。"""
    reg = _prompt_reg(key)
    if not reg:
        raise HTTPException(404, "提示词不存在")
    row = db.query(PromptConfig).filter_by(key=key).first()
    if not row:
        row = PromptConfig(key=key, name=reg["name"], module=reg["module"],
                           category=reg.get("category"), func_type=reg.get("func_type"),
                           usage_type=reg.get("usage_type"),
                           description=reg["description"], content=reg["content"], is_active=True)
        db.add(row)
    else:
        row.content = reg["content"]
        row.name = reg["name"]
        row.description = reg["description"]
        row.category = reg.get("category")
        row.func_type = reg.get("func_type")
        row.usage_type = reg.get("usage_type")
        row.is_active = True
    # 恢复内置默认时，一并清除总结库里该类提示词的默认选择标记
    for kind in KINDS:
        if kind["target_key"] == key:
            _state_set(db, "prompt_default_" + kind["key"], "")
    db.commit(); db.refresh(row)
    _audit(db, admin, "prompt.reset", key, {"name": row.name})
    return row


# ----------------------------- 登录 / 用户 / 审计 -----------------------------
def _audit(db: Session, user, action: str, target: str = None, detail: dict = None):
    db.add(AuditLog(username=getattr(user, "username", None), action=action,
                    target=target, detail=detail))
    db.commit()


def _client_ip(request: Request) -> Optional[str]:
    """取真实客户端 IP：优先 X-Forwarded-For 第一段（Cloudflare Tunnel / Caddy 反向代理场景），
    其次 X-Real-IP，最后回退到直连 socket 地址。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip() or None
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip() or None
    return request.client.host if request.client else None


def _log_login(db: Session, username: Optional[str], request: Request,
               success: bool = True, detail: dict = None):
    """V4.47：记录一次登录尝试（成功与失败均记录）。异常不阻断登录主流程。"""
    try:
        db.add(LoginLog(username=username, ip=_client_ip(request),
                        user_agent=request.headers.get("user-agent"),
                        success=success, detail=detail))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/auth/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    u = db.query(User).filter((User.email == req.email) | (User.username == req.email)).first()
    if not u or not u.active or not verify_password(req.password, u.password_hash, u.salt):
        _log_login(db, req.email, request, success=False,
                   detail={"reason": "invalid_credentials" if (u and u.active) else "no_user_or_inactive",
                           "attempt": req.email})
        raise HTTPException(401, "邮箱或密码错误")
    _log_login(db, u.username, request, success=True)
    return create_token(u)

@router.get("/auth/me")
def whoami(user: User = Depends(current_user)):
    return user_dict(user)

@router.get("/auth/roles")
def role_catalog():
    return {"roles": ROLE_LABELS, "can_edit": CAN_EDIT, "can_review": CAN_REVIEW}

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return db.query(User).order_by(User.id).all()

@router.post("/users", response_model=UserOut)
def create_user(req: UserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_roles("admin"))):
    if req.role not in ROLES:
        raise HTTPException(400, f"角色必须是 {ROLES}")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    email = (req.email or "").strip().lower()
    local, sep, domain = email.partition("@")
    if not (sep and local and "." in domain):
        raise HTTPException(400, "请输入有效的邮箱地址")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(400, "该邮箱已注册")
    # 用户名：优先用填写值，否则由邮箱本地部分派生并去重
    username = (req.username or "").strip() or local
    base, n = username, 1
    while db.query(User).filter_by(username=username).first():
        n += 1
        username = f"{base}{n}"
    h, s = hash_password(req.password)
    u = User(email=email, username=username, display_name=req.display_name or local,
             role=req.role, password_hash=h, salt=s, active=True)
    db.add(u); db.commit(); db.refresh(u)
    _audit(db, admin, "user.create", email, {"role": req.role})
    return u

@router.put("/users/{uid}", response_model=UserOut)
def update_user(uid: int, req: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_roles("admin"))):
    u = db.query(User).filter_by(id=uid).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    if req.role and req.role not in ROLES:
        raise HTTPException(400, f"角色必须是 {ROLES}")
    # 防止最后一个管理员被降级/停用
    if u.role == "admin" and ((req.role and req.role != "admin") or req.active is False):
        if db.query(User).filter_by(role="admin", active=True).count() <= 1:
            raise HTTPException(400, "至少保留一个启用的管理员")
    if req.display_name is not None:
        u.display_name = req.display_name
    if req.role:
        u.role = req.role
    if req.active is not None:
        u.active = req.active
    if req.password:
        if len(req.password) < 6:
            raise HTTPException(400, "密码至少 6 位")
        u.password_hash, u.salt = hash_password(req.password)
    db.commit(); db.refresh(u)
    _audit(db, admin, "user.update", u.username, {"role": u.role, "active": bool(u.active)})
    return u

@router.delete("/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db),
                admin: User = Depends(require_roles("admin"))):
    u = db.query(User).filter_by(id=uid).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    if u.id == admin.id:
        raise HTTPException(400, "不能停用当前登录账号")
    if u.role == "admin" and db.query(User).filter_by(role="admin", active=True).count() <= 1:
        raise HTTPException(400, "至少保留一个启用的管理员")
    u.active = False       # 软删除，保留审计线索
    db.commit()
    _audit(db, admin, "user.deactivate", u.username)
    return {"ok": True}

@router.get("/audit-logs")
def audit_logs(limit: int = 50, db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))):
    limit = min(max(int(limit), 1), 2000)
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "username": r.username, "action": r.action, "target": r.target,
             "detail": r.detail, "created_at": r.created_at} for r in rows]


@router.get("/login-logs")
def login_logs(limit: int = 100, success: Optional[bool] = None,
               db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))):
    """V4.47：账号登录日志（admin 可见）。可选 success 过滤（true=成功 / false=失败）。"""
    limit = min(max(int(limit), 1), 2000)
    q = db.query(LoginLog)
    if success is not None:
        q = q.filter_by(success=success)
    rows = q.order_by(LoginLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "username": r.username, "ip": r.ip,
             "user_agent": r.user_agent, "success": bool(r.success),
             "detail": r.detail, "created_at": r.created_at} for r in rows]


@router.post("/creation-recommendation")
def creation_recommendation(body: dict,
                            _: User = Depends(require_roles(*ROLES))):
    """V4.45 / D2：默认自动创作的策划结果（确定性，不调用新模型）。

    输入是既有 `POST /api/landing-analysis` 的分析结果 + 已选媒体 + 工作区默认值；
    输出「推荐怎么拍 / 怎么画」的直观描述、理由、缺口与覆盖摘要。
    推荐描述与 `visual_brief` 来自同一对象，避免两次生成互相矛盾。
    """
    from media_platforms import validate_platform, MediaRuleError
    from creation_planner import build_recommendation
    analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else {}
    plats = body.get("platforms") if isinstance(body.get("platforms"), list) else []
    if not plats and body.get("platform"):
        plats = [str(body.get("platform"))]
    plats = [str(x).strip() for x in plats if str(x or "").strip()][:8]
    # V4.45 / N04 / A10：未知平台在策划阶段就拒绝，不静默套用其它平台规则。
    try:
        for p in plats:
            validate_platform(p)
    except MediaRuleError as e:
        raise HTTPException(422, detail={"message": "媒体平台目录校验未通过",
                                        "errors": e.errors})
    defaults = body.get("workspace_defaults") if isinstance(body.get("workspace_defaults"), dict) else {}
    return build_recommendation(analysis, plats,
                                workspace_defaults=defaults,
                                mode=str(body.get("mode") or "auto"))


# ===========================================================================
# V4.46 / D5：自动创作持久计划（多阶段编排 + 版本冻结 + 质检归档）
# ===========================================================================
def _plan_feature_off() -> bool:
    """灰度开关：关闭时新入口不可达，但资产 / 计划 / 任务记录保留（文档回滚要求）。"""
    return not bool(ENABLE_AUTO_CREATION_PLAN)


@router.post("/creation-plans", status_code=202)
def api_create_plan(body: dict, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*CAN_EDIT))):
    """D5：基于落地页分析创建持久计划，落库推荐与覆盖快照，返回 plan_id + 状态。

    输入 analysis（来自 /api/landing-analysis）+ 已选平台 + 工作区默认值；不调用新模型。
    未知平台在创建时即由 `validate_platform` 拒绝（A10）。
    """
    if _plan_feature_off():
        raise HTTPException(503, detail={"message": "自动创作计划功能当前已关闭（灰度开关）"})
    analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else {}
    platforms = body.get("platforms") if isinstance(body.get("platforms"), list) else []
    defaults = body.get("workspace_defaults") if isinstance(body.get("workspace_defaults"), dict) else {}
    if not analysis:
        raise HTTPException(422, detail={"message": "请提供落地页分析结果"})
    try:
        plan = create_plan(db, analysis, platforms, defaults, user)
    except MediaRuleError as e:
        raise HTTPException(422, detail={"message": "媒体平台目录校验未通过", "errors": e.errors})
    return {**plan_to_dict(plan), "created": True,
            "message": "计划已创建；确认平台与费用授权后可生成"}


@router.get("/creation-plans/{plan_id}")
def api_get_plan(plan_id: str, db: Session = Depends(get_db),
                 _: User = Depends(require_roles(*ROLES))):
    """读取计划的推荐描述、概念、覆盖摘要、阶段与确认状态；刷新 / 关闭后据此恢复。"""
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "创作计划不存在")
    return plan_to_dict(plan)


@router.post("/creation-plans/{plan_id}/coverage")
def api_plan_coverage(plan_id: str, body: dict, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*CAN_EDIT))):
    """D4 / A11：用户确认平台后计算「全规则图片」覆盖计划与成本上界（只按已选范围）。"""
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "创作计划不存在")
    platforms = body.get("platforms") if isinstance(body.get("platforms"), list) else []
    try:
        plan = set_coverage(db, plan_id, platforms, user)
    except MediaRuleError as e:
        raise HTTPException(422, detail={"message": "媒体平台目录校验未通过", "errors": e.errors})
    return {**plan_to_dict(plan),
            "message": "覆盖计划已按所选平台与概念数计算（超批自动拆子批，不截断版位）"}


@router.post("/creation-plans/{plan_id}/confirm")
def api_plan_confirm(plan_id: str, body: dict, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*CAN_EDIT))):
    """D5 / A13 / A14：冻结版本、范围与费用授权，生成 approval_token。

    费用授权须 ≥ 预计成本上界，否则明确拒绝（不隐瞒缺口）；冻结后产品事实 / 目标地区变化
    将使下游推荐、提示词、覆盖与确认令牌失效。
    """
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "创作计划不存在")
    fee = float(body.get("fee_authorized_usd") or 0)
    try:
        plan = confirm_plan(db, plan_id, fee, user)
    except ValueError as e:
        raise HTTPException(422, detail={"message": str(e)})
    return {**plan_to_dict(plan),
            "message": "计划已冻结；可携带 plan_id / plan_version 创建生成任务"}


@router.post("/creation-plans/{plan_id}/finalize")
def api_plan_finalize(plan_id: str, body: dict, db: Session = Depends(get_db),
                      _: User = Depends(require_roles(*CAN_EDIT))):
    """D5 / D6：汇总关联生成任务结果 → 质检 → 归档 manifest。"""
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(404, "创作计划不存在")
    job_results = body.get("job_results") if isinstance(body.get("job_results"), list) else []
    plan = finalize(db, plan_id, job_results)
    return {**plan_to_dict(plan), "message": "计划已质检并归档"}
