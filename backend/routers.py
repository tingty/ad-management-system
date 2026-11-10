from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from datetime import datetime
import os, time, re

from database import get_db
from models import (ModelConfig, User, AuditLog, PromptConfig, SystemState,
                    CreationHistory, utcnow)
from schemas import (ModelConfigIn, ModelConfigOut, ModelTestIn,
                     LoginRequest, UserOut, UserCreate, UserUpdate,
                     PromptOut, PromptUpdate, PromptDefaultIn,
                     LandingAnalysisRequest, LandingAnalysis, MediaCopyRequest, MediaImageRequest)
from services import PROMPT_REGISTRY, analyze_landing_concise
from llm_catalog import test_llm_connection, _resolve_protocol
from presets import creative_presets_payload
from prompt_catalog import (library_dimensions, library_entries,
                            get_practice, target_key_for_kind, KINDS, FUNC_TYPES,
                            USAGE_TYPES, BEST_PRACTICES)
from media_platforms import list_media_platforms
from media_ad import generate_media_copy, generate_media_images
from auth import (current_user, require_roles, verify_password, hash_password, create_token,
                  user_dict, ROLE_LABELS, CAN_EDIT, CAN_REVIEW, ROLES, decode_token)
from creation_history import (
    history_to_dict, derive_title, site_name_of, safe_image_path,
    media_type_of, image_files_of, copy_as_text, build_files_zip,
    build_history_zip, cleanup_orphan_files,
)

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
    return LandingAnalysis(**result)

# ----------------------------- 素材创作：营销推广的媒体平台设置 -----------------------------
@router.get("/media-platforms")
async def api_media_platforms(_: User = Depends(require_roles(*CAN_EDIT))):
    """营销推广媒体平台规格：数量 / 规格 / 尺寸 / 常规方案 / 字数红线。供前端展示与预选。"""
    return list_media_platforms()


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
    result = await generate_media_copy(db, req.analysis.model_dump(), req.platform, req.lang)
    return result

@router.post("/media-campaign/images")
async def api_media_campaign_images(req: MediaImageRequest, db: Session = Depends(get_db),
                                    user: User = Depends(require_roles(*CAN_EDIT))):
    """基于「勾选的创意文案组合」+ 落地页分析结论 + 风格/样式/颜色，生成推广图片素材。

    V4.38：copy_variants 由前端按用户勾选的文案拼出，后端按版位顺序轮换叠加；
    未传时兼容旧行为。每张图片会标注所用文案组合，未配置文生图模型时自动用模板兜底。
    """
    slots = [s.model_dump() for s in req.slots]
    variants = [v.model_dump() for v in req.copy_variants]
    result = await generate_media_images(db, req.analysis.model_dump(), req.platform, req.lang,
                                         req.copy_fields, req.style_opts, slots, req.logo or "",
                                         copy_variants=variants)
    return result


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
    for r in rows:
        db.delete(r)
    db.commit()
    deleted_files = cleanup_orphan_files(db, targets)   # commit 之后再清磁盘，避免误删共享图片
    _audit(db, user, "history.delete", target="creation_history",
           detail={"ids": found, "deleted_files": deleted_files})
    return {"ok": True, "deleted": len(found), "deleted_files": deleted_files}


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
        row.images_json = uniq[-80:]        # 单会话最多保留 80 张，防止无限膨胀
        row.image_count = len(row.images_json)
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
def release_notes(_: User = Depends(require_roles(*ROLES))):
    """返回版本发布更新内容，供前端「新版通知」展示。"""
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

@router.get("/audit-logs")
def audit_logs(limit: int = 50, db: Session = Depends(get_db),
               _: User = Depends(require_roles("admin"))):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "username": r.username, "action": r.action, "target": r.target,
             "detail": r.detail, "created_at": r.created_at} for r in rows]
