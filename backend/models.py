from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, Float
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
    # V4.98「素材提示管理」：一句话意图 + 六层心理链条（可多选，逗号分隔 key）。
    # 二者由「素材提示管理」页维护，与生成链路的 content 一起存，不改旧字段语义。
    intent = Column(Text, nullable=True)                 # 这条提示词想表达什么（一句话概括）
    psychological_layers = Column(String(256), nullable=True)  # 六层心理链条 key，逗号分隔
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

class GenerationJob(Base):
    """V4.42 / F12：服务端持久化的生成任务。

    浏览器创建任务后立即拿回 job_id，生成与归档都在服务端完成；刷新 / 关闭浏览器后
    仍可按 job_id 查到结果与状态。`idempotency_key` 保证重复提交不会重复出图 / 重复归档。
    """
    __tablename__ = "generation_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(40), unique=True, index=True)
    idempotency_key = Column(String(200), unique=True, index=True, nullable=True)
    # V4.44 / N05：同 key 不同内容必须冲突（409），不能再静默返回旧任务
    payload_hash = Column(String(64), nullable=True, index=True)
    kind = Column(String(24), default="images")       # images / auto_creation
    # V4.46 / D5：关联持久计划；执行版本须与计划冻结版本一致，禁止客户端改写事实绕过计划
    plan_id = Column(String(40), nullable=True, index=True)
    plan_version = Column(String(40), nullable=True)
    status = Column(String(24), default="queued")     # queued/running/succeeded/partial_success/failed/canceled
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    history_id = Column(Integer, nullable=True, index=True)
    retry_of = Column(String(40), nullable=True)      # 分项重试指向的原任务
    request_json = Column(JSON, nullable=True)        # 完整入参快照（含归档信息）
    result_json = Column(JSON, nullable=True)         # generate_media_images 的结果
    subtasks_json = Column(JSON, nullable=True)       # 逐项状态，供分项重试
    error = Column(Text, nullable=True)
    progress = Column(Integer, default=0)
    attempts = Column(Integer, default=0)
    cancel_requested = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime, nullable=True)
    # ---- V4.81 / P2：视频子任务的持久化执行字段（重启后可按供应商任务号继续查询）----
    batch_id = Column(String(40), nullable=True, index=True)     # 所属创作批次
    stage = Column(String(32), nullable=True)                    # submitting/provider_pending/downloading/validating
    provider_config_id = Column(Integer, nullable=True, index=True)   # 用哪条模型配置（并发按此维度限制）
    provider_model = Column(String(128), nullable=True)
    provider_task_id = Column(String(200), nullable=True, index=True)  # 供应商任务号（拿片/续查的唯一凭据）
    provider_request_id = Column(String(200), nullable=True)     # 脱敏请求追踪号，只做取证
    next_poll_at = Column(DateTime, nullable=True, index=True)   # 下一次该被 worker 领取的时间
    heartbeat_at = Column(DateTime, nullable=True)
    lease_until = Column(DateTime, nullable=True, index=True)    # 租约：避免多 worker 重复消费
    error_code = Column(String(40), nullable=True)
    error_stage = Column(String(32), nullable=True)
    error_message = Column(Text, nullable=True)
    error_action = Column(Text, nullable=True)                   # 唯一可执行动作
    last_provider_status = Column(String(40), nullable=True)     # 供应商最近一次回报的状态原文
    asset_ids = Column(JSON, nullable=True)                      # 已归档资产（资产以 asset_id 命名）
    evidence_json = Column(JSON, nullable=True)                  # 脱敏证据（提交/轮询/下载摘要）


class CreativeBatch(Base):
    """V4.81 / P2：一次「创作」的批次记录（一个批次可含图片、视频多个子任务）。

    为什么单独建表：任务列表要按「创作」聚合展示（产品名 / 类型 / 真实阶段 / 已等待 /
    成功数量），若每次列表都按 generation_jobs 分组聚合，页码与计数会随子任务写入抖动。
    批次行只在创建时写入，状态由子任务聚合回写，列表直接读这一行。
    草稿 `draft_id` 与 `batch_id` 独立：新建创作只换草稿，不动已有批次与结果。
    """
    __tablename__ = "creative_batches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(40), unique=True, index=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    draft_id = Column(String(40), nullable=True, index=True)
    product_name = Column(String(200), nullable=True)
    source_url = Column(String(1000), nullable=True)
    material_types = Column(JSON, nullable=True)     # ["image","video"]
    platforms = Column(JSON, nullable=True)          # ["TikTok", ...]
    status = Column(String(24), default="queued")    # 聚合：queued/running/done/partial/needs_attention/canceled
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime, nullable=True)


class CreativeAsset(Base):
    """V4.42 / F12：不可变的历史资产记录。

    一次生成一张 = 一行；只插入、不覆盖、不静默截断。历史会话的 `images_json`
    退化为「最近若干张的展示缓存」，完整历史通过 `/api/creative-assets` 分页读取。
    删除策略显式：删除历史记录时同步删除其资产行与不再被引用的文件。
    """
    __tablename__ = "creative_assets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(40), unique=True, index=True)
    job_id = Column(String(40), nullable=True, index=True)
    history_id = Column(Integer, nullable=True, index=True)
    owner_id = Column(Integer, nullable=True, index=True)
    file = Column(String(255), nullable=False)
    size = Column(String(32), nullable=True)
    placement = Column(String(128), nullable=True)
    concept_id = Column(String(64), nullable=True)
    spec_version = Column(String(40), nullable=True)
    status = Column(String(24), default="ok")
    meta_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=True)
    action = Column(String(64))      # spec.update / user.create / model.update ...
    target = Column(String(128), nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ----------------------------- V4.47：账号登录日志 -----------------------------
class LoginLog(Base):
    """V4.47：账号登录日志（成功与失败均记录），用于安全追溯与合规审计。

    字段与需求一一对应：username=登陆账号名称，ip=登陆 IP 地址，created_at=登陆时间。
    V4.86：action 区分 login（登录，成功/失败均记）与 logout（登出）；两类都记录 IP 与时间。
    旧库由 migrations.ensure_schema 自动补列，默认 'login'，历史数据语义不变。
    """
    __tablename__ = "login_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=True, index=True)   # 登陆账号名称（成功为系统内 username；失败为尝试输入的邮箱/用户名）
    ip = Column(String(64), nullable=True, index=True)          # 登陆来源 IP 地址
    action = Column(String(16), default="login", index=True)    # V4.86：login / logout
    user_agent = Column(String(512), nullable=True)
    success = Column(Boolean, default=True, index=True)
    detail = Column(JSON, nullable=True)                        # 失败原因 / 备注
    created_at = Column(DateTime, default=utcnow, index=True)   # 登陆时间


# ----------------------------- V4.46 / D5：自动创作持久计划 -----------------------------
class CreationPlan(Base):
    """D5：自动创作的持久计划（与 GenerationJob 解耦，承载多阶段编排与版本冻结）。

    不另造生成系统：计划只持有「分析 / 推荐 / 覆盖 / 确认令牌 / 关联任务 / 归档 manifest」，
    真正的出图仍通过既有 `GenerationJob` 执行。状态机：
    created → analyzing → needs_input / recommendation_ready → platform_confirmed
    → planning → generating → validating → succeeded / partial_success / failed / canceled。
    迁移幂等：`ensure_schema()` 的 `create_all` 只在表不存在时建表，不删列。
    """
    __tablename__ = "creation_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(40), unique=True, index=True)
    plan_version = Column(String(40), default="")     # 冻结版本，执行版本须一致
    mode = Column(String(16), default="auto")          # auto / custom
    stage = Column(String(24), default="created")      # 状态机当前阶段
    status = Column(String(24), default="draft")       # draft / partial_success / succeeded / failed / canceled
    analysis_json = Column(JSON, nullable=True)
    recommendation_json = Column(JSON, nullable=True)   # 来自 creation_planner
    coverage_json = Column(JSON, nullable=True)         # 来自 media_coverage
    approval_token = Column(String(64), nullable=True)  # 冻结版本 + 范围 + 费用授权的令牌
    fee_authorized = Column(Boolean, default=False)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    history_id = Column(Integer, nullable=True, index=True)
    job_ids = Column(JSON, nullable=True)              # 关联的 generation job id 列表
    manifest_json = Column(JSON, nullable=True)        # 归档 manifest（media/concept/role/缺失报告）
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ----------------------------- V4.50 创意工作台：全球创意分析 -----------------------------
class CreativeAnalysis(Base):
    """「创意工作台 · 全球创意分析」：对参考素材（链接/文本）调用大模型归类的创意风格/类型，
    并产出可复用的图片/视频提示词模板。结果落库，可「存入提示词库」复用。"""
    __tablename__ = "creative_analyses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    title = Column(String(255), nullable=True)          # 用户给的分析标题
    inputs_json = Column(JSON, nullable=True)           # {urls:[], text:""}
    result_json = Column(JSON, nullable=True)           # LLM 结构化结果（summary/categories/model_info）
    model_info = Column(JSON, nullable=True)            # 本次实际调用模型快照
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)



# ----------------------------- V4.52 创意工作台：创意策略 / 路线规划 + 历史 -----------------------------
class CreativePlan(Base):
    """「创意工作台 · 创意策略」：基于产品分析结论 + 所选媒体平台，由大模型为每平台规划一条创意路线
    （创意概念 / 切入角度 / 视觉风格 / 文案方向 / 文生图方向）。一次工作台创作会话落库一条，
    生成完成后回填状态与素材数量，构成「历史库」。"""
    __tablename__ = "creative_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    title = Column(String(255), nullable=True)
    analysis_json = Column(JSON, nullable=True)          # 落页分析结论（LandingAnalysis dict）
    platforms = Column(JSON, nullable=True)              # 所选平台列表
    gen_image = Column(Boolean, default=True)
    gen_video = Column(Boolean, default=False)
    routes_json = Column(JSON, nullable=True)            # LLM 产出的创意路线列表
    status = Column(String(24), default="draft")        # draft / generating / done / failed
    asset_count = Column(Integer, default=0)
    history_id = Column(Integer, nullable=True)          # 关联的素材历史会话 id
    model_info = Column(JSON, nullable=True)             # 本次实际调用模型快照
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ----------------------------- V4.61 / B4：创意工作台「素材沉淀库」 -----------------------------
class CwLibrary(Base):
    """创意工作台·素材沉淀库：把一次创作用到的参考图 / 产品快照 / 品牌沉淀为可复用条目，
    新会话可「一键引用」，避免重复上传或重复分析。

    - kind: reference（商品/品牌参考图）/ product（B1 真实抓取或手动文本的产品快照）/ brand（文案品牌）
    - 去重键：product → source_plan_id（一个方案一条产品）；reference → (owner_id, file)；brand → (owner_id, title)
    - file 仅 reference 必填，存 /files/<name> 本地路径；product/brand 可空。
    """
    __tablename__ = "cw_library"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    kind = Column(String(24), index=True)             # reference / product / brand
    title = Column(String(255), nullable=True)
    file = Column(String(512), nullable=True)         # /files/<name>，仅 reference 必填
    url = Column(String(1024), nullable=True)          # 产品链接（kind=product）
    meta_json = Column(JSON, nullable=True)            # brand / summary / snapshot_id / evidence_ids / platform 等
    source_plan_id = Column(Integer, nullable=True, index=True)   # 关联创意方案（产品去重用）
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ============ V4.117 素材创意模板库：三层数据模型（素材条目 / 分析记录 / 模板） ============
class CreativeAssetSource(Base):
    """素材创意模板库 L1 · 原始素材条目：本地上传 / 图片 URL / 网页截图 / 视频导入的原件。
    原件长期归档（软归并不物理删除）；视频存原文件 + 封面帧。"""
    __tablename__ = "creative_asset_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    title = Column(String(255), nullable=True)
    source_type = Column(String(24), default="upload")  # upload / url / screenshot / video
    file = Column(String(512), nullable=True)           # /files/<name> 原件
    thumb = Column(String(512), nullable=True)          # 封面帧（视频）或缩略图
    source_url = Column(String(1024), nullable=True)    # 来源链接
    platform = Column(String(64), nullable=True)        # 来源平台（Meta/Google/...）
    media_kind = Column(String(16), default="image")    # image / video
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_sec = Column(Float, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)  # 去重（文件 sha256）
    status = Column(String(24), default="imported")     # imported/analyzing/analyzed/merged/failed/unavailable
    # V4.119：软归并标记（merged_to_template_X），原件与解构永久保留，可取消归并。
    merged_template_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CreativeAssetAnalysis(Base):
    """素材创意模板库 L2 · 解构分析记录：一次解构一条，可对同一素材多次分析。
    dims_json=版本化维度结果；category_json=分类体系结果；template_guess=模板归属建议。"""
    __tablename__ = "creative_asset_analyses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(Integer, nullable=True, index=True)
    owner_id = Column(Integer, nullable=True, index=True)
    framework_version = Column(String(32), nullable=True)  # asset-deconstruct/1.0
    model_info = Column(JSON, nullable=True)
    dims_json = Column(JSON, nullable=True)            # 布局/视觉/信息/效果/呈现 维度结果
    category_json = Column(JSON, nullable=True)        # 主分类轴 + 辅助标签
    template_guess = Column(JSON, nullable=True)       # {name, confidence, diff[]}
    completeness = Column(Float, nullable=True)        # 框架完整度 0~1（Q6 golden 选择依据）
    confidence = Column(Float, nullable=True)
    status = Column(String(24), default="analyzed")    # analyzing/analyzed/failed/unavailable/low_confidence
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CreativeTemplate(Base):
    """素材创意模板库 L3 · 可复用模板：同一类同一目的只保留一条「唯一表达」。
    只含图片骨架（Q9），文案不受模板影响；golden 素材由框架完整度选出（Q6）。"""
    __tablename__ = "creative_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(64), nullable=True)
    name = Column(String(255), nullable=True)
    primary_category = Column(String(64), nullable=True, index=True)  # 主分类轴（12 类）
    purpose = Column(JSON, nullable=True)             # 推广目的标签数组
    platform_tags = Column(JSON, nullable=True)       # 平台标签数组
    image_skeleton_json = Column(JSON, nullable=True) # 图片结构骨架（构图/信息层级/钩子/CTA）
    variables_json = Column(JSON, nullable=True)      # 变量字典（{{变量}} → 含义/来源）
    golden_asset_id = Column(Integer, nullable=True)  # 唯一表达对应的素材 id
    merged_asset_ids = Column(JSON, nullable=True)    # 已归并的素材 id 列表（软归并）
    edit_note = Column(Text, nullable=True)           # 人工编辑/完善内容
    version = Column(Integer, default=1)
    status = Column(String(24), default="active")     # draft / active / archived
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ============ V4.124 广告主数据模块：API 模板 / 连接实例 ============
class ApiChannelTemplate(Base):
    """模板定义（预置只读）。把「接口怎么调」沉淀为配置，接新渠道=加一行模板。"""
    __tablename__ = "api_channel_template"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    vendor = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    method = Column(String(16), default="POST")
    auth_type = Column(String(24), default="bearer")
    default_endpoint = Column(String(512), nullable=True)
    required_fields_json = Column(JSON, nullable=True)   # 表单字段 schema（schema-driven）
    query_skeleton_json = Column(JSON, nullable=True)    # GraphQL 查询骨架 / 分页 / 限流
    framework_version = Column(String(32), nullable=True)
    status = Column(String(24), default="active")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ApiConnection(Base):
    """连接实例：用户只填 Token / CID / Endpoint，其余继承模板。Token 加密存储。"""
    __tablename__ = "api_connection"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=True, index=True)
    name = Column(String(128), nullable=True)
    template_code = Column(String(64), nullable=True, index=True)
    cid = Column(String(64), nullable=True)              # 发布者 CID（非登录邮箱）
    endpoint = Column(String(512), nullable=True)        # 留空用模板默认
    token_enc = Column(String(1024), nullable=True)      # 加密后的 Token，不回显
    token_mask = Column(String(64), nullable=True)       # 列表展示用掩码
    status = Column(String(24), default="draft")         # draft/active/disabled
    last_test_ok = Column(Boolean, nullable=True)
    last_test_at = Column(DateTime, nullable=True)
    last_test_error = Column(Text, nullable=True)        # 脱敏错误摘要
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
