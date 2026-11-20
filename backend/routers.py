from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Response, Header
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import os, time, re, json, asyncio, uuid

from database import get_db, SessionLocal
from models import (ModelConfig, User, AuditLog, LoginLog, PromptConfig, SystemState,
                    CreationHistory, GenerationJob, CreativeAsset, CreativeAnalysis, CreativePlan, CwLibrary, utcnow)
from schemas import (ModelConfigIn, ModelConfigOut, ModelTestIn,
                     LoginRequest, UserOut, UserCreate, UserUpdate,
                     PromptOut, PromptUpdate, PromptDefaultIn, LayerMatchIn, ImageQualityAuditIn,
                     LandingAnalysisRequest, LandingAnalysis, MediaCopyRequest, MediaImageRequest,
                     CreativeBriefPreviewIn,
                     CreativeAnalysisRequest, CreativeAnalysisResult,
                     CreativePlanRequest, CreativePlanResult, CreativeRoute,
                     CWAnalyzeRequest, CWAnalysisResult, CWRoutesRequest, CWRoute, CWRoutesResult,
                     CWIntentParseRequest, CWIntentParseResult,
                     ProductSnapshot, CwLibraryOut, CwLibraryCreate,
                     CWVideoPlanRequest, CWVideoPlanResult, CWVideoGenerateRequest, CWVideoGenerateResult,
                     CWVideoAsset, CWVideoJobOut, ModelInfo,
                     WorkshopAnalyzeRequest, WorkshopGenerateRequest,
                     MediaImageSlot, MediaCopyVariant)
from services import PROMPT_REGISTRY, analyze_landing_concise
from llm_catalog import test_llm_connection, _resolve_protocol
from providers import (get_llm_with_info, finalize_invocation, parse_json, get_video,
                       _active_config, StoryboardVideo, video_route_report,
                       VideoPipelineError, is_video_capable)
from presets import creative_presets_payload
from prompt_catalog import (library_dimensions, library_entries,
                            get_practice, target_key_for_kind, KINDS, FUNC_TYPES,
                            USAGE_TYPES, BEST_PRACTICES)
from media_platforms import (list_media_platforms, validate_platform,
                             validate_task_matrix, media_rules_payload,
                             canonical_platform,
                             MediaRuleError, SPEC_VERSION, MEDIA_RULES)
# V4.84：媒体素材规格标准库（图片/视频单一事实来源），生成链路统一引用
from media_spec_library import (library_payload as spec_library_payload,
                                video_target as spec_video_target,
                                validate_video_delivery as spec_validate_delivery)
# V4.88：文档提示词契约——视频出片提示词与图片纯图模式共用同一套无字视觉约束
from prompt_contract import build_prompt_contract, render_video_contract_block
from media_ad import generate_media_copy, generate_media_images
from industry_profiles import resolve_profile
from analysis_contract import as_text, as_text_list, normalize_analysis
from creation_plan_service import (
    create_plan, set_coverage, confirm_plan, attach_job, finalize,
    get_plan, plan_to_dict,
)
# V4.98 / V4.100：提示词管理（三类通用模板 / 六层心理链条 / 变量来源）
from material_prompt_manage import (
    MODULE as MATERIAL_PROMPT_MODULE, LEGACY_MODULE as MATERIAL_PROMPT_LEGACY_MODULE,
    PROMPT_TYPES, PSYCHOLOGICAL_LAYERS,
    variables_of as material_variables_of, auto_match_layers,
)
# V4.101：文案 / 图片 / 视频共用的创意框架与用户确认 brief
from creative_brief import (
    framework_options, framework_of, normalize_brief,
    build_copy_brief_block, build_image_brief_block, build_video_brief_block,
)
# V4.105 / 方案C：结构化创作意图（分析前确认创作要求，三类素材共用）
import creative_intent as cw_intent
import workshop as cw_workshop
from version import ENABLE_AUTO_CREATION_PLAN
# V4.82：视频链路复用 D0 证据 / 限定保护，避免图片链路拦住的夸大承诺从视频溜出去
from video_claims import (video_evidence_context, audit_video_plan,
                          repair_video_plan, video_asset_gate)
# V4.103 / 方案A：生成前统一证据硬门（文案 / 图片 / 视频 / 通用任务共用）
from claims import generation_evidence_gate
# V4.90：视频文字 / 文案预检与保守修复（只管文本形态和批准文案，不重复证据门）
from video_text_guard import (audit_video_text, repair_video_text,
                              render_video_text_guard_block)
# V4.93：品牌 / 文案黄金词典——上屏文字的唯一事实源，杜绝品牌名 / 单词错拼
from brand_lexicon import build_lexicon, enforce_onscreen, render_lexicon_block
from brand_lexicon import build_text_overlay  # V4.94 阶段二：播放层叠加配置

# V4.81 / P2-P3：出片任务持久化（唯一任务事实在库，进程重启不丢）与创作批次列表
import creative_tasks
from creative_tasks import (create_video_batch, STAGE_LABEL as CREATIVE_STAGE_LABEL,
                            _duration_verdict)
from job_service import IdempotencyConflict
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
                      evidence_prompt_part, evidence_prompt_part_async)

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


@router.get("/media-spec-library")
async def api_media_spec_library(_: User = Depends(require_roles(*ROLES))):
    """V4.84：媒体素材规格标准库快照（图片+视频，逐广告产品，带来源/核验分级）。

    这是展示与生成的单一事实来源。前端「媒体平台设置」和导出清单都应引用本端点，
    不再各写一套尺寸/时长；每条规则标注 A 官方核验 / B 内部基准 / C 待确认。
    """
    return spec_library_payload()


def _rule_error(exc: MediaRuleError) -> HTTPException:
    """把规则拒绝整理成接口可读的明确错误（不吞掉任何一条原因）。"""
    return HTTPException(422, detail={
        "message": "媒体规则校验未通过，已在调用模型前拦截",
        "errors": exc.errors,
        "spec_version": SPEC_VERSION,
    })


def _enforce_evidence_gate(analysis: dict) -> None:
    """V4.103 / 方案A：真实抓取分析无可用证据时，在调用模型 / 入队前硬阻断。

    返回 None 表示放行；否则抛 422 needs_input，前端按结构化 detail 展示原因。
    精确限定于「真实抓取链路」，演示 / 粘贴 / 历史简化分析不受影响。
    """
    gate = generation_evidence_gate(analysis or {})
    if not gate["allowed"]:
        raise HTTPException(422, detail={
            "message": "证据校验未通过，已在调用模型前阻断（needs_input）",
            "errors": [gate["reason"]],
            "evidence_gate": gate["status"],
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
    # V4.101：未经用户确认的 brief 不得进入生成；前端也做同口径禁用。
    if req.brief and not req.brief.get("confirmed"):
        raise HTTPException(400, "创意 brief 尚未确认，请先在预览中确认后再生成文案")
    # V4.103 / 方案A：真实抓取分析无证据时硬阻断，不调用付费模型。
    _enforce_evidence_gate(req.analysis.model_dump())
    result = await generate_media_copy(db, req.analysis.model_dump(), platform, req.lang,
                                       ad_product=req.ad_product,
                                       style_opts=req.style_opts or {},
                                       brief=req.brief or None)
    return result


# ----------------------------- V4.101 创意框架 / 用户 brief 预览 -----------------------------
@router.get("/creative-frameworks")
def api_creative_frameworks(_: User = Depends(require_roles(*ROLES))):
    """九类高转化创意框架注册表，供前端下拉与展示叙事节奏。"""
    return {"frameworks": framework_options()}


@router.post("/creative-brief/preview")
@router.post("/media-campaign/copy/prompt-preview")
def api_creative_brief_preview(req: CreativeBriefPreviewIn,
                               _: User = Depends(require_roles(*ROLES))):
    """把用户原始提示词补全为结构化 brief 供查阅 / 编辑 / 确认。

    纯规则补全，不调用付费模型、不生成素材；返回 confirmed=false，
    前端必须让用户确认后才能把 brief 传入生成接口。
    """
    brief = normalize_brief(req.raw_input, req.analysis or {}, req.framework,
                            req.layers or [], confirmed=False)
    if req.platform:
        brief["prompt_text"] += "\n投放平台：%s" % req.platform
    return brief

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
    # V4.103 / 方案A：真实抓取分析无证据时硬阻断，不调用付费模型。
    _enforce_evidence_gate(analysis)
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
    "你是资深的出海效果广告创意策略师。基于产品分析结论、项目简报、目标媒体平台、用户确认 brief "
    "与 creative_intent_block（创作意图，其中禁止项是硬约束），"
    "规划【N】条差异化的创意概念路线（概念级，不逐平台拆分；【N】由 user_prompt 中的 count 给定，1–10）。只返回 JSON："
    "{\"title\": \"本次创意路线主题\","
    " \"routes\": ["
    "   {\"key\": \"A\", \"name\": \"路线名\", \"description\": \"路线说明（切入方式与表达）\","
    "    \"tags\": [\"标签1\",\"标签2\"], \"angle\": \"切入角度\","
    "    \"framework\": \"aida|pas|bab|hso|4p|contrast_proof|scene|social_proof|scarcity 之一\","
    "    \"hook\": \"首屏/前三秒钩子（具体动作或利益，不是空泛口号）\","
    "    \"proof\": \"可信证据如何呈现（只能引用页面证据，不写数字/评分/用户数）\","
    "    \"visual_hook\": \"画面视觉钩子（构图/光线/动作/对比，不写文字）\","
    "    \"cta_role\": \"结尾收口动作或叠加位意图（不写入画面文字）\"},"
    "   {\"key\": \"B\", ...}, ..."
    " ]}"
    "要求：routes 条数恰好等于 count；key 从 A 开始按字母顺序依次为 A/B/C/…/J；"
    "每条路线必须绑定一种框架，且 framework / hook / proof / visual_hook / cta_role 与 name/description 一致；"
    "每条路线都必须体现创作意图里的受众与核心价值，禁止项一条都不得触碰（不得用「换一种说法」绕过）；"
    "十条路线要覆盖不同框架与不同角度，不得复用同一角度换词；tags 2-3 个；"
    "若 user_prompt 给出 user_brief，则以其中确认的框架、钩子与叙事节奏为准；"
    "禁止编造价格、折扣、评分、用户数、倒计时与背书，证据不足时把 proof 写成「真实功能演示」。"
)

# V4.101 / P2：兜底路线升级为「框架 + 具体钩子 + 证据 + 视觉钩子 + 收口」，
# 并按 seed 轮换，避免换一批仍返回同一组。
_CW_FALLBACK_ROUTES = [
    {"name": "前后对比实验", "description": "用同机位同光线的真实前后对照，让变化在前三秒被看见。",
     "tags": ["转化导向", "产品演示"], "angle": "前后对比", "framework": "contrast_proof",
     "hook": "同一场景的两种状态直接并置", "proof": "用页面已明示功能做同条件演示，不写数字",
     "visual_hook": "左右分屏 / 同机位切换，产品出现在变化处", "cta_role": "变化之后顺势引导了解"},
    {"name": "半路受阻痛点", "description": "先呈现未满足的痛点代价，再把产品作为干净利落的解法登场。",
     "tags": ["痛点放大", "转化导向"], "angle": "痛点→解法", "framework": "pas",
     "hook": "受阻瞬间作为开场画面", "proof": "以真实操作解决该痛点，不虚构效果数据",
     "visual_hook": "受阻特写 → 产品介入的镜头切换", "cta_role": "从痛点回到可行动的解法"},
    {"name": "续航自由出发", "description": "用连续通勤场景展示产品自然融入，强化可依赖感。",
     "tags": ["场景叙事", "功能利益"], "angle": "场景证明", "framework": "scene",
     "hook": "出门瞬间的连续动作，不用空镜铺垫", "proof": "页面已明示的续航能力用真实场景呈现",
     "visual_hook": "第一视角手持跟随，光线从清晨到傍晚", "cta_role": "低干扰的轻 CTA"},
    {"name": "晨间日常切片", "description": "以真实生活时刻切入，让产品成为日常节奏的一部分。",
     "tags": ["生活方式", "日常场景"], "angle": "日常陪伴", "framework": "bab",
     "hook": "熟悉的清晨场景先建立代入", "proof": "用连续动作说明产品如何跨越现状到理想状态",
     "visual_hook": "同一空间的两种状态对照，产品出现在转折处", "cta_role": "邀请进入理想状态"},
    {"name": "细节微距特写", "description": "用材质与工艺近景建立品质感，再用整体画面给出结果。",
     "tags": ["质感", "产品特写"], "angle": "质感证明", "framework": "4p",
     "hook": "微距细节先行，随后拉开揭示整体", "proof": "只呈现页面可确认的外观与材质，不写评分",
     "visual_hook": "浅景深微距 + 光线扫过表面", "cta_role": "证据之后的顺势推动"},
    {"name": "用户口碑现场", "description": "用真实使用场景中的群体信号建立信任，不伪造评价截图。",
     "tags": ["信任背书", "口碑"], "angle": "社会认同", "framework": "social_proof",
     "hook": "多人自然使用同一产品的画面", "proof": "只引用页面可定位的口碑事实，无数据则用场景表达",
     "visual_hook": "群像中景转到产品近景", "cta_role": "跟随可信群体的行动"},
    {"name": "开箱第一视角", "description": "第一视角开箱，让外观与核心功能在同一动作链里被看见。",
     "tags": ["开箱", "第一视角"], "angle": "沉浸体验", "framework": "aida",
     "hook": "拆封动作直接开场", "proof": "功能演示只展示页面已确认能力",
     "visual_hook": "手部动作 + 产品主体逐步露出", "cta_role": "明确下一步且降低风险"},
    {"name": "功能可视化", "description": "把核心功能做成一眼看懂的可视化演示，降低理解成本。",
     "tags": ["功能利益", "信息可视"], "angle": "功能演示", "framework": "4p",
     "hook": "结果先出现，再回溯怎么做到的", "proof": "用真实功能演示承担证明，不写用户数",
     "visual_hook": "结果可视化 + 简洁动作特写", "cta_role": "结果之后的顺势推动"},
    {"name": "户外挑战验证", "description": "在出行与户外条件中验证可靠性，强化适用场景。",
     "tags": ["场景叙事", "挑战验证"], "angle": "极限验证", "framework": "contrast_proof",
     "hook": "把产品放进真实压力场景", "proof": "同条件对照展示能力边界，不夸大适用环境",
     "visual_hook": "广角环境 + 产品稳定工作的特写", "cta_role": "以结论引导进一步了解"},
    {"name": "价值锚定对照", "description": "用使用场景与长期价值做对照，突出物有所值但不编造价格。",
     "tags": ["价值导向", "转化导向"], "angle": "价值锚定", "framework": "hso",
     "hook": "先给使用场景中的具体收益", "proof": "收益必须由页面事实支撑；无优惠事实时不写优惠",
     "visual_hook": "场景收益与产品并置，不绘制价格字样", "cta_role": "利益驱动的立即行动"},
]


def _apply_route_variation(routes: list[dict], seed: str, exclude_names: list[str]) -> list[dict]:
    """模型真的返回路线时，换一批同样要改变顺序 / 排除上一批，而不是只改兜底。"""
    if not routes or (not seed and not exclude_names):
        return routes
    pool = list(routes)
    if seed:
        offset = sum(ord(c) for c in seed) % len(pool)
        pool = pool[offset:] + pool[:offset]
    excluded = {str(x).strip() for x in (exclude_names or []) if str(x).strip()}
    if excluded:
        filtered = [r for r in pool if r.get("name") not in excluded]
        if filtered:
            pool = filtered
    for i, r in enumerate(pool):
        r["key"] = chr(65 + i) if i < 26 else chr(65 + i % 26)
    return pool


def _rotated_fallback_routes(seed: str, exclude_names: list[str], count: int) -> list[dict]:
    pool = list(_CW_FALLBACK_ROUTES)
    if seed:
        offset = sum(ord(c) for c in seed) % len(pool)
        pool = pool[offset:] + pool[:offset]
    excluded = {str(x).strip() for x in (exclude_names or []) if str(x).strip()}
    if excluded:
        filtered = [r for r in pool if r["name"] not in excluded]
        if len(filtered) >= count:
            pool = filtered
    return pool[:count]


# V4.66 创意工作台·视频素材创作区：对话式分镜策划
_CW_VIDEO_PLAN_SYS = (
    "你是资深的出海效果广告视频创意导演。用户会给你：① 产品分析结论（定位/受众/卖点/平台打法）；"
    "② 目标媒体平台；③ 参考图（可选，图生视频用）；④ 多轮对话（用户对提示词、创作构想、分镜方案的微调）；"
    "⑤ 已有的分镜方案（微调时带入，你需要增量修订而非重写）；"
    "⑥ creative_intent_block（创作意图，受众 / 核心价值 / 场景 / 风格 / 禁止项，禁止项是硬约束）。\n"
    "你要始终围绕「媒体平台推广、吸引流量、完成转化」的目标，确保视频：贴合产品定位、精准捕捉信息、"
    "表达产品核心卖点与转化路径，严禁使用静态推拉运镜冒充真实动态；"
    "创作意图里的禁止项一条都不得出现（包括字幕、VO、钩子与画面文字），与其它要求冲突时以禁止项为准。\n"
    "请只返回 JSON："
    "{\"reply\": \"给用户的自然语言回复（建议 / 已做的调整 / 下一步），中文，≤120字\","
    " \"plan\": {"
    "   \"mode\": \"text_to_video | image_to_video\","
    "   \"duration_sec\": 15,"
    "   \"aspect\": \"9:16 | 1:1 | 16:9\","
    "   \"voiceover\": \"none | narration | tts\","
    "   \"framework\": \"aida|pas|bab|hso|4p|contrast_proof|scene|social_proof|scarcity 之一\","
    "   \"framework_label\": \"框架中文名\","
    "   \"hook\": \"前3秒钩子（用动作/反差表达，不作为上屏文字）\","
    "   \"cta\": \"结尾行动号召（作为收口动作/叠加位，不画字）\","
    "   \"frames\": {\"hook\": \"钩子段\", \"pain\": \"痛点段\", \"solution\": \"方案段\", \"proof\": \"证据段\", \"cta\": \"收口段\"},"
    "   \"sound_design\": \"音效/BGM/旁白节奏建议（静音浏览也要能理解主动作）\","
    "   \"shots\": ["
    "     {\"idx\": 1, \"t\": \"0-3s\", \"shot\": \"镜头方式(image_to_video|source_video|motion_graphics|scene_3d|text_to_video)\","
    "      \"visual\": \"画面描述（动作/主体/场景，必须可动态呈现）\", \"text\": \"叠加字幕\", \"vo\": \"旁白文案\","
    "      \"camera\": \"运镜（如手持跟随/推近/环绕）\", \"motion\": \"主体运动/转场\"},"
    "     {\"idx\": 2, ...}, {\"idx\": 3, ...}, {\"idx\": 4, ...}"
    "   ],"
    "   \"deliverables\": [\"15s 主片\", \"6s 剪辑版\", \"首帧封面图\"],"
    "   \"note\": \"制作须知（合规/节奏/音乐方向）\""
    " }}"
    "要求：shots 默认 4 镜覆盖 15 秒；必须把所选framework映射为具体五段节奏："
    "0-3s 钩子（反差动作/结果前置，不用空镜）→ 3-6s 痛点放大 → 6-10s 方案演示 → "
    "10-13s 证据证明 → 13-15s CTA 收口（产品定格 + 叠加位意图）；"
    "frames 与 shots 必须一一对应，sound_design 给出可执行的节奏与音频建议；"
    "每镜 visual 必须描述真实可生成的动态画面，camera/motion 要具体到运镜与转场，不能只是静态图；"
    "可按对话微调节奏/卖点/时长；若 payload 给出 user_brief，则以其中确认的框架、钩子与节奏为准；"
    "若 regenerate=true，必须换一套完全不同的框架或钩子，不得复述 current_plan；"
    "不要编造产品未提及的事实；信息不足时给合理默认。\n"
    "V4.82 硬约束：必须严格遵守 payload.evidence_contract。字幕 / 旁白 / 钩子 / CTA 中"
    "任何数字、评分、用户数、价格、效果、试用、订阅或兼容性表述，都必须能在本次页面原文"
    "定位并保留原有「最多 / 测试条件 / 计费周期 / 适用范围」限定；原文没有就一个字都不要写，"
    "不得用「信息不足时给合理默认」作为编造数值的借口。\n"
    "V4.88 无字策略：text / cta 字段仍按上述 JSON 结构保留，但只用于内部节奏、VO 与策划"
    "追溯；出片提示词不会把它们绘制到画面，不要把它们设计成上屏字幕或端卡。\n"
    "V4.90 文字审查：hook / cta / 每镜 text / vo 必须完整、无乱码、无截断、无连续重复标点；"
    "不要写出画面放不下的长句。若确实需要上屏文字，必须在 plan.approved_texts 中逐字列出，"
    "并把对应镜头标记 text_effect（或 shot=motion_graphics）；未列入批准清单的文字一律不得上屏。"
    "效果化文字仍必须保持原文完整、清晰、可辨认。"
)


def _build_cw_result(title, summary, boxes, brief, rec_plat, *,
                     analysis_meta=None, snapshot, info, db, user, platforms,
                     evidence_pack=None):
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
    # V4.101 / P2：自动识别行业画像与已确认品牌，避免 MOOD/STYLE/BRAND_CONTEXT 长期为空。
    _profile_hint = {"industry": boxes.get("industry") or "", "type": boxes.get("industry") or "",
                     "audience": boxes.get("coreAudience") or ""}
    _profile = resolve_profile(_profile_hint)
    _brand = getattr(snapshot, "brand", "") or ""
    if getattr(snapshot, "brand_status", "") not in ("confirmed", "unverified"):
        _brand = ""
    analysis = {
        "title": title,
        "summary": summary,
        "product": title,
        "brand": _brand,
        "industry": boxes.get("industry") or "",
        "type": boxes.get("industry") or "",
        "audience": ("、".join(as_text_list(brief.get("targetAudience")))
                     or as_text(boxes.get("coreAudience"))).strip(),
        "advantages": as_text_list(brief.get("sellingPoints")),
        "competitors": [],
        "channels": rec_plat,
        "language": "en",
        "industry_profile": _profile["key"],
        "purchaseMotivation": boxes.get("purchaseMotivation") or "",
        "priceBand": boxes.get("priceBand") or "",
        "coreAudience": boxes.get("coreAudience") or "",
        "promotionGoal": brief.get("promotionGoal") or "",
        "targetAudience": as_text_list(brief.get("targetAudience")),
        "sellingPoints": as_text_list(brief.get("sellingPoints")),
        "recommendedPlatforms": rec_plat,
        "boxes": boxes,
        "brief": brief,
        "snapshot": snapshot.model_dump(),
        "url": analysis_meta.get("url") or "",
        "final_url": analysis_meta.get("final_url") or "",
    }
    # V4.103 / 方案A+C02：把真实抓取的证据包内嵌进统一 analysis，作为 D0 证据门、
    # prompt_contract 与 claim_contract 的单一事实来源。此前 pack 只用于拼提示词，
    # 分析落库不带证据 → 证据门读到空快照 → evidence_status=unverified / source_id=null。
    if evidence_pack:
        gate = evidence_pack.get("gate") or {}
        evidence = evidence_pack.get("evidence") or []
        analysis.update({
            "facts": [], "assumptions": [], "gaps": [],
            "evidence_ids": evidence_pack.get("evidence_ids") or [],
            "evidence_chain": [], "evidence_index": evidence,
            "sections_index": evidence_pack.get("sections_index") or [],
            "evidence_snapshot_id": evidence_pack.get("evidence_snapshot_id") or "",
            "evidence_fetched_at": evidence_pack.get("fetched_at") or "",
            "evidence_review_status": "locatable_not_reviewed" if evidence else "legacy_unverified",
            "evidence_gate": gate.get("status") or "",
            "blocked_reasons": gate.get("reasons") or [],
            "evidence_coverage": evidence_pack.get("coverage") or {},
            "evidence_note": evidence_pack.get("note") or "",
            "legacy_unverified": bool(evidence_pack.get("legacy_unverified")),
        })
    # V4.112：统一收敛成 LandingAnalysis 可接受的类型（文本 / 字符串数组 / channels），
    # 否则真实模型输出（industry 给对象、advantages 给字符串）会让文案与出图接口 422。
    analysis = normalize_analysis(analysis)
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


@router.post("/cw/intent/parse", response_model=CWIntentParseResult)
async def api_cw_intent_parse(req: CWIntentParseRequest,
                             _: User = Depends(require_roles(*CAN_EDIT))):
    """V4.105 / 方案C：把「确认创作要求」的一句话解析成结构化意图（纯规则、不调模型）。

    - 输入：已确认意图（可空）+ 用户刚输入的一段话
    - 输出：合并后的意图、字段级变更摘要、冲突提示、改动类型（visual / concept）
    - 只识别受众 / 目标 / 核心价值 / 场景 / 风格 / 禁止项；未识别片段按原文保留并提示，
      绝不静默丢弃用户的约束。
    """
    base = cw_intent.normalize(req.intent or {})
    parsed = cw_intent.parse_text(req.text or "", base=base)
    merged = cw_intent.merge(base, parsed.get("patch") or {})
    new_intent = merged["intent"]
    return CWIntentParseResult(
        intent=new_intent,
        patch=parsed.get("patch") or {},
        changes=merged.get("changes") or [],
        notes=list(parsed.get("notes") or []),
        conflicts=cw_intent.conflicts(new_intent),
        change_kind=cw_intent.classify_change(base, new_intent),
        summary=cw_intent.summary(new_intent),
    )


@router.get("/cw/model-status")
def api_cw_model_status(db: Session = Depends(get_db),
                        _: User = Depends(require_roles(*ROLES))):
    """V4.113：创意工作台的模型自检（只读，不调用模型、不产生费用）。

    V4.113 的真实故障里，用户点「生成」后只看到「文案未生成成功」，无法判断是
    没配置、Key 过期还是模型返回格式不对。这里在页面打开时就给出三种用途的
    生效配置与具体原因（含「文案复用分析模型」的如实标注）。
    """
    return cw_workshop.workbench_model_status(db)


@router.post("/cw/analyze", response_model=CWAnalysisResult)
async def api_cw_analyze(req: CWAnalyzeRequest, db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·产品分析的 HTTP 入口。

    V4.108：核心逻辑抽到 `_cw_analyze_core`，素材工作坊复用同一份分析链路，
    避免两个入口各写一套抓取 / 证据 / 意图逻辑而结论不一致。
    """
    return await _cw_analyze_core(req, db, user)


async def _cw_analyze_core(req: CWAnalyzeRequest, db: Session,
                           user: User) -> CWAnalysisResult:
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

    # ---- ⓪ V4.105 / 方案C：分析前先确认创作要求（结构化意图），随分析进入路线与生成 ----
    intent_base = cw_intent.normalize(req.creative_intent or {})
    intent_parsed = cw_intent.parse_text(req.intent_text or "", base=intent_base)
    intent_merged = cw_intent.merge(intent_base, intent_parsed.get("patch") or {})
    intent = intent_merged["intent"]
    intent_block = cw_intent.prompt_block(intent)
    intent_meta = {
        "intent": intent,
        "intent_notes": list(intent_parsed.get("notes") or []),
        "intent_conflicts": cw_intent.conflicts(intent),
        "intent_change": cw_intent.classify_change(intent_base, intent),
        "intent_summary": cw_intent.summary(intent),
    }

    def _with_intent(result: dict) -> dict:
        """意图同时写进统一分析（生成链路读这里）与响应顶层（前端展示）。"""
        if intent_block:
            if isinstance(result.get("analysis"), dict):
                result["analysis"]["creative_intent"] = intent
            else:
                result["analysis"] = {"creative_intent": intent}
        result.update(intent_meta)
        return result

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
        return CWAnalysisResult(**_with_intent(result))

    # ---- ② URL：服务端真实抓取 + 证据包驱动 ----
    if url:
        fetch = await fetch_product(url)
        if not fetch["ok"]:
            # 抓取失败且无文本：明确阻断，不再静默套用演示数据
            quality = fetch["page"].get("fetch_quality") or "fetch_failed"
            # V4.87：按失败类别给可操作提示，避免用户反复试同一个大文件/二进制链接
            reason_map = {
                "too_large": "页面内容超过 8MB 上限（可能是文件下载页），已停止抓取以保护服务稳定",
                "unsupported_content_type": "链接返回的是图片 / PDF / 视频等非网页内容，不是可分析的落地页",
                "unsupported_scheme": "仅支持 http / https 链接",
            }
            errors = [reason_map.get(quality,
                      "链接不可达或返回空页；请检查网址可达性，或开启「演示模式」，或直接粘贴产品描述文本")]
            raise HTTPException(422, detail={
                "message": "产品链接抓取失败，已在调用模型前阻断分析（needs_input）",
                "errors": errors,
                "fetch_quality": quality,
                "final_url": fetch["page"].get("final_url") or url,
                "hint": "系统不会从 URL 猜测产品事实；请补充正文或开启演示模式后重试。",
            })
        page = fetch["page"]
        pack = fetch["pack"]
        snapshot = ProductSnapshot(**fetch["snapshot"])
        evidence_text = await evidence_prompt_part_async(url, page, pack)
        user_prompt = (
            json.dumps({"url": url, "platforms": platforms}, ensure_ascii=False)
            + ("\n\n" + intent_block if intent_block else "")
            + "\n\n" + evidence_text
            + "\n\n请严格基于上方带 [E###] 编号的页面真实内容输出产品分析 JSON；"
              "不得从 URL / 域名推断页面未出现的事实，缺资料时留空。"
              "若给出了创作意图，brief 的推广目标 / 目标受众 / 核心卖点必须与之对齐。"
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
                                 user=user, platforms=platforms, evidence_pack=pack)
        return CWAnalysisResult(**_with_intent(result))

    # ---- ③ 仅文本：基于用户粘贴描述分析（source=pasted） ----
    llm, info = get_llm_with_info(db, "analysis")
    user_prompt = json.dumps({"text": text, "platforms": platforms}, ensure_ascii=False)
    if intent_block:
        user_prompt += "\n\n" + intent_block + "\n简报需与创作意图对齐（受众 / 目标 / 核心价值）。"
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
    return CWAnalysisResult(**_with_intent(result))


# ----------------------------- V4.105 / 方案C：路线卡就地编辑（改一句推荐描述） -----------------------------
@router.patch("/cw/routes/{plan_id}/{key}")
def patch_cw_route(plan_id: int, key: str, payload: dict,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT))):
    """就地修改一条创意路线的展示 / 表达字段，或保存「改一句」的修改意见（只改这一条）。

    - 只允许改展示与表达字段：name / description / angle / tags；
      framework / hook / proof / visual_hook / cta_role 也允许微调，但不允许改 key。
    - V4.114：user_note 是用户输入的「修改意见」，与原 description 分开保存；
      生成图片时作为本路线最高优先级的视觉调整指令注入提示词，不覆盖原规划内容。
    - 修改后路线仍按 key 参与「每条路线独立生成」，不需要重新规划整批。
    """
    rec = db.query(CreativePlan).filter_by(id=plan_id).first()
    if not rec:
        raise HTTPException(404, "创意方案不存在")
    if rec.owner_id and user.role != "admin" and rec.owner_id != user.id:
        raise HTTPException(403, "无权修改他人的创意方案")
    routes = list(rec.routes_json or [])
    target = None
    for r in routes:
        if isinstance(r, dict) and str(r.get("key") or "") == str(key or ""):
            target = r
            break
    if target is None:
        raise HTTPException(404, f"路线 {key} 不存在")
    editable = {"name", "description", "angle", "tags", "hook", "proof",
                "visual_hook", "cta_role", "user_note"}
    changed = []
    for k, v in (payload or {}).items():
        if k not in editable:
            continue
        if k == "tags":
            if not isinstance(v, list):
                continue
            v = [str(t).strip()[:20] for t in v if str(t or "").strip()][:4]
        else:
            v = str(v or "").strip()[:200]
        if target.get(k) != v:
            target[k] = v
            changed.append(k)
    if changed:
        rec.routes_json = routes
        # 用户手动改过路线描述：方案回到 draft，避免历史视图里被当成模型原始结论
        rec.status = "draft"
        db.commit(); db.refresh(rec)
    return {"id": rec.id, "key": key, "routes": routes, "changed": changed}


@router.post("/cw/routes", response_model=CWRoutesResult)
async def api_cw_routes(req: CWRoutesRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_roles(*CAN_EDIT))):
    """创意工作台·创意路线：产品分析 + 简报 + 平台 → 大模型规划 N 条创意概念路线；写回创意方案。

    V4.96：count 1–10，默认 3 保持旧调用兼容；创意工作台前端显式传 10。
    """
    plan_id = req.plan_id
    platforms = [str(p).strip() for p in (req.platforms or []) if str(p).strip()]
    analysis = req.analysis or {}
    brief = req.brief or {}
    try:
        count = max(1, min(10, int(req.count or 3)))
    except (TypeError, ValueError):
        count = 3
    llm, info = get_llm_with_info(db, "analysis")
    fw_key = str(req.framework or "").strip()
    user_brief = req.user_brief if isinstance(req.user_brief, dict) and req.user_brief.get("confirmed") else {}
    if user_brief and not fw_key:
        fw_key = str(user_brief.get("framework") or "")
    # V4.105 / 方案C：创作意图与 brief 同层进入策划；只调整切入方式，不替代证据
    intent = cw_intent.normalize(req.creative_intent or cw_intent.from_analysis(analysis))
    intent_block = cw_intent.prompt_block(intent)
    user_prompt = json.dumps({
        "analysis": analysis, "brief": brief, "platforms": platforms,
        "count": count, "framework": fw_key,
        "user_brief": user_brief,
        "creative_intent": intent,
        "creative_intent_block": intent_block,
        "exclude_names": req.exclude_names or [], "seed": req.seed or "",
    }, ensure_ascii=False)
    try:
        resp = await llm.chat(_CW_ROUTES_SYS, user_prompt)
        parsed = parse_json(resp) or {}
        info = finalize_invocation(info, llm, bool(parsed))
    except Exception:
        parsed, info = {}, finalize_invocation(info, llm, False)
    routes = []
    for r in (parsed.get("routes") or [])[:count]:
        if isinstance(r, dict):
            r_fw = framework_of(str(r.get("framework") or fw_key or ""))
            routes.append({
                "key": str(r.get("key") or "").strip(),
                "name": str(r.get("name") or "").strip(),
                "description": str(r.get("description") or "").strip(),
                "tags": [str(t).strip() for t in (r.get("tags") or []) if str(t).strip()][:4],
                "angle": str(r.get("angle") or "").strip(),
                "selected": True,
                "framework": r_fw["key"],
                "framework_label": r_fw["label"],
                "hook": str(r.get("hook") or "").strip(),
                "proof": str(r.get("proof") or "").strip(),
                "visual_hook": str(r.get("visual_hook") or "").strip(),
                "cta_role": str(r.get("cta_role") or "").strip(),
            })
    keys = [chr(65 + i) for i in range(10)]
    for i, r in enumerate(routes):
        if not r["key"]:
            r["key"] = keys[i] if i < len(keys) else chr(65 + i)
    # V4.101：模型返回路线也参与换一批，seed / exclude_names 对两条路径一致生效。
    routes = _apply_route_variation(routes, req.seed or "", req.exclude_names or [])
    # Mock / 解析失败兜底：框架化路线 + seed 轮换（不伪造产品事实）
    if not routes:
        base = _rotated_fallback_routes(req.seed or "", req.exclude_names or [], count)
        routes = []
        for i, item in enumerate(base):
            r_fw = framework_of(item["framework"])
            routes.append({
                "key": keys[i], "name": item["name"], "description": item["description"],
                "tags": list(item["tags"]), "angle": item["angle"], "selected": True,
                "framework": r_fw["key"], "framework_label": r_fw["label"],
                "hook": item["hook"], "proof": item["proof"],
                "visual_hook": item["visual_hook"], "cta_role": item["cta_role"],
            })
    result = {"title": str(parsed.get("title") or "创意路线规划").strip(),
              "routes": routes, "model_info": info, "source": info.get("source", "local"),
              "intent": intent, "intent_summary": cw_intent.summary(intent)}
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
    fw_key = str(req.framework or "").strip()
    user_brief = req.user_brief if isinstance(req.user_brief, dict) and req.user_brief.get("confirmed") else {}
    if user_brief and not fw_key:
        fw_key = str(user_brief.get("framework") or "")
    fw = framework_of(fw_key)
    # V4.101：换一批时不带旧方案，避免模型被 current_plan 锚定。
    current_plan = None if req.regenerate else (req.current_plan or None)
    convo = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}: {m.content}"
        for m in (req.messages or []) if m.content and m.content.strip()
    )
    payload = {
        "analysis": analysis,
        "platform": platform,
        "reference_image": req.reference_image or "",
        "options": req.options or {},
        "current_plan": current_plan,
        "conversation": convo,
        "language": lang,
        # V4.101：框架化规划 / 换一批 / 用户确认 brief
        "framework": fw["key"],
        "framework_label": fw["label"],
        "regenerate": bool(req.regenerate),
        "seed": req.seed or "",
        "user_brief": user_brief,
        "creative_brief_block": build_video_brief_block(user_brief, platform),
        # V4.82：证据契约与可用事实显式进 prompt；不再只靠「不要编造」这句口头约束
        "evidence_contract": video_evidence_context(analysis),
        # V4.105 / 方案C：创作意图对分镜同样生效（禁止项优先级最高）
        "creative_intent": cw_intent.from_analysis(analysis),
        "creative_intent_block": cw_intent.prompt_block(cw_intent.from_analysis(analysis)),
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
        # V4.82 / N01 + A06 + A07：兜底模板不得自带评分、用户数与"三步完成"这类
        # 页面未确认的数字承诺。旧模板里的虚构评分 / 用户数正是验收文档点名的样本。
        facts = [str(x).strip()[:40] for x in (a.get("facts") or a.get("advantages")
                                               or a.get("sellingPoints") or [])
                 if str(x or "").strip()][:2]
        support = facts[0] if facts else "页面已明示的核心价值"
        plan = {
            "mode": "text_to_video",
            "duration_sec": 15,
            "aspect": "9:16",
            "voiceover": (req.options or {}).get("voiceover", "none"),
            "hook": f"看清{product}在这一步的不同",
            "cta": "了解它如何做到",
            "shots": [
                {"idx": 1, "t": "0-3s", "shot": "text_to_video", "visual": f"{product} 使用场景中的自然动作特写", "text": "真实使用场景", "vo": "看看实际效果", "camera": "手持跟随推近", "motion": "主体入画"},
                {"idx": 2, "t": "3-8s", "shot": "text_to_video", "visual": f"{product} 核心功能连续演示，动作自然衔接", "text": support, "vo": "看看它如何完成这个任务", "camera": "俯拍＋特写", "motion": "功能演示循环"},
                {"idx": 3, "t": "8-12s", "shot": "text_to_video", "visual": "页面已确认的价值点以简洁画面呈现，不出现评分或数量角标", "text": support, "vo": "信息来自产品页面", "camera": "定格推近", "motion": "信息画面淡入"},
                {"idx": 4, "t": "12-15s", "shot": "text_to_video", "visual": f"{product} Logo ＋ 收口画面（仅使用已确认的品牌标识）", "text": "了解更多", "vo": "了解更多", "camera": "拉远收尾", "motion": "品牌定格"},
            ],
            "deliverables": ["15s 主片", "6s 剪辑版", "首帧封面图"],
            "note": "通用模板（草案）：未配置 / 未返回视频分镜，已移除所有未经页面确认的数字承诺；在对话框继续微调。",
        }
        if not reply:
            reply = "已基于产品分析生成一份默认 15 秒四镜分镜；告诉我你想强调的卖点或平台打法，我帮你微调。"

    # V4.101：把用户确认的框架 / brief 回填进 plan，供结果展示与出片提示词消费
    if not plan.get("framework") and fw_key:
        plan["framework"] = fw["key"]
        plan["framework_label"] = fw["label"]
    if user_brief:
        plan["creative_brief"] = user_brief
    # 把平台 / 选项 / 参考图回填进 plan，便于前端展示与生成复用
    plan["platform"] = platform
    plan["options"] = req.options or {}
    plan["reference_image"] = req.reference_image or ""
    # V4.82：分镜必须过证据 / 限定审计。先做一次保守修复，修不掉的明确标 generation_blocked
    a0 = (analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else analysis) or {}
    plan, claim_audit, repaired = repair_video_plan(
        plan, analysis, str(a0.get("product") or analysis.get("title") or ""))
    # V4.93：品牌 / 文案黄金词典——品牌名 / 产品名 / CTA 唯一事实源，只取已确认来源。
    lexicon = build_lexicon(analysis, plan)
    # V4.90 + V4.93：文本形态预检；批准清单收紧为黄金词典，facts 整句不再自动上屏。
    plan, text_guard, text_repaired = repair_video_text(plan, analysis, req.options or {}, lexicon)
    plan["brand_lexicon"] = lexicon
    # V4.94 阶段二：播放层叠加配置——品牌字样由 DOM 渲染，不交给视频模型画字。
    plan["text_overlay"] = build_text_overlay(lexicon, plan, req.options)
    if text_repaired:
        # 文字修复可能改动字幕 / VO 的数字与限定，证据审计必须基于修复后的 plan 重跑。
        claim_audit = audit_video_plan(plan, analysis)
        plan["claim_audit"] = claim_audit
        if claim_audit["status"] == "needs_revision":
            plan["generation_blocked"] = True
    gate = video_asset_gate(plan, req.reference_image)
    plan["asset_gate"] = gate
    plan["delivery_grade"] = gate["delivery_grade"]
    if repaired:
        extra = f"已移除 {repaired} 处页面原文不支持的数字 / 承诺。"
        reply = (reply + extra if reply else extra)[:240]
    if text_repaired:
        extra = f"已修正 {text_repaired} 处文字截断 / 乱码 / 可读性问题。"
        reply = (reply + extra if reply else extra)[:240]
    if text_guard["status"] == "needs_revision":
        extra = f"文字审查未通过：{text_guard['blocking_count']} 处需修正后才可出片。"
        reply = (reply + extra if reply else extra)[:240]
    if gate["status"] == "asset_missing":
        reply = (reply + " 图生视频缺少参考图，请补充后出片。" if reply
                 else "图生视频缺少参考图，请补充后出片。")[:240]
    # 实际输出比例：当前视频模型固定比例时显式标注（如阿里云百炼 MaaS → 9:16）
    vcfg = _active_config(db, "video")
    vparams = (vcfg.params if (vcfg and isinstance(getattr(vcfg, "params", None), dict)) else {}) or {}
    vforced = (vparams.get("output_aspect") or "").strip()
    if not vforced and (vparams.get("body_shape") or "").strip() == "dashscope_maas":
        vforced = "9:16"
    plan_output_aspect = vforced or plan.get("aspect") or (req.options or {}).get("aspect") or "9:16"

    # V4.78：分镜文案（文本模型）与出片（视频模型）分开回传。
    # 此前两者共用 model_info —— 分镜规划用的是 analysis 文本模型（如 deepseek），
    # 视频面板据此把「视频模型」显示成了 deepseek，与实际出片模型根本不是一回事。
    video_info = ModelInfo(
        provider=("kling" if (getattr(vcfg, "provider", "") or "") == "keling" else "model"),
        model=(vcfg.model or ""), role="video", fallback=False,
        config_id=vcfg.id, source="llm",
    ) if vcfg else ModelInfo(provider="storyboard", model="", role="video",
                             fallback=True, source="local")
    return CWVideoPlanResult(
        reply=reply, plan=plan, output_aspect=plan_output_aspect,
        model_info=_mini_model_info(info), video_model_info=video_info,
        video_model_ready=bool(vcfg), source=info.get("source", "local"),
        claim_status=claim_audit["status"],
        text_guard_status=text_guard["status"],
        generation_blocked=bool(plan.get("generation_blocked")),
        delivery_grade=gate["delivery_grade"])


@router.get("/cw-video/diagnose")
def api_cw_video_diagnose(db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*CAN_EDIT))):
    """视频生成链路自检（V4.75 / V4.78 增强）：不发起真实出片，只报告「会命中哪条配置、谁被跳过、为什么」。

    用户常见困惑是「已经在设置里加过视频大模型，却生成不出视频」，或「配置的是千问视频模型，
    实际却显示调用了 deepseek」。原因通常有三类：
    1. 没有 video 用途、配置被停用、缺 Key/链接/模型 → 回退分镜；
    2. 同用途下有多条，选中了 id 更大 / 测试通过的另一条；
    3. **用途含 video 的其实是文本模型**（deepseek-chat 等误勾「视频模型」）→ V4.78 起会被自动
       剔除，但必须在页面上说清楚，否则用户只会看到「视频模型变成了 deepseek」。
    本接口把实际选中的配置、候选清单与被跳过原因一次性摊开。
    """
    from urllib.parse import urlparse

    rep = video_route_report(db)
    cfg = rep["picked"]
    tagged, skipped = rep["tagged"], rep["skipped"]
    hints: list[str] = []

    def brief(c) -> dict:
        return {"id": c.id, "name": c.name or "", "provider": c.provider or "",
                "model": c.model or "", "is_active": bool(c.is_active),
                "last_test_ok": c.last_test_ok,
                "usages": [str(x) for x in ((c.usages if isinstance(c.usages, list) else [c.usage]) or [])]}

    out: dict = {
        "configured": False,
        # V4.79：四态 + 唯一动作。界面不再让用户在一堆提示里自己找结论。
        "state": "no_config",
        "state_label": "未配置视频模型",
        "action": "",
        "has_video_config": bool(tagged),
        "video_config_count": len(tagged),
        "config_id": None,
        "provider": "",
        "model": "",
        "host": "",
        "usages": [],
        "is_active": None,
        "last_test_ok": None,
        "last_test_error": "",
        "params": {},
        "missing": [],
        "candidates": [brief(c) for c in sorted(rep["candidates"], key=lambda c: -c.id)],
        "skipped": [{"id": s["cfg"].id, "name": s["cfg"].name or "", "provider": s["cfg"].provider or "",
                     "model": s["cfg"].model or "", "reason": s["reason"]} for s in skipped],
        "hints": hints,
    }

    if not tagged:
        out.update(state="no_config", state_label="未配置视频模型",
                   action="到「系统设置 → 大模型配置」新增一条文生视频模型（如「文生视频 · 阿里云百炼 MaaS」），用途勾「视频」。")
        hints.append("还没有任何「用途包含视频」的模型配置：到「系统设置 → 大模型配置」新增，"
                     "选「文生视频」类协议（如文生视频 · 阿里云百炼 MaaS），用途勾选「视频」。")
        return out
    if cfg is None:
        text_like = [s for s in skipped if not is_video_capable(s["cfg"])]
        if text_like and len(text_like) == len(skipped):
            out.update(state="text_model", state_label="配的其实是文本模型",
                       action="到「大模型配置」新增一条文生视频模型（用途选「视频」）；那条文本模型的「视频」用途可以取消。")
            hints.append("标了「视频」用途的配置全是文本模型（不能出片）：")
        else:
            out.update(state="disabled", state_label="视频配置未启用或缺要素",
                       action="到「大模型配置」确认该视频配置已启用，且 API Key / 请求链接 / 模型版本三项齐全。")
            hints.append("有视频配置，但没有一条同时满足「已启用 + Key/链接/模型齐全 + 用途含 video」：")
        hints.append("有配置标了「视频」用途，但没有一条是可出片的视频模型，因此生成时会回退分镜脚本。"
                     "常见原因：该配置其实是文本模型（见下方「已跳过」），或未启用、缺 API Key / 请求链接 / 模型版本。")
        return out

    params = cfg.params if isinstance(cfg.params, dict) else {}
    body_shape = str(params.get("body_shape") or "").strip()
    endpoint = str(params.get("endpoint") or "").strip()
    async_header = str(params.get("async_header") or "").strip().lower() in ("true", "1", "yes")
    poll_path = str(params.get("poll_path") or "").strip()
    missing: list[str] = []
    if body_shape == "dashscope_maas":
        if not endpoint:
            missing.append("endpoint")
        if not async_header:
            missing.append("async_header=true")
        if not poll_path:
            missing.append("poll_path")
    elif not endpoint:
        # 通用视频网关默认 /video/generations，不算缺失
        pass
    out.update({
        "configured": True,
        "config_id": cfg.id,
        "provider": cfg.provider or "",
        "model": cfg.model or "",
        "host": (urlparse(cfg.base_url or "").netloc or cfg.base_url or ""),
        "usages": [str(x) for x in ((cfg.usages if isinstance(cfg.usages, list) else [cfg.usage]) or [])],
        "is_active": bool(cfg.is_active),
        "last_test_ok": cfg.last_test_ok,
        "last_test_error": (cfg.last_test_error or "")[:400],
        "params": {k: str(v) for k, v in params.items()},
        "missing": missing,
    })
    # V4.79 四态收敛：契约缺参 / 连通失败 / 就绪——每种只给一个动作
    if missing:
        out.update(state="contract_missing", state_label="协议参数不齐（会把请求打到错误端点）",
                   action="到「大模型配置」删除该条后重新选择同一协议（自动装配默认参数），或按下方缺失项补齐高级参数。")
    elif cfg.last_test_ok is False:
        out.update(state="connect_failed", state_label="最近一次连通测试失败",
                   action="到「大模型配置」更新 API Key，并确认部署机公网 IP 已加入厂商白名单后重新测试。")
    else:
        out.update(state="ready", state_label="视频模型已就绪",
                   action="可直接生成；若仍无成片，展开生成结果里的「证据」看厂商原文。")
    # V4.78：把「被跳过的文本配置」显式讲出来，避免用户误以为系统在用 deepseek 出片
    if skipped:
        names = "、".join(f"「{s['cfg'].name or s['cfg'].model or ('#' + str(s['cfg'].id))}」" for s in skipped[:4])
        hints.append(f"{names} 的用途里勾了「视频」，但它们是文本模型，V4.78 起已自动跳过、不会再被用于出片。"
                     "如不再需要，可在「大模型配置」中取消其「视频」用途，避免混淆。")
    if len(rep["candidates"]) > 1:
        others = "、".join(f"#{c.id} {c.name or c.model}" for c in sorted(rep["candidates"], key=lambda c: -c.id) if c.id != cfg.id)
        hints.append(f"当前有多条可用视频配置，系统按「连通测试通过优先 → id 更大优先」选中 #{cfg.id}；"
                     f"未选中的有：{others}。如选错了，请停用不需要的那条。")
    if missing:
        hints.append("该协议缺少契约参数：" + "、".join(missing) +
                     "。请在配置编辑弹窗的「高级参数」中补齐，或删除后重新选择该协议（会自动装配默认参数）。")
    if cfg.last_test_ok is False:
        hints.append("最近一次连通测试未通过，通常是 Key 无效或部署机公网 IP 未加入厂商白名单；"
                     "原文见下方 last_test_error。")
    if not hints:
        hints.append(f"配置齐全，出片将使用 #{cfg.id}「{cfg.name or cfg.model}」（{cfg.model}），可直接生成；"
                     "若仍无成片，请查看生成结果里的失败原文（HTTP 状态 + 服务端返回）。")
    return out


# ---------------------- V4.81 出片任务持久化（P2）：提交即返回，worker 驱动 ----------------------
# V4.76 曾把任务放在进程内字典 `_CW_VIDEO_JOBS` 里：刷新页面靠前端 sessionStorage 续命，服务
# 重启全丢，多进程部署还会「查到另一个进程 404」。现在唯一事实在数据库（creative_tasks），
# 这里只负责把持久化任务映射成前端已用的响应结构，不再保留第二份内存状态。
CW_VIDEO_EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "video_evidence")


def _cw_video_filename(user_id) -> str:
    """出片落盘文件名：用户 + 秒级时间 + 随机短 UUID（同秒并发/重试不会互相覆盖）。"""
    return f"cw_video_{int(user_id or 0)}_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"


def _persist_video_evidence(user_id: int, payload: dict) -> str:
    """把脱敏证据落盘（V4.79 / P0）：用户报障时可据此核对「到底返回了什么」，不必重现。

    只写已脱敏的摘要（providers._video_evidence_snippet 已抹掉 Key / Token），
    不写完整响应体，避免把厂商返回里的敏感字段留在磁盘上。
    """
    os.makedirs(CW_VIDEO_EVIDENCE_DIR, exist_ok=True)
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_u{int(user_id or 0)}_{uuid.uuid4().hex[:6]}.json"
    path = os.path.join(CW_VIDEO_EVIDENCE_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}, f, ensure_ascii=False, indent=2)
    return name


def _cw_video_result_of(job) -> CWVideoGenerateResult:
    """把持久化任务还原成前端已用的结果结构（videos / storyboard / 错误字段 / 证据）。"""
    snap = job.request_json or {}
    res = job.result_json or {}
    plan = dict(snap.get("plan") or {})
    aspect = str(snap.get("aspect") or plan.get("aspect") or "")
    storyboard = dict(plan)
    storyboard.setdefault("platform", snap.get("platform") or "")
    storyboard.setdefault("options", snap.get("options") or {})
    storyboard.setdefault("shots", [])
    storyboard.setdefault("duration_sec", snap.get("duration") or 15)
    storyboard["duration_sec_actual"] = res.get("duration_sec") or 0
    if aspect:
        storyboard["aspect"] = aspect
        storyboard["output_aspect"] = aspect
    videos = [
        CWVideoAsset(type="video", url=a.get("url") or "",
                     caption=a.get("caption") or snap.get("product") or "",
                     duration_sec=a.get("duration_sec") or 0,
                     duration_source=a.get("duration_source") or "")
        for a in (res.get("assets") or []) if isinstance(a, dict) and a.get("url")
    ]
    ev = dict(job.evidence_json or {})
    if job.error_code and ev:
        try:
            ev["log_file"] = _persist_video_evidence(job.owner_id or 0, ev)
        except Exception:
            pass
    provider = "kling" if (job.provider_model and "kling" in (job.provider_model or "").lower()) else "model"
    return CWVideoGenerateResult(
        provider=provider if res.get("assets") else "storyboard",
        model=job.provider_model or "",
        videos=videos, storyboard=storyboard,
        model_info=ModelInfo(provider=provider if job.provider_model else "storyboard",
                             model=job.provider_model or "", role="video",
                             fallback=not job.provider_model,
                             config_id=job.provider_config_id, source="llm" if job.provider_model else "local"),
        note=res.get("note") or (job.error_message or ""),
        output_aspect=aspect, source="llm" if job.provider_model else "local",
        stage=job.error_stage or job.stage or "",
        error_code=job.error_code or "",
        error_message=job.error_message or "",
        error_action=job.error_action or "",
        error_task_id=job.provider_task_id or "",
        evidence=ev,
        requested_duration=res.get("requested_duration") or 0,
        measured_duration=res.get("measured_duration") or res.get("duration_sec") or 0,
        delivery_status=res.get("delivery_status") or "",
    )


_CW_JOB_STATUS = {"succeeded": "done", "failed": "needs_attention",
                  "needs_attention": "needs_attention", "canceled": "needs_attention",
                  "queued": "queued", "running": "running"}


def _cw_video_job_out(job) -> CWVideoJobOut:
    """持久化任务 → 兼容响应。status 沿用前端已有的 done / needs_attention 语义。"""
    status = _CW_JOB_STATUS.get(job.status or "queued", "running")
    started = job.created_at
    end = job.finished_at or job.updated_at or started
    elapsed = int(max(0.0, (end - started).total_seconds())) if (started and end) else 0
    # V4.83 / C04：终态阶段标签以 status / 错误码为准，不能出现「done 但下载校验中」。
    if job.status == "succeeded":
        stage_label = "已完成"
    elif job.error_code == "DURATION_MISMATCH":
        stage_label = "时长未达标"
    elif job.error_code == "TEXT_VISION_MISMATCH":
        stage_label = "画面文字未通过"
    elif job.status in ("needs_attention", "failed", "canceled"):
        stage_label = {"needs_attention": "待核实", "failed": "失败",
                       "canceled": "已停止"}.get(job.status, job.status)
    else:
        stage_label = CREATIVE_STAGE_LABEL.get(job.stage or "") or job.stage or ""
    return CWVideoJobOut(
        job_id=job.job_id, status=status,
        stage=stage_label,
        elapsed_sec=elapsed,
        error=(job.error_message or "")[:400],
        error_code=job.error_code or "",
        error_action=job.error_action or "",
        batch_id=job.batch_id or "",
        result=_cw_video_result_of(job),
    )


def _cw_owned_job(db: Session, job_id: str, user) -> GenerationJob:
    job = db.query(GenerationJob).filter_by(job_id=job_id, kind="video").first()
    # 归属校验：用 404 而不是 403，避免泄露「该任务存在」
    if not job or (user is not None and job.owner_id
                   and getattr(user, "id", None) != job.owner_id):
        raise HTTPException(404, "视频任务不存在或已过期，请重新生成")
    return job


@router.post("/cw-video/generate-jobs", response_model=CWVideoJobOut)
async def api_cw_video_create_job(req: CWVideoGenerateRequest, db: Session = Depends(get_db),
                                  user: User = Depends(require_roles(*CAN_EDIT)),
                                  idempotency_key: str = Header(default="", alias="Idempotency-Key"),
                                  draft_id: str = Header(default="", alias="X-Draft-Id"),
                                  batch_id: str = Header(default="", alias="X-Batch-Id")):
    """提交视频出片任务并立即返回 job_id（V4.81 起落库，进程重启不丢）。

    出片要等模型 1–6 分钟。若让 HTTP 请求一直挂着，反向代理会先超时——宿主 nginx 默认
    proxy_read_timeout 60s、Cloudflare 100s——前端只会看到 504，而任务其实还在厂商侧跑。
    现在提交只做「落库 + 返回 ID」，出片由后台 worker 分阶段推进；同一幂等键重复提交
    不会产生第二次收费任务。
    """
    built = _cw_video_request_build(req, db)
    # V4.103 / 方案A：真实抓取分析无可用证据时先硬阻断（claim_audit 对空快照返回
    # legacy_unverified 不触发 needs_revision，需这道门补齐）。此时无供应商任务号、无费用。
    _enforce_evidence_gate(built.get("analysis") or {})
    # V4.82：无证据 / 丢限定的承诺在入队前拦截。此时还没有供应商任务号，也没有费用。
    if built["claim_audit"]["status"] == "needs_revision":
        bad = "；".join(str(v.get("reason") or v.get("field") or "")[:80]
                       for v in (built["claim_audit"].get("violations") or [])[:3])
        raise HTTPException(422, "分镜文案未通过证据校验，未提交出片：" + bad)
    # V4.90：文字形态 / 批准文案未通过时不产生厂商费用，直接拦截。
    if built["text_guard"]["status"] == "needs_revision":
        bad = "；".join(str(v.get("reason") or v.get("field") or "")[:80]
                       for v in (built["text_guard"].get("violations") or [])[:3])
        raise HTTPException(422, "视频文字未通过预检，未提交出片：" + bad)
    if built["asset_gate"]["status"] == "asset_missing":
        raise HTTPException(422, built["asset_gate"]["note"])
    payload = {
        "product": built["product"], "platform": built["platform"],
        "prompt": built["prompt"], "meta": built["meta"], "plan": built["plan"],
        "analysis": built["analysis"], "options": built["options"],
        "aspect": built["output_aspect"], "duration": built["duration"],
        "reference_image": req.reference_image or "",
        "source_url": str((built["analysis"] or {}).get("url") or ""),
    }
    try:
        batch, job, _created = create_video_batch(db, user, payload,
                                                 idempotency_key=idempotency_key,
                                                 draft_id=draft_id, batch_id=batch_id)
    except IdempotencyConflict as e:
        raise HTTPException(409, str(e))
    if built["has_video_cfg"] and job.status in ("queued", "running"):
        # 提交后立即催一次，别等 worker 的下一拍（用户点了生成就该马上看到「提交中」）
        job.next_poll_at = utcnow()
        job.updated_at = utcnow()
        db.commit()
    return _cw_video_job_out(job)


@router.get("/cw-video/generate-jobs/{job_id}", response_model=CWVideoJobOut)
def api_cw_video_get_job(job_id: str, db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*CAN_EDIT))):
    """轮询出片任务：done 时 result 与同步接口结构一致；needs_attention 时带失败分类与动作。"""
    return _cw_video_job_out(_cw_owned_job(db, job_id, user))


# ---------------------- V4.81 / P3：创作任务列表（批次 + 子任务） ----------------------
@router.post("/creative-tasks")
def api_creative_task_create(body: dict, db: Session = Depends(get_db),
                             user: User = Depends(require_roles(*CAN_EDIT))):
    """先建批次头：图片与视频都要排队时，各子任务挂到同一批次上（A10 混合任务）。"""
    return creative_tasks.create_batch(db, user, body or {})


@router.get("/creative-tasks")
def api_creative_tasks(db: Session = Depends(get_db), user: User = Depends(require_roles(*CAN_EDIT)),
                       status: str = "", cursor: str = "", limit: int = 20):
    """本人创作批次列表。status = active（进行中）/ done（已完成）/ needs（需处理）"""
    return creative_tasks.list_batches(db, user, status=status, cursor=cursor, limit=limit)


@router.get("/creative-tasks/{batch_id}")
def api_creative_task_detail(batch_id: str, db: Session = Depends(get_db),
                             user: User = Depends(require_roles(*CAN_EDIT))):
    try:
        return creative_tasks.get_batch(db, user, batch_id)
    except LookupError:
        raise HTTPException(404, "创作任务不存在")


@router.post("/creative-tasks/{batch_id}/retry")
def api_creative_task_retry(batch_id: str, body: dict, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*CAN_EDIT))):
    """分项重试：action = repoll（继续查询原任务）/ redownload（只重下）/ regenerate（重新生成）。"""
    action = str((body or {}).get("action") or "").strip()
    job_id = str((body or {}).get("job_id") or "").strip()
    try:
        out = creative_tasks.retry(db, user, batch_id, job_id, action)
    except LookupError:
        raise HTTPException(404, "创作任务不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return out


@router.post("/creative-tasks/{batch_id}/cancel")
def api_creative_task_cancel(batch_id: str, body: dict | None = None, db: Session = Depends(get_db),
                             user: User = Depends(require_roles(*CAN_EDIT))):
    """停止后续步骤（不做供应商取消：厂商无取消接口时，在途任务仍可能完成并计费）。

    V4.115：body.reason="user"（默认）标记 MANUAL_STOP，方便今后按「手动停止」查询。
    """
    job_id = str((body or {}).get("job_id") or "").strip()
    reason = str((body or {}).get("reason") or "user").strip()
    try:
        return creative_tasks.cancel(db, user, batch_id, job_id, reason=reason)
    except LookupError:
        raise HTTPException(404, "创作任务不存在")


@router.post("/cw-video/generate", response_model=CWVideoGenerateResult)
async def api_cw_video_generate(req: CWVideoGenerateRequest, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(*CAN_EDIT))):
    """同步出片（保留兼容，直连脚本/调试用）。

    ⚠️ 该接口自身耗时 1–6 分钟，调用方必须保证反向代理读超时足够（nginx ≥ 660s），
    否则会被拦成 504。页面已统一改用 /cw-video/generate-jobs 异步模式。
    """
    return await _cw_video_generate_impl(req, db, user)


def _cw_video_request_build(req: CWVideoGenerateRequest, db: Session) -> dict:
    """出片请求构建（同步接口 / 后台任务共用）：提示词、元数据、实际比例、配置判定。

    抽出来是为了让「手动出片」与「后台任务出片」用**同一份**提示词与比例推导：两边各写
    一遍迟早漂移，用户会发现同一个分镜在两条链路里出的片子不一样。
    """
    plan = req.plan or {}
    analysis = req.analysis or {}
    platform = (req.platform or "").strip()
    options = req.options or {}
    a = (analysis.get("analysis") if isinstance(analysis.get("analysis"), dict) else analysis) or {}
    product = a.get("product") or analysis.get("title") or "Product"
    brief = analysis.get("brief") or {}
    # V4.93：出片前重建黄金词典（以提交时的 plan/analysis 为准，不信任前端缓存）。
    lexicon = build_lexicon(analysis, plan, brief)
    # V4.90 + V4.93：出片前同样跑文字预检，批准清单收紧为黄金词典；
    # 避免前端绕过规划接口直接提交带问题文字 / 未批准品牌字样的 plan。
    plan, text_guard, text_repaired = repair_video_text(plan, analysis, options, lexicon)

    # 解析当前视频配置，确定「实际输出比例」并显式标注：
    # 部分厂商（阿里云百炼 MaaS / wan3.0-video 等）忽略 size、固定输出某一比例；
    # 通过模型配置参数 output_aspect 显式声明，缺省时 dashscope_maas 默认 9:16 竖屏。
    cfg = _active_config(db, "video")
    requested_aspect = str(plan.get("aspect") or options.get("aspect") or "9:16")
    cfg_params = (cfg.params if (cfg and isinstance(getattr(cfg, "params", None), dict)) else {}) or {}
    forced = (cfg_params.get("output_aspect") or "").strip()
    if not forced and (cfg_params.get("body_shape") or "").strip() == "dashscope_maas":
        forced = "9:16"
    output_aspect = forced or requested_aspect

    # 从分镜方案构造一段可供文生/图生视频模型消费的提示词。
    # V4.88：无字策略下不把 shot.text 送进模型（只保留在分镜 JSON 供节奏 / VO 策划）。
    # V4.101：过去只送 t/visual/vo，导致规划出的 hook/cta/camera/motion 全部丢失；
    # 这里把运镜与转场作为「导演指令」送达供应商，hook/cta 只作为动作意图，不画字。
    shots = plan.get("shots") or []
    seg_lines = []
    for s in shots:
        seg = f"[{s.get('t') or ''}] {s.get('visual') or ''}"
        if s.get("camera"): seg += f"（运镜：{s['camera']}）"
        if s.get("motion"): seg += f"（动作/转场：{s['motion']}）"
        if s.get("vo"): seg += f"（旁白：{s['vo']}）"
        seg_lines.append(seg)
    duration = int(plan.get("duration_sec") or options.get("duration") or 15)

    # V4.94 阶段三：视觉复核开关随任务冻结；默认开启，options.vision_audit=false 可关闭。
    _va = options.get("vision_audit")
    vision_audit_cfg = (
        {"enabled": bool(_va.get("enabled", True)), "frames": int(_va.get("frames") or 3)}
        if isinstance(_va, dict) else {"enabled": _va is not False, "frames": 3}
    )

    # V4.84：从标准库解析本平台的视频规格目标（比例/尺寸/时长区间/伴随素材/核验状态）。
    # 生成前冻结进请求，交付时 creative_tasks 用同一份 spec 复核，两处结论始终一致。
    spec_ref = spec_video_target(platform, output_aspect, duration,
                                 ad_product=str(options.get("ad_product") or ""))
    # V4.88：把同一份规格快照编译成文档要求的结构化提示词契约，随 meta 落库可追溯。
    placement_spec = {
        "platform": platform,
        "ad_product": options.get("ad_product") or spec_ref.get("ad_product"),
        "target_aspect": output_aspect,
        "target_size": spec_ref.get("target_size"),
        "duration": duration,
        "spec_version": spec_ref.get("library_version"),
        "verification": spec_ref.get("verification"),
        "source_url": spec_ref.get("source_url"),
    }
    prompt_contract = build_prompt_contract(
        media_type="video", analysis=analysis, brief=brief,
        profile_key=str(a.get("industry_profile") or ""), plan=plan,
        placement=placement_spec,
        text_policy=str(text_guard.get("text_policy") or "none"),
        approved_texts=list(text_guard.get("approved_texts") or []))
    prompt_parts: list[str] = []
    if spec_ref.get("duration_ok") is False:
        # 官方已核验的规则里，所选时长越界：不静默放行，写入提示交结果区/诊断展示
        prompt_parts.append(f"规格提示：{spec_ref['duration_reason']}")
    prompt_parts.append(f"产品：{product}")
    if brief.get("promotionGoal"): prompt_parts.append(f"推广目标：{brief.get('promotionGoal')}")
    if brief.get("sellingPoints"): prompt_parts.append("核心卖点：" + "、".join(brief["sellingPoints"][:3]))
    prompt_parts.append(f"时长：{duration} 秒；比例：{output_aspect}")
    # V4.101：框架 / 钩子 / 收口作为导演指令进入出片提示词；措辞明确「不画字」，
    # 与零文字契约及三道防线保持一致。
    if plan.get("framework_label") or plan.get("framework"):
        beat = plan.get("frames") or {}
        beat_text = "；".join(f"{k}={v}" for k, v in beat.items() if v) if isinstance(beat, dict) else ""
        prompt_parts.append("创意框架：%s%s" % (
            plan.get("framework_label") or plan.get("framework"),
            "；五段节奏：" + beat_text if beat_text else ""))
    if plan.get("hook"):
        prompt_parts.append("开场钩子意图（用动作/反差表达，不作为上屏文字）：" + str(plan["hook"]))
    if plan.get("cta"):
        prompt_parts.append("收口动作意图（仅作为动作/叠加位，不绘制文字）：" + str(plan["cta"]))
    if plan.get("sound_design"):
        prompt_parts.append("节奏与音频建议：" + str(plan["sound_design"]))
    brief_block = build_video_brief_block(plan.get("creative_brief"), platform)
    if brief_block:
        prompt_parts.append(brief_block)
    if seg_lines: prompt_parts.append("分镜：" + "；".join(seg_lines))
    # V4.82：出片提示词带同一份证据契约 —— 分镜阶段被删掉的数字不会在生成阶段被"补充要求"找回来
    prompt_parts.append(video_evidence_context(analysis))
    claim_audit = audit_video_plan(plan, analysis)
    asset_gate = video_asset_gate(plan, req.reference_image)
    if options.get("prompt_hint"): prompt_parts.append("补充要求：" + str(options["prompt_hint"]))
    prompt_parts.append(render_video_contract_block(prompt_contract))
    # V4.93：黄金词典块——明确禁止模型绘制品牌名 / 英文单词，从源头杜绝错拼。
    prompt_parts.append(render_lexicon_block(lexicon))
    prompt_parts.append(render_video_text_guard_block(text_guard))
    prompt = "\n".join(prompt_parts)

    meta = {
        "product": product,
        "headline": plan.get("hook") or product,
        "cta": plan.get("cta") or "立即下载",
        "framework": plan.get("framework") or "",
        "creative_brief_hash": str((plan.get("creative_brief") or {}).get("brief_hash") or "")
        if isinstance(plan.get("creative_brief"), dict) else "",
        "spec": "1080x1920" if output_aspect == "9:16" else ("1080x1080" if output_aspect == "1:1" else "1920x1080"),
        "lang": str(options.get("lang") or "en"),
        "duration": duration,
        "aspect": output_aspect,
        # V4.84：把标准库冻结引用写入 meta，随任务落库、交付复核共用同一份
        "spec_ref": spec_ref,
        # V4.88：提示词契约快照随任务落库，便于追溯每次出片实际使用的无字约束。
        "prompt_contract_id": prompt_contract["prompt_id"],
        "prompt_contract": prompt_contract,
        # V4.90：文字审查快照随任务落库，批准清单 / 修正记录 / 未通过原因均可追溯。
        "text_guard": text_guard,
        "text_policy": text_guard.get("text_policy") or "none",
        "text_repair_count": text_repaired,
        # V4.93：黄金词典快照——本次出片使用的品牌名 / 产品名 / CTA 唯一事实源。
        "brand_lexicon": lexicon,
        # V4.94 阶段二：播放层叠加配置随任务冻结，交付结果据此在播放器上叠加品牌字样。
        "text_overlay": build_text_overlay(lexicon, plan, options),
        # V4.94 阶段三：成片视觉复核配置；真实模型不可用时如实标 unavailable。
        "vision_audit": vision_audit_cfg,
    }
    # 图生视频：把参考图作为 image 带入（Kling / 通用模型据端点决定是否消费）
    if str(plan.get("mode") or options.get("mode") or "") == "image_to_video" and req.reference_image:
        meta["image"] = req.reference_image
        meta["mode"] = "image_to_video"

    # V4.78：出片未命中视频模型时，明确区分「压根没配」与「配了但配错成文本模型」，
    # 否则用户只会看到「调用了 deepseek」，却不知道文本模型根本不参与出片。
    skip_note = ""
    if not (cfg and cfg.api_key and cfg.base_url and cfg.model):
        try:
            rep = video_route_report(db)
            skipped = rep.get("skipped") or []
            if skipped:
                names = "、".join(f"「{s['cfg'].name or s['cfg'].model or ('#' + str(s['cfg'].id))}」"
                                  for s in skipped[:3])
                skip_note = (f"{names} 的用途被勾成了「视频」，但它们是文本模型，无法出片，已自动跳过；"
                             "请在「大模型配置」中新增一条文生视频模型（用途选「视频」）。")
            elif rep.get("tagged"):
                skip_note = ("存在标为「视频」用途的配置，但未启用或缺 API Key / 请求链接 / 模型版本，"
                             "因此暂时只能出分镜脚本。")
        except Exception:
            pass

    return {
        "plan": plan, "analysis": analysis, "platform": platform, "options": options,
        "product": product, "brief": brief, "cfg": cfg, "output_aspect": output_aspect,
        "requested_aspect": requested_aspect, "duration": duration, "prompt": prompt,
        "meta": meta, "skip_note": skip_note, "forced": forced, "cfg_params": cfg_params,
        "claim_audit": claim_audit, "asset_gate": asset_gate, "spec_ref": spec_ref,
        "prompt_contract": prompt_contract,
        "text_guard": text_guard, "text_repaired": text_repaired,
        "has_video_cfg": bool(cfg and cfg.api_key and cfg.base_url and cfg.model),
    }


async def _cw_video_generate_impl(req: CWVideoGenerateRequest, db: Session, user) -> CWVideoGenerateResult:
    """出片主流程（同步接口与后台任务共用）：
    解析视频配置 → 组装可消费提示词 → 调模型（含厂商侧异步轮询取片）→ 归一化产物与比例标注。
    """
    built = _cw_video_request_build(req, db)
    plan, analysis = built["plan"], built["analysis"]
    platform, options = built["platform"], built["options"]
    product, brief = built["product"], built["brief"]
    cfg, output_aspect, requested_aspect = built["cfg"], built["output_aspect"], built["requested_aspect"]
    duration, prompt, meta = built["duration"], built["prompt"], built["meta"]
    skip_note, has_video_cfg = built["skip_note"], built["has_video_cfg"]
    forced, cfg_params = built["forced"], built["cfg_params"]
    claim_audit = built["claim_audit"]
    text_guard = built["text_guard"]
    asset_gate = built["asset_gate"]
    spec_ref = built["spec_ref"]
    provider = get_video(db) if has_video_cfg else StoryboardVideo()
    if has_video_cfg:
        m_info = ModelInfo(provider=("kling" if (cfg.provider or "") == "keling" else "model"),
                           model=cfg.model, role="video", fallback=False, config_id=cfg.id, source="llm")
    else:
        m_info = ModelInfo(provider="storyboard", model="", role="video", fallback=True, source="local")
    # V4.80 / P1：文件名加 UUID —— 同一秒内并发出片（批量生成、多次重试）不再互相覆盖。
    filename = _cw_video_filename(getattr(user, "id", 0) or 0)

    # V4.79 / P0：失败不再装成「完成」。provider 抛 VideoPipelineError 时保留可执行分镜作为兜底
    # 交付物，但同时把 error_code / 动作 / 脱敏证据一并回传，界面据此显示「卡在哪一步、该做什么」。
    # V4.82：分镜/补充要求里若仍有原文不支持的承诺，提交前就地拦截，绝不产生厂商费用
    err: Optional[VideoPipelineError] = None
    evidence: dict = {}
    if claim_audit["status"] == "needs_revision":
        ev = {"claim_audit": claim_audit}
        err = VideoPipelineError(
            "CLAIM_UNSUPPORTED",
            "分镜文案含 " + str(len(claim_audit.get("violations") or []))
            + " 处缺少原文证据或限定的表述：" + "；".join(
                str(v.get("reason") or v.get("field") or "")[:80]
                for v in (claim_audit.get("violations") or [])[:3]),
            stage="config", evidence=ev)
        evidence = ev
        res = await StoryboardVideo().generate(prompt, platform, filename, meta)
        res["note"] = ""
    # V4.90：文字预检未通过同样只保留分镜，不调用视频厂商。
    elif text_guard["status"] == "needs_revision":
        ev = {"text_guard": text_guard, "claim_audit": claim_audit}
        err = VideoPipelineError(
            "TEXT_GUARD_BLOCKED",
            "分镜文字含 " + str(text_guard.get("blocking_count", 0))
            + " 处截断 / 乱码 / 不可读 / 未批准文字：" + "；".join(
                str(v.get("reason") or v.get("field") or "")[:80]
                for v in (text_guard.get("violations") or [])[:3]),
            stage="config", evidence=ev)
        evidence = ev
        res = await StoryboardVideo().generate(prompt, platform, filename, meta)
        res["note"] = ""
    elif asset_gate["status"] == "asset_missing":
        ev = {"asset_gate": asset_gate}
        err = VideoPipelineError("ASSET_MISSING", asset_gate["note"],
                                 stage="config", evidence=ev)
        evidence = ev
        res = await StoryboardVideo().generate(prompt, platform, filename, meta)
        res["note"] = ""
    elif has_video_cfg:
        try:
            res = await provider.generate(prompt, platform, filename, meta)
        except VideoPipelineError as e:
            err, evidence = e, e.evidence
            res = await StoryboardVideo().generate(prompt, platform, filename, meta)
            res["note"] = ""
            # 徽标仍显示「本次尝试出片的模型」，只是标注 fallback，避免误以为没配置
            m_info = ModelInfo(provider=m_info.provider, model=cfg.model, role="video",
                               fallback=True, config_id=cfg.id, source="llm")
        except Exception as e:  # 兜底：未分类异常也不能静默
            err = VideoPipelineError("PROVIDER_ERROR", f"{type(e).__name__}: {e}", stage="generate")
            res = await StoryboardVideo().generate(prompt, platform, filename, meta)
            res["note"] = ""
            m_info = ModelInfo(provider=m_info.provider, model=cfg.model, role="video",
                               fallback=True, config_id=cfg.id, source="llm")
    else:
        res = await StoryboardVideo().generate(prompt, platform, filename, meta)

    # 无视频配置时的分镜标注（这不是失败，是能力未配置）
    if res.get("provider") == "storyboard" and err is None:
        m_info = ModelInfo(provider="storyboard", model="", role="video", fallback=True, source="local")

    # V4.80 / P1：交付时长用实测值（读 moov/mvhd 或 ffprobe），只有拿不到元数据时才退回计划时长，
    # 并如实标注来源，避免「计划 15s、实际 5s」被当成 15s 交付。
    measured_sec = 0.0
    try:
        measured_sec = float(res.get("duration_sec") or 0) or 0.0
    except (TypeError, ValueError):
        measured_sec = 0.0
    asset_sec = round(measured_sec, 2) if measured_sec > 0 else duration
    dur_source = ("measured" if measured_sec > 0 else "planned") if res.get("file_path") else ""

    videos: list = []
    note = res.get("note") or ""
    if err is not None:
        note = (f"出片失败（{err.error_code}）：{err.message}"
                + (f" 建议：{err.action}" if err.action else "")
                + " 已保留可执行分镜脚本，可照单制作或按建议修正后重试。")
    if res.get("file_path"):
        rel = os.path.basename(res["file_path"])
        videos.append(CWVideoAsset(type="video", url=f"/files/{rel}", caption=product,
                                   duration_sec=asset_sec, duration_source=dur_source))
    elif res.get("url") and err is None:
        # V4.79：err 不为空时绝不回传外链（外链可能是过期签名，落不了盘就是没出片）
        videos.append(CWVideoAsset(type="video", url=res["url"], caption=product,
                                   duration_sec=asset_sec, duration_source=dur_source))
    elif err is None:
        note = note or (skip_note or "未配置视频模型，已输出可执行分镜脚本（在设置页配置 video 用途的模型后可直连生成）。")

    # 实际输出比例：优先取 provider 回传，其次用本次推导的 output_aspect
    actual_aspect = res.get("output_aspect") or output_aspect
    # 当模型固定比例与用户所选比例不一致时，显式提示并统一标注为实际比例
    if forced and forced != requested_aspect:
        label = "竖屏" if actual_aspect == "9:16" else ("方版" if actual_aspect == "1:1" else "横版")
        forced_note = f"⚠️ 当前视频模型固定输出 {actual_aspect}（{label}），已按实际比例 {actual_aspect} 标注（与所选「{requested_aspect}」不一致）。"
        note = (note + " " + forced_note).strip() if note else forced_note

    # V4.83 / C05：交付时长门。同步链路与持久任务共用同一判定，不允许「这里警告、那里标成功」。
    verdict = _duration_verdict({"duration": duration},
                                {"duration_sec": measured_sec,
                                 "duration_source": res.get("duration_source") or ""})
    delivery_status = verdict["delivery_status"] if res.get("file_path") else ""
    note = (note + " " + verdict["note"]).strip() if (verdict["note"] and res.get("file_path")) else note
    if delivery_status and not verdict["ok"] and err is None:
        # 原片保留可下载，但交付结论改为未达标（needs_attention 语义），不计合格成片。
        err = VideoPipelineError(
            "DURATION_MISMATCH", verdict["note"], stage="validating",
            action="原片已保留可预览下载；如需达标成片请点「重新生成」（会产生新费用），"
                   "或确认视频模型支持所选时长后重试。")

    # V4.84：标准库规格复核——用同一份冻结的 spec_ref 与实测值对照。
    # 只有 A 级（官方已核验）规则越界才升级为硬失败；B/C 级仅提示，不冒充官方硬规则。
    spec_check = spec_validate_delivery(spec_ref, measured_sec, actual_aspect) if res.get("file_path") else {}
    if spec_check.get("status") == "hard_fail" and err is None:
        err = VideoPipelineError(
            "SPEC_MISMATCH", spec_check["note"], stage="validating",
            action="成片不符合该平台官方规格（已核验），原片保留可下载；请按规格调整时长/比例后重新生成。")
    if spec_check.get("note") and res.get("file_path"):
        note = (note + " " + spec_check["note"]).strip()

    # 始终回传分镜方案（展示 + 可下载 JSON），比例标注为实际输出比例
    storyboard = dict(plan)
    storyboard["platform"] = platform
    storyboard["options"] = options
    storyboard["reference_image"] = req.reference_image or ""
    storyboard.setdefault("duration_sec", duration)
    # 计划时长与实测时长分开记：分镜是计划，duration_sec_actual 是真实交付
    storyboard["duration_sec_actual"] = asset_sec if measured_sec > 0 else 0
    storyboard["aspect"] = actual_aspect
    storyboard["output_aspect"] = actual_aspect
    storyboard.setdefault("shots", [])
    storyboard["claim_audit"] = claim_audit
    storyboard["text_guard"] = text_guard
    storyboard["asset_gate"] = asset_gate
    # V4.79：证据落盘（best-effort，绝不因写日志失败影响出片结果）
    if evidence:
        try:
            evidence["log_file"] = _persist_video_evidence(getattr(user, "id", 0), evidence)
        except Exception:
            pass
    return CWVideoGenerateResult(
        provider=res.get("provider", "storyboard"),
        model=(cfg.model if (cfg and cfg.model) else ""),
        videos=videos, storyboard=storyboard,
        model_info=m_info, note=note, output_aspect=actual_aspect, source=m_info.source,
        stage=(err.stage if err else ""),
        error_code=(err.error_code if err else ""),
        error_message=(err.message if err else ""),
        error_action=(err.action if err else ""),
        error_task_id=(err.task_id if err else ""),
        evidence=evidence,
        requested_duration=verdict["requested"] if res.get("file_path") else 0,
        measured_duration=verdict["actual"] if res.get("file_path") else 0,
        delivery_status=delivery_status,
        spec_check=spec_check,
        spec_ref=spec_ref if res.get("file_path") else {},
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
    # V4.103 / 方案A：实际出图入口（前端走此路）统一证据硬门；
    # 分析取自 images_request.analysis（auto_creation 取持久 plan 的 analysis_json）。
    if not plan_id:
        _job_analysis = (body.get("images_request") or {}).get("analysis") or {}
        if _job_analysis:
            _enforce_evidence_gate(_job_analysis if isinstance(_job_analysis, dict) else {})
    try:
        job, created = job_service.create_job(
            db, body, user, idempotency_key=str(body.get("idempotency_key") or "").strip(),
            kind=kind, plan_id=plan_id, plan_version=plan_version,
            batch_id=str(body.get("batch_id") or "").strip())
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
                         user: User = Depends(require_roles(*CAN_EDIT))):
    # V4.102 / S01：通用任务接口按归属过滤；admin 可跨账号，其他角色只看自己。
    q = db.query(GenerationJob)
    if getattr(user, "role", "") != "admin":
        q = q.filter(GenerationJob.owner_id == getattr(user, "id", None))
    if history_id is not None:
        q = q.filter(GenerationJob.history_id == history_id)
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    rows = q.order_by(GenerationJob.id.desc()).offset(off).limit(lim).all()
    return {"items": [job_service.job_to_dict(r, include_result=False) for r in rows],
            "total": q.count(), "limit": lim, "offset": off}


@router.get("/generation-jobs/{job_id}")
def get_generation_job(job_id: str, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(*CAN_EDIT))):
    """刷新 / 关闭浏览器后按 job_id 恢复：状态、逐项结果与归档信息都在这里。"""
    return job_service.job_to_dict(_job_row(db, job_id, user), include_result=True)


def _job_row(db: Session, job_id: str, user: User | None = None) -> GenerationJob:
    """V4.102 / S01：详情 / 取消 / 重试统一带归属校验；admin 例外放行。

    普通用户只能读改自己的任务，返回 404 不泄露他人任务是否存在；
    user 为空时保持旧行为（仅供内部可信调用）。
    """
    row = db.query(GenerationJob).filter_by(job_id=job_id).first()
    if not row:
        raise HTTPException(404, "生成任务不存在")
    if (user is not None and getattr(user, "role", "") != "admin"
            and row.owner_id != getattr(user, "id", None)):
        raise HTTPException(404, "生成任务不存在")
    return row


@router.post("/generation-jobs/{job_id}/cancel")
def cancel_generation_job(job_id: str, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*CAN_EDIT))):
    return job_service.cancel_job(db, _job_row(db, job_id, user))


@router.post("/generation-jobs/{job_id}/retry", status_code=202)
async def retry_generation_job(job_id: str, db: Session = Depends(get_db),
                               user: User = Depends(require_roles(*CAN_EDIT))):
    """只重试失败子任务：成功项不重复调用模型、不重复归档。"""
    origin = _job_row(db, job_id, user)
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
def export_one_creation_history(request: Request, hid: int, batch_id: str = "",
                                db: Session = Depends(get_db)):
    """再下载整条历史：图片 + 广告文案 TXT/JSON + 落地页分析 + 生成信息。

    V4.83 / C06：可选 `batch_id` 把该创作批次的视频 / 配套素材并入同一个 ZIP。
    视频资产以 `concept_id = batch_id` 关联，并按 owner 隔离，避免越权导出他人成片。
    """
    _download_access(request)
    row = _history_row(db, hid)
    extra: list[dict] = []
    if batch_id:
        claims = _download_access(request)
        owner_id = claims.get("user_id") or claims.get("sub") or claims.get("uid")
        q = db.query(CreativeAsset).filter(CreativeAsset.concept_id == batch_id)
        if owner_id:
            q = q.filter(CreativeAsset.owner_id == owner_id)
        for a in q.all():
            meta = a.meta_json if isinstance(a.meta_json, dict) else {}
            extra.append({"file": a.file or "",
                          "role": meta.get("kind") or a.size or "asset",
                          "delivery_status": meta.get("delivery_status") or "compliant",
                          "note": f"时长 {meta.get('duration_sec') or 0}s（{meta.get('duration_source') or '未探测'}）"
                                  if meta.get("duration_sec") else ""})
    buf = build_history_zip([row], multi=False, extra_assets=extra)
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
    """把远程图片下载到本地 uploads，返回 /files/<name>（素材导入用）。

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
        "params": req.params,
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
            # V4.100：旧模块名「素材提示管理」等价于新模块名「提示词管理」，
            # 兼容旧缓存 / 外部筛选调用；模板按 key 读写，用户已保存内容不受影响。
            if not (module == MATERIAL_PROMPT_LEGACY_MODULE
                    and item.get("module") == MATERIAL_PROMPT_MODULE):
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
                                    intent=item.get("intent"),
                                    psychological_layers=item.get("psychological_layers"),
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


# ----------------------------- V4.104 / 方案E：图片质检开关 -----------------------------
@router.get("/settings/image-quality-audit")
def get_image_quality_audit(db: Session = Depends(get_db),
                            _: User = Depends(require_roles(*ROLES))):
    """图片质量扩展质检开关；缺行时默认打开（不 seed 即默认 true）。"""
    import app_settings
    return {"enabled": app_settings.get_bool(db, app_settings.IMAGE_QUALITY_AUDIT_ENABLED, True)}


@router.put("/settings/image-quality-audit")
def put_image_quality_audit(req: ImageQualityAuditIn, db: Session = Depends(get_db),
                            admin: User = Depends(require_roles("admin"))):
    """系统设置：打开 / 关闭图片质量扩展质检（纯色检查始终保留）。"""
    import app_settings
    app_settings.set_bool(db, app_settings.IMAGE_QUALITY_AUDIT_ENABLED, bool(req.enabled))
    db.commit()
    _audit(db, admin, "settings.image_quality_audit", app_settings.IMAGE_QUALITY_AUDIT_ENABLED,
           {"enabled": bool(req.enabled)})
    return {"ok": True, "enabled": bool(req.enabled)}


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
    # V4.98 / V4.100：提示词管理的一句意图与六层心理链条
    if req.intent is not None:
        row.intent = req.intent
    if req.psychological_layers is not None:
        row.psychological_layers = req.psychological_layers
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
                           intent=reg.get("intent"), psychological_layers=reg.get("psychological_layers"),
                           description=reg["description"], content=reg["content"], is_active=True)
        db.add(row)
    else:
        row.content = reg["content"]
        row.name = reg["name"]
        row.description = reg["description"]
        row.category = reg.get("category")
        row.func_type = reg.get("func_type")
        row.usage_type = reg.get("usage_type")
        row.intent = reg.get("intent")
        row.psychological_layers = reg.get("psychological_layers")
        row.is_active = True
    # 恢复内置默认时，一并清除总结库里该类提示词的默认选择标记
    for kind in KINDS:
        if kind["target_key"] == key:
            _state_set(db, "prompt_default_" + kind["key"], "")
    db.commit(); db.refresh(row)
    _audit(db, admin, "prompt.reset", key, {"name": row.name})
    return row


# ----------------------------- V4.98 / V4.100 提示词管理 -----------------------------
@router.get("/settings/material-prompts/meta")
def material_prompt_meta(_: User = Depends(require_roles(*ROLES))):
    """三类提示词类型、六层心理链条、以及每类模板的真实变量来源（供页面渲染，无需改代码即可展示）。"""
    return {
        "module": MATERIAL_PROMPT_MODULE,
        "legacy_module": MATERIAL_PROMPT_LEGACY_MODULE,
        "types": PROMPT_TYPES,
        "layers": PSYCHOLOGICAL_LAYERS,
        "variables": {t["key"]: material_variables_of(t["key"]) for t in PROMPT_TYPES},
    }


@router.post("/settings/material-prompts/match-layers")
def material_prompt_match_layers(req: LayerMatchIn,
                                 _: User = Depends(require_roles(*ROLES))):
    """按产品分析内容自动匹配心理链条覆盖层；用户仍可手动改为全部六层。"""
    return auto_match_layers(req.analysis or {})


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
               success: bool = True, detail: dict = None, action: str = "login"):
    """V4.47 / V4.86：记录一次账号事件（login 登录 / logout 登出，成功与失败均记录）。

    异常不阻断登录 / 登出主流程；username / ip / created_at 三要素一律落库。
    """
    try:
        db.add(LoginLog(username=username, ip=_client_ip(request),
                        action=action or "login",
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
    _log_login(db, u.username, request, success=True, action="login")
    return create_token(u)


@router.post("/auth/logout")
def logout(request: Request, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    """V4.86：登出记录。前端清除本地 token 前调用，落库 username / IP / 时间。

    这是「会话终止」的事件记录；JWT 本身无服务端状态，无法强制失效，
    但审计上必须能追溯谁在何时从何 IP 退出。写库失败不阻断前端登出（异常已被 _log_login 吞掉）。
    """
    _log_login(db, user.username, request, success=True, action="logout",
               detail={"event": "logout"})
    return {"ok": True}


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
               action: Optional[str] = None,
               db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))):
    """V4.47 / V4.86：账号事件日志（登录 + 登出，admin 可见）。

    可选过滤：success（true=成功 / false=失败）、action（login / logout）。
    """
    limit = min(max(int(limit), 1), 2000)
    q = db.query(LoginLog)
    if success is not None:
        q = q.filter_by(success=success)
    if action and str(action).strip().lower() in ("login", "logout"):
        q = q.filter_by(action=str(action).strip().lower())
    rows = q.order_by(LoginLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "username": r.username, "ip": r.ip,
             "action": r.action or "login",
             "user_agent": r.user_agent, "success": bool(r.success),
             "detail": r.detail, "created_at": r.created_at} for r in rows]


@router.get("/log-stats")
def log_stats(db: Session = Depends(get_db),
              _: User = Depends(require_roles("admin"))):
    """V4.86：日志真实统计（admin 可见），与列表的 limit / 前端搜索无关。

    返回全表口径的条数，供「日志」页标题显示准确总数；不再用「已加载且被过滤的条数」
    冒充总数（此前搜索或切换 limit 会让标题的 N 条随意变化）。
    """
    from sqlalchemy import func
    login_q = db.query(LoginLog)
    total = login_q.count()
    success = login_q.filter(LoginLog.success.is_(True)).count()
    fail = login_q.filter(LoginLog.success.is_(False)).count()
    # 兼容旧库：action 为 NULL 的历史记录按 login 计入（迁移默认 'login'）。
    logout = login_q.filter(LoginLog.action == "logout").count()
    login = total - logout
    return {
        "audit_total": db.query(AuditLog).count(),
        "login_total": total,
        "login_success": success,
        "login_fail": fail,
        "login_count": login,
        "logout_count": logout,
    }


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


# ----------------------------- V4.108 素材工作坊（独立一级模块） -----------------------------
@router.get("/workshop/options")
def api_workshop_options(db: Session = Depends(get_db),
                         _: User = Depends(require_roles(*CAN_EDIT))):
    """素材工作坊启动参数：模型就绪状态 + 标准库尺寸选项。

    前端只用这份数据渲染，不在界面上写任何尺寸或模型名，避免与标准库 / 配置页漂移。
    """
    return {
        "models": cw_workshop.model_status(db),
        "platforms": cw_workshop.platform_options(),
        "limits": {"max_images": cw_workshop.MAX_IMAGES},
    }


@router.post("/workshop/analyze")
async def api_workshop_analyze(req: WorkshopAnalyzeRequest, db: Session = Depends(get_db),
                               user: User = Depends(require_roles(*CAN_EDIT))):
    """素材工作坊·第一步：链接或产品描述 → 统一分析结论。

    与分析接口共用 `_cw_analyze_core`：抓取、证据包、创作意图完全一致，
    工作坊只是不展示中间结构。未测试通过的分析模型在调用前直接阻断。
    """
    missing = cw_workshop.missing_models(db, ["analysis"])
    if missing:
        raise HTTPException(422, detail={
            "message": "分析模型未就绪：请先在「系统设置 → 大模型配置」完成测试并通过",
            "models": missing, "blocked": "model_not_ready",
        })
    url, text = cw_workshop.split_input(req.input)
    if not url and not text:
        raise HTTPException(400, "请提供落地页链接或产品描述")
    platforms = [str(p).strip() for p in (req.platforms or []) if str(p).strip()] or ["Meta"]
    res = await _cw_analyze_core(CWAnalyzeRequest(
        url=url, text=text, platforms=platforms, demo_mode=bool(req.demo_mode),
        creative_intent=req.creative_intent or {}, intent_text=req.intent_text or "",
    ), db, user)
    info = res.model_info
    # 分析模型失败时 get_llm_with_info 会回退 MockLLM，产出的是样例文案。
    # 工作坊不交付模拟内容：直接报错，让用户去修配置，而不是拿假结论继续出图。
    if info.fallback or str(info.source) in ("mock", "local"):
        raise HTTPException(502, detail={
            "message": "分析模型未返回有效结果，已阻止使用本地模拟内容",
            "blocked": "model_failed",
            "models": cw_workshop.model_status(db)["items"],
        })
    return {
        "plan_id": res.id,
        "title": res.title,
        "summary": res.summary,
        "analysis": res.analysis,
        "brief": res.brief,
        "snapshot": res.snapshot.model_dump(),
        "intent_summary": res.intent_summary,
        "source": res.source,
        "models": [i for i in cw_workshop.model_status(db)["items"]
                   if i["usage"] == "analysis"],
    }


@router.post("/workshop/generate")
async def api_workshop_generate(req: WorkshopGenerateRequest, db: Session = Depends(get_db),
                                user: User = Depends(require_roles(*CAN_EDIT))):
    """素材工作坊·第二步：逐个平台生成文案，并按所选尺寸建出图任务。

    文案与出图都是真实调用：文案失败（模型回退 Mock）的平台不出图，避免用样例文案
    叠到图上；出图任务走 `generation_jobs`，刷新 / 关页后仍可按 job_id 取回结果。
    """
    analysis = req.analysis if isinstance(req.analysis, dict) else {}
    if not analysis:
        raise HTTPException(400, "缺少分析结果，请先解析产品")

    # 文案平台：以请求里的平台为准（只出文案时尺寸可以为空）；
    # 尺寸任务：由标准库复核后的 targets 决定。
    known = {o["platform"] for o in cw_workshop.platform_options()}
    copy_platforms: list[str] = []
    for t in (req.targets or []):
        p = str(getattr(t, "platform", "") or "").strip()
        if not p:
            continue
        if p not in known:
            raise HTTPException(422, detail={"message": "尺寸选择未通过标准库校验",
                                             "errors": [f"未登记的平台：{p}"]})
        if p not in copy_platforms:
            copy_platforms.append(p)

    targets, errors = cw_workshop.resolve_targets([t.model_dump() for t in (req.targets or [])])
    if errors:
        raise HTTPException(422, detail={"message": "尺寸选择未通过标准库校验", "errors": errors})
    if len(targets) > cw_workshop.MAX_IMAGES:
        raise HTTPException(422, detail={
            "message": f"一次最多生成 {cw_workshop.MAX_IMAGES} 张图，请减少尺寸后重试"})

    # 文案模型是硬前提；图片模型缺失时降级为「只出文案」，不阻断、也不假装出图。
    missing_copy = cw_workshop.missing_models(db, ["copy"])
    if missing_copy:
        raise HTTPException(422, detail={
            "message": "文案模型未就绪：请先在「系统设置 → 大模型配置」完成测试并通过",
            "models": missing_copy, "blocked": "model_not_ready",
        })
    missing_image = cw_workshop.missing_models(db, ["image"])
    image_ready = not missing_image
    if image_ready and not targets:
        raise HTTPException(400, "请至少选择一个平台与尺寸")
    if not image_ready and not copy_platforms:
        raise HTTPException(400, "请至少选择一个平台")
    _enforce_evidence_gate(analysis)

    copies: list[dict] = []
    image_jobs: list[dict] = []
    warnings: list[str] = []
    if not image_ready:
        warnings.append("图片模型未就绪，本次只生成文案（不调用文生图、不产生图片费用）")

    # ① 文案：按用户选中的平台逐个生成（图片模型缺失时这就是全部交付）
    copy_by_platform: dict[str, dict] = {}
    copy_status: dict[str, str] = {}
    for platform in copy_platforms:
        copy_res = await generate_media_copy(
            db, analysis, platform, req.lang or "en",
            style_opts={}, brief=(analysis.get("brief") or {}))
        item = cw_workshop.copy_view(platform, copy_res)
        copies.append(item)
        copy_by_platform[platform] = copy_res
        copy_status[platform] = item["status"]
        if item["status"] == "failed":
            warnings.append(f"{platform}：{item['reason']}，已跳过该平台出图")

    # ② 图片：仅在有可用文案时按平台建任务；文案回退 Mock 的平台不出图，
    #    避免把模拟文案叠到真实图片上冒充交付物。
    if image_ready:
        for platform, rows in cw_workshop.group_targets(targets).items():
            copy_res = copy_by_platform.get(platform) or {}
            if copy_status.get(platform) == "failed":
                continue
            if not copy_res:
                warnings.append(f"{platform}：缺少可用文案，已跳过该平台出图")
                continue
            try:
                slots = [MediaImageSlot(size=r["size"], spec_id=r.get("spec_id") or "")
                         for r in rows]
                # V4.111：入队前先跑一遍执行期同一套媒体规则。此前后端要等后台任务
                # 启动才校验，一旦尺寸与规则目录不一致，任务直接 failed、页面只看到
                # 「没有图片」却拿不到原因。这里必败的组合当场说清楚，不排进付费队列。
                try:
                    validate_task_matrix(platform, [s.model_dump() for s in slots])
                except MediaRuleError as e:
                    warnings.append(f"{platform}：尺寸未通过媒体规则（{'；'.join(e.errors)}）")
                    continue
                # V4.111：工作坊没有「编辑文案」这一步，文案超出图内排版预算时整批会被
                # 判 needs_revision（一张图都出不来且无从修改）。开启 fit_overlay 后由
                # 出图链路按**实际版式**把图上那一行收敛到可排版长度；完整文案仍留在
                # 「文案素材」里作为投放字段，不做删减。
                ov = cw_workshop.overlay_variant(copy_res, analysis)
                i_req = MediaImageRequest(
                    analysis=LandingAnalysis(**cw_workshop.landing_payload(analysis)),
                    platform=platform, lang=req.lang or "en",
                    copy_fields=copy_res.get("fields") or {},
                    copy_variants=[MediaCopyVariant(**ov)],
                    style_opts={"fit_overlay": True}, slots=slots,
                )
                job, created = job_service.create_job(
                    db, {"images_request": i_req.model_dump(), "archive": {}}, user,
                    idempotency_key="", kind="images")
            except Exception as e:
                warnings.append(f"{platform}：出图任务未创建（{type(e).__name__}）")
                continue
            job_service.spawn_job(job.job_id)
            image_jobs.append({
                "platform": platform,
                "job_id": job.job_id,
                "created": created,
                "sizes": [{"size": r["size"], "label": r["label"], "aspect": r["aspect"]}
                          for r in rows],
                "poll_url": f"/api/generation-jobs/{job.job_id}",
            })

    return {"copies": copies, "image_jobs": image_jobs, "warnings": warnings,
            "images_skipped": (not image_ready),
            "plan_id": req.plan_id,
            "models": cw_workshop.model_status(db)["items"]}
