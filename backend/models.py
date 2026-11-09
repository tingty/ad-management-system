from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from datetime import datetime, timezone
from database import Base

def utcnow():
    return datetime.now(timezone.utc)

class ModelConfig(Base):
    __tablename__ = "model_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=True)      # 用户自定义的配置名称
    usage = Column(String(32))          # 主用途（兼容旧数据 / 单用途场景，取 usages[0]）
    usages = Column(JSON, nullable=True) # 多用途数组：analysis / copy / image / video
    provider = Column(String(64))
    api_key = Column(String(512), nullable=True)
    base_url = Column(String(512), nullable=True)
    model = Column(String(128), nullable=True)      # 模型版本 / 标识（API 调用使用）
    params = Column(JSON, nullable=True)            # 厂商专属附加字段，如 endpoint
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    # V4.34 连通性健康状态：由「每日自动测试 / 手动测试」写回。
    # last_test_ok: NULL=尚未测试, True=成功, False=失败
    last_test_ok = Column(Boolean, nullable=True)
    last_test_at = Column(DateTime, nullable=True)          # 最后一次测试时间（UTC）
    last_test_http_code = Column(Integer, nullable=True)   # 服务器返回的 HTTP code；网络层失败为 0/NULL
    last_test_error = Column(Text, nullable=True)          # 失败 log：HTTP code + 服务器返回错误 + 诊断
    last_test_latency_ms = Column(Integer, nullable=True) # 成功时记录延迟

class SystemState(Base):
    """轻量 KV：记录全局运行戳（如每日连通测试的最后执行日期），跨进程/多 worker 去重。"""
    __tablename__ = "system_state"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class PromptConfig(Base):
    """系统提示词：按 key 管理各功能模块使用的提示词，设置页可查可改，保存即生效。"""
    __tablename__ = "prompt_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(64), unique=True, index=True)   # site_analysis / angle / copy / landing_*
    name = Column(String(128))                           # 展示名，如「网站核心内容分析」
    module = Column(String(128))                         # 对应功能模块，如「素材创作（落地页分析）」
    category = Column(String(128), nullable=True)        # 分类（如「落地页分析」），用于在「素材提示词」中分门别类展示
    # V4.35「素材提示词」两套分类维度：功能类型（落在哪个生成环节）/ 使用类型（提示词如何被使用）
    func_type = Column(String(64), nullable=True)
    usage_type = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)            # 用途与编辑注意事项
    content = Column(Text)                               # 提示词正文（系统提示词）
    is_active = Column(Boolean, default=True)            # 停用后回退内置默认
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

# ----------------------------- V2.0 用户 / 审阅 / 审计 -----------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True)
    email = Column(String(255), nullable=True, unique=True, index=True)   # 登录邮箱；历史账号由启动补填
    display_name = Column(String(64), nullable=True)
    password_hash = Column(String(256))
    salt = Column(String(64))
    role = Column(String(16), default="editor")     # admin / manager / editor / viewer
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

class CreationHistory(Base):
    """V4.36「素材历史」：一次「素材创作」会话的落库快照。

    一次会话 = 落地页分析 → 广告文案 → 推广图片，按步骤增量写回。
    目的是让已分析过的网站、已生成的文案与图片可反复查阅 / 再下载，
    不必重新调用大模型生成，节约时间并降低重复素材的产生。
    """
    __tablename__ = "creation_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=True)          # 展示标题（域名 / 品牌 · 平台）
    url = Column(String(1024), nullable=True)           # 落地页地址
    site_name = Column(String(255), nullable=True)      # 从 URL 推断的站点名，便于检索
    platform = Column(String(64), nullable=True)        # 媒体推广平台
    lang = Column(String(16), nullable=True)            # 文案语言
    analysis_json = Column(JSON, nullable=True)         # 完整 LandingAnalysis（8 字段 + model_info）
    copy_json = Column(JSON, nullable=True)             # 文案字段 / schema / brand / model_info / 校验
    images_json = Column(JSON, nullable=True)           # [{file,url,size,w,h,placement}]
    style_opts_json = Column(JSON, nullable=True)       # 创意方向 / 内容风格 / 配色
    image_model_json = Column(JSON, nullable=True)      # 本次文生图调用的模型
    note = Column(Text, nullable=True)                  # 生成说明（含兜底标注）
    image_count = Column(Integer, default=0)
    has_copy = Column(Boolean, default=False)
    owner_id = Column(Integer, nullable=True)
    owner_name = Column(String(64), nullable=True)
    source_id = Column(Integer, nullable=True)          # 「复用分析」来源记录 id
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=True)
    action = Column(String(64))      # spec.update / user.create / model.update ...
    target = Column(String(128), nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
