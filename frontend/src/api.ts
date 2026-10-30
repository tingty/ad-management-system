const _envApiBase = (import.meta as any).env?.VITE_API_BASE
// 生产部署：构建时通过 VITE_API_BASE='' 让前端使用同源相对路径（/api、/files 由 nginx 反代到后端）。
// 本地开发：未设置该变量时回退到默认后端地址，保持原有开发体验。
export const API_BASE: string =
  _envApiBase !== undefined ? _envApiBase : 'http://127.0.0.1:8033'

const TOKEN_KEY = 'admb_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

export interface Framework {
  id: number
  product: string
  category?: string
  audience?: string
  geo?: string
  languages?: string[]
  selling_points?: string[]
  platform_analysis?: Record<string, string>
  domain?: string
  metrics?: string[]
  brand_color?: string
  assets?: { product?: string; logo?: string }
  analyzer?: string
  evidence?: {
    product?: { value: string; source: string }
    category?: { value: string; matched_words?: string[] }
    selling_points?: { value: string[]; source: string }
    metrics?: { value: string[]; source: string }
    audience?: { value: string; source: string }
    geo?: { value: string[]; source: string }
    source_len?: number
  }
}

export interface PlanEstimate {
  angles: number
  platforms: string[]
  languages: string[]
  sizes_per_angle: number
  video_mode: string
  per_platform: { platform: string; sizes: number; available: number }[]
  images: number
  copy: number
  video: number
  keyword: number
  total: number
  limit?: number
  over_limit?: boolean
}

export interface Angle {
  id: number
  framework_id: number
  key: string
  name: string
  insight?: string
  visual?: string
  template?: string
  hook?: string
  kpi?: string
  platform_fit?: string[]
  sort: number
}

export interface CopyFieldSpec {
  key: string
  label: string
  max: number
  count: number
  multiline?: boolean
  enum?: string[]
}

export interface CharRow {
  field: string
  text: string
  len: number
  max: number
  over: boolean
}

export interface Material {
  id: number
  campaign_id: number
  type: string
  platform: string
  angle_key?: string
  language?: string
  spec_json?: any
  content?: any
  text_content?: string
  file_path?: string
  version: number
  variant?: string
  selected?: boolean
  prompt_log?: string
  validation?: {
    valid: boolean
    issues: { level: string; code: string; message: string }[]
    problems?: { level: string; field: string; msg: string }[]
  }
}

export interface PlatformSpec {
  id: number
  platform: string
  ad_placement?: string
  image_sizes?: string[]
  video_spec?: string
  copy_rules?: string
  keyword_logic?: string
  copy_limits?: { title_max?: number; description_max?: number; primary_text_max?: number }
  updated_at?: string
}

export interface Campaign {
  id: number
  name: string
  framework_id: number
  platforms?: string[]
  angle_keys?: string[]
  options?: { sizes_per_angle?: number; video_mode?: string; material_types?: string[]; languages?: string[] }
  status: string
  owner_id?: number
  reviewer_id?: number
  review_note?: string
  materials: Material[]
}

export interface SlotInfo {
  platform: string
  language?: string
  type: string
  variants: {
    id: number; version: number; variant: string; selected: boolean
    valid: boolean; issues: number; chars: number; prompt_log?: string
  }[]
  selected_id: number | null
}

export interface CompareField {
  key: string
  left: any
  right: any
  changed: boolean
  left_chars: number | number[] | null
  right_chars: number | number[] | null
}

export interface MaterialBrief {
  id: number
  version: number
  variant: string
  selected: boolean
  platform: string
  language?: string
  type: string
  content: any
  text: string
  char_total: number
  validation?: any
  prompt_log?: string
}

export interface CompareResult {
  slot: { campaign_id: number; platform: string; language?: string; type: string }
  left: MaterialBrief
  right: MaterialBrief
  char_delta: number
  fields: CompareField[]
  changed_count: number
}

export interface ModelConfig {
  id: number
  usage: string
  provider: string
  api_key?: string
  base_url?: string
  model?: string
  params?: any
  is_active: boolean
}

export interface Meta {
  platforms: string[]
  material_types: string[]
  languages: string[]
  copy_schema?: Record<string, CopyFieldSpec[]>
  angle_library?: { key: string; name: string; insight: string; visual: string; kpi: string; template: string; platform_fit: string[] }[]
}

// ----------------------------- V3.2 分析报告 / 素材优化 -----------------------------
export interface ReportRow {
  label: string
  value: string
  note?: string
  level?: string
}

export interface ReportSection {
  key: string
  title: string
  summary?: string
  rows?: ReportRow[]
  items?: any[]
}

export interface ValueProp {
  rank: number
  point: string
  type: 'metric' | 'proof' | 'benefit' | string
  strength: '强' | '中' | '弱' | string
  evidence: string
}

export interface MetricDetail {
  value: string
  kind: 'rating' | 'price' | 'ratio' | 'multiple' | 'scale' | 'other' | string
  label: string
}

export interface AnglePreview {
  key: string
  name: string
  hook: string
  insight: string
  template: string
  kpi: string
  recommended: boolean
}

export interface AnalysisReport {
  framework_id: number
  source: {
    url: string
    fetched: boolean
    chars: number
    status?: number
    title: string
    description: string
    h1: string[]
    h2: string[]
    ctas: string[]
    images: number
    has_video: boolean
    lang: string
    analyzer: string
    extracted_at: string
  }
  verdict: {
    one_liner: string
    claim: string
    confidence: number
    confidence_label: string
    reasons: string[]
  }
  sections: ReportSection[]
  value_props: ValueProp[]
  proof: { metrics: MetricDetail[]; rating: MetricDetail | null; scale: MetricDetail[]; ratios: MetricDetail[]; prices: MetricDetail[] }
  audience: { primary: string; source: string; geo: string; languages: string[] }
  creative: { angles: AnglePreview[]; platform_notes: Record<string, string>; hooks: string[] }
  risks: { level: string; item: string; detail: string }[]
  gaps: { level: string; item: string; impact: string }[]
  actions: string[]
  raw: any
}

export interface ReportResponse {
  framework: Framework
  report: AnalysisReport
  angles: Angle[]
}

export interface OptimizeChange {
  field: string
  before: string
  after: string
}

export interface OptimizeRuleResult {
  rule: string
  label: string
  note: string
  hit: number
  changes: OptimizeChange[]
}

export interface OptimizeResult {
  created: number
  version: number
  /** 规则听懂了，但这批素材本来就无需改动（created=0） */
  noop?: boolean
  applied: OptimizeRuleResult[]
  warnings: string[]
  notes: string[]
  rules: { key: string; label: string; arg?: string }[]
  campaign: Campaign
}


export interface BatchItem {
  campaign_name: string
  landing_text: string
  platforms: string[]
  languages: string[]
  material_types: string[]
  extra_prompt?: string
}

export interface JobResultRow {
  index: number
  name: string
  campaign_id: number | null
  framework_id: number | null
  materials: number
  ok: boolean
  error?: string | null
}

export interface Job {
  id: number
  type: string
  status: 'pending' | 'running' | 'success' | 'partial' | 'failed' | 'canceled'
  total: number
  done: number
  failed: number
  payload?: { items?: BatchItem[]; defaults?: any; skipped?: number }
  result?: JobResultRow[] | null
  error?: string | null
  cancel_requested?: boolean
  created_at?: string
  started_at?: string
  finished_at?: string
}

export interface User {
  id: number
  username: string
  display_name?: string
  role: 'admin' | 'manager' | 'editor' | 'viewer'
  active: boolean
}

export interface ReviewRecord {
  id: number
  action: string
  comment?: string
  username?: string
  from_status?: string
  to_status?: string
  created_at?: string
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
  meta: () => req<Meta>('/api/meta'),
  // 认证
  login: (username: string, password: string) =>
    req<{ token: string; expires_in: number; user: User }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  me: () => req<User>('/api/auth/me'),
  roles: () => req<{ roles: Record<string, string>; can_edit: string[]; can_review: string[] }>('/api/auth/roles'),
  // 用户管理
  users: () => req<User[]>('/api/users'),
  createUser: (u: { username: string; password: string; display_name?: string; role: string }) =>
    req<User>('/api/users', { method: 'POST', body: JSON.stringify(u) }),
  updateUser: (id: number, u: Partial<User> & { password?: string }) =>
    req<User>(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(u) }),
  deactivateUser: (id: number) => req<any>(`/api/users/${id}`, { method: 'DELETE' }),
  auditLogs: () => req<any[]>('/api/audit-logs'),
  // 分析与生成
  analyze: (url: string, text: string) =>
    req<Framework>('/api/analyze', { method: 'POST', body: JSON.stringify({ url, text }) }),
  // 结构化分析报告（抓整页 → 报告 → 顺带规划方向）
  report: (payload: { url?: string; text?: string; platforms?: string[]; lang?: string }) =>
    req<ReportResponse>('/api/report', { method: 'POST', body: JSON.stringify(payload) }),
  reportMdUrl: (fid: number) =>
    `${API_BASE}/api/reports/${fid}/export.md?token=${encodeURIComponent(getToken())}`,
  // 素材优化：一句话说清要改什么，产出新版本
  optimize: (cid: number, payload: { instruction: string; scope?: string; angle_keys?: string[] }) =>
    req<OptimizeResult>(`/api/campaigns/${cid}/optimize`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  planAngles: (framework_id: number, platforms: string[], extra_prompt?: string, lang?: string) =>
    req<Angle[]>('/api/angles/plan', {
      method: 'POST', body: JSON.stringify({ framework_id, platforms, extra_prompt, lang }),
    }),
  angles: (fid: number) => req<Angle[]>(`/api/frameworks/${fid}/angles`),
  produce: (payload: {
    framework_id: number; campaign_name: string; angle_keys: string[]; platforms: string[]
    material_types: string[]; languages: string[]; extra_prompt?: string
    sizes_per_angle?: number; video_mode?: 'off' | 'first' | 'all'
  }) => req<Campaign>('/api/produce', { method: 'POST', body: JSON.stringify(payload) }),
  estimate: (payload: {
    angle_keys: string[]; platforms: string[]; material_types: string[]; languages: string[]
    sizes_per_angle?: number; video_mode?: string
  }) => req<PlanEstimate>('/api/estimate', { method: 'POST', body: JSON.stringify(payload) }),
  updateBrand: (fid: number, patch: { brand_color?: string; assets?: any }) =>
    req<any>(`/api/frameworks/${fid}/brand`, { method: 'PATCH', body: JSON.stringify(patch) }),
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
  generate: (payload: {
    framework_id: number; campaign_name: string; platforms: string[]
    material_types: string[]; languages: string[]; extra_prompt?: string
  }) => req<Campaign>('/api/generate', { method: 'POST', body: JSON.stringify(payload) }),
  regenerate: (id: number, extra_prompt: string) =>
    req<Material>(`/api/materials/${id}/regenerate`, { method: 'POST', body: JSON.stringify({ extra_prompt }) }),
  versions: (mid: number) =>
    req<{ slot: any; count: number; versions: Material[] }>(`/api/materials/${mid}/versions`),
  compare: (mid: number, against: number) =>
    req<CompareResult>(`/api/materials/${mid}/compare?against=${against}`),
  selectMaterial: (mid: number) =>
    req<Material>(`/api/materials/${mid}/select`, { method: 'POST' }),
  slots: (cid: number) => req<{ campaign_id: number; slots: SlotInfo[] }>(`/api/campaigns/${cid}/slots`),
  // 素材库
  campaigns: () => req<Campaign[]>('/api/campaigns'),
  material: (id: number) => req<Material>(`/api/materials/${id}`),
  // 审阅流
  reviews: (cid: number) => req<ReviewRecord[]>(`/api/campaigns/${cid}/reviews`),
  submitReview: (cid: number, comment?: string) =>
    req<Campaign>(`/api/campaigns/${cid}/submit`, { method: 'POST', body: JSON.stringify({ comment }) }),
  approveReview: (cid: number, comment?: string) =>
    req<Campaign>(`/api/campaigns/${cid}/approve`, { method: 'POST', body: JSON.stringify({ comment }) }),
  rejectReview: (cid: number, comment: string) =>
    req<Campaign>(`/api/campaigns/${cid}/reject`, { method: 'POST', body: JSON.stringify({ comment }) }),
  commentReview: (cid: number, comment: string) =>
    req<any>(`/api/campaigns/${cid}/comment`, { method: 'POST', body: JSON.stringify({ comment }) }),
  // 设置
  models: () => req<ModelConfig[]>('/api/settings/models'),
  createModel: (m: Partial<ModelConfig>) =>
    req<ModelConfig>('/api/settings/models', { method: 'POST', body: JSON.stringify(m) }),
  updateModel: (id: number, m: Partial<ModelConfig>) =>
    req<ModelConfig>(`/api/settings/models/${id}`, { method: 'PUT', body: JSON.stringify(m) }),
  deleteModel: (id: number) =>
    req<any>(`/api/settings/models/${id}`, { method: 'DELETE' }),
  testModel: (m: Partial<ModelConfig>) =>
    req<{ ok: boolean; latency_ms?: number; reply?: string; error?: string }>(
      '/api/settings/models/test', { method: 'POST', body: JSON.stringify(m) }),
  // 规格库
  specs: () => req<PlatformSpec[]>('/api/platform-specs'),
  updateSpec: (id: number, patch: Partial<PlatformSpec>) =>
    req<PlatformSpec>(`/api/platform-specs/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  // 批量
  templateUrl: () => `${API_BASE}/api/batch/template?token=${encodeURIComponent(getToken())}`,
  batchParse: (rows: string) =>
    req<{ count: number; items: BatchItem[]; headers: string[]; errors: string[] }>(
      '/api/batch/parse', { method: 'POST', body: JSON.stringify({ rows }) }),
  batchUpload: async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const token = getToken()
    const res = await fetch(API_BASE + '/api/batch/upload', {
      method: 'POST', body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`上传失败 ${res.status}`)
    return res.json() as Promise<{ count: number; items: BatchItem[]; errors: string[] }>
  },
  createJob: (payload: {
    rows?: string; items?: BatchItem[]; platforms: string[]
    languages: string[]; material_types: string[]; extra_prompt?: string
  }) => req<Job>('/api/batch/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  jobs: () => req<Job[]>('/api/jobs'),
  job: (id: number) => req<Job>(`/api/jobs/${id}`),
  cancelJob: (id: number) => req<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  // 下载（浏览器直接打开，token 通过查询参数不适用，故下载走后端公开静态/签名路径）
  exportUrl: (cid: number) => `${API_BASE}/api/export/campaign/${cid}?token=${encodeURIComponent(getToken())}`,
  // 只打包校验通过的素材（超字数、缺字段的会被跳过）
  exportValidUrl: (cid: number) =>
    `${API_BASE}/api/export/campaign/${cid}?only_valid=true&token=${encodeURIComponent(getToken())}`,
  batchExportUrl: (ids: number[]) =>
    `${API_BASE}/api/export/batch?ids=${ids.join(',')}&token=${encodeURIComponent(getToken())}`,
  abExportUrl: (cid: number, selectedOnly = false) =>
    `${API_BASE}/api/export/ab/${cid}?${selectedOnly ? 'selected_only=true&' : ''}token=${encodeURIComponent(getToken())}`,
  downloadUrl: (mid: number) => `${API_BASE}/api/materials/${mid}/download?token=${encodeURIComponent(getToken())}`,
  // 关键帧存放在 uploads 的子目录（<campaign>_<platform>_<angle>_kf/kf1.png），
  // 只取文件名会 404，所以按 uploads/ 之后的相对路径拼。
  fileUrl: (filePath?: string) => {
    if (!filePath) return ''
    const rel = filePath.includes('/uploads/') ? filePath.split('/uploads/')[1] : filePath.split('/').pop()
    return `${API_BASE}/files/${rel}`
  },
}
