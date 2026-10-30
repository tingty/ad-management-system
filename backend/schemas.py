from pydantic import BaseModel
from typing import Optional, List, Any

class AnalyzeRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None

class ReportRequest(BaseModel):
    """分析报告请求：URL 抓取，或直接给正文；platforms 会影响方向推荐。"""
    url: Optional[str] = None
    text: Optional[str] = None
    platforms: List[str] = []
    lang: Optional[str] = None

class FrameworkOut(BaseModel):
    id: int
    product: str
    category: Optional[str] = None
    audience: Optional[str] = None
    geo: Optional[str] = None
    languages: Optional[Any] = None
    selling_points: Optional[Any] = None
    platform_analysis: Optional[Any] = None
    raw_json: Optional[Any] = None
    domain: Optional[str] = None
    metrics: Optional[Any] = None
    brand_color: Optional[str] = None
    assets: Optional[Any] = None
    analyzer: Optional[str] = None
    evidence: Optional[Any] = None
    class Config:
        from_attributes = True

class GenerateRequest(BaseModel):
    framework_id: int
    campaign_name: str
    platforms: List[str]
    material_types: List[str]   # image / video / copy / keyword
    languages: List[str]
    extra_prompt: Optional[str] = None

class MaterialOut(BaseModel):
    id: int
    campaign_id: int
    type: str
    platform: str
    angle_key: Optional[str] = None
    language: Optional[str] = None
    spec_json: Optional[Any] = None
    content: Optional[Any] = None
    text_content: Optional[str] = None
    file_path: Optional[str] = None
    version: int = 1
    variant: Optional[str] = None
    selected: Optional[bool] = False
    prompt_log: Optional[str] = None
    validation: Optional[Any] = None
    class Config:
        from_attributes = True

class CampaignOut(BaseModel):
    id: int
    name: str
    framework_id: int
    platforms: Optional[Any] = None
    angle_keys: Optional[Any] = None
    options: Optional[Any] = None
    status: str = "draft"
    owner_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    review_note: Optional[str] = None
    materials: List[MaterialOut] = []
    class Config:
        from_attributes = True

class ModelConfigIn(BaseModel):
    usage: str
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    params: Optional[dict] = None
    is_active: bool = True

class ModelConfigOut(BaseModel):
    id: int
    usage: str
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    params: Optional[Any] = None
    is_active: bool = True
    class Config:
        from_attributes = True

class RegenerateRequest(BaseModel):
    extra_prompt: str

class JobCreate(BaseModel):
    """批量任务：可传 CSV 原文（rows）或结构化 items；defaults 为各条缺省配置。"""
    rows: Optional[str] = None
    items: Optional[List[Any]] = None
    platforms: List[str] = []
    languages: List[str] = []
    material_types: List[str] = []
    extra_prompt: Optional[str] = None

class JobOut(BaseModel):
    id: int
    type: str
    status: str
    total: int = 0
    done: int = 0
    failed: int = 0
    payload: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    created_at: Optional[Any] = None
    started_at: Optional[Any] = None
    finished_at: Optional[Any] = None
    class Config:
        from_attributes = True

class BatchParseRequest(BaseModel):
    rows: str

# ----------------------------- V3.0 创意工厂 -----------------------------
class AngleOut(BaseModel):
    id: int
    framework_id: int
    key: str
    name: str
    insight: Optional[str] = None
    visual: Optional[str] = None
    template: Optional[str] = None
    hook: Optional[str] = None
    kpi: Optional[str] = None
    platform_fit: Optional[Any] = None
    sort: int = 0
    class Config:
        from_attributes = True

class AnglePlanRequest(BaseModel):
    framework_id: int
    platforms: List[str] = []
    extra_prompt: Optional[str] = None
    lang: Optional[str] = None

class ProduceRequest(BaseModel):
    framework_id: int
    campaign_name: str
    angle_keys: List[str] = []
    platforms: List[str]
    material_types: List[str] = ["image", "copy"]
    languages: List[str] = []
    extra_prompt: Optional[str] = None
    sizes_per_platform: Optional[int] = None    # 旧字段，等价 sizes_per_angle
    sizes_per_angle: Optional[int] = None       # 每个方向、每个平台出几个版位
    video_mode: Optional[str] = "all"           # off / first / all

class EstimateRequest(BaseModel):
    framework_id: Optional[int] = None
    angle_keys: List[str] = []
    platforms: List[str] = []
    material_types: List[str] = ["image", "copy"]
    languages: List[str] = []
    sizes_per_angle: Optional[int] = None
    video_mode: Optional[str] = "all"


class BrandUpdate(BaseModel):
    brand_color: Optional[str] = None
    assets: Optional[Any] = None

class OptimizeRequest(BaseModel):
    """素材优化：自然语言要求 + 作用范围。scope=all/copy/image，angle_keys 为空表示全部方向。"""
    instruction: str
    scope: str = "all"
    angle_keys: List[str] = []


class SlotVersionsOut(BaseModel):
    slot: Any
    count: int
    versions: List[MaterialOut]


# ----------------------------- V2.0 -----------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: str
    active: bool = True
    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "editor"

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None

class ReviewRequest(BaseModel):
    action: Optional[str] = None   # submit/approve/reject/comment 由接口决定，这里仅承载备注
    comment: Optional[str] = None

class SpecUpdate(BaseModel):
    ad_placement: Optional[str] = None
    image_sizes: Optional[List[str]] = None
    video_spec: Optional[str] = None
    copy_rules: Optional[str] = None
    keyword_logic: Optional[str] = None
    copy_limits: Optional[Any] = None
