from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_
from datetime import datetime
import io, zipfile, csv, json, os, time, re, asyncio, shutil
import httpx

from database import get_db
from models import (Campaign, Material, Framework, ModelConfig, PlatformSpec, LandingPage, Job,
                    User, ReviewRecord, AuditLog, Angle, PromptConfig)
from schemas import (AnalyzeRequest, FrameworkOut, GenerateRequest, CampaignOut,
                     MaterialOut, ModelConfigIn, ModelConfigOut, ModelTestIn, RegenerateRequest,
                     JobCreate, JobOut, BatchParseRequest, SlotVersionsOut,
                     LoginRequest, UserOut, UserCreate, UserUpdate, ReviewRequest, SpecUpdate,
                     AngleOut, AnglePlanRequest, ProduceRequest, BrandUpdate, EstimateRequest,
                     ReportRequest, OptimizeRequest, PromptOut, PromptUpdate,
                     LandingAnalysisRequest, LandingAnalysis, MediaCopyRequest, MediaImageRequest)
from services import (analyze_landing_page, generate_campaign_materials, regenerate_material,
                      plan_angles, produce_campaign, fetch_page, optimize_campaign,
                      IMAGE_MAX_SIZES, PROMPT_REGISTRY, analyze_landing_concise)
from creative import COPY_SCHEMA, ANGLE_LIBRARY, ANGLE_MAP
from report import build_report, report_markdown
from batch import parse_csv, run_job, template_csv, CSV_HEADERS
from specs_data import PLATFORMS, MATERIAL_TYPES, LANGUAGES
from llm_catalog import LLM_PRESETS, test_llm_connection
from presets import build_directives, creative_presets_payload
from media_platforms import list_media_platforms
from media_ad import generate_media_copy, generate_media_images
from auth import (current_user, require_roles, verify_password, hash_password, create_token,
                  user_dict, ROLE_LABELS, CAN_EDIT, CAN_REVIEW, ROLES)

router = APIRouter(prefix="/api")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
_bg_tasks = set()   # 持有后台任务引用，避免被 GC
# 单次生成上限：一次几百个素材既跑很久，投放人员也挑不过来，宁可让他分批
MAX_MATERIALS = int(os.getenv("MAX_MATERIALS_PER_CAMPAIGN", "240"))
VIDEO_MODES = ("off", "first", "all")
VALID_TYPES = ("image", "copy", "video", "keyword")


def _plan_count(db, angle_keys, platforms, types, langs, sizes_per_angle, video_mode) -> dict:
    """按参数预估产出量：前端在点生成前就能看到会出多少个素材。"""
    keys = [k for k in (angle_keys or []) if k in ANGLE_MAP] or ["benefit"]
    langs = langs or ["en"]
    sizes = max(1, min(int(sizes_per_angle or IMAGE_MAX_SIZES), 8))
    per_platform, images = [], 0
    for p in platforms:
        spec = db.query(PlatformSpec).filter_by(platform=p).first()
        avail = len(spec.image_sizes or []) if spec else 1
        use = min(sizes, avail)
        per_platform.append({"platform": p, "sizes": use, "available": avail})
        images += len(keys) * len(langs) * use
    copies = len(keys) * len(platforms) * len(langs)
    vk = len(keys) if video_mode == "all" else (1 if video_mode == "first" else 0)
    videos = vk * len(platforms) if "video" in types else 0
    keywords = copies if "keyword" in types else 0
    return {"angles": len(keys), "platforms": list(platforms), "languages": langs,
            "sizes_per_angle": sizes, "video_mode": video_mode,
            "per_platform": per_platform,
            "images": images, "copy": copies, "video": videos, "keyword": keywords,
            "total": images + copies + videos + keywords}

# ----------------------------- 元数据 -----------------------------
@router.get("/meta")
def meta():
    return {"platforms": PLATFORMS, "material_types": MATERIAL_TYPES, "languages": LANGUAGES,
            "copy_schema": COPY_SCHEMA,
            "angle_library": [{k: a[k] for k in ("key", "name", "insight", "visual",
                                                 "kpi", "template", "platform_fit")}
                              for a in ANGLE_LIBRARY]}

@router.get("/platform-specs")
def platform_specs(db: Session = Depends(get_db)):
    return db.query(PlatformSpec).all()

# ----------------------------- 分析 -----------------------------
@router.post("/analyze", response_model=FrameworkOut)
async def analyze(req: AnalyzeRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*CAN_EDIT))):
    if not req.url and not req.text:
        raise HTTPException(400, "请提供落地页 URL 或文本")
    fw = await analyze_landing_page(db, req.url, req.text)
    return fw


@router.post("/landing-analysis", response_model=LandingAnalysis)
async def landing_analysis(req: LandingAnalysisRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*CAN_EDIT))):
    """素材创作：落地页分析。调用已配置的「分析 / 文案」大模型推理，产出 8 个必要字段，
    并回传实际调用了哪个模型（provider/model/role/fallback），便于持续跟踪各模型优劣势。结果不落库。"""
    url, text = (req.url or "").strip(), (req.text or "").strip()
    if not url and not text:
        raise HTTPException(400, "请提供落地页 URL 或正文")
    result = await analyze_landing_concise(db, url or None, text or None)
    return LandingAnalysis(**result)

# ----------------------------- 素材创作：营销推广的媒体平台设置 -----------------------------
@router.get("/media-platforms")
async def api_media_platforms(_: User = Depends(require_roles(*CAN_EDIT))):
    """营销推广媒体平台规格：数量 / 规格 / 尺寸 / 常规方案 / 字数红线。供前端展示与预选。"""
    return list_media_platforms()

@router.post("/media-campaign/copy")
async def api_media_campaign_copy(req: MediaCopyRequest, db: Session = Depends(get_db),
                                  user: User = Depends(require_roles(*CAN_EDIT))):
    """基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案，并标注本次调用的模型。

    文案必须结合落地页分析结论（行业/类型/优势/竞品/受众/推广途径），生成后立即返回，前端展示并允许编辑。
    """
    result = await generate_media_copy(db, req.analysis.model_dump(), req.platform, req.lang)
    return result

@router.post("/media-campaign/images")
async def api_media_campaign_images(req: MediaImageRequest, db: Session = Depends(get_db),
                                    user: User = Depends(require_roles(*CAN_EDIT))):
    """基于编辑后的文案 + 落地页分析结论 + 风格/样式/颜色，生成推广图片素材，并标注图片实际调用的模型。

    生成前可在前端选风格/样式/颜色；未配置文生图模型时自动用 Pillow 品牌渐变模板兜底，并如实标注回退。
    """
    slots = [s.model_dump() for s in req.slots]
    result = await generate_media_images(db, req.analysis.model_dump(), req.platform, req.lang,
                                         req.copy_fields, req.style_opts, slots, req.logo or "")
    return result

# ----------------------------- 产品分析报告 -----------------------------
@router.post("/report")
async def create_report(req: ReportRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_roles(*CAN_EDIT))):
    """抓落地页 → 结构化分析报告 → 顺带把创意方向也规划好。

    一次调用完成"看懂产品 + 想好怎么投"，前端一个按钮就能往下走。
    """
    url, text = (req.url or "").strip(), (req.text or "").strip()
    if not url and not text:
        raise HTTPException(400, "请提供落地页 URL 或产品说明")
    page = None
    if url and not text:
        page = await fetch_page(url)
        if not page.get("text"):
            raise HTTPException(
                422, f"没能读取落地页（HTTP {page.get('status') or '无响应'}）。"
                     f"该页面可能需要登录或由 JS 动态渲染，请把正文粘贴到下方输入框后重试。")
    fw = await analyze_landing_page(db, url or None, text or None, page)
    lang = req.lang or ((fw.languages or ["en"])[0])
    angles = await plan_angles(db, fw, req.platforms, None, lang)
    body_text = (page or {}).get("text") or text
    report = build_report(fw, angles, page or ((fw.evidence or {}).get("page") or {}), body_text)
    return {"framework": FrameworkOut.model_validate(fw).model_dump(),
            "report": report,
            "angles": [AngleOut.model_validate(a).model_dump() for a in angles]}

@router.get("/reports/{fid}")
def get_report(fid: int, db: Session = Depends(get_db)):
    """重新打开某次分析：基于已落库的事实重建报告，不再重复抓取。"""
    fw = db.query(Framework).filter_by(id=fid).first()
    if not fw:
        raise HTTPException(404, "分析记录不存在")
    angles = db.query(Angle).filter_by(framework_id=fid).order_by(Angle.sort).all()
    return {"framework": FrameworkOut.model_validate(fw).model_dump(),
            "report": build_report(fw, angles, (fw.evidence or {}).get("page") or {}, ""),
            "angles": [AngleOut.model_validate(a).model_dump() for a in angles]}

@router.get("/reports/{fid}/export.md")
def export_report_md(fid: int, db: Session = Depends(get_db)):
    """下载分析报告（Markdown），方便贴进评审文档。"""
    fw = db.query(Framework).filter_by(id=fid).first()
    if not fw:
        raise HTTPException(404, "分析记录不存在")
    angles = db.query(Angle).filter_by(framework_id=fid).order_by(Angle.sort).all()
    md = report_markdown(build_report(fw, angles, (fw.evidence or {}).get("page") or {}, ""), fw.product)
    safe = _slug(fw.product)
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition":
                                      f'attachment; filename="{safe}_analysis.md"'})

# ----------------------------- 生成 -----------------------------
@router.post("/generate", response_model=CampaignOut)
async def generate(req: GenerateRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT))):
    fw = db.query(Framework).filter_by(id=req.framework_id).first()
    if not fw:
        raise HTTPException(404, "推广框架不存在")
    langs = req.languages or (fw.languages or ["en"])
    campaign = Campaign(name=req.campaign_name, framework_id=fw.id,
                        platforms=req.platforms, status="draft", owner_id=user.id)
    db.add(campaign); db.commit(); db.refresh(campaign)   # 先落库，避免生成期间持有写锁
    mats = await generate_campaign_materials(
        db, fw, campaign, req.platforms, req.material_types, langs, req.extra_prompt)
    db.refresh(campaign)
    _ = list(campaign.materials)   # 强制预加载，确保响应含素材
    return campaign

# ----------------------------- 创意方向 / 生产（V3.0） -----------------------------
@router.get("/copy-schema")
def copy_schema():
    return {"schema": COPY_SCHEMA,
            "angles": [{k: a[k] for k in ("key", "name", "insight", "visual",
                                          "kpi", "template", "platform_fit")}
                       for a in ANGLE_LIBRARY]}

@router.post("/angles/plan", response_model=list[AngleOut])
async def angles_plan(req: AnglePlanRequest, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*CAN_EDIT))):
    fw = db.query(Framework).filter_by(id=req.framework_id).first()
    if not fw:
        raise HTTPException(404, "推广框架不存在")
    return await plan_angles(db, fw, req.platforms, req.extra_prompt, req.lang)

@router.get("/frameworks/{fid}/angles", response_model=list[AngleOut])
def framework_angles(fid: int, db: Session = Depends(get_db)):
    return db.query(Angle).filter_by(framework_id=fid).order_by(Angle.sort).all()

@router.patch("/frameworks/{fid}/brand")
def update_brand(fid: int, req: BrandUpdate, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*CAN_EDIT))):
    fw = db.query(Framework).filter_by(id=fid).first()
    if not fw:
        raise HTTPException(404, "推广框架不存在")
    if req.brand_color:
        fw.brand_color = req.brand_color
    if req.assets is not None:
        fw.assets = req.assets
    db.commit()
    return {"ok": True, "brand_color": fw.brand_color, "assets": fw.assets}

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

@router.post("/produce", response_model=CampaignOut)
async def produce(req: ProduceRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*CAN_EDIT))):
    fw = db.query(Framework).filter_by(id=req.framework_id).first()
    if not fw:
        raise HTTPException(404, "推广框架不存在")
    if not req.platforms:
        raise HTTPException(400, "请至少选择一个投放平台")
    langs = req.languages or (fw.languages or ["en"])
    keys = [k for k in (req.angle_keys or []) if k] or ["benefit"]
    types = [t for t in (req.material_types or ["image", "copy"]) if t in VALID_TYPES]
    if not types:
        types = ["image", "copy"]
    video_mode = req.video_mode if req.video_mode in VIDEO_MODES else "all"
    if video_mode == "off" and "video" in types:
        types = [t for t in types if t != "video"]
    sizes = req.sizes_per_angle or req.sizes_per_platform or IMAGE_MAX_SIZES

    plan = _plan_count(db, keys, req.platforms, types, langs, sizes, video_mode)
    if plan["total"] > MAX_MATERIALS:
        raise HTTPException(
            400, f"本次将生成 {plan['total']} 个素材，超过单次上限 {MAX_MATERIALS}。"
                 f"请减少创意方向、每方向版位数或平台数后重试。")

    campaign = Campaign(name=req.campaign_name, framework_id=fw.id, platforms=req.platforms,
                        angle_keys=keys, status="draft", owner_id=user.id,
                        options={"sizes_per_angle": plan["sizes_per_angle"],
                                 "video_mode": video_mode, "material_types": types,
                                 "languages": langs, "full_video": bool(req.full_video)})
    db.add(campaign); db.commit(); db.refresh(campaign)

    await produce_campaign(db, fw, campaign, keys, req.platforms, types, langs,
                           req.extra_prompt, plan["sizes_per_angle"], video_mode,
                           full_video=bool(req.full_video),
                           directives=build_directives(
                               creative_direction=req.creative_direction,
                               content_style=req.content_style,
                               color_scheme=req.color_scheme,
                               market_insight=req.market_insight,
                               lang=langs[0] if langs else "en"))
    db.refresh(campaign)
    _ = list(campaign.materials)
    return campaign


@router.get("/settings/creative-presets")
def creative_presets():
    """返回「素材创作」三大提示词库：创意方向（D01-D20）/ 内容风格（S01-S26）/ 配色（C01-C16）。

    前端「素材提示词管理」与「素材创作」生成均从此处取数，便于后续在后台扩充。
    """
    return creative_presets_payload()


@router.post("/estimate")
def estimate(req: EstimateRequest, db: Session = Depends(get_db)):
    """预估产出量（不落库、不渲染），用于前端在生成前提示规模。"""
    types = [t for t in (req.material_types or ["image", "copy"]) if t in VALID_TYPES]
    video_mode = req.video_mode if req.video_mode in VIDEO_MODES else "all"
    if video_mode == "off":
        types = [t for t in types if t != "video"]
    plan = _plan_count(db, req.angle_keys, req.platforms, types, req.languages,
                       req.sizes_per_angle, video_mode)
    plan["limit"] = MAX_MATERIALS
    plan["over_limit"] = plan["total"] > MAX_MATERIALS
    return plan

@router.post("/campaigns/{cid}/optimize")
async def optimize(cid: int, req: OptimizeRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_EDIT))):
    """对已生成素材按自然语言要求做一轮优化，产出新版本并返回逐条改动。"""
    c = db.query(Campaign).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "批次不存在")
    instruction = (req.instruction or "").strip()
    if len(instruction) < 2:
        raise HTTPException(400, "请填写优化要求，例如：标题更短、去掉数字、突出免费")
    scope = req.scope if req.scope in ("all", "copy", "image") else "all"
    try:
        res = await optimize_campaign(db, c, instruction, scope, req.angle_keys)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 没听懂（一条规则都没命中）才算错误；听懂了但这批文案本来就无需改动，
    # 是正常结果——退回 200 + created:0，前端按中性提示展示，不要报红。
    if not res["rules"]:
        raise HTTPException(
            422, "没听懂这条要求。" +
                 "可以试试：标题更短 / 去掉数字 / 突出评分 / 换成纯文字版式 / 主色改蓝。")
    _audit(db, user, "campaign.optimize", f"campaign:{cid}",
           {"instruction": instruction, "scope": scope, "created": res["created"],
            "rules": [r["key"] for r in res["rules"]]})
    db.refresh(c)
    _ = list(c.materials)
    return {**res, "noop": not res["created"],
            "campaign": CampaignOut.model_validate(c).model_dump()}


# ----------------------------- 重生成 -----------------------------
@router.post("/materials/{mid}/regenerate", response_model=MaterialOut)
async def regen(mid: int, req: RegenerateRequest, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*CAN_EDIT))):
    m = db.query(Material).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    new = await regenerate_material(db, m, req.extra_prompt)
    return new

# ----------------------------- 素材库 / 历史 -----------------------------
@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db),
                   product: str = Query(None), platform: str = Query(None),
                   lang: str = Query(None), from_date: str = Query(None), to_date: str = Query(None)):
    q = db.query(Campaign).options(selectinload(Campaign.materials))
    if product:
        q = q.join(Framework).filter(Framework.product.ilike(f"%{product}%"))
    if platform:
        # platforms 存为 JSON 数组，简单包含判断
        q = q.filter(Campaign.platforms.like(f'%"{platform}"%'))
    if from_date:
        q = q.filter(Campaign.created_at >= from_date)
    if to_date:
        q = q.filter(Campaign.created_at <= to_date)
    camps = q.order_by(Campaign.created_at.desc()).all()
    return camps

@router.get("/campaigns/{cid}", response_model=CampaignOut)
def get_campaign(cid: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).options(selectinload(Campaign.materials)).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    return c

@router.get("/materials/{mid}", response_model=MaterialOut)
def get_material(mid: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    return m

# ----------------------------- 批量删除 -----------------------------
def _collect_campaign_files(c: Campaign):
    """收集一个 Campaign 下所有素材的磁盘文件（图片 / 视频 / 关键帧 / 成片 / 封面）。

    删除方案时必须一并清掉这些文件，否则 uploads 目录会残留孤立文件。
    """
    files: list[str] = []
    dirs: set[str] = set()
    for m in c.materials:
        if m.file_path:
            files.append(m.file_path)
        content = m.content or {}
        for kf in (content.get("keyframes") or []):
            f = kf.get("file")
            if f:
                files.append(f)
                dirs.add(os.path.dirname(f))
        for k in ("video_file", "cover"):
            v = content.get(k)
            if v:
                files.append(v)
    return files, dirs


@router.delete("/campaigns/batch", response_model=dict)
def delete_campaigns_batch(body: dict, db: Session = Depends(get_db),
                           user: User = Depends(require_roles("admin", "manager", "editor"))):
    """批量删除历史方案（及其下全部素材与磁盘文件）。

    请求体 {"ids": [int, ...]}；物理删除、不可恢复，前端须二次确认。
    """
    ids = body.get("ids") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "请提供要删除的 campaign id 列表")
    ids = [int(x) for x in ids if str(x).strip().isdigit()]
    if not ids:
        raise HTTPException(400, "请提供有效的 campaign id")
    camps = db.query(Campaign).options(selectinload(Campaign.materials)).filter(Campaign.id.in_(ids)).all()
    if not camps:
        raise HTTPException(404, "未找到对应方案")
    found = {c.id for c in camps}

    deleted_files = 0
    for c in camps:
        files, dirs = _collect_campaign_files(c)
        for f in files:
            try:
                if os.path.isfile(f):
                    os.remove(f); deleted_files += 1
            except OSError:
                pass
        for d in dirs:
            try:
                if os.path.isdir(d):
                    shutil.rmtree(d); deleted_files += 1
            except OSError:
                pass

    # 关联的审阅记录一并清理，避免留下孤儿行
    db.query(ReviewRecord).filter(ReviewRecord.campaign_id.in_(found)).delete(synchronize_session=False)

    mat_count = sum(len(c.materials) for c in camps)
    for c in camps:
        db.delete(c)  # Campaign.materials 配置了 ORM 级联删除
    db.commit()
    return {"ok": True, "deleted_campaigns": len(camps),
            "deleted_materials": mat_count, "deleted_files": deleted_files}

# ----------------------------- 导出 / 批量下载 -----------------------------
def _material_text(m: Material) -> str:
    if m.type == "copy":
        return m.text_content or json.dumps(m.content, ensure_ascii=False)
    if m.type == "keyword":
        return m.text_content or json.dumps(m.content, ensure_ascii=False)
    if m.type == "video":
        return json.dumps(m.content, ensure_ascii=False, indent=2)
    return ""

def _slug(name: str, fallback: str = "campaign") -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", (name or "").strip())[:40].strip("_")
    return s or fallback

def _write_campaign_zip(z: zipfile.ZipFile, db: Session, c: Campaign, prefix: str = "",
                        only_valid: bool = False, all_versions: bool = False):
    """按「平台/创意方向」目录结构打包，附 copy.csv 与投放建议，拿到即可分配上传。

    默认只打每组的最新版本：优化过的批次里 v1/v2 同时存在，
    全打进去会让投放人员重复上传旧稿。
    """
    from creative import ANGLE_MAP
    fw = db.query(Framework).filter_by(id=c.framework_id).first()
    mats = db.query(Material).filter_by(campaign_id=c.id).order_by(Material.id).all()

    def _key(m):
        size = (m.spec_json or {}).get("size", "") if m.type == "image" else ""
        return (m.type, m.platform, m.angle_key, m.language, size)

    if not all_versions:
        latest = {}
        for m in mats:
            k = _key(m)
            if k not in latest or (m.version or 1) >= (latest[k].version or 1):
                latest[k] = m
        mats = sorted(latest.values(), key=lambda x: x.id)
    total_before = len(mats)
    if only_valid:
        mats = [m for m in mats if (m.validation or {}).get("valid", True)]
    brand = _slug((fw.product if fw else "ad"), "ad")

    manifest = {
        "campaign": {"id": c.id, "name": c.name, "platforms": c.platforms,
                     "angle_keys": c.angle_keys, "status": c.status},
        "pack": {"latest_only": not all_versions, "only_valid": only_valid,
                 "materials": len(mats), "skipped_invalid": total_before - len(mats)},
        "framework": {
            "product": fw.product if fw else None,
            "category": fw.category if fw else None,
            "audience": fw.audience if fw else None,
            "geo": fw.geo if fw else None,
            "languages": fw.languages if fw else None,
            "selling_points": fw.selling_points if fw else None,
            "metrics": fw.metrics if fw else None,
            "platform_analysis": fw.platform_analysis if fw else None,
        },
        "materials": [
            {"id": m.id, "type": m.type, "platform": m.platform, "angle": m.angle_key,
             "language": m.language, "version": m.version, "spec": m.spec_json,
             "content": m.content, "validation": m.validation}
            for m in mats
        ],
    }
    z.writestr(f"{prefix}manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    csv_rows = []
    for m in mats:
        angle = m.angle_key or "base"
        folder = f"{prefix}{m.platform}/{angle}/"
        if m.type == "image":
            size = (m.spec_json or {}).get("size", "")
            name = f"{brand}_{m.platform}_{angle}_{m.language or 'xx'}_{size}_v{m.version}.png"
            if m.file_path and os.path.exists(m.file_path):
                z.write(m.file_path, folder + name)
        elif m.type == "video":
            content = m.content or {}
            for kf in content.get("keyframes") or []:
                p = kf.get("file")
                if p and os.path.exists(p):
                    z.write(p, f"{folder}{brand}_{m.platform}_{angle}_{m.language}_kf{kf['index']}.png")
            if m.file_path and os.path.exists(m.file_path):
                z.write(m.file_path, f"{folder}{brand}_{m.platform}_{angle}_{m.language}_cover.png")
            z.writestr(f"{folder}storyboard.json",
                       json.dumps(content, ensure_ascii=False, indent=2))
        elif m.type == "copy":
            fields = (m.content or {}).get("fields", {})
            for f, v in fields.items():
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    csv_rows.append([m.platform, angle, m.language or "", f, x, len(str(x))])
        elif m.type == "keyword":
            z.writestr(f"{folder}keywords.txt", _material_text(m))

    if csv_rows:
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(["platform", "angle", "language", "field", "value", "chars"])
        wr.writerows(csv_rows)
        z.writestr(f"{prefix}copy.csv", "\ufeff" + buf.getvalue())

    if fw:
        tips = [
            f"# {fw.product} 投放建议",
            "",
            f"- 品类：{fw.category or '—'}　地区：{fw.geo or '—'}",
            f"- 本轮创意方向：{' / '.join(ANGLE_MAP.get(k, {}).get('name', k) for k in (c.angle_keys or []))}"
            + (f"　版本：v{max((m.version or 1) for m in mats)}" if mats else ""),
            "",
            "## 素材使用",
            "- 每个方向都覆盖了所选平台的全部主尺寸，同一方向的多个尺寸是重新排版，可直接对应版位上传。",
            "- copy.csv 是平台字段级文案，FB 的 primary_text/headline/description 与 Google RSA 的 headline/description 已分别列出。",
            "",
            "## 测试建议",
            "- 同一方向内先横向测尺寸（Reels 竖版 vs Feed 方版），方向之间再比 CTR/CVR，避免同时变两个变量。",
            "- 单方向素材连续投放 7 天 CTR 下滑超过 30%，视为疲劳，换下一个方向。",
        ]
        for a in (c.angle_keys or []):
            meta = ANGLE_MAP.get(a)
            if meta:
                tips.append(f"- {meta['name']}：{meta['insight']}")
        z.writestr(f"{prefix}delivery_notes.md", "\n".join(tips))

@router.get("/export/campaign/{cid}")
def export_campaign(cid: int, only_valid: bool = Query(False, description="仅打包校验通过的素材"),
                    all_versions: bool = Query(False, description="包含历史版本"),
                    db: Session = Depends(get_db)):
    c = db.query(Campaign).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        _write_campaign_zip(z, db, c, only_valid=only_valid, all_versions=all_versions)
    buf.seek(0)
    suffix = "valid" if only_valid else "all"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      f'attachment; filename="campaign_{cid}_{suffix}.zip"'})

@router.get("/export/batch")
def export_batch(ids: str = Query(..., description="逗号分隔的 campaign id"),
                 db: Session = Depends(get_db)):
    """多 Campaign 合并导出：每个 Campaign 一个目录，附总 manifest。"""
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        raise HTTPException(400, "请提供有效的 campaign id")
    camps = db.query(Campaign).filter(Campaign.id.in_(id_list)).order_by(Campaign.id).all()
    if not camps:
        raise HTTPException(404, "未找到 Campaign")
    buf = io.BytesIO()
    index = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        used = set()
        for c in camps:
            folder = f"{c.id}_{_slug(c.name)}"
            while folder in used:
                folder += "_x"
            used.add(folder)
            _write_campaign_zip(z, db, c, prefix=f"{folder}/")
            index.append({"campaign_id": c.id, "name": c.name, "folder": folder,
                          "materials": db.query(Material).filter_by(campaign_id=c.id).count()})
        z.writestr("batch_manifest.json", json.dumps(
            {"count": len(camps), "campaigns": index}, ensure_ascii=False, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="batch_export.zip"'})

@router.get("/materials/{mid}/download")
def download_material(mid: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    if m.file_path and os.path.exists(m.file_path):
        return FileResponse(m.file_path, filename=os.path.basename(m.file_path))
    ext = _text_ext(m)
    base = f"{m.campaign_id}_{m.platform}_{m.language or 'xx'}_{m.type}_v{m.version}{ext}"
    return StreamingResponse(iter([_material_text(m)]), media_type="text/plain",
                             headers={"Content-Disposition": f"attachment; filename={base}"})

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

@router.get("/settings/models", response_model=list[ModelConfigOut])
def list_models(db: Session = Depends(get_db)):
    return db.query(ModelConfig).order_by(ModelConfig.id).all()

@router.post("/settings/models", response_model=ModelConfigOut)
def create_model(req: ModelConfigIn, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles("admin"))):
    usages = _normalize_usage(req.usage)
    if not usages:
        raise HTTPException(400, "请至少选择一个用途")
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


# ----------------------------- 设置：提示词管理 -----------------------------
def _prompt_reg(key: str):
    return next((p for p in PROMPT_REGISTRY if p["key"] == key), None)


@router.get("/settings/prompts", response_model=list[PromptOut])
def list_prompts(db: Session = Depends(get_db),
                 module: str = Query(None, description="按功能模块筛选，如：素材创作（落地页分析）"),
                 _: User = Depends(require_roles("admin"))):
    """按注册表顺序输出提示词；未落库的用内置默认兜底展示（与运行时 get_prompt 行为一致）。
    传入 module 时只返回该模块的提示词（供「素材提示词」分门别类展示）。"""
    rows = {p.key: p for p in db.query(PromptConfig).all()}
    out = []
    for item in PROMPT_REGISTRY:
        if module and item.get("module") != module:
            continue
        row = rows.get(item["key"])
        if row:
            out.append(row)
        else:
            out.append(PromptConfig(id=0, key=item["key"], name=item["name"], module=item["module"],
                                    category=item.get("category"), description=item["description"],
                                    content=item["content"], is_active=True, updated_at=None))
    return out


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
                           description=reg["description"], content=reg["content"])
        db.add(row)
    row.content = req.content
    if req.name is not None:
        row.name = req.name
    if req.description is not None:
        row.description = req.description
    if req.category is not None:
        row.category = req.category
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
                           description=reg["description"], content=reg["content"], is_active=True)
        db.add(row)
    else:
        row.content = reg["content"]
        row.name = reg["name"]
        row.description = reg["description"]
        row.is_active = True
    db.commit(); db.refresh(row)
    _audit(db, admin, "prompt.reset", key, {"name": row.name})
    return row


# ----------------------------- V1.1 批量任务 -----------------------------
def _spawn(coro):
    """启动后台任务并持引用，避免 asyncio 任务被回收。"""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t

@router.post("/batch/parse")
def batch_parse(req: BatchParseRequest):
    """预解析：让前端在提交前看到将被执行的行。"""
    items = parse_csv(req.rows)
    return {
        "count": len(items),
        "items": items[:50],
        "headers": CSV_HEADERS,
        "errors": [] if items else ["未解析到有效行：请确认包含 landing_text 列，或每行第一列即落地页文案"],
    }

@router.post("/batch/upload")
async def batch_upload(file: UploadFile = File(...)):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    items = parse_csv(raw)
    return {"count": len(items), "items": items[:50], "headers": CSV_HEADERS,
            "errors": [] if items else ["CSV 为空或缺少有效行"]}

@router.get("/batch/template")
def batch_template():
    return PlainTextResponse(template_csv(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="batch_template.csv"'})

@router.post("/batch/jobs", response_model=JobOut)
async def create_batch_job(req: JobCreate, db: Session = Depends(get_db),
                           user: User = Depends(require_roles(*CAN_EDIT))):
    raw_items = req.items if req.items else parse_csv(req.rows or "")
    items, skipped = [], 0
    for it in raw_items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        land = it.get("landing_text")
        if isinstance(land, (int, float)):
            land = str(land)
        if not isinstance(land, str) or not land.strip():
            skipped += 1
            continue
        items.append({
            "campaign_name": (it.get("campaign_name") or land[:24]),
            "landing_text": land,
            "platforms": it.get("platforms") if isinstance(it.get("platforms"), list) else [],
            "languages": it.get("languages") if isinstance(it.get("languages"), list) else [],
            "material_types": it.get("material_types") if isinstance(it.get("material_types"), list) else [],
            "extra_prompt": it.get("extra_prompt") if isinstance(it.get("extra_prompt"), str) else "",
        })
    if not items:
        raise HTTPException(400, "没有可执行的行：请提供 CSV 或 items（每行需含 landing_text）")
    if len(items) > 200:
        raise HTTPException(400, "单批最多 200 行，请拆分后提交")
    defaults = {
        "platforms": req.platforms or ["Facebook"],
        "languages": req.languages or ["en"],
        "material_types": req.material_types or ["copy"],
        "extra_prompt": req.extra_prompt or "",
    }
    job = Job(type="batch_generate", status="pending", total=len(items),
              payload={"items": items, "defaults": defaults, "skipped": skipped,
                       "owner_id": user.id})
    db.add(job); db.commit(); db.refresh(job)
    _spawn(run_job(job.id))
    return job

@router.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 20, db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).limit(limit).all()

@router.get("/jobs/{jid}", response_model=JobOut)
def get_job(jid: int, db: Session = Depends(get_db)):
    j = db.query(Job).filter_by(id=jid).first()
    if not j:
        raise HTTPException(404, "任务不存在")
    return j

@router.post("/jobs/{jid}/cancel", response_model=JobOut)
def cancel_job(jid: int, db: Session = Depends(get_db)):
    j = db.query(Job).filter_by(id=jid).first()
    if not j:
        raise HTTPException(404, "任务不存在")
    if j.status in ("success", "failed", "canceled"):
        return j
    j.cancel_requested = True   # 当前条目结束后停止
    db.commit(); db.refresh(j)
    return j


# ----------------------------- V1.2 版本链 / 对比 / A/B -----------------------------
def _slot_of(m: Material) -> dict:
    return {"campaign_id": m.campaign_id, "platform": m.platform,
            "language": m.language, "type": m.type}

def _slot_query(db: Session, m: Material):
    return db.query(Material).filter(
        Material.campaign_id == m.campaign_id, Material.type == m.type,
        Material.platform == m.platform, Material.language == m.language)

def _text_ext(m: Material) -> str:
    if m.type == "keyword":
        return ".csv"
    if m.type == "video":
        return ".json"     # 分镜脚本以 JSON 交付，便于剪辑/自动化读取
    return ".txt"

def _material_ext(m: Material) -> str:
    if m.file_path and os.path.exists(m.file_path):
        return os.path.splitext(m.file_path)[1]
    return _text_ext(m)

def _chars_of(v):
    if isinstance(v, list):
        return [len(str(x)) for x in v]
    if isinstance(v, str):
        return len(v)
    return None

def _brief(m: Material) -> dict:
    text = (m.text_content or "").replace("\n", "")
    return {
        "id": m.id, "version": m.version, "variant": m.variant or f"V{m.version}",
        "selected": bool(m.selected), "platform": m.platform, "language": m.language,
        "type": m.type, "content": m.content or {}, "text": m.text_content or "",
        "char_total": len(text), "validation": m.validation, "prompt_log": m.prompt_log,
    }

@router.get("/materials/{mid}/versions", response_model=SlotVersionsOut)
def material_versions(mid: int, db: Session = Depends(get_db)):
    """同一素材位（平台×语言×类型）的全部版本，构成版本链。"""
    m = db.query(Material).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    rows = _slot_query(db, m).order_by(Material.version.asc()).all()
    return {"slot": _slot_of(m), "count": len(rows), "versions": rows}

@router.get("/campaigns/{cid}/slots")
def campaign_slots(cid: int, db: Session = Depends(get_db)):
    """按素材位聚合，返回每个位点的版本概览（供 A/B 面板渲染）。"""
    mats = db.query(Material).filter_by(campaign_id=cid).order_by(Material.id).all()
    if not mats:
        return {"campaign_id": cid, "slots": []}
    slots: dict = {}
    for m in mats:
        key = (m.platform, m.language, m.type)
        s = slots.setdefault(key, {
            "platform": m.platform, "language": m.language, "type": m.type,
            "variants": [], "selected_id": None,
        })
        s["variants"].append({
            "id": m.id, "version": m.version, "variant": m.variant or f"V{m.version}",
            "selected": bool(m.selected), "valid": bool((m.validation or {}).get("valid", True)),
            "issues": len((m.validation or {}).get("issues") or []),
            "chars": len((m.text_content or "").replace("\n", "")),
            "prompt_log": m.prompt_log,
        })
        if m.selected:
            s["selected_id"] = m.id
    for s in slots.values():
        s["variants"].sort(key=lambda x: x["version"])
    return {"campaign_id": cid, "slots": list(slots.values())}

@router.get("/materials/{mid}/compare")
def compare_material(mid: int, against: int = Query(..., description="对比的另一版本 material id"),
                     db: Session = Depends(get_db)):
    """两个版本的结构化差异（逐字段 + 字数），用于并排对比。"""
    a = db.query(Material).filter_by(id=mid).first()
    b = db.query(Material).filter_by(id=against).first()
    if not a or not b:
        raise HTTPException(404, "素材不存在")
    if (a.campaign_id, a.platform, a.language, a.type) != (b.campaign_id, b.platform, b.language, b.type):
        raise HTTPException(400, "只能对比同一素材位的版本")
    ca = a.content if isinstance(a.content, dict) else {}
    cb = b.content if isinstance(b.content, dict) else {}
    fields = []
    for k in list(dict.fromkeys(list(ca.keys()) + list(cb.keys()))):
        lv, rv = ca.get(k), cb.get(k)
        fields.append({"key": k, "left": lv, "right": rv, "changed": lv != rv,
                       "left_chars": _chars_of(lv), "right_chars": _chars_of(rv)})
    return {
        "slot": _slot_of(a),
        "left": _brief(a),
        "right": _brief(b),
        "char_delta": _brief(b)["char_total"] - _brief(a)["char_total"],
        "fields": fields,
        "changed_count": sum(1 for f in fields if f["changed"]),
    }

@router.post("/materials/{mid}/select", response_model=MaterialOut)
def select_material(mid: int, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*CAN_EDIT))):
    """定稿：同组内只保留一个选用版本。"""
    m = db.query(Material).filter_by(id=mid).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    _slot_query(db, m).update({"selected": False})
    m.selected = True
    db.commit(); db.refresh(m)
    return m

@router.get("/export/ab/{cid}")
def export_ab(cid: int, selected_only: bool = Query(False, description="仅导出已定稿变体"),
              db: Session = Depends(get_db)):
    """A/B 分组导出：每个素材位一个目录，内含 A/B/C… 变体 + ab_plan.csv。"""
    c = db.query(Campaign).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    mats = db.query(Material).filter_by(campaign_id=cid).order_by(Material.id).all()
    if not mats:
        raise HTTPException(400, "该 Campaign 暂无素材")

    slots: dict = {}
    for m in mats:
        slots.setdefault((m.platform, m.language, m.type), []).append(m)

    buf = io.BytesIO()
    plan_rows = []
    used_dirs = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for (platform, lang, mtype), rows in slots.items():
            rows.sort(key=lambda x: x.version)
            chosen = [r for r in rows if r.selected]
            if selected_only:
                rows = chosen or rows[-1:]   # 未定稿时退回最新版本
            base_dir = _slug(f"{platform}_{lang}_{mtype}")
            d, i = base_dir, 2
            while d in used_dirs:
                d = f"{base_dir}_{i}"; i += 1
            used_dirs.add(d)
            for m in rows:
                variant = m.variant or f"V{m.version}"
                size_tag = ""
                if m.type == "image" and isinstance(m.spec_json, dict) and m.spec_json.get("size"):
                    size_tag = "_" + str(m.spec_json["size"])
                fname = f"{variant}_v{m.version}{size_tag}{_material_ext(m)}"
                target = f"{d}/{fname}"
                if m.file_path and os.path.exists(m.file_path):
                    z.write(m.file_path, target)
                else:
                    z.writestr(target, _material_text(m))
                plan_rows.append({
                    "slot_dir": d, "platform": platform, "language": lang or "", "type": mtype,
                    "variant": variant, "version": m.version, "material_id": m.id,
                    "selected": "Y" if m.selected else "",
                    "valid": "Y" if (m.validation or {}).get("valid", True) else "N",
                    "issues": len((m.validation or {}).get("issues") or []),
                    "chars": len((m.text_content or "").replace("\n", "")),
                    "file": fname,
                    "prompt_log": (m.prompt_log or "").replace("\n", " "),
                })
        buf_csv = io.StringIO()
        w = csv.DictWriter(buf_csv, fieldnames=list(plan_rows[0].keys()) if plan_rows else ["slot_dir"])
        w.writeheader(); w.writerows(plan_rows)
        z.writestr("ab_plan.csv", "\ufeff" + buf_csv.getvalue())
        z.writestr("manifest.json", json.dumps({
            "campaign": {"id": c.id, "name": c.name, "platforms": c.platforms},
            "mode": "selected_only" if selected_only else "all_variants",
            "slots": len(slots), "files": len(plan_rows),
        }, ensure_ascii=False, indent=2))
    buf.seek(0)
    suffix = "selected" if selected_only else "ab"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="campaign_{cid}_{suffix}.zip"'})


# ----------------------------- V2.0 登录 / 用户 / 审阅 / 审计 -----------------------------
def _audit(db: Session, user, action: str, target: str = None, detail: dict = None):
    db.add(AuditLog(username=getattr(user, "username", None), action=action,
                    target=target, detail=detail))
    db.commit()

@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    u = db.query(User).filter((User.email == req.email) | (User.username == req.email)).first()
    if not u or not u.active or not verify_password(req.password, u.password_hash, u.salt):
        raise HTTPException(401, "邮箱或密码错误")
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

# ---- 审阅流：draft → in_review → approved / rejected ----
def _record_review(db: Session, c: Campaign, action: str, to_status: str, user: User, comment: str = None):
    db.add(ReviewRecord(campaign_id=c.id, action=action, comment=comment, user_id=user.id,
                        username=user.username, from_status=c.status, to_status=to_status))
    if to_status:
        c.status = to_status
        if action in ("approve", "reject"):
            c.reviewer_id = user.id
            c.review_note = comment

@router.post("/campaigns/{cid}/submit", response_model=CampaignOut)
def submit_review(cid: int, req: ReviewRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*CAN_EDIT))):
    c = db.query(Campaign).options(selectinload(Campaign.materials)).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    if c.status == "in_review":
        raise HTTPException(400, "已在审阅中")
    if not (c.materials or []):
        raise HTTPException(400, "没有素材可提交")
    _record_review(db, c, "submit", "in_review", user, req.comment)
    db.commit(); db.refresh(c)
    _ = list(c.materials)
    return c

@router.post("/campaigns/{cid}/approve", response_model=CampaignOut)
def approve_review(cid: int, req: ReviewRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*CAN_REVIEW))):
    c = db.query(Campaign).options(selectinload(Campaign.materials)).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    if c.status not in ("in_review", "rejected"):
        raise HTTPException(400, f"当前状态 {c.status} 不可通过（需先提交审阅）")
    _record_review(db, c, "approve", "approved", user, req.comment)
    db.commit(); db.refresh(c)
    _ = list(c.materials)
    return c

@router.post("/campaigns/{cid}/reject", response_model=CampaignOut)
def reject_review(cid: int, req: ReviewRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*CAN_REVIEW))):
    c = db.query(Campaign).options(selectinload(Campaign.materials)).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    if c.status != "in_review":
        raise HTTPException(400, "只有在审阅中的方案可以驳回")
    if not req.comment:
        raise HTTPException(400, "驳回必须填写原因")
    _record_review(db, c, "reject", "rejected", user, req.comment)
    db.commit(); db.refresh(c)
    _ = list(c.materials)
    return c

@router.post("/campaigns/{cid}/comment")
def add_comment(cid: int, req: ReviewRequest, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*CAN_EDIT))):
    c = db.query(Campaign).filter_by(id=cid).first()
    if not c:
        raise HTTPException(404, "Campaign 不存在")
    _record_review(db, c, "comment", None, user, req.comment)
    db.commit()
    return {"ok": True}

@router.get("/campaigns/{cid}/reviews")
def list_reviews(cid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.query(ReviewRecord).filter_by(campaign_id=cid).order_by(ReviewRecord.id).all()
    return [{"id": r.id, "action": r.action, "comment": r.comment, "username": r.username,
             "from_status": r.from_status, "to_status": r.to_status, "created_at": r.created_at}
            for r in rows]

# ---- 规格库后台维护 ----
@router.put("/platform-specs/{sid}")
def update_spec(sid: int, req: SpecUpdate, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*CAN_REVIEW))):
    s = db.query(PlatformSpec).filter_by(id=sid).first()
    if not s:
        raise HTTPException(404, "规格不存在")
    before = {"image_sizes": s.image_sizes, "copy_limits": s.copy_limits}
    for k, v in req.dict(exclude_unset=True).items():
        if v is not None:
            setattr(s, k, v)
    s.updated_at = datetime.utcnow()
    db.commit(); db.refresh(s)
    _audit(db, user, "spec.update", s.platform,
           {"before": before, "after": {"image_sizes": s.image_sizes, "copy_limits": s.copy_limits}})
    return {"id": s.id, "platform": s.platform, "ad_placement": s.ad_placement,
            "image_sizes": s.image_sizes, "video_spec": s.video_spec, "copy_rules": s.copy_rules,
            "keyword_logic": s.keyword_logic, "copy_limits": s.copy_limits,
            "updated_at": s.updated_at}

@router.get("/audit-logs")
def audit_logs(limit: int = 50, db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "username": r.username, "action": r.action, "target": r.target,
             "detail": r.detail, "created_at": r.created_at} for r in rows]
