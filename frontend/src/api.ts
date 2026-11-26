const _envApiBase = (import.meta as any).env?.VITE_API_BASE
// 生产部署：构建时通过 VITE_API_BASE='' 让前端使用同源相对路径（/api、/files 由 nginx 反代到后端）。
// 本地开发：未设置该变量时回退到默认后端地址，保持原有开发体验。
export const API_BASE: string =
  _envApiBase !== undefined ? _envApiBase : 'http://127.0.0.1:8033'

const TOKEN_KEY = 'admb_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

/** 把可选筛选条件拼成 query string（忽略空值） */
const qs = (o: object) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  })
  const s = p.toString()
  return s ? '?' + s : ''
}

/** V4.43：版本通知只保留版本号与「总结式」更新要点，最新在前 */
export interface ReleaseNote {
  version: string
  title: string
  date: string | null
  summary: string                 // 一句话总结
  points: string[]                // 总结式更新要点（不含功能细节 / 前因后果）
  change_types: string[]
  modules: string[]
  auto_generated: boolean         // true = CHANGELOG 漏写时按系统版本自动补齐
}
export interface ReleaseNotesResponse {
  latest: string | null
  app_version: string             // 当前系统版本对应的发布号，如 V4.43
  version: string                 // 运行版本，如 4.43.0
  notes: ReleaseNote[]
  current: ReleaseNote | null
  total: number
  auto_generated: boolean
  synced_at: string
}

export interface ModelConfig {
  id: number
  name?: string | null
  usage?: string | null            // 主用途（兼容旧数据）
  usages?: string[]                // 多用途数组
  provider: string
  api_key?: string
  base_url?: string
  model?: string
  params?: any
  is_active: boolean
  // V4.34 连通性健康（每日自动测试 / 手动测试写回）
  last_test_ok?: boolean | null        // null = 尚未测试
  last_test_at?: string | null
  last_test_http_code?: number | null
  last_test_error?: string | null      // 失败 log：HTTP code + 服务器返回错误 + 诊断
  last_test_latency_ms?: number | null
  in_use?: boolean                     // 是否为该用途当前实际生效（被系统功能采用）
}

export interface ModelPreset {
  key: string
  name: string
  protocol: string
  modality: 'text' | 'image' | 'video'
  mainstream?: boolean
  default_base_url: string
  base_url_editable: boolean
  models: string[]
  api_key_label: string
  api_key_placeholder: string
  model_placeholder: string
  docs_url: string
  setup_guide: string
  notes: string
  extra_fields: { key: string; label: string; placeholder?: string; hint?: string }[]
  default_params?: Record<string, string>
}

export interface ModelTestResult {
  ok: boolean
  latency_ms?: number
  reply?: string
  error?: string
  error_type?: string
  message?: string
  hint_url?: string
  hint_url_label?: string
  raw?: string
  http_status?: number               // V4.34：服务器返回的 HTTP code（网络层失败为 0）
}

export interface ModelHealthInfo {
  enabled: boolean
  hour: number
  last_daily_date?: string | null
  last_daily_at?: string | null
  total_configs: number
}

export interface ModelTestAllResult {
  reason: string
  total: number
  ok: number
  failed: number
  tested_at: string
  results: {
    id: number
    name?: string | null
    ok: boolean
    http_status: number
    latency_ms?: number | null
    error?: string | null
    message?: string | null
  }[]
}

export interface PromptConfig {
  id: number
  key: string
  name: string
  module: string
  category?: string | null
  func_type?: string | null
  usage_type?: string | null
  intent?: string | null
  psychological_layers?: string | null
  description?: string
  content: string
  is_active: boolean
  updated_at?: string | null
}

/** V4.98 / V4.100 提示词管理：类型 / 六层心理链条 / 变量来源 */
export interface PsychLayer { key: string; label: string; desc: string }
export interface PromptTypeMeta { key: string; label: string; desc: string }
export interface PromptVariable { name: string; source: string }
export interface MaterialPromptMeta {
  module: string
  legacy_module?: string
  types: PromptTypeMeta[]
  layers: PsychLayer[]
  variables: Record<string, PromptVariable[]>
}
export interface LayerMatchResult { layers: string[]; labels: string[]; reason: string }

/** V4.35 素材提示词：分类维度（功能类型 / 使用类型） */
export interface PromptTaxonomyItem {
  key: string
  label: string
  desc: string
  count: number
}
export interface PromptTaxonomy {
  func_types: PromptTaxonomyItem[]
  usage_types: PromptTaxonomyItem[]
  total: number
}

/** V4.35 优秀提示词总结库条目（四维标签） */
export interface PromptLibraryItem {
  id: string
  kind: string
  name: string
  type: string
  style: string
  scene: string
  audience: string
  platforms: string[]
  source: string
  summary: string
  content: string
  tags: string[]
}
export interface PromptDefaultInfo {
  kind: string
  label: string
  target_key: string
  id: string | null
  name: string
  source: string
  builtin: boolean
  customized: boolean
}
export interface PromptLibraryResponse {
  kinds: { key: string; label: string; target_key: string; desc: string }[]
  dimensions: { key: string; label: string; options: string[] }[]
  items: PromptLibraryItem[]
  total: number
  all_total: number
  defaults: Record<string, PromptDefaultInfo>
}

export interface PromptListOpts {
  module?: string
  scope?: string
  func_type?: string
  usage_type?: string
}
export interface PromptLibraryFilters {
  kind?: string
  type?: string
  style?: string
  scene?: string
  audience?: string
  q?: string
}

/** 素材创作三大提示词库中的单条预设 */
export interface CreativePreset {
  id: string
  name: string
  desc: string
  applies: string
  prompt: string
}

export interface CreativePresets {
  directions: CreativePreset[]
  styles: CreativePreset[]
  colors: CreativePreset[]
}

/** 素材创作：落地页分析（8 字段 LLM 推理）输出 */
export interface LandingChannel {
  platform: string
  reason: string
}

export interface ModelInfo {
  provider: string
  model: string
  role: string        // 实际用途：analysis / copy（分析模型未配则复用文案模型）
  fallback: boolean   // true = 调用后确实走了 Mock 兜底
  /** V4.39 / F10：调用快照，展示与真实调用一致 */
  config_id?: number | null
  source?: string     // llm / mock / invalid_response / local
  request_id?: string
  error_type?: string
  retries?: number
}

export interface LandingAnalysis {
  url: string              // (1) 网站地址 —— 仅展示
  logo: string             // 从落地页抓取到的品牌 / 公司 logo（绝对 URL，可空）
  language: string         // (2) 语言
  industry: string         // (3) 行业
  type: string             // (4) 类型（网站属性）
  audience: string         // (5) 对象
  competitors: string[]    // (6) 竞品（top 3）
  advantages: string[]     // (7) 优势（≤5）
  channels: LandingChannel[]  // (8) 推广途径（≤5，含平台+理由）
  model_info: ModelInfo
  source: string           // llm / mock / local —— 结果是否真的来自大模型推理
  /** V4.39 / F02：抓取环境与品牌 / Logo 证据；输入链接只用于追踪 */
  brand?: string
  brand_status?: 'confirmed' | 'unverified' | 'needs_input'
  brand_candidates?: string[]
  brand_reason?: string
  logo_source?: string
  logo_verified?: boolean
  logo_reason?: string
  input_url?: string
  final_url?: string
  redirect_chain?: string[]
  fetch_quality?: string
  /** 行业 / 品类画像：可局部调整，不改通用主干 */
  industry_profile?: string
  industry_profile_label?: string
  /** V4.42 / F09：事实证据链、采样覆盖与空证据阻断 */
  facts?: string[]
  assumptions?: string[]
  gaps?: string[]
  evidence_ids?: string[]
  evidence_chain?: { claim: string; evidence_ids: string[]; kind: string; rejected?: boolean }[]
  evidence_index?: EvidenceRecord[]
  evidence_coverage?: EvidenceCoverage[]
  /** V4.44 / N01：唯一 [E###] 命名空间与不可变证据快照审计 */
  evidence_snapshot_id?: string
  evidence_fetched_at?: string
  evidence_review_status?: string
  evidence_invalid_ids?: string[]
  evidence_ref_audit?: { checked: number; invalid: number; status: string; note?: string }
  sections_index?: { section_id?: string; sample_ids?: string[]; referenceable: boolean }[]
  evidence_dropped_chars?: number
  evidence_source_chars?: number
  evidence_expired_offers?: { expires_on: string; quote: string }[]
  evidence_note?: string
  evidence_gate?: 'ok' | 'needs_input'
  gate_status?: 'ok' | 'needs_input'
  blocked_reasons?: string[]
  legacy_unverified?: boolean
}

/** V4.42 / F09：一条可回溯到原文的证据 */
export interface EvidenceRecord {
  evidence_id: string
  quote: string
  source_url: string
  section: string
  char_start: number
  char_end: number
  fetched_at?: string
  clause_kinds?: string[]
  verified?: boolean
  verification?: string
  applicable_scope?: string
  legacy_unverified?: boolean
  has_key_clause?: boolean
  /** V4.44 / N01：可定位原文与商业真实性审核分离 */
  review_status?: string
  referenceable?: boolean
  section_ids?: string[]
  tags?: string[]
}

export interface EvidenceCoverage {
  evidence_id: string
  char_start: number
  char_end: number
  tags: string[]
}

/** V4.45 / D1–D3：自动创作的工作区默认值（不从页面语言推断投放国家） */
export interface WorkspaceDefaults {
  country: string
  language: string
  os: string
  goal: string
  budget_cap: number
  concept_count: number
}
/** V4.45 / D2：结构化概念，购买理由不同才算不同概念 */
export interface StructuredConcept {
  concept_id: string
  axis: string
  audience: string
  situation: string
  purchase_reason: string
  promise: string
  claim_ids: string[]
  claim_status: 'locatable_not_reviewed' | 'unsupported' | 'no_claim'
  claim_audit: { ok: boolean; ids: string[]; invalid_ids: string[]; reason: string }
  qualifiers: Record<string, string[]>
  must_preserve_qualifiers: string[]
  format: string
  forbidden_inferences: string[]
  distinct_reason: string
}
/** V4.45 / D2：确定性策划结果，推荐描述与 VisualBrief 来自同一对象 */
export interface CreationRecommendation {
  schema_version: string
  mode: string
  status: 'ready' | 'draft_only' | 'needs_input'
  recommended_visual_summary: string
  rationale: string[]
  missing_inputs: string[]
  blocking_reasons: string[]
  product_profile: {
    entity_type: string; brand: string; brand_status: string; sku_or_plan: string
    business_model: string; assets: string[]; source: string
    multi_product_page: boolean; uncertainty: string
  }
  visual_brief: {
    version: string; entity_type: string; subject: string; subject_asset: string; scene: string
    scene_types: string[]; value: string; product_facts: string[]
    composition: string; layout: string; detail: string; copy_zone: string
    short_copy: string; asset_roles: string[]; required_tasks: number
    forbidden_inferences: string[]; asset_requirement: string
  }
  industry_profile: string
  industry_profile_label: string
  industry_profile_version: string
  structured_concepts: StructuredConcept[]
  workspace_defaults: WorkspaceDefaults
  evidence: { snapshot_id: string; count: number; review_status: string }
  coverage_summary: {
    platforms: string[]; asset_roles: string[]; required_tasks: number
    spec_verified: boolean; spec_version: string; estimate_note: string
  }
  /** N03 / A15：V4.45 自动流程一律草案，不计作可投放商品广告 */
  quality_gate: {
    delivery_grade: 'draft' | 'standard'; deliverable: boolean
    checks: { key: string; passed: boolean; note: string }[]
    note: string
  }
  delivery_grade: 'draft' | 'standard'
  pricing_gate: {
    has_price_terms: boolean; region_source: string; region_confirmed: boolean
    price_statement_allowed: boolean; note: string
  }
  claim_audit: { checked: number; unsupported: string[]; must_preserve_qualifiers: string[] }
  plan_id: string
  plan_version: string
  plan_hash: string
  note: string
}

/** V4.46 / D5：自动创作的持久计划（多阶段编排 + 版本冻结 + 质检归档）。 */
export interface CreationPlan {
  plan_id: string
  plan_version: string
  mode: string
  /** 状态机阶段：created → analyzing → needs_input / recommendation_ready →
   *  platform_confirmed → planning → generating → validating → succeeded / … */
  stage: string
  status: string
  recommendation: CreationRecommendation | null
  coverage: {
    coverage?: {
      platforms: string[]; asset_roles: string[]; required_tasks: number
      sub_batch_count: number; spec_verified: boolean; spec_verified_on: string
    }
    cost_estimate?: {
      model_calls_upper: number; cost_upper_usd: number
      budget_cap_usd: number; over_budget: boolean; is_estimate: boolean; note: string
    }
    report?: Record<string, any>
    [k: string]: any
  } | null
  approval_token: string | null
  fee_authorized: boolean
  job_ids: string[]
  manifest: {
    item_count?: number; plan_required_tasks?: number; missing_report?: any[]
    complete?: boolean; incomplete_reason?: string; qa?: Record<string, any>
  } | null
  owner_id?: number | null
  owner_name?: string
  created_at?: string | null
  updated_at?: string | null
}

/** V4.39：行业 / 品类画像（用于「素材创作」局部调整） */
export interface IndustryProfile {
  key: string
  label: string
  value_axes: string[]
  evidence_types: string[]
  visual_subject: string
  must_preserve: string[]
  copy_focus: string
  /** V4.40 / 第 2 期：行业局部配置——建议版位 id（仅提示，不自动勾选） */
  placement_preferences?: string[]
}
export interface IndustryProfilesResponse {
  profiles: IndustryProfile[]
  total: number
  generic_rules: string[]
  note: string
}

/* ----------------------------- 媒体推广的媒体平台设置 ----------------------------- */
export interface MediaPlacement {
  id: string
  name: string
  sizes: string[]
  desc: string
  default: boolean
  /** V4.40 / F08：版位的交付语义（服务端目录给出，前端不自行推断） */
  ad_product?: string
  asset_role?: string
  os?: string
}

export interface MediaRules {
  spec_version: string
  spec_source: string
  spec_verified_on: string
  disclaimer: string
  limits: { max_slots: number; max_total_pixels: number; max_slot_pixels: number
            min_side: number; max_side: number; max_copy_variants: number }
  hard: string[]
  policy: string[]
  advisory: string[]
  platforms?: Record<string, string[]>
  industry_placement_preferences?: Record<string, string[]>
}

export interface MediaPlatform {
  platform: string
  placements: MediaPlacement[]
  image_sizes: string[]
  recommended_sizes: string[]
  recommended_count: number
  copy_limits: { title_max?: number; description_max?: number; primary_text_max?: number; body_max?: number }
  usage: string
  cta_options: string[]
  /** V4.40 / F08：版本化媒体规则 */
  ad_products?: string[]
  spec_version?: string
  spec_source?: string
  spec_verified_on?: string
  spec_disclaimer?: string
  rules?: MediaRules
}

/** V4.39 / F01：一条需要人工修改的超长文案（不得作为合格素材导出） */
export interface CopyRevisionNeeded {
  field: string
  label: string
  index: number
  original: string
  limit: number
  protected: string[]
  reason: string
}
/** V4.44 / N01：证据→广告承诺的生成后审计（与字数 / 压缩无关） */
export interface ClaimAudit {
  status: 'ok' | 'needs_revision' | 'legacy_unverified'
  rules_version?: string
  snapshot?: { snapshot_id: string; evidence_ids: string[]; count: number;
               review_status?: string }
  checked?: number
  violations?: { field: string; index?: number | null; text: string;
                 type: string; missing?: string[]; invalid_ids?: string[]; reason: string }[]
  note?: string
}
/** V4.101：用户确认后的创意表达策略快照 */
/** V4.105 / 方案C：结构化创作意图（文案 / 图片 / 视频三类素材共用） */
export interface CreativeIntent {
  audience?: string[]
  goal?: string
  core_value?: string
  scenario?: string
  style?: string
  avoid?: string[]
  raw_text?: string
}

export interface CreativeBrief {
  raw_input?: string
  framework?: string
  framework_label?: string
  product?: string
  audience?: string
  hook?: string
  pain?: string
  desire?: string
  proof?: string
  attribution?: string
  decision?: string
  cta?: string
  visual_hook?: string
  beat?: string
  tone?: string
  layers?: string[]
  warnings?: string[]
  confirmed?: boolean
  brief_hash?: string
  prompt_text?: string
  /** 同一 brief 下「换一批文案」的变体序号 */
  variation?: number
}

export interface MediaCopyResult {
  platform: string
  /** V4.40 / F08：广告产品（用于区分 Google RSA / UAC 等文案 schema） */
  ad_product?: string
  lang: string
  fields: Record<string, any>
  schema: { key: string; label: string; max: number; count: number }[]
  char_table: { field: string; text: string; len: number; max: number; over: boolean }[]
  validation: {
    valid: boolean
    status?: string       // ok / needs_revision / invalid
    issues: { level: string; code: string; message: string }[]
    problems?: any[]
    needs_revision?: CopyRevisionNeeded[]
  }
  model_info: ModelInfo
  brand: string
  /** V4.39：原始模型输出、裁剪记录、语义压缩记录 */
  raw_fields?: Record<string, any>
  clips?: any[]
  copy_revisions?: any[]
  needs_revision?: CopyRevisionNeeded[]
  /** V4.44 / N01：每次生成后都执行的证据与限定校验 */
  claim_audit?: ClaimAudit
  industry_profile?: string
  industry_profile_label?: string
  compress_calls?: number
  /** V4.41 / F04：本次文案实际使用的配置快照（后续改预设不覆盖） */
  creative_config?: CreativeConfigSnapshot
  creative_prompt_hash?: string
  creative_brief?: CreativeBrief | null
}

/** V4.41 / F04：归档用的不可变配置快照 */
export interface CreativeConfigSnapshot {
  config_id: string
  version: string
  hash: string
  preset_ids?: Record<string, string>
  custom_fields?: string[]
  visual?: { layout: string; template: string; palette_accent: string }
  scope?: Record<string, string>
  reference_mode?: string
}

/** V4.41 / F03：每张图对应的视觉简报（概念 → 画面） */
export interface VisualBrief {
  concept_id: string
  concept_key: string
  layout: string
  subject: string
  action: string
  setting: string
  core_promise: string
  evidence: string
  reference_mode: string
  capability_note: string
}

/** V4.38：一条被勾选的「创意文案组合」，会叠加到一张推广图片上 */
export interface CopyVariant {
  headline: string
  sub: string
  cta: string
  brand: string
  label: string
  /** V4.40 / F07：概念标识，用于追溯同一概念跨版位的承诺一致性 */
  concept_id?: string
}

export interface MediaImageItem {
  url: string
  file: string
  size: string
  w: number
  h: number
  placement: string
  /** V4.38：本张图片实际选用的文案组合 */
  variant?: string
  copy?: { headline: string; sub: string; cta: string }
  /** V4.40 / F11：逐图状态，不再用批次级 ai_used 掩盖模板回退 */
  status?: 'ok' | 'fallback'
  /** V4.104 / 方案E：质量状态独立于文件生成状态；unverified 正常交付但如实标注 */
  quality_status?: 'ok' | 'fail' | 'unverified'
  quality_checks?: Record<string, { status: string; detail?: string }>
  ai_background?: boolean
  fallback?: boolean
  fallback_reason?: string
  model?: { provider: string; model: string; config_id: number | null; request_id: string }
  retries?: number
  batch_id?: string
  /** V4.40 / F07 + F08：任务矩阵与规则标记 */
  concept_id?: string
  concept_index?: number
  placement_id?: string
  ad_product?: string
  asset_role?: string
  os?: string
  spec_version?: string
  /** V4.41 / F03 + F04 + F05：概念、视觉简报、版式、配置与提示词哈希 */
  concept_key?: string
  layout?: string
  prompt_hash?: string
  creative_config_id?: string
  visual_brief?: VisualBrief
  creative_config?: CreativeConfigSnapshot
  /** V4.42 / F06：请求尺寸 / 实际返回尺寸 / 真实裁切参数 */
  request_size?: number[]
  target_size?: number[]
  returned_size?: number[] | null
  composition?: ImageComposition
  size_capability?: {
    provider: string; needs_outpaint: boolean; ratio_delta: number
    size_verified_on: string; capability_note: string
  }
  /** V4.42 / F12：产出该图的服务端任务 */
  job_id?: string
}

/** V4.42 / F06：逐图构图记录（T08 可核对比例与主体保护） */
export interface ImageComposition {
  mode: string
  target_size?: number[]
  source_size?: number[]
  requested_size?: number[]
  returned_size?: number[] | null
  scale?: number
  anchor?: number[]
  crop?: number[] | null
  subject_box?: number[]
  text_box?: number[]
  protected?: boolean
  extreme_ratio?: boolean
  ratio_gap?: number
  layout?: string
  capability_note?: string
  applied_mode?: string
  content_box?: number[]
}

/** V4.39 / F01：因图内文案超预算被阻止；V4.40 / F11：失败任务同样逐项列出 */
export interface MediaImageIssue {
  level: string
  status?: string
  size: string
  placement: string
  concept_id?: string
  ad_product?: string
  message: string
}

export interface MediaImageTaskResult {
  status: string
  size: string
  placement: string
  concept_id: string
  ad_product: string
  spec_version: string
  file: string
  ai_background: boolean
  fallback: boolean
  error: string
  retries: number
  batch_id: string
  /** V4.41：逐图版式与配置追溯 */
  layout?: string
  prompt_hash?: string
  creative_config_id?: string
  /** V4.42：分项重试定位 + 构图记录 */
  task_index?: number | null
  request_size?: number[] | null
  returned_size?: number[] | null
  composition_mode?: string
  crop?: number[] | null
}

/** V4.42 / F12：图片生成入参（同步接口与持久任务共用） */
export interface MediaImagePayload {
  analysis: LandingAnalysis; platform: string; lang?: string
  copy_fields: Record<string, any>; copy_variants?: CopyVariant[]
  style_opts: Record<string, any>
  slots: { size: string; placement: string; placement_id?: string
           concept_index?: number; concept_id?: string; spec_id?: string }[]
  logo?: string
  spec_version?: string
  total_pixels?: number
}

export interface MediaImageResult {
  platform: string
  images: MediaImageItem[]
  image_model: ModelInfo
  note: string
  count: number
  copy_variant_count?: number
  /** V4.40 / F11：failed = 整批无可用素材，不静默当成功 */
  status?: 'ok' | 'partial_success' | 'failed'
  issues?: MediaImageIssue[]
  skipped?: any[]
  strict_text?: boolean
  task_results?: MediaImageTaskResult[]
  batch_id?: string
  spec_version?: string
  /** V4.41 / F04：整批配置快照，写入「素材历史」后不可被后续预设修改覆盖 */
  creative_config?: CreativeConfigSnapshot
  reference_mode?: string
  capability_note?: string
  rules?: Record<string, any>
  /** V4.42 / F06：整批构图与尺寸能力汇总 */
  composition?: {
    provider: string; modes: string[]; outpaint_count: number
    protected_count: number; size_capabilities: Record<string, any>; note: string
  }
  /** V4.42 / F12：服务端任务与归档信息 */
  job_id?: string
  archive?: JobArchiveInfo
}

/* ----------------------------- V4.42 服务端持久任务 / 不可变资产 ----------------------------- */

export interface JobArchiveInfo {
  archived?: string[]
  duplicates?: string[]
  errors?: string[]
  history_update?: Record<string, any>
  retention_policy?: string
}

/** 服务端持久任务：刷新 / 关闭浏览器后仍可按 job_id 恢复 */
export interface GenerationJob {
  job_id: string
  idempotency_key?: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'partial_success' | 'failed' | 'canceled'
  owner_id?: number | null
  owner_name?: string
  history_id?: number | null
  retry_of?: string | null
  progress: number
  attempts?: number
  cancel_requested?: boolean
  error?: string
  result: MediaImageResult | null
  subtasks?: MediaImageTaskResult[]
  created_at?: string
  updated_at?: string
  finished_at?: string | null
  terminal: boolean
  /** 仅创建接口返回 */
  created?: boolean
  poll_url?: string
  message?: string
}

/** V4.108 素材工作坊 —— 只用「大模型配置」里当前生效且测试通过的模型 */
export interface WorkshopModelStatus {
  usage: 'analysis' | 'copy' | 'image'
  label: string
  ready: boolean
  reason: string
  name: string
  provider: string
  model: string
  config_id: number | null
  last_test_at: string | null
  /** V4.109：该用途被勾选的配置条数（0 = 真的没配，>0 = 配了但不可用） */
  candidates?: number
}
export interface WorkshopSize {
  size: string; aspect: string; label: string
  spec_id: string; ad_product: string; verification: string
}
export interface WorkshopPlatform { platform: string; sizes: WorkshopSize[] }
export interface WorkshopOptions {
  models: { items: WorkshopModelStatus[]; ready: boolean; missing: string[] }
  platforms: WorkshopPlatform[]
  limits: { max_images: number }
}
export interface WorkshopAnalyzeResult {
  plan_id: number | null
  title: string
  summary: string
  analysis: any
  brief: any
  snapshot: any
  intent_summary: string
  source: string
  models: WorkshopModelStatus[]
}
export interface WorkshopCopyRow { key: string; label: string; max: number; values: string[] }
export interface WorkshopCopy {
  platform: string
  status: 'ok' | 'review' | 'failed'
  reason: string
  rows: WorkshopCopyRow[]
  text: string
  model: { provider: string; model: string; config_id: number | null }
}
export interface WorkshopImageJob {
  platform: string
  job_id: string
  created: boolean
  sizes: Array<{ size: string; label: string; aspect: string }>
  poll_url: string
}
export interface WorkshopGenerateResult {
  copies: WorkshopCopy[]
  image_jobs: WorkshopImageJob[]
  warnings: string[]
  /** 图片模型未就绪时后端降级为「只出文案」，不假装出图 */
  images_skipped: boolean
  plan_id: number | null
  models: WorkshopModelStatus[]
  /** V4.120：按模板创作的图片溯源（模板只影响图片） */
  template_id?: number | null
  template_name?: string
}

export interface CreativeAsset {
  asset_id: string
  job_id: string | null
  history_id: number | null
  file: string
  url: string
  size: string
  placement: string
  concept_id: string
  spec_version: string
  status: string
  meta: Record<string, any>
  created_at?: string | null
}

export interface CreativeAssetList {
  items: CreativeAsset[]
  total: number
  limit: number
  offset: number
  retention_policy: string
}

export interface ImageCapabilities {
  providers: Record<string, Record<string, any>>
  ratio_tolerance: number
  extreme_ratio: number
  note: string
}

/* ----------------------------- V4.36 素材历史 ----------------------------- */
/** 一次「素材创作」会话：落地页分析 → 广告文案 → 推广图片，可反复查阅与再下载。 */
export interface CreationHistory {
  id: number
  title: string
  url: string
  site_name: string
  platform: string
  lang: string
  analysis: LandingAnalysis | null
  copy: Partial<MediaCopyResult> | null
  images: MediaImageItem[]
  style_opts: Record<string, string>
  image_model: ModelInfo | null
  note: string
  image_count: number
  has_copy: boolean
  owner_name: string
  source_id: number | null
  created_at: string | null
  updated_at: string | null
  /** V4.42 / F12：images 只是展示缓存，完整不可变记录按 history_id 分页读取 */
  display_cache_limit?: number
  retention_policy?: string
  asset_list_url?: string
}

export interface CreationHistoryList {
  items: CreationHistory[]
  total: number
  limit: number
  offset: number
}

export interface User {
  id: number
  username: string
  email?: string
  display_name?: string
  role: 'admin' | 'manager' | 'editor' | 'viewer'
  active: boolean
}

export interface LoginLog {
  id: number
  username: string | null
  ip: string | null
  action?: 'login' | 'logout'   // V4.86：登录 / 登出（旧数据缺省视为 login）
  user_agent: string | null
  success: boolean
  detail: any | null
  created_at: string
}

export interface LogStats {
  audit_total: number
  login_total: number
  login_success: number
  login_fail: number
  login_count: number   // 登录事件数（含成功/失败）
  logout_count: number  // 登出事件数
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(API_BASE + path, {
    // V4.81：先展开 opts 再合并 headers —— 否则调用方传的自定义头会把
    // Content-Type / Authorization 整块覆盖掉（幂等键请求头就是这么丢的）。
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('admb:unauthorized'))
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    // V4.87：网关（nginx / Cloudflare）错误页是 HTML，不是后端 JSON。
    // 旧实现把整段 HTML（含 padding 注释）塞进 message，用户看到一大坨乱码。
    // 这里识别并转成可诊断的中文提示，同时保留状态码便于排查。
    const isHtmlError = /<html[\s>]/i.test(t.slice(0, 300)) || /<title>[^<]*(502|503|504|bad gateway|gateway timeout)/i.test(t.slice(0, 500))
    if (isHtmlError) {
      const code = res.status
      const byGateway = /nginx|cloudflare|bad gateway|gateway timeout/i.test(t.slice(0, 1000))
      const hint = code === 502 || code === 503
        ? '网关无法连接后端服务，通常是服务正在重启或负载过高，请稍后重试'
        : code === 504
          ? '网关等待后端响应超时，请稍后重试；若持续出现请联系管理员检查部署代理超时配置'
          : '网关返回异常，请稍后重试'
      throw new Error(`服务暂时不可用（${code}${byGateway ? ' · 网关' : ''}）：${hint}`)
    }
    let detail = t
    try {
      const d = JSON.parse(t).detail
      // V4.40 / F08：服务端规则校验返回结构化错误对象时，展开成人读原因
      detail = typeof d === 'string' ? d
        : Array.isArray(d) ? d.map((x: any) => x?.msg || x?.message || String(x)).join('；')
        : d && typeof d === 'object'
          ? [d.message, ...(Array.isArray(d.errors) ? d.errors : [])].filter(Boolean).join('；')
          : t
    } catch { /* 保留原文 */ }
    throw new Error(`请求失败 ${res.status}: ${detail || res.statusText}`)
  }
  return res.json() as Promise<T>
}

/** V4.142：下载二进制响应（CSV 导出），复用统一鉴权与 401/网关错误处理；从 Content-Disposition 取文件名。 */
export async function downloadFile(path: string): Promise<void> {
  const token = getToken()
  const res = await fetch(API_BASE + path, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('admb:unauthorized'))
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(`导出失败（${res.status}）：${t.slice(0, 200)}`)
  }
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/)
  const filename = match ? match[1] : 'export.csv'
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * V4.76 视频出片异步化：提交任务 → 轮询状态 → 返回结果（结构与同步接口完全一致）。
 *
 * 出片需等模型 1–6 分钟。若让一个 HTTP 请求一直挂着等结果，反向代理会先超时
 * （宿主 nginx 默认 60s、Cloudflare 100s），前端只会看到「504 Gateway Time-out」，
 * 而任务其实还在厂商侧跑。改成「提交即返回 + 轮询」后，代理超时与出片时长彻底解耦。
 */
export async function cwVideoGenerateAsync(
  payload: { analysis: any; platform: string; reference_image?: string; plan: any; options?: any },
  onTick?: (info: { elapsed: number; stage: string; status: string }) => void,
  opts: { timeoutMs?: number; intervalMs?: number } = {},
): Promise<any> {
  const timeoutMs = opts.timeoutMs ?? 12 * 60 * 1000
  const intervalMs = opts.intervalMs ?? 2500
  const job = await req<any>('/api/cw-video/generate-jobs', {
    method: 'POST', body: JSON.stringify(payload),
  })
  const jobId = job?.job_id
  if (!jobId) throw new Error('提交视频任务失败：未拿到任务号')
  const startedAt = Date.now()
  let last: any = job
  let fails = 0
  onTick?.({ elapsed: 0, stage: job?.stage || '排队中', status: job?.status || 'queued' })
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise(r => setTimeout(r, intervalMs))
    try {
      last = await req<any>(`/api/cw-video/generate-jobs/${jobId}`)
      fails = 0
    } catch (e: any) {
      // 单次轮询抖动（网关限流 / 断网）不该终止出片；连续 3 次失败才放弃
      if (++fails >= 3) throw e
      continue
    }
    const elapsed = last?.elapsed_sec ?? Math.round((Date.now() - startedAt) / 1000)
    onTick?.({ elapsed, stage: last?.stage || '', status: last?.status || '' })
    if (last?.status === 'needs_attention') {
      // V4.79：链路跑完但没出片（不再是 done + 空 videos 的假成功）。
      // 仍返回 result，让页面把 error_code / 唯一动作 / 证据链展示出来，同时保留分镜兜底。
      if (!last.result) throw new Error(last.error || '视频生成失败')
      return last.result
    }
    if (last?.status === 'done') {
      if (!last.result) throw new Error('视频任务已完成但未返回结果')
      return last.result
    }
    if (last?.status === 'error') throw new Error(last.error || '视频生成失败')
  }
  throw new Error(
    `视频任务仍在生成中（任务号 ${jobId}，已等待 ${Math.round(timeoutMs / 1000)} 秒）。` +
    '厂商侧可能仍在渲染，可稍后到厂商控制台按该任务号取片。'
  )
}

export const api = {
  login: (email: string, password: string) =>
    req<{ token: string; expires_in: number; user: User }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    }),
  me: () => req<User>('/api/auth/me'),
  roles: () => req<{ roles: Record<string, string>; can_edit: string[]; can_review: string[] }>('/api/auth/roles'),
  // 用户管理
  users: () => req<User[]>('/api/users'),
  createUser: (u: { email: string; password: string; display_name?: string; role: string; username?: string }) =>
    req<User>('/api/users', { method: 'POST', body: JSON.stringify(u) }),
  updateUser: (id: number, u: Partial<User> & { password?: string }) =>
    req<User>(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(u) }),
  deactivateUser: (id: number) => req<any>(`/api/users/${id}`, { method: 'DELETE' }),
  auditLogs: (limit = 100) => req<any[]>(`/api/audit-logs?limit=${limit}`),
  loginLogs: (limit = 100, success?: boolean, action?: 'login' | 'logout') =>
    req<LoginLog[]>(`/api/login-logs?limit=${limit}${success === undefined ? '' : `&success=${success}`}${action ? `&action=${action}` : ''}`),
  // V4.86：全表真实统计，与列表 limit / 前端搜索无关
  logStats: () => req<LogStats>('/api/log-stats'),
  // V4.86：登出记录（失败不阻断本地登出，由调用方 catch）
  logout: () => req<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  landingAnalysis: (payload: { url?: string; text?: string }) =>
    req<LandingAnalysis>('/api/landing-analysis', { method: 'POST', body: JSON.stringify(payload) }),
  // 素材创作：营销推广的媒体平台设置 —— 平台规格目录
  mediaPlatforms: () =>
    req<MediaPlatform[]>('/api/media-platforms'),
  // V4.40 / F08：版本化媒体规则（强制 / 政策 / 建议、上限、行业版位偏好）
  mediaRules: () =>
    req<MediaRules>('/api/media-rules'),
  // V4.84：媒体素材规格标准库（图片+视频，逐广告产品，带来源/核验分级）——展示与生成的单一事实来源
  mediaSpecLibrary: () =>
    req<{
      library_version: string
      reviewed_on: string
      verification_label: Record<string, string>
      entries: {
        spec_id: string
        platform: string; ad_product: string; asset_role: string; media: string
        verification: string; verification_label: string; source_url: string | null
        verified_on: string | null; sizes: string[]; min_sizes: string[]
        aspect_ratios: string[]; formats: string[]; max_bytes: number | null
        duration_min: number | null; duration_max: number | null; fps_min: number | null
        codec: string | null; companions: string[]; note: string; library_version: string
      }[]
    }>('/api/media-spec-library'),
  // V4.42 / F06：供应商尺寸能力 / 核验状态
  imageCapabilities: () =>
    req<ImageCapabilities>('/api/image-capabilities'),
  // V4.39：行业 / 品类画像（通用主干 + 局部调整）
  industryProfiles: () =>
    req<IndustryProfilesResponse>('/api/industry-profiles'),
  // V4.45 / D2：默认自动创作的策划结果（确定性，不触发新模型调用）
  creationRecommendation: (payload: {
    analysis: LandingAnalysis; platforms?: string[]; platform?: string
    workspace_defaults?: Partial<WorkspaceDefaults>; mode?: 'auto' | 'custom'
  }) =>
    req<CreationRecommendation>('/api/creation-recommendation',
      { method: 'POST', body: JSON.stringify(payload) }),
  // V4.46 / D5：自动创作的持久计划（创建 → 确认平台 → 冻结版本与费用授权 → 归档）
  createCreationPlan: (payload: {
    analysis: LandingAnalysis; platforms?: string[]; workspace_defaults?: Partial<WorkspaceDefaults>
  }) =>
    req<CreationPlan>('/api/creation-plans', { method: 'POST', body: JSON.stringify(payload) }),
  getCreationPlan: (planId: string) =>
    req<CreationPlan>(`/api/creation-plans/${encodeURIComponent(planId)}`),
  setPlanCoverage: (planId: string, platforms: string[]) =>
    req<CreationPlan>(`/api/creation-plans/${encodeURIComponent(planId)}/coverage`,
      { method: 'POST', body: JSON.stringify({ platforms }) }),
  confirmPlan: (planId: string, feeAuthorizedUsd: number) =>
    req<CreationPlan>(`/api/creation-plans/${encodeURIComponent(planId)}/confirm`,
      { method: 'POST', body: JSON.stringify({ fee_authorized_usd: feeAuthorizedUsd }) }),
  finalizePlan: (planId: string, jobResults: any[]) =>
    req<CreationPlan>(`/api/creation-plans/${encodeURIComponent(planId)}/finalize`,
      { method: 'POST', body: JSON.stringify({ job_results: jobResults }) }),
  // 基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案
  mediaCopy: (payload: { analysis: LandingAnalysis; platform: string; lang?: string
    /** V4.41 / F04：编辑过的方向 / 风格 / 配色预设参与文案生成 */
    style_opts?: Record<string, any>
    /** V4.101：用户确认后的创意 brief（未确认会被后端 400 拦截） */
    brief?: CreativeBrief | null }) =>
    req<MediaCopyResult>('/api/media-campaign/copy', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.101：框架目录 + 用户提示词补全预览（纯规则，不生成素材、不产生出片费用）
  creativeFrameworks: () => req<{ frameworks: Array<{ key: string; label: string; desc: string;
    beats: string[]; layers: string[]; requires_evidence: boolean }> }>('/api/creative-frameworks'),
  previewCreativeBrief: (payload: { raw_input: string; analysis?: any; platform?: string;
    framework?: string; layers?: string[] }) =>
    req<CreativeBrief>('/api/creative-brief/preview', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.108 素材工作坊：链接/描述 → 文案 + 图片，模型只用「大模型配置」里已验证的配置
  workshopOptions: () =>
    req<WorkshopOptions>('/api/workshop/options'),
  workshopAnalyze: (payload: { input: string; platforms: string[]
    creative_intent?: Record<string, any>; intent_text?: string; demo_mode?: boolean }) =>
    req<WorkshopAnalyzeResult>('/api/workshop/analyze', { method: 'POST', body: JSON.stringify(payload) }),
  workshopGenerate: (payload: { analysis: any; plan_id?: number | null
    targets: Array<{ platform: string; sizes: string[] }>; lang?: string; template_id?: number | null }) =>
    req<WorkshopGenerateResult>('/api/workshop/generate', { method: 'POST', body: JSON.stringify(payload) }),
  // 按模板创作：模板列表 + 逐条基础可用性状态（只驱动图片，不影响文案）
  workshopTemplates: () => req<any[]>('/api/workshop/templates'),
  // 基于「勾选的创意文案组合」+ 落地页分析结论 + 风格/样式/颜色，生成推广图片
  mediaImages: (payload: MediaImagePayload) =>
    req<MediaImageResult>('/api/media-campaign/images', { method: 'POST', body: JSON.stringify(payload) }),
  /* V4.42 / F12：服务端持久任务。生成 + 归档都在服务端完成，浏览器只轮询状态。 */
  createGenerationJob: (payload: {
    images_request: MediaImagePayload
    archive?: { history_id?: number | null; platform?: string; lang?: string
                copy?: any; style_opts?: Record<string, any>
                /** V4.45 / N03：草案标记随任务快照持久化，避免事后被当作合格商品广告 */
                delivery_grade?: 'draft' | 'standard'
                plan_id?: string; plan_version?: string }
    idempotency_key?: string
  }) =>
    req<GenerationJob>('/api/generation-jobs', { method: 'POST', body: JSON.stringify(payload) }),
  generationJob: (jobId: string) =>
    req<GenerationJob>(`/api/generation-jobs/${encodeURIComponent(jobId)}`),
  generationJobs: (params: { history_id?: number; limit?: number; offset?: number } = {}) =>
    req<{ items: GenerationJob[]; total: number; limit: number; offset: number }>(
      `/api/generation-jobs${qs(params)}`),
  cancelGenerationJob: (jobId: string) =>
    req<{ ok: boolean; status: string; message: string }>(
      `/api/generation-jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }),
  retryGenerationJob: (jobId: string) =>
    req<GenerationJob>(`/api/generation-jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' }),
  creativeAssets: (params: { history_id?: number; job_id?: string; limit?: number; offset?: number } = {}) =>
    req<CreativeAssetList>(`/api/creative-assets${qs(params)}`),
  // 素材历史：一次创作会话按「分析 → 文案 → 图片」增量落库
  creationHistory: (params: { q?: string; platform?: string; limit?: number; offset?: number } = {}) =>
    req<CreationHistoryList>(`/api/creation-history${qs(params)}`),
  createCreationHistory: (payload: {
    analysis: LandingAnalysis; platform?: string; lang?: string; source_id?: number
  }) =>
    req<CreationHistory>('/api/creation-history', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.50 创意工作台 · 全球创意分析（参考素材 → 大模型归类创意风格/类型 → 可复用提示词模板）
  creativeAnalyze: (payload: { urls?: string[]; text?: string; title?: string }) =>
    req<any>('/api/creative-analysis', { method: 'POST', body: JSON.stringify(payload) }),
  creativeAnalyses: (params: { limit?: number; offset?: number } = {}) =>
    req<{ items: any[]; total: number; limit: number; offset: number }>(
      `/api/creative-analysis${qs(params)}`),
  creativeAnalysis: (id: number) =>
    req<any>(`/api/creative-analysis/${id}`),
  // V4.117 素材创意模板库：三层数据模型 CRUD（素材条目 / 分析记录 / 模板）
  tlAssets: (params: { kind?: string; limit?: number; offset?: number } = {}) =>
    req<any[]>(`/api/template-library/assets${qs(params)}`),
  tlAddAsset: (payload: any) =>
    req<any>('/api/template-library/assets', { method: 'POST', body: JSON.stringify(payload) }),
  tlDeleteAsset: (id: number) =>
    req<any>(`/api/template-library/assets/${id}`, { method: 'DELETE' }),
  tlAnalyses: (params: { asset_id?: number; limit?: number; offset?: number } = {}) =>
    req<any[]>(`/api/template-library/analyses${qs(params)}`),
  tlAddAnalysis: (payload: any) =>
    req<any>('/api/template-library/analyses', { method: 'POST', body: JSON.stringify(payload) }),
  tlTemplates: (params: { category?: string; limit?: number; offset?: number } = {}) =>
    req<any[]>(`/api/template-library/templates${qs(params)}`),
  tlAddTemplate: (payload: any) =>
    req<any>('/api/template-library/templates', { method: 'POST', body: JSON.stringify(payload) }),
  tlUpdateTemplate: (id: number, payload: any) =>
    req<any>(`/api/template-library/templates/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  tlDeleteTemplate: (id: number) =>
    req<any>(`/api/template-library/templates/${id}`, { method: 'DELETE' }),
  // V4.118 素材创意模板库：统一导入登记 + 图片解构
  tlImport: (payload: any) =>
    req<any>('/api/template-library/import', { method: 'POST', body: JSON.stringify(payload) }),
  tlAnalyze: (assetId: number) =>
    req<any>(`/api/template-library/analyze/${assetId}`, { method: 'POST' }),
  // V4.119 素材创意模板库：分类字典 / 归并候选 / 人工确认沉淀 / golden 覆盖 / 撤销归并
  tlTaxonomy: () =>
    req<any>('/api/template-library/taxonomy'),
  tlMergeCandidates: () =>
    req<any>('/api/template-library/merge-candidates'),
  tlMergeConfirm: (payload: any) =>
    req<any>('/api/template-library/merge/confirm', { method: 'POST', body: JSON.stringify(payload) }),
  tlConfirmCategory: (analysisId: number, payload: any) =>
    req<any>(`/api/template-library/analyses/${analysisId}/category`, { method: 'PATCH', body: JSON.stringify(payload) }),
  tlSetGolden: (templateId: number, payload: any) =>
    req<any>(`/api/template-library/templates/${templateId}/golden`, { method: 'POST', body: JSON.stringify(payload) }),
  tlUnmerge: (templateId: number, payload: any) =>
    req<any>(`/api/template-library/templates/${templateId}/unmerge`, { method: 'POST', body: JSON.stringify(payload) }),
  // V4.52 创意工作台 · 创意策略 / 路线规划 + 历史库
  creativePlan: (payload: { title?: string; analysis: any; platforms: string[]; gen_image?: boolean; gen_video?: boolean }) =>
    req<any>('/api/creative-plan', { method: 'POST', body: JSON.stringify(payload) }),
  updateCreativePlan: (id: number, payload: { status?: string; asset_count?: number; history_id?: number; routes_json?: any[]; title?: string }) =>
    req<any>(`/api/creative-plan/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  creativePlans: (params: { limit?: number; offset?: number } = {}) =>
    req<{ items: any[]; total: number; limit: number; offset: number }>(`/api/creative-plan${qs(params)}`),
  creativePlanDetail: (id: number) =>
    req<any>(`/api/creative-plan/${id}`),
  // V4.53 创意工作台：设计对齐的产品分析 + 3 条创意路线（复用 CreativePlan 存储）
  // V4.59 / B1：支持 demo_mode（演示模式开关，仅开启时返回样例数据并标注 source=demo）
  // V4.105 / 方案C：创作意图随分析一起提交（结构化 + 一句话），并支持分析前预览解析结果
  cwAnalyze: (payload: { url?: string; text?: string; platforms: string[]; demo_mode?: boolean
    creative_intent?: CreativeIntent; intent_text?: string }) =>
    req<any>('/api/cw/analyze', { method: 'POST', body: JSON.stringify(payload) }),
  cwIntentParse: (payload: { intent?: CreativeIntent; text?: string }) =>
    req<{ intent: CreativeIntent; patch: CreativeIntent; changes: string[]; notes: string[]
      conflicts: string[]; change_kind: 'none' | 'visual' | 'concept'; summary: string }>(
      '/api/cw/intent/parse', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.113：创意工作台模型自检（只读）——打开页面即显示三类用途的生效配置与未就绪原因
  cwModelStatus: () =>
    req<{ items: { usage: string; label: string; ready: boolean; reason: string
      name?: string; provider?: string; model?: string; config_id?: number
      reused_from?: string; note?: string }[]
      ready: boolean; missing: string[] }>('/api/cw/model-status'),
  cwRoutes: (payload: { plan_id?: number; analysis: any; platforms: string[]; brief: any; count?: number
    framework?: string; user_brief?: CreativeBrief | null; seed?: string; exclude_names?: string[]
    creative_intent?: CreativeIntent }) =>
    req<any>('/api/cw/routes', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.105 / 方案C：路线卡就地改一句推荐描述（只改这一条，不必重规划整批）
  patchCwRoute: (planId: number, key: string, payload: { name?: string; description?: string
    angle?: string; tags?: string[]; hook?: string; proof?: string; visual_hook?: string; cta_role?: string
    user_note?: string }) =>
    req<{ id: number; key: string; routes: any[]; changed: string[] }>(
      `/api/cw/routes/${planId}/${key}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  // V4.61 / B4：创意工作台「素材沉淀库」（参考图 / 产品 / 品牌）增查删
  cwLibrary: (params: { kind?: string; limit?: number; offset?: number } = {}) =>
    req<any[]>('/api/cw/library' + qs(params)),
  addCwLibrary: (payload: { kind: string; title?: string; file?: string; url?: string; meta?: any; source_plan_id?: number }) =>
    req<any>('/api/cw/library', { method: 'POST', body: JSON.stringify(payload) }),
  deleteCwLibrary: (id: number) =>
    req<{ ok: boolean }>(`/api/cw/library/${id}`, { method: 'DELETE' }),
  // V4.66 创意工作台 · 视频素材创作区：对话式分镜策划 + 生成（直连视频模型 / 回退分镜脚本）
  cwVideoPlan: (payload: {
    analysis: any; platform: string; reference_image?: string;
    messages: { role: string; content: string }[]; current_plan?: any; options?: any;
    framework?: string; user_brief?: CreativeBrief | null; regenerate?: boolean; seed?: string;
  }) =>
    req<any>('/api/cw-video/plan', { method: 'POST', body: JSON.stringify(payload) }),
  cwVideoGenerate: (payload: {
    analysis: any; platform: string; reference_image?: string; plan: any; options?: any;
  }) =>
    req<any>('/api/cw-video/generate', { method: 'POST', body: JSON.stringify(payload) }),
  // V4.76 出片异步化：页面统一走这条（提交任务 + 轮询），避免反向代理 504
  cwVideoGenerateAsync,
  // V4.81 / P2：提交即返回（不轮询），进度看「任务」抽屉；同一幂等键不会产生第二次收费任务
  submitVideoJob: (payload: {
    analysis: any; platform: string; reference_image?: string; plan: any; options?: any;
  }, opts: { idempotencyKey?: string; draftId?: string; batchId?: string } = {}) =>
    req<any>('/api/cw-video/generate-jobs', {
      method: 'POST', body: JSON.stringify(payload),
      headers: {
        ...(opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : {}),
        ...(opts.draftId ? { 'X-Draft-Id': opts.draftId } : {}),
        ...(opts.batchId ? { 'X-Batch-Id': opts.batchId } : {}),
      },
    }),
  cwVideoGenerateJob: (payload: {
    analysis: any; platform: string; reference_image?: string; plan: any; options?: any;
  }) => req<any>('/api/cw-video/generate-jobs', { method: 'POST', body: JSON.stringify(payload) }),
  cwVideoJob: (jobId: string) => req<any>(`/api/cw-video/generate-jobs/${jobId}`),
  // V4.81 / P3：创作任务列表（本人批次，服务端唯一事实）
  createCreativeTask: (payload: { product_name?: string; source_url?: string; material_types?: string[]; platforms?: string[]; draft_id?: string }) =>
    req<any>('/api/creative-tasks', { method: 'POST', body: JSON.stringify(payload) }),
  creativeTasks: (params: { status?: string; cursor?: string; limit?: number } = {}) =>
    req<any>('/api/creative-tasks' + qs(params)),
  creativeTask: (batchId: string) => req<any>(`/api/creative-tasks/${batchId}`),
  retryCreativeTask: (batchId: string, jobId: string, action: 'repoll' | 'redownload' | 'regenerate') =>
    req<any>(`/api/creative-tasks/${batchId}/retry`,
      { method: 'POST', body: JSON.stringify({ job_id: jobId, action }) }),
  cancelCreativeTask: (batchId: string, jobId = '', reason = 'user') =>
    req<any>(`/api/creative-tasks/${batchId}/cancel`,
      { method: 'POST', body: JSON.stringify({ job_id: jobId, reason }) }),
  // V4.75 视频链路自检：报告当前生效的视频模型配置与契约参数是否齐备（不出片）
  cwVideoDiagnose: () => req<any>('/api/cw-video/diagnose'),
  updateCreationHistory: (id: number, payload: {
    // V4.38：copy 允许附带 selected_copy / copy_variants，记录本次选用的创意文案
    platform?: string; lang?: string; copy?: any
    images?: MediaImageItem[]; images_mode?: 'append' | 'replace'
    style_opts?: Record<string, any>; image_model?: ModelInfo | null; note?: string
  }) =>
    req<CreationHistory>(`/api/creation-history/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteCreationHistory: (ids: number[]) =>
    req<{ ok: boolean; deleted: number; deleted_files: number }>('/api/creation-history',
      { method: 'DELETE', body: JSON.stringify({ ids }) }),
  // 版本发布公告（V4.43）：禁缓存 + 时间戳，系统更新后重新拉取即为最新内容
  releaseNotes: () => req<ReleaseNotesResponse>(
    `/api/system/release-notes?_t=${Date.now()}`, { cache: 'no-store' }),
  uploadAsset: async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const token = getToken()
    const res = await fetch(API_BASE + '/api/assets/upload', {
      method: 'POST', body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`上传失败 ${res.status}`)
    return res.json() as Promise<{ path: string; url: string; name: string }>
  },
  // 把远程图片下载到本地 uploads，返回 /files/<name>（素材导入用；图片参考图链路 V4.110 已下线）
  fetchAssetUrl: (url: string) =>
    req<{ path: string; url: string; name: string }>('/api/assets/fetch-url',
      { method: 'POST', body: JSON.stringify({ url }) }),
  // V4.118：网页链接自动截图（服务端 headless chromium + SSRF 防护）
  screenshotAsset: (url: string, mode: 'viewport' | 'fullpage' = 'viewport') =>
    req<{ path: string | null; url: string | null; status: string; reason?: string;
          width?: number; height?: number; integrity_note?: string }>('/api/assets/screenshot',
      { method: 'POST', body: JSON.stringify({ url, mode }) }),
  // V4.118：素材视频上传（归档 + 封面帧；解构在 V4.121）
  uploadVideoAsset: async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const token = getToken()
    const res = await fetch(API_BASE + '/api/assets/upload-video', {
      method: 'POST', body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) {
      let msg = `上传失败 ${res.status}`
      try { msg = (await res.json()).detail || msg } catch { /* ignore */ }
      throw new Error(msg)
    }
    return res.json() as Promise<{ path: string; url: string; name: string;
      thumb?: string; duration_sec?: number; status: string; note?: string }>
  },
  // V4.60 / B3：按 id 取单条素材历史（含 copy_json），用于恢复已生成的文案
  creationHistoryDetail: (id: number) =>
    req<any>(`/api/creation-history/${id}`),
  models: () => req<ModelConfig[]>('/api/settings/models'),
  modelPresets: (usage?: string) =>
    req<ModelPreset[]>(`/api/settings/models/presets${usage ? `?usage=${encodeURIComponent(usage)}` : ''}`),
  // 全量预设（文本 + 文生图 + 文生视频），弹窗下拉一次性拉取
  modelPresetsAll: () =>
    req<ModelPreset[]>('/api/settings/models/presets?usage=all'),
  creativePresets: () => req<CreativePresets>('/api/settings/creative-presets'),
  createModel: (m: Partial<Omit<ModelConfig, 'usage'>> & { usage?: string | string[] }) =>
    req<ModelConfig>('/api/settings/models', { method: 'POST', body: JSON.stringify(m) }),
  updateModel: (id: number, m: Partial<Omit<ModelConfig, 'usage'>> & { usage?: string | string[] }) =>
    req<ModelConfig>(`/api/settings/models/${id}`, { method: 'PUT', body: JSON.stringify(m) }),
  deleteModel: (id: number) =>
    req<any>(`/api/settings/models/${id}`, { method: 'DELETE' }),
  testModel: (m: Partial<ModelConfig> & { endpoint?: string; protocol?: string }) =>
    req<ModelTestResult>(
      '/api/settings/models/test', { method: 'POST', body: JSON.stringify(m) }),
  // V4.34 连通性健康
  modelHealth: () => req<ModelHealthInfo>('/api/settings/models/health'),
  testAllModels: () => req<ModelTestAllResult>('/api/settings/models/test-all', { method: 'POST' }),
  testSavedModel: (id: number) =>
    req<ModelTestResult & { config?: ModelConfig }>(`/api/settings/models/${id}/test`, { method: 'POST' }),
  // V4.35 统一提示词目录（可传字符串=按 module 筛选，兼容旧调用；或传筛选对象）
  prompts: (opts?: string | PromptListOpts) => {
    const o: PromptListOpts = typeof opts === 'string' ? { module: opts } : (opts || {})
    return req<PromptConfig[]>(`/api/settings/prompts${qs(o)}`)
  },
  updatePrompt: (key: string, payload: { content: string; name?: string; description?: string;
    category?: string; func_type?: string; usage_type?: string;
    intent?: string; psychological_layers?: string; is_active?: boolean }) =>
    req<PromptConfig>(`/api/settings/prompts/${key}`, { method: 'PUT', body: JSON.stringify(payload) }),
  resetPrompt: (key: string) =>
    req<PromptConfig>(`/api/settings/prompts/${key}/reset`, { method: 'POST' }),
  // V4.98 / V4.100 提示词管理：元数据 + 心理链条自动匹配
  materialPromptMeta: () => req<MaterialPromptMeta>('/api/settings/material-prompts/meta'),
  matchLayers: (analysis: any) => req<LayerMatchResult>('/api/settings/material-prompts/match-layers',
    { method: 'POST', body: JSON.stringify({ analysis }) }),
  // V4.35 分类维度 / 优秀提示词总结库 / 系统默认
  promptTaxonomy: () => req<PromptTaxonomy>('/api/settings/prompt-taxonomy'),
  promptLibrary: (f?: PromptLibraryFilters) =>
    req<PromptLibraryResponse>(`/api/settings/prompt-library${qs(f || {})}`),
  setPromptDefault: (kind: string, id: string | null) =>
    req<{ ok: boolean; kind: string; target_key: string; id: string | null; name: string;
          defaults: Record<string, PromptDefaultInfo> }>(
      '/api/settings/prompt-defaults', { method: 'PUT', body: JSON.stringify({ kind, id }) }),
  // V4.104 / 方案E：图片质量扩展质检开关（系统设置，默认打开）
  imageQualityAudit: () =>
    req<{ enabled: boolean }>('/api/settings/image-quality-audit'),
  setImageQualityAudit: (enabled: boolean) =>
    req<{ ok: boolean; enabled: boolean }>('/api/settings/image-quality-audit',
      { method: 'PUT', body: JSON.stringify({ enabled }) }),
  fileUrl: (filePath?: string) => {
    if (!filePath) return ''
    const rel = filePath.includes('/uploads/') ? filePath.split('/uploads/')[1] : filePath.split('/').pop()
    return `${API_BASE}/files/${rel}`
  },
  /* V4.36 推广图片查阅 / 下载：浏览器直链无法带 Header，token 走 query（后端验签 + 角色校验） */
  mediaFileDownloadUrl: (file: string) =>
    `${API_BASE}/api/media-files/download?file=${encodeURIComponent(file)}&token=${encodeURIComponent(getToken())}`,
  mediaZipUrl: (files: string[], label = '推广图片') =>
    `${API_BASE}/api/media-files/zip?files=${encodeURIComponent(files.join(','))}` +
    `&label=${encodeURIComponent(label)}&token=${encodeURIComponent(getToken())}`,
  historyItemZipUrl: (id: number, batchId = '') =>
    `${API_BASE}/api/creation-history/${id}/export.zip?token=${encodeURIComponent(getToken())}`
      + (batchId ? `&batch_id=${encodeURIComponent(batchId)}` : ''),
  historyBatchZipUrl: (ids: number[]) =>
    `${API_BASE}/api/creation-history/export?ids=${ids.join(',')}&token=${encodeURIComponent(getToken())}`,
  historyCopyUrl: (id: number) =>
    `${API_BASE}/api/creation-history/${id}/copy.txt?token=${encodeURIComponent(getToken())}`,
}

/* ===== V4.124 广告主数据模块 ===== */
export interface ApiTemplate {
  code: string
  name: string
  vendor: string
  description: string
  method: string
  auth_type: string
  default_endpoint: string
  required_fields: { key: string; label: string; type: string; required: boolean }[]
  limits: string
  framework_version: string
  status: string
  // V4.129：模板声明的请求对象（PublisherCommission 订单明细）
  record_object: string
  record_object_desc: string
}
export interface ApiSchedule {
  enabled: boolean
  frequency: 'daily' | '6h'
  hour: number
  lookback_days: number
  backfill_days: number
}
export interface ApiConnection {
  id: number
  name: string
  template_code: string
  cid: string
  endpoint: string
  token_mask: string
  status: string
  last_test_ok: boolean | null
  last_test_at: string | null
  last_test_error: string
  last_test_http_code: number | null
  last_test_count: number | null
  last_test_url: string
  last_test_request_body: Record<string, unknown>
  last_test_response_text: string
  schedule: ApiSchedule
  created_at: string | null
  // V4.133：更新时间（新建/配置变更）与 API 同步时间（最近一次请求）
  config_updated_at: string | null
  last_sync_at: string | null
}
export interface ApiTestResult {
  ok: boolean
  error: string
  count: number
  http_code: number
  payload_complete: boolean
  max_commission_id: string
  // V4.128：完整请求 / 响应明细，供列表「测试」右侧滑窗展示
  request_url: string
  request_method: string
  request_body: Record<string, unknown>
  response_text: string
  response: Record<string, unknown> | null
  tested_at: string
  // V4.129：实际拉取的 PublisherCommission 明细对象与条数
  record_object: string
  record_count: number
  sample_records: Record<string, unknown>[]
  // V4.131：实际查询窗口与空明细提示
  window_since: string
  window_before: string
  hint: string
}

// V4.132 / P1-B：拉取并幂等落库的执行结果
export interface ApiFetchResult {
  run_id: number
  ok: boolean
  error?: string
  window_since: string
  window_before: string
  http_code?: number
  fetched_count?: number
  inserted?: number
  updated?: number
  unchanged?: number
  skipped?: number
  void_recalculated?: number
  warnings?: string[]
}

// V4.134 / P1-C：历史回填汇总
export interface ApiBackfillResult {
  connection_id: number
  days: number
  slices: number
  ok: boolean
  fetched: number
  inserted: number
  updated: number
  void_recalculated: number
  runs: { run_id: number; ok: boolean; window_since: string; window_before: string }[]
  errors: string[]
}

// V4.134 / P2：运行记录与调度状态
export interface ApiFetchRun {
  id: number
  connection_id: number
  status: string
  run_mode: string
  window_from: string | null
  window_to: string | null
  fetched_count: number
  inserted_count: number
  updated_count: number
  cursor_json: Record<string, unknown> | null
  error: string
  started_at: string | null
  finished_at: string | null
}

export interface ApiSchedulerInfo {
  enabled: boolean
  auto_backfill: boolean
  loop_running: boolean
  tasks: {
    id: number; connection_id: number; name: string; enabled: boolean
    frequency: string; hour: number; lookback_days: number; backfill_days: number
    status: string; last_run_at: string | null; next_run_at: string | null
  }[]
}

export const advertiserApi = {
  status: () => req<{ enabled: boolean }>('/api/advertiser-data/status'),
  templates: () => req<ApiTemplate[]>('/api/advertiser-data/templates'),
  connections: () => req<ApiConnection[]>('/api/advertiser-data/connections'),
  createConnection: (b: { name: string; template_code: string; token: string; cid: string; endpoint?: string }) =>
    req<ApiConnection>('/api/advertiser-data/connections', { method: 'POST', body: JSON.stringify(b) }),
  // V4.125：弹窗一个「保存」按钮 = 创建 + 真实测试 + 状态回写
  createAndTestConnection: (b: { name: string; template_code: string; token: string; cid: string; endpoint?: string }) =>
    req<ApiConnection>('/api/advertiser-data/connections/create-and-test', { method: 'POST', body: JSON.stringify(b) }),
  updateConnection: (id: number, b: Partial<{ name: string; cid: string; endpoint: string; token: string; status: string; schedule: ApiSchedule }>) =>
    req<ApiConnection>(`/api/advertiser-data/connections/${id}`, { method: 'PATCH', body: JSON.stringify(b) }),
  deleteConnection: (id: number) =>
    req<void>(`/api/advertiser-data/connections/${id}`, { method: 'DELETE' }),
  testConnection: (b: {
    connection_id?: number; template_code?: string; token?: string; cid?: string; endpoint?: string
    since_event_date?: string; before_event_date?: string
  }) =>
    req<ApiTestResult>('/api/advertiser-data/connections/test', { method: 'POST', body: JSON.stringify(b) }),
  // V4.132：手动拉取 PublisherCommission 明细并按映射幂等落库
  fetchConnection: (id: number, b?: { since_event_date?: string; before_event_date?: string }) =>
    req<ApiFetchResult>(`/api/advertiser-data/connections/${id}/fetch`, { method: 'POST', body: JSON.stringify(b || {}) }),
  // V4.134 / P1-C：按 ≤31 天分片回填历史并全量重算取消单
  backfillConnection: (id: number, days?: number) =>
    req<ApiBackfillResult>(`/api/advertiser-data/connections/${id}/backfill`, {
      method: 'POST', body: JSON.stringify(days ? { days } : {}),
    }),
  // V4.134 / P2：调度概况、手动触发一轮到期扫描、运行记录
  schedulerInfo: () => req<ApiSchedulerInfo>('/api/advertiser-data/scheduler'),
  runSchedulerOnce: () => req<{ reason: string; checked: number; ran: number }>(
    '/api/advertiser-data/scheduler/run', { method: 'POST', body: '{}' }),
  fetchRuns: (connectionId?: number) =>
    req<ApiFetchRun[]>(`/api/advertiser-data/fetch-runs?limit=20${connectionId ? `&connection_id=${connectionId}` : ''}`),

  // ---- V4.135 / P3：广告主报表（纯读，表头/口径全部由后端配置驱动）----
  reportLabels: (scope: 'fact' | 'order_final' | 'item' = 'fact') =>
    req<ReportLabels>(`/api/advertiser-data/reports/labels${qs({ scope })}`),
  reportDimensions: () => req<{ dimensions: { key: string; label: string }[] }>(
    '/api/advertiser-data/reports/dimensions'),
  reportKpi: (f: ReportFilter = {}) =>
    req<ReportKpi>(`/api/advertiser-data/reports/kpi${qs(f)}`),
  reportTrend: (f: ReportFilter & { dimension?: string; dimension_value?: string } = {}) =>
    req<ReportTrend>(`/api/advertiser-data/reports/trend${qs(f)}`),
  reportRankings: (f: ReportFilter & { dimension?: string; limit?: number } = {}) =>
    req<ReportRankings>(`/api/advertiser-data/reports/rankings${qs(f)}`),
  reportDetails: (f: ReportFilter & { keyword?: string; page?: number; page_size?: number } = {}) =>
    req<ReportDetails>(`/api/advertiser-data/reports/details${qs(f)}`),
  reportDrilldown: (factId: number) =>
    req<ReportDrilldown>(`/api/advertiser-data/reports/drilldown/${factId}`),
  // V4.142：导出当前筛选的全部明细 CSV（二进制下载，非 JSON）
  reportExport: (f: ReportFilter = {}) =>
    downloadFile(`/api/advertiser-data/reports/export${qs(f)}`),
}

// ---- V4.135 / P3：广告主报表类型 ----
export interface ReportColumn {
  column_key: string
  label: string
  unit: string | null
  format: string
  enum_map: Record<string, string>
  sort_no: number
  visible: boolean
}
export interface ReportLabels {
  scope: string
  columns: ReportColumn[]
  all: ReportColumn[]
  unavailable_metrics: string[]
}
export interface ReportFilter {
  connection_id?: number
  date_from?: string
  date_to?: string
  // V4.140：KPI 与明细共用的维度 / 关键词筛选
  advertiser_name?: string
  campaign_name?: string
  event_name?: string
  action_status?: string
  keyword?: string
}
export interface ReportKpi {
  net_sale_usd: number
  net_commission_usd: number
  order_count: number
  void_count: number
  detail_count: number
  avg_order_value_usd: number
  source_view: string
  unavailable_metrics: string[]
}
export interface ReportTrendPoint {
  event_date: string
  net_sale_usd: number
  net_commission_usd: number
  order_count: number
}
export interface ReportTrend {
  points: ReportTrendPoint[]
  metric_labels: Record<string, string>
  total: number
}
export interface ReportRankItem {
  name: string
  net_sale_usd: number
  net_commission_usd: number
  order_count: number
}
export interface ReportRankings {
  dimension: string
  dimension_label: string
  items: ReportRankItem[]
  metric_labels: Record<string, string>
}
export interface ReportDetails {
  rows: Record<string, unknown>[]
  columns: ReportColumn[]
  total: number
  page: number
  page_size: number
  total_pages: number
  source_table: string
}
export interface ReportDrilldown {
  found: boolean
  fact?: Record<string, unknown>
  columns?: ReportColumn[]
  items?: Record<string, unknown>[]
  ext?: Record<string, unknown>
  source?: Record<string, unknown> | null
  field_maps?: { source_path: string; target_field: string; transform: string; note: string }[]
  chain?: string[]
}

/* V4.145 · 模仿创作视频（骨架）：任务视图类型与接口。 */
export interface ImitateTask {
  job_id: string
  name?: string
  status: string
  stage?: string
  source?: string
  created_at?: string
}

export const imitateVideoApi = {
  tasks: () => req<ImitateTask[]>('/api/imitate-video/tasks'),
}
