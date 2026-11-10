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
  description?: string
  content: string
  is_active: boolean
  updated_at?: string | null
}

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
  evidence_chain?: { claim: string; evidence_ids: string[]; kind: string }[]
  evidence_index?: EvidenceRecord[]
  evidence_coverage?: EvidenceCoverage[]
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
}

export interface EvidenceCoverage {
  evidence_id: string
  char_start: number
  char_end: number
  tags: string[]
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
  industry_profile?: string
  industry_profile_label?: string
  compress_calls?: number
  /** V4.41 / F04：本次文案实际使用的配置快照（后续改预设不覆盖） */
  creative_config?: CreativeConfigSnapshot
  creative_prompt_hash?: string
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
           concept_index?: number; concept_id?: string }[]
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

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(API_BASE + path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
    ...opts,
  })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event('admb:unauthorized'))
    throw new Error('未登录或登录已过期')
  }
  if (!res.ok) {
    const t = await res.text().catch(() => '')
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
  landingAnalysis: (payload: { url?: string; text?: string }) =>
    req<LandingAnalysis>('/api/landing-analysis', { method: 'POST', body: JSON.stringify(payload) }),
  // 素材创作：营销推广的媒体平台设置 —— 平台规格目录
  mediaPlatforms: () =>
    req<MediaPlatform[]>('/api/media-platforms'),
  // V4.40 / F08：版本化媒体规则（强制 / 政策 / 建议、上限、行业版位偏好）
  mediaRules: () =>
    req<MediaRules>('/api/media-rules'),
  // V4.42 / F06：供应商尺寸能力 / 核验状态
  imageCapabilities: () =>
    req<ImageCapabilities>('/api/image-capabilities'),
  // V4.39：行业 / 品类画像（通用主干 + 局部调整）
  industryProfiles: () =>
    req<IndustryProfilesResponse>('/api/industry-profiles'),
  // 基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案
  mediaCopy: (payload: { analysis: LandingAnalysis; platform: string; lang?: string
    /** V4.41 / F04：编辑过的方向 / 风格 / 配色预设参与文案生成 */
    style_opts?: Record<string, any> }) =>
    req<MediaCopyResult>('/api/media-campaign/copy', { method: 'POST', body: JSON.stringify(payload) }),
  // 基于「勾选的创意文案组合」+ 落地页分析结论 + 风格/样式/颜色，生成推广图片
  mediaImages: (payload: MediaImagePayload) =>
    req<MediaImageResult>('/api/media-campaign/images', { method: 'POST', body: JSON.stringify(payload) }),
  /* V4.42 / F12：服务端持久任务。生成 + 归档都在服务端完成，浏览器只轮询状态。 */
  createGenerationJob: (payload: {
    images_request: MediaImagePayload
    archive?: { history_id?: number | null; platform?: string; lang?: string
                copy?: any; style_opts?: Record<string, any> }
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
    category?: string; func_type?: string; usage_type?: string; is_active?: boolean }) =>
    req<PromptConfig>(`/api/settings/prompts/${key}`, { method: 'PUT', body: JSON.stringify(payload) }),
  resetPrompt: (key: string) =>
    req<PromptConfig>(`/api/settings/prompts/${key}/reset`, { method: 'POST' }),
  // V4.35 分类维度 / 优秀提示词总结库 / 系统默认
  promptTaxonomy: () => req<PromptTaxonomy>('/api/settings/prompt-taxonomy'),
  promptLibrary: (f?: PromptLibraryFilters) =>
    req<PromptLibraryResponse>(`/api/settings/prompt-library${qs(f || {})}`),
  setPromptDefault: (kind: string, id: string | null) =>
    req<{ ok: boolean; kind: string; target_key: string; id: string | null; name: string;
          defaults: Record<string, PromptDefaultInfo> }>(
      '/api/settings/prompt-defaults', { method: 'PUT', body: JSON.stringify({ kind, id }) }),
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
  historyItemZipUrl: (id: number) =>
    `${API_BASE}/api/creation-history/${id}/export.zip?token=${encodeURIComponent(getToken())}`,
  historyBatchZipUrl: (ids: number[]) =>
    `${API_BASE}/api/creation-history/export?ids=${ids.join(',')}&token=${encodeURIComponent(getToken())}`,
  historyCopyUrl: (id: number) =>
    `${API_BASE}/api/creation-history/${id}/copy.txt?token=${encodeURIComponent(getToken())}`,
}
