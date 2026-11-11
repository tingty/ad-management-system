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
