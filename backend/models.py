from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

def utcnow():
    return datetime.now(timezone.utc)

class LandingPage(Base):
    __tablename__ = "landing_pages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(1024), nullable=True)
    raw_text = Column(Text, nullable=True)
    parsed_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)

class Framework(Base):
    __tablename__ = "frameworks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    landing_page_id = Column(Integer, ForeignKey("landing_pages.id"), nullable=True)
    product = Column(String(255))
    category = Column(String(255), nullable=True)
    audience = Column(Text, nullable=True)
    geo = Column(Text, nullable=True)
    languages = Column(JSON, nullable=True)
    selling_points = Column(JSON, nullable=True)
    platform_analysis = Column(JSON, nullable=True)
    raw_json = Column(JSON, nullable=True)
    # V3.0 创意工厂：品类、可量化指标、品牌色、上传素材、分析来源
    domain = Column(String(32), nullable=True)
    metrics = Column(JSON, nullable=True)
    brand_color = Column(String(16), nullable=True)
    assets = Column(JSON, nullable=True)
    analyzer = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    @property
    def evidence(self):
        """抽取依据（存在 raw_json 里），供前端展示"这条结论从哪来"。"""
        return self.raw_json or {}

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    framework_id = Column(Integer, ForeignKey("frameworks.id"))
    platforms = Column(JSON, nullable=True)
    status = Column(String(32), default="draft")   # draft/in_review/approved/rejected/active
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note = Column(Text, nullable=True)
    angle_keys = Column(JSON, nullable=True)     # 本次生产选中的创意方向
    options = Column(JSON, nullable=True)        # 本次生产参数（尺寸数/视频策略/类型/语言）
    created_at = Column(DateTime, default=utcnow)
    materials = relationship("Material", back_populates="campaign", cascade="all, delete-orphan")

class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    type = Column(String(32))            # image / video / copy / keyword
    platform = Column(String(64))
    language = Column(String(16), nullable=True)
    spec_json = Column(JSON, nullable=True)
    content = Column(JSON, nullable=True)
    text_content = Column(Text, nullable=True)
    file_path = Column(String(512), nullable=True)
    version = Column(Integer, default=1)
    variant = Column(String(8), nullable=True)     # A/B/C 变体标签（与版本序号对应）
    selected = Column(Boolean, default=False)      # 组内选用标记（A/B 定稿）
    prompt_log = Column(Text, nullable=True)
    angle_key = Column(String(32), nullable=True)   # 所属创意方向
    validation = Column(JSON, nullable=True)   # 规格校验结果
    created_at = Column(DateTime, default=utcnow)
    campaign = relationship("Campaign", back_populates="materials")

class Angle(Base):
    """创意方向：投放人员做素材的最小单位（洞察 + 钩子 + 视觉方案）。"""
    __tablename__ = "angles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    framework_id = Column(Integer, ForeignKey("frameworks.id"), index=True)
    key = Column(String(32))          # pain / benefit / proof / curiosity / ugc / promo
    name = Column(String(64))
    insight = Column(Text, nullable=True)
    visual = Column(Text, nullable=True)
    template = Column(String(32), nullable=True)
    hook = Column(Text, nullable=True)
    kpi = Column(String(64), nullable=True)
    platform_fit = Column(JSON, nullable=True)
    sort = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class PlatformSpec(Base):
    __tablename__ = "platform_specs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(64))
    ad_placement = Column(String(64), nullable=True)
    image_sizes = Column(JSON, nullable=True)
    video_spec = Column(Text, nullable=True)
    copy_rules = Column(Text, nullable=True)
    keyword_logic = Column(Text, nullable=True)
    copy_limits = Column(JSON, nullable=True)   # 结构化字数红线
    updated_at = Column(DateTime, default=utcnow)

class Job(Base):
    """异步任务（批量生成）。进度以 DB 为准，前端轮询。"""
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(32), default="batch_generate")
    status = Column(String(16), default="pending")   # pending/running/success/partial/failed/canceled
    total = Column(Integer, default=0)
    done = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    payload = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)             # [{index, name, campaign_id, framework_id, materials, error}]
    error = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class ModelConfig(Base):
    __tablename__ = "model_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    usage = Column(String(32))          # analysis / copy / image / video
    provider = Column(String(64))
    api_key = Column(String(512), nullable=True)
    base_url = Column(String(512), nullable=True)
    model = Column(String(128), nullable=True)
    params = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


# ----------------------------- V2.0 用户 / 审阅 / 审计 -----------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True)
    display_name = Column(String(64), nullable=True)
    password_hash = Column(String(256))
    salt = Column(String(64))
    role = Column(String(16), default="editor")     # admin / manager / editor / viewer
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class ReviewRecord(Base):
    __tablename__ = "review_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    action = Column(String(16))      # submit / approve / reject / comment
    comment = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(64), nullable=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=True)
    action = Column(String(64))      # spec.update / user.create / model.update ...
    target = Column(String(128), nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
