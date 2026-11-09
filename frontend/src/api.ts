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

/** V4.37 结构化版本通知：按「涉及模块 / 变更类型」可筛选，含影响范围与验证结果 */
export interface ReleaseNoteChange {
  type: string        // 新增 / 优化 / 修复 / 删除 / 重构 / 发布 …
  module: string      // 涉及模块
  title: string       // 功能 / 子模块
  detail: string      // 具体改动说明
}
export interface ReleaseNote {
  version: string
  title: string
  date: string | null
  body: string                    // 完整发版记录（原始 Markdown）
  summary: string                 // 变更摘要
  modules: string[]               // 涉及模块
  change_types: string[]          // 变更类型
  changes: ReleaseNoteChange[]    // 本次优化与更改的功能 / 模块
  impact: string[]                // 影响范围
  verification: string[]          // 验证结果
  has_structured: boolean         // 是否为 V4.37 起的结构化版本
}
export interface ReleaseNotesResponse {
  latest: string | null
  notes: ReleaseNote[]
  modules: string[]
  change_types: string[]
  total: number
  structured_count: number
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
  fallback: boolean   // true = 实际走了 Mock 兜底（未配置有效模型）
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
  source: string           // llm / local —— 结果是否真的来自大模型推理
}

/* ----------------------------- 媒体推广的媒体平台设置 ----------------------------- */
export interface MediaPlacement {
  id: string
  name: string
  sizes: string[]
  desc: string
  default: boolean
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
}

export interface MediaCopyResult {
  platform: string
  lang: string
  fields: Record<string, any>
  schema: { key: string; label: string; max: number; count: number }[]
  char_table: { field: string; text: string; len: number; max: number; over: boolean }[]
  validation: { valid: boolean; issues: { level: string; code: string; message: string }[]; problems?: any[] }
  model_info: ModelInfo
  brand: string
}

/** V4.38：一条被勾选的「创意文案组合」，会叠加到一张推广图片上 */
export interface CopyVariant {
  headline: string
  sub: string
  cta: string
  brand: string
  label: string
}

export interface MediaImageItem {
  url: string
  file: string
  size: string
  w: number
  h: number
  placement: string
  /** V4.38：本张图片实际选用的文案组合（后端按版位轮换写入） */
  variant?: string
  copy?: { headline: string; sub: string; cta: string }
}

export interface MediaImageResult {
  platform: string
  images: MediaImageItem[]
  image_model: ModelInfo
  note: string
  count: number
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
    try { detail = JSON.parse(t).detail || t } catch { /* 保留原文 */ }
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
  // 基于落地页分析结论 + 选中平台，调用大模型生成可编辑广告文案
  mediaCopy: (payload: { analysis: LandingAnalysis; platform: string; lang?: string }) =>
    req<MediaCopyResult>('/api/media-campaign/copy', { method: 'POST', body: JSON.stringify(payload) }),
  // 基于「勾选的创意文案组合」+ 落地页分析结论 + 风格/样式/颜色，生成推广图片
  mediaImages: (payload: {
    analysis: LandingAnalysis; platform: string; lang?: string
    copy_fields: Record<string, any>; copy_variants?: CopyVariant[]
    style_opts: Record<string, string>; slots: { size: string; placement: string }[]
    logo?: string
  }) =>
    req<MediaImageResult>('/api/media-campaign/images', { method: 'POST', body: JSON.stringify(payload) }),
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
    style_opts?: Record<string, string>; image_model?: ModelInfo | null; note?: string
  }) =>
    req<CreationHistory>(`/api/creation-history/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteCreationHistory: (ids: number[]) =>
    req<{ ok: boolean; deleted: number; deleted_files: number }>('/api/creation-history',
      { method: 'DELETE', body: JSON.stringify({ ids }) }),
  // 版本发布公告（新版通知）
  releaseNotes: () => req<ReleaseNotesResponse>('/api/system/release-notes'),
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
