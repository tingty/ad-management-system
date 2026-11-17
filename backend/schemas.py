from pydantic import BaseModel, model_validator, field_serializer
from typing import Optional, List, Any
from datetime import datetime, timezone

class ModelConfigIn(BaseModel):
    name: Optional[str] = None
    usage: Any = "analysis"          # 单用途字符串，或多用途数组
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    params: Optional[dict] = None
    is_active: bool = True

class ModelTestIn(BaseModel):
    """连通测试只需 provider + 连接信息，不依赖 usage（避免与创建校验耦合）。"""
    provider: str = "custom"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    endpoint: Optional[str] = None
    # V4.75：视频/图像测试需要厂商契约参数（endpoint / body_shape / async_header / poll_path）。
    # 此前缺少该字段，routers.test_model 读取 req.params 会抛 AttributeError → 接口 500，
    # 前端「保存并测试」必然失败。
    params: Optional[dict] = None

class ModelConfigOut(BaseModel):
    id: int
    name: Optional[str] = None
    usage: Optional[str] = None        # 主用途（兼容旧数据）
    usages: Optional[List[str]] = None # 多用途数组（旧数据可能为 NULL）
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    params: Optional[Any] = None
    is_active: bool = True
    # V4.34 连通性健康状态（由每日自动测试 / 手动测试写回）
    last_test_ok: Optional[bool] = None          # None=未测试 / True=成功 / False=失败
    last_test_at: Optional[datetime] = None
    last_test_http_code: Optional[int] = None
    last_test_error: Optional[str] = None
    last_test_latency_ms: Optional[int] = None
    in_use: bool = False                          # 是否为该用途当前实际生效（被系统功能采用）的配置
    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _fill_usages(self):
        # 兼容未迁移的旧数据：usages 为 NULL 时由 usage(单字符串) 推导；
        # 始终保证返回的是 list（前端依赖 m.usages.length / .map），避免序列化直接 500。
        if self.usages is None:
            self.usages = [self.usage] if self.usage else []
        return self

    @field_serializer("last_test_at")
    def _ser_last_test_at(self, v: Optional[datetime]) -> Optional[str]:
        # SQLite 取回的是 naive UTC；补 +00:00 让前端按本地时区正确显示，避免差 8 小时
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()

class PromptOut(BaseModel):
    id: int
    key: str
    name: str
    module: str
    category: Optional[str] = None
    func_type: Optional[str] = None
    usage_type: Optional[str] = None
    description: Optional[str] = None
    content: str
    is_active: bool = True
    updated_at: Optional[Any] = None
    class Config:
        from_attributes = True

class PromptUpdate(BaseModel):
    content: str
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    func_type: Optional[str] = None
    usage_type: Optional[str] = None
    is_active: Optional[bool] = None

class PromptDefaultIn(BaseModel):
    """V4.35：把总结库里的一条优秀提示词设为系统默认（id 为空 = 恢复系统内置默认）。"""
    kind: str                       # ad_copy / ad_image
    id: Optional[str] = None

# ----------------------------- 素材创作：落地页分析（8 字段 LLM 推理） -----------------------------
class LandingAnalysisRequest(BaseModel):
    """落地页分析请求：给 URL 抓取，或直接给正文。"""
    url: Optional[str] = None
    text: Optional[str] = None

class LandingChannel(BaseModel):
    """推广途径：媒体平台 + 推荐理由 / 数据依据。"""
    platform: str
    reason: str

class ModelInfo(BaseModel):
    """本次分析实际调用的大模型信息（V4.39 / F10：调用快照，不含任何凭据）。"""
    model_config = {"protected_namespaces": ()}   # 允许字段名 model_info 不被 "model_" 保护前缀拦截
    provider: str = ""          # 厂商，如 openai / dashscope / anthropic
    model: str = ""             # 具体模型标识
    role: str = "analysis"      # 实际用途：analysis / copy（分析模型未配时复用文案模型）
    fallback: bool = True       # True = 调用后确实走了 Mock 兜底
    config_id: Optional[int] = None    # 实际调用的配置 id（与设置页「系统采用」一致）
    source: str = "local"       # llm / mock / invalid_response / local
    request_id: str = ""        # 单次调用标识，便于日志追溯
    error_type: str = ""        # timeout / auth / rate_limit / network / upstream
    retries: int = 0

class LandingAnalysis(BaseModel):
    """落地页分析结果：8 个必要字段 + 模型信息 + 来源标记。"""
    url: str = ""               # (1) 网站地址 —— 仅展示，不做分析
    logo: str = ""              # 从落地页抓取到的品牌 / 公司 logo（绝对 URL，可空）
    language: str = ""          # (2) 语言
    industry: str = ""          # (3) 行业
    type: str = ""              # (4) 类型（网站属性：公益/电商/技术服务/家政/旅游/政府…）
    audience: str = ""          # (5) 对象（目标人群 / 对象 / 地区）
    competitors: List[str] = []  # (6) 竞品（全球排名 top 3）
    advantages: List[str] = []   # (7) 优势（提炼核心卖点，非功能罗列，默认 ≤5）
    channels: List[LandingChannel] = []  # (8) 推广途径（媒体平台 + 推荐理由，默认 ≤5）
    model_info: ModelInfo = ModelInfo()
    source: str = "local"       # llm / mock / local —— 结果真的来自大模型、Mock 还是本地兜底
    # V4.39 / F02：抓取环境与品牌 / Logo 证据，输入链接保留用于追踪，不作为产品身份
    brand: str = ""
    brand_status: str = "needs_input"       # confirmed / unverified / needs_input
    brand_candidates: List[str] = []
    brand_reason: str = ""
    logo_source: str = ""
    logo_verified: bool = False
    logo_reason: str = ""
    input_url: str = ""
    final_url: str = ""
    redirect_chain: List[str] = []
    fetch_quality: str = "not_fetched"      # ok / thin_content / fetch_failed / manual_text
    industry_profile: str = "general"       # 行业画像 key（前端可覆盖，实现局部调整）
    industry_profile_label: str = "通用 / 未分类"
    # V4.42 / F09：事实证据链与空证据阻断
    facts: List[str] = []                   # 已验证事实（须有 evidence_ids 可引用）
    assumptions: List[str] = []             # 营销假设，不能当已验证事实投放
    gaps: List[str] = []                    # 资料缺口
    evidence_ids: List[str] = []            # V4.44：本次快照唯一可用编号 [E###]
    evidence_chain: List[Any] = []          # [{claim, evidence_ids, kind, rejected}]
    evidence_index: List[Any] = []          # 原文 / 来源 / 区块 / 字符区间 / 核验状态
    evidence_coverage: List[Any] = []       # 实际送入模型的字符区间
    evidence_dropped_chars: int = 0
    evidence_source_chars: int = 0
    evidence_expired_offers: List[Any] = [] # 已过期优惠，不得沿用
    evidence_note: str = ""
    evidence_gate: str = "ok"               # ok / needs_input
    gate_status: str = "ok"                 # ok / needs_input（router 据此阻断）
    blocked_reasons: List[str] = []
    legacy_unverified: bool = False         # 旧数据无证据 ID，不自动补成已验证
    # V4.44 / N01：不可变证据快照与无效引用审计
    evidence_snapshot_id: str = ""
    evidence_fetched_at: str = ""
    evidence_review_status: str = "locatable_not_reviewed"
    evidence_invalid_ids: List[str] = []
    evidence_ref_audit: dict = {}
    sections_index: List[Any] = []
    class Config:
        from_attributes = True
        protected_namespaces = ()   # 允许字段名 model_info 不被 "model_" 保护前缀拦截

# ----------------------------- 素材创作：营销推广的媒体平台设置 -----------------------------
class MediaCopyRequest(BaseModel):
    """生成媒体平台广告文案：以落地页 8 字段分析结论为依据，调用大模型产出可编辑文案。"""
    analysis: LandingAnalysis      # 落地页分析结论（生成依据）
    platform: str                  # 选中的媒体推广平台
    lang: str = "en"              # 文案语言
    # V4.40 / F08：可选广告产品，用于把 Google RSA 与 UAC 之类不同产品的文案 schema 分开。
    ad_product: str = ""
    # V4.41 / F04：编辑过的方向 / 风格 / 配色预设必须参与文案生成。
    # 只注入 ResolvedCreativeConfig.strategy；纯视觉字段不进入文案大模型。
    style_opts: dict = {}

class MediaImageSlot(BaseModel):
    """V4.40 / F07 + F08：任务矩阵中的一行（一个版位 × 尺寸 × 概念）。

    `size` 仍是自由字符串（旧调用兼容），但格式、允许尺寸与像素上限由服务端规则目录
    `media_platforms.validate_task_matrix()` 在调用模型前统一校验并给出明确错误。
    广告产品 / 资产角色 / 规则版本一律由服务端目录重新解析，不接受客户端自报。
    """
    size: str                     # 尺寸，如 1080x1080
    placement: str = ""          # 广告版位名称（旧调用只传这个）
    placement_id: str = ""       # 广告版位 id（V4.40 任务矩阵传）
    concept_index: Optional[int] = None   # 本任务使用的创意文案组合下标（旧调用为空 → 顺序轮换）
    concept_id: str = ""         # 前端可展示的概念标识（不参与服务端解析）

class MediaCopyVariant(BaseModel):
    """V4.38：一条被用户勾选的「创意文案组合」，作为一张推广图的叠加文案。"""
    headline: str = ""
    sub: str = ""
    cta: str = ""
    brand: str = ""
    label: str = ""

class MediaImageRequest(BaseModel):
    """生成推广图片：依据「勾选的创意文案组合」+ 落地页分析结论 + 风格/样式/颜色选项。"""
    analysis: LandingAnalysis
    platform: str
    lang: str = "en"
    copy_fields: dict = {}       # 编辑后的文案字段（覆盖平台 schema，保留完整文案库）
    # V4.38：不传时兼容旧行为（取每个字段第 1 条）；传入后按版位顺序轮换叠加。
    copy_variants: List[MediaCopyVariant] = []
    style_opts: dict = {}         # {creative_direction, content_style, color_scheme}
    slots: List[MediaImageSlot] = []
    logo: str = ""               # 品牌 logo（/files/... 已上传路径 或 远程 http(s) URL），用于合成到图片
    # V4.40 / F08：客户端声明的规则版本与像素总量，仅用于一致性核对，不作为放行依据。
    spec_version: str = ""
    total_pixels: Optional[int] = None
    # V4.62：叠加模式，控制成图是否含文字/按钮/logo。可选值：
    #   "pure"         — 纯图片，无文字、无按钮、无 logo
    #   "text"         — 图片 + 文字（标题/副标/品牌）+ logo，无按钮
    #   "text_button"  — 图片 + 文字 + 按钮 + logo（默认，保持旧行为向后兼容）
    overlay_mode: str = "text_button"

# ----------------------------- V4.50 创意工作台：全球创意分析 -----------------------------
class CreativeAnalysisRequest(BaseModel):
    """全球创意分析请求：给参考素材链接，或直接给参考文案/描述。"""
    urls: List[str] = []          # 参考素材链接（广告/落地页/竞品创意）
    text: str = ""                # 或直接粘贴参考文案 / 素材描述
    title: Optional[str] = None   # 用户自定义分析标题

class CreativeCategory(BaseModel):
    """LLM 归类出的一种创意风格/类型，附带可复用提示词模板。"""
    name: str = ""                # 创意类型/风格名，如「极简产品特写」
    description: str = ""         # 该类型的定义与适用场景
    traits: List[str] = []        # 关键特征（构图/色调/情绪/文案语气…）
    examples: List[str] = []      # 典型应用场景 / 示例
    image_prompt: str = ""        # 可复用的图片提示词模板
    video_prompt: str = ""        # 可复用的视频提示词模板（本期预留，可空）

class CreativeAnalysisResult(BaseModel):
    """全球创意分析结果：整体洞察 + 归类创意类型 + 实际调用模型快照。"""
    model_config = {"protected_namespaces": ()}   # 允许字段名 model_info 不被 "model_" 保护前缀拦截
    id: Optional[int] = None      # 落库记录 id
    title: str = ""
    summary: str = ""             # 对参考素材的整体洞察与可借鉴点
    categories: List[CreativeCategory] = []
    model_info: ModelInfo = ModelInfo()
    source: str = "local"         # llm / mock / local

class LoginRequest(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    active: bool = True
    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    email: str
    username: Optional[str] = None
    password: str
    display_name: Optional[str] = None
    role: str = "editor"

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None



# ----------------------------- V4.52 创意工作台：创意策略 / 路线规划 -----------------------------
class CreativeRoute(BaseModel):
    """LLM 为单个媒体平台规划的创意路线。"""
    platform: str = ""              # 媒体平台
    concept: str = ""               # 创意概念
    angle: str = ""                 # 切入角度
    visual_style: str = ""          # 视觉风格
    copy_direction: str = ""        # 文案方向
    image_prompt: str = ""          # 用于文生图的创意方向 / 提示词
    notes: str = ""                 # 补充说明


class CreativePlanRequest(BaseModel):
    """创意工作台·创意策略请求：产品分析结论 + 所选媒体平台 → 大模型规划每平台创意路线。"""
    title: Optional[str] = None
    analysis: dict = {}             # LandingAnalysis 结论（dict）
    platforms: List[str] = []
    gen_image: bool = True
    gen_video: bool = False


class CreativePlanResult(BaseModel):
    """创意策略结果：每平台创意路线 + 实际调用模型快照。"""
    model_config = {"protected_namespaces": ()}   # 允许字段名 model_info 不被 "model_" 保护前缀拦截
    id: Optional[int] = None
    title: str = ""
    platforms: List[str] = []
    gen_image: bool = True
    gen_video: bool = False
    routes: List[CreativeRoute] = []
    status: str = "draft"
    asset_count: int = 0
    history_id: Optional[int] = None
    model_info: ModelInfo = ModelInfo()
    source: str = "local"



# ----------------------------- V4.59 / B1：产品来源快照（真实抓取 / 演示 / 手动文本） -----------------------------
class ProductSnapshot(BaseModel):
    """V4.59 / B1：本次产品分析的来源快照，保证结论可追溯、可区分「真实抓取 / 演示 / 手动文本 / 抓取失败」。

    - source: real_fetch（服务端真实抓取并带入证据）/ demo（演示模式样例，非真实结论）/
      pasted（用户粘贴文本）/ fetch_failed（链接不可达，已在调用模型前阻断）/ local（兜底）
    - 仅记录可追溯元数据，绝不带任何凭据；evidence_ids 为本次抓取证据包的可引用编号。
    """
    model_config = {"protected_namespaces": ()}
    source: str = "local"          # real_fetch / demo / pasted / fetch_failed / local
    url: str = ""
    final_url: str = ""            # 抓取后的最终地址（含重定向链终点）
    fetched_at: str = ""           # 抓取时间（ISO UTC）
    fetch_quality: str = "not_fetched"  # ok / thin_content / fetch_failed / manual_text / demo
    snapshot_id: str = ""          # 证据包唯一 id（可追溯到 [E###] 采样）
    title: str = ""                # 抓到的页面标题（或演示标识）
    evidence_ids: List[str] = []


# ----------------------------- V4.53 创意工作台：设计对齐的产品分析 + 3 条创意路线 -----------------------------
class CWAnalyzeRequest(BaseModel):
    """创意工作台·产品分析请求：产品链接 / 文本 + 所选媒体平台 → 大模型产出产品定位与项目简报。

    V4.59 / B1：新增 `demo_mode` —— 仅当它显式为 True 时才返回「降噪耳机」样例数据，
    并标注 source=demo；默认关闭，避免解析失败时静默套用演示数据冒充真实分析。
    """
    url: str = ""
    text: str = ""
    platforms: List[str] = []
    demo_mode: bool = False


class CWAnalysisResult(BaseModel):
    """产品分析结果：一句话定位 + 4 个分析盒 + 项目简报（推广目标 / 目标受众 / 核心卖点）。

    V4.58 / B2：新增 `analysis`，作为「生成素材」的唯一权威依据（替代前端再调一次
    landing-analysis 产生的第二份分析），保证路线规划与图片生成都来自同一份结论。
    `analysis` 兼容媒体生成链路（media_ad）读取的字段（industry/type/audience/advantages/
    channels/language/industry_profile 等），并保留 boxes/brief 嵌套以便前端展示。
    """
    model_config = {"protected_namespaces": ()}
    id: Optional[int] = None
    title: str = ""
    summary: str = ""
    boxes: dict = {}                 # {industry, coreAudience, purchaseMotivation, priceBand}
    brief: dict = {}                 # {promotionGoal, targetAudience:[], sellingPoints:[]}
    recommendedPlatforms: List[str] = []
    analysis: dict = {}              # 生成所需统一分析来源（B2：消除二次模型理解）
    snapshot: ProductSnapshot = ProductSnapshot()   # V4.59 / B1：来源快照（真实抓取/演示/手动文本）
    model_info: ModelInfo = ModelInfo()
    source: str = "local"


class CWRoutesRequest(BaseModel):
    """创意工作台·创意路线请求：产品分析 + 所选平台 + 项目简报 → 大模型规划 3 条创意概念路线。"""
    plan_id: Optional[int] = None
    analysis: dict = {}
    platforms: List[str] = []
    brief: dict = {}


# ----------------------------- V4.61 / B4：创意工作台「素材沉淀库」 -----------------------------
class CwLibraryOut(BaseModel):
    """素材沉淀库条目（响应）。"""
    model_config = {"protected_namespaces": ()}
    id: int
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    kind: str                                  # reference / product / brand
    title: str = ""
    file: Optional[str] = None                 # /files/<name>，仅 reference 必填
    url: Optional[str] = None                  # 产品链接（kind=product）
    meta_json: Optional[dict] = None
    source_plan_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CwLibraryCreate(BaseModel):
    """新增/沉淀一条素材库条目（后端按 kind 去重 upsert）。"""
    model_config = {"protected_namespaces": ()}
    kind: str                                  # reference / product / brand
    title: str = ""
    file: Optional[str] = None
    url: Optional[str] = None
    meta: Optional[dict] = None
    source_plan_id: Optional[int] = None


class CWRoute(BaseModel):
    """单条创意路线（概念级，非逐平台）。"""
    key: str = ""                    # A / B / C
    name: str = ""
    description: str = ""
    tags: List[str] = []
    angle: str = ""
    selected: bool = True


class CWRoutesResult(BaseModel):
    """3 条创意路线结果。"""
    model_config = {"protected_namespaces": ()}
    id: Optional[int] = None
    title: str = ""
    routes: List[CWRoute] = []
    model_info: ModelInfo = ModelInfo()
    source: str = "local"


# ----------------------------- V4.66 创意工作台 · 视频素材创作区 -----------------------------
class CWVideoMessage(BaseModel):
    """视频策划对话的一条消息（多轮微调提示词 / 构想 / 方案）。"""
    role: str = "user"          # user / assistant
    content: str = ""


class CWVideoPlanRequest(BaseModel):
    """视频分镜策划请求：产品分析 + 平台 + 参考图 + 对话历史 + 当前方案（可空）→ 大模型产出/微调分镜 JSON。"""
    model_config = {"protected_namespaces": ()}
    analysis: dict = {}             # 创意工作台「统一分析来源」（同 cw/analyze 的 analysis 字段）
    platform: str = ""
    reference_image: str = ""      # /files/<name> 或 URL（图生视频参考图）
    brand_logo: str = ""           # /files/<name> 或 URL（品牌 Logo，勾选「注入生成链路」时带入）
    messages: List[CWVideoMessage] = []   # 多轮对话（含 user 微调 + assistant 上一轮回复）
    current_plan: Optional[dict] = None   # 已有的分镜方案（微调时带入，由模型增量修订）
    options: dict = {}             # {mode, voiceover, duration, aspect, lang}


class CWVideoPlanResult(BaseModel):
    """视频分镜策划结果：自然语言回复 + 分镜方案 JSON + 模型快照。

    V4.78 起把「分镜文案模型」与「出片模型」彻底分开：
    - `model_info`：本次分镜策划实际调用的**文本**模型（role=analysis）——它只写分镜文案；
    - `video_model_info`：真正负责出片的**视频**模型（role=video），未配置时 provider=storyboard。
    此前两者共用 `model_info`，导致视频面板把文本模型（如 deepseek）显示成视频模型。
    """
    model_config = {"protected_namespaces": ()}
    reply: str = ""                # 给用户的自然语言回复 / 建议
    plan: dict = {}                # VIDEO_JSON v2 风格的分镜方案（duration/shots/...）
    model_info: ModelInfo = ModelInfo()
    video_model_info: ModelInfo = ModelInfo()   # 实际出片模型（V4.78）
    video_model_ready: bool = False             # 出片模型是否就绪（未就绪将回退分镜）
    output_aspect: str = ""        # 实际输出比例（如 9:16）；视频模型固定比例时显式标注
    source: str = "local"          # llm / mock / local
    # V4.82：分镜已过证据 / 限定审计；generation_blocked 时提交端会拒绝入队
    claim_status: str = "ok"
    generation_blocked: bool = False
    delivery_grade: str = "draft"


class CWVideoGenerateRequest(BaseModel):
    """视频生成请求：分镜方案 + 选项 + 分析/平台/参考图 → 调用真实视频模型或回退分镜脚本。"""
    model_config = {"protected_namespaces": ()}
    analysis: dict = {}
    platform: str = ""
    reference_image: str = ""
    brand_logo: str = ""          # /files/<name> 或 URL（品牌 Logo，勾选「注入生成链路」时带入）
    plan: dict = {}                # 来自 /cw-video/plan 的 plan（含 shots / duration / aspect / ...）
    options: dict = {}             # {mode, voiceover, duration, aspect, lang, prompt_hint}


class CWVideoAsset(BaseModel):
    """单个视频产物（本地 /files 直链或外部 URL）。"""
    type: str = "video"
    url: str = ""
    caption: str = ""
    shot_index: Optional[int] = None
    duration_sec: float = 0            # 实测成片时长（读 mvhd / ffprobe），拿不到时退回计划时长
    duration_source: str = ""          # measured（实测）/ planned（计划值兜底）


class CWVideoGenerateResult(BaseModel):
    """视频生成结果：实际视频产物（若有）+ 分镜方案（始终返回）+ 模型快照。

    V4.79：失败不再伪装成成功。`error_code` 非空即表示本次出片失败，`videos` 必为空，
    但仍回传 `storyboard`（可执行分镜）作为兜底交付物；`error_action` 是唯一建议动作，
    `evidence` 是脱敏证据链（提交/轮询/下载各阶段原文），供用户与管理员定位。
    """
    model_config = {"protected_namespaces": ()}
    provider: str = "storyboard"   # model / kling / storyboard
    model: str = ""
    videos: List[CWVideoAsset] = []
    storyboard: dict = {}          # VIDEO_JSON v2 分镜方案（展示 + 可下载）
    model_info: ModelInfo = ModelInfo()
    note: str = ""                 # 人类可读说明（如「未配置视频模型，已回退分镜」）
    output_aspect: str = ""        # 实际输出比例（如 9:16）；视频模型固定比例时显式标注
    source: str = "local"
    # ---- V4.79 失败可分类 ----
    stage: str = ""                # 失败阶段：config / submit / poll / download / storage
    error_code: str = ""           # 空 = 成功；非空见 providers._VIDEO_ERROR_ACTIONS
    error_message: str = ""        # 厂商原文摘要（已脱敏）
    error_action: str = ""         # 唯一可执行动作
    error_task_id: str = ""        # 厂商任务号（POLL_TIMEOUT 时可凭它继续查询）
    evidence: dict = {}            # 脱敏证据链
    # V4.83 / C05：交付时长判定（实测来自媒体探测，不由计划值回填）
    requested_duration: float = 0
    measured_duration: float = 0
    delivery_status: str = ""      # compliant / noncompliant / unverified
    # V4.84：标准库规格复核（生成前冻结 spec_ref → 交付时用实测值复核）
    spec_check: dict = {}          # {status, spec_ok, reasons, note, verification, library_version}
    spec_ref: dict = {}            # 生成前冻结的平台规格目标（比例/尺寸/时长区间/伴随素材/来源）


class CWVideoJobOut(BaseModel):
    """视频出片后台任务状态（V4.76 / V4.79）。

    出片是分钟级长任务，直接放在 HTTP 请求里会被反向代理（nginx 默认 60s、
    Cloudflare 100s）掐断成 504。这里改为「提交即返回 + 前端轮询」：
    - queued / running：任务在后台跑，前端按 elapsed_sec 展示已等待时长；
    - done：真的出了成片（result.videos 非空）；
    - needs_attention：链路跑完但没出片，result 里带 error_code / error_action / evidence，
      分镜仍可用；**不再用 done 掩盖失败**；
    - error：任务本身异常终止（服务端 bug / 进程被杀）。
    """
    model_config = {"protected_namespaces": ()}
    job_id: str = ""
    status: str = "queued"         # queued / running / done / needs_attention / error
    stage: str = ""                # 阶段描述（提交中 / 等待模型出片 / 取片写入 / 完成）
    elapsed_sec: int = 0
    error: str = ""
    error_code: str = ""
    error_action: str = ""
    batch_id: str = ""             # V4.81：所属创作批次（任务抽屉按批次聚合展示）
    result: Optional[CWVideoGenerateResult] = None
