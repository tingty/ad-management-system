/**
 * V4.38 · 素材创作会话中枢
 *
 * 目标：用户在「素材创作」里发起分析 / 文案 / 图片任务后，切换到其它一级菜单时，
 * 工作台不被卸载、请求不中断，且在任何页面都能查阅进度、返回继续调整。
 *
 * 做法：把整条创作链路的状态从组件内部 useState 提升为外部 store（useSyncExternalStore），
 * 并按登录用户隔离持久化到 localStorage。App 常驻挂载 MaterialCreation，
 * 组件卸载不再发生；即使刷新 / 关闭浏览器，也能恢复到中断前的进度。
 */
import { useSyncExternalStore } from 'react'
import type {
  LandingAnalysis, MediaCopyResult, MediaImageItem, MediaImageIssue,
  ModelInfo, CopyVariant, WorkspaceDefaults, CreationRecommendation,
} from './api'
import { buildConcepts, toCopyVariants } from './taskMatrix'
export type { CopyVariant } from './api'

export type CreationStage =
  | 'idle' | 'analyzing' | 'analyzed'
  | 'copy' | 'copy_ready' | 'images' | 'images_ready' | 'error'

export type StudioStep = 1 | 2 | 3

export interface TaskLogEntry {
  at: number
  text: string
  kind: 'info' | 'ok' | 'error'
}

export interface CopyItem {
  key: string
  label: string
  index: number
  text: string
  selected: boolean
}

export interface CreationSession {
  version: number
  /* 落地页分析输入与结果 */
  urlInput: string
  textInput: string
  showText: boolean
  analysis: LandingAnalysis | null
  historyId: number | null
  logoMode: 'auto' | 'upload' | 'none'
  uploadedLogo: string
  error: string                  // 落地页分析错误
  studioError: string            // 推广工作台错误
  /* 后台任务进度（跨页面可见） */
  stage: CreationStage
  running: boolean
  /** V4.42 / F12：服务端持久任务 ID 与状态；刷新 / 关闭浏览器后据此恢复 */
  jobId: string | null
  jobStatus: string
  /** 出图批次序号：同批次重复提交复用同一幂等键，主动重新生成则递增 */
  jobSeq: number
  taskLabel: string
  taskDetail: string
  taskStartedAt: number | null
  taskUpdatedAt: number | null
  taskLogs: TaskLogEntry[]
  /* 营销推广工作台 */
  step: StudioStep
  platform: string
  selectedPlacements: string[]
  count: number
  lang: string
  copy: MediaCopyResult | null
  copyEdit: Record<string, any>
  brandEdit: string
  /** V4.38：字段 key → 每条文案是否被选为创意素材（单条字段长度为 1） */
  selectedCopy: Record<string, boolean[]>
  /** V4.40 / F07：任务矩阵的四个独立控制量 */
  conceptCount: number             // 本批使用概念数
  variantsPerConcept: number       // 每概念标题变体数
  assignment: 'round_robin' | 'full_cover'
  keepDistinctRoles: boolean       // 是否保留同尺寸但不同广告产品的任务
  direction: string
  styleName: string
  colorName: string
  images: MediaImageItem[]
  imageModel: ModelInfo | null
  imgNote: string
  /** V4.39 / F01：因图内文案超预算被阻止生成的版位（不合格不导出） */
  imageIssues: MediaImageIssue[]
  viewer: number | null
  checked: string[]
  savedNote: string
  /* V4.45 / D3：默认自动创作 + 可选定制创作；旧会话固定迁移为 custom */
  mode: 'auto' | 'custom'
  showAdvanced: boolean
  /** 用户点击「确认媒体并生成」后置位，工作台据此自动串联文案 → 出图（不隐式触发） */
  autoContinue: boolean
  /** 自动链路的阶段，写入会话以便刷新后继续，不依赖组件内存 */
  autoStage: 'idle' | 'await_images'
  workspaceDefaults: WorkspaceDefaults
  recommendation: CreationRecommendation | null
}

/** localStorage key 保持不变：旧会话必须能被读到并迁移，不能靠换 key 丢弃历史。 */
const STORAGE_PREFIX = 'admb:creationSession:v2:'
const MAX_LOGS = 40
/** v2 = V4.38–V4.44 定制会话；v3 = V4.45 起新增 mode / 策划结果。 */
const SESSION_VERSION = 3

/** V4.45 / D3：工作区默认值，不从页面语言推断投放国家、不从域名推断授权或库存。 */
export function defaultWorkspace(): WorkspaceDefaults {
  return {
    country: 'US', language: 'en', os: 'iOS/Android',
    goal: 'conversion', budget_cap: 0, concept_count: 1,
  }
}

export function studioDefaults(): Partial<CreationSession> {
  return {
    step: 1,
    platform: '',
    selectedPlacements: [],
    count: 3,
    lang: 'en',
    copy: null,
    copyEdit: {},
    brandEdit: '',
    selectedCopy: {},
    conceptCount: 3,
    variantsPerConcept: 1,
    assignment: 'round_robin',
    keepDistinctRoles: false,
    direction: '',
    styleName: '',
    colorName: '',
    images: [],
    imageModel: null,
    imgNote: '',
    imageIssues: [],
    viewer: null,
    checked: [],
    savedNote: '',
    jobId: null,
    jobStatus: '',
    jobSeq: 0,
  }
}

function defaults(): CreationSession {
  return {
    version: SESSION_VERSION,
    urlInput: '', textInput: '', showText: false,
    analysis: null, historyId: null,
    logoMode: 'auto', uploadedLogo: '', error: '', studioError: '',
    stage: 'idle', running: false,
    taskLabel: '', taskDetail: '',
    taskStartedAt: null, taskUpdatedAt: null, taskLogs: [],
    ...studioDefaults(),
    /* V4.45：模式与工作区默认值属于「会话级」而非「工作台级」设置。
       重新分析只清工作台结果，不把用户已选的定制模式重置回自动。 */
    mode: 'auto',
    showAdvanced: false,
    autoContinue: false,
    autoStage: 'idle',
    workspaceDefaults: defaultWorkspace(),
    recommendation: null,
  } as CreationSession
}

/**
 * 恢复时清洗：页面刷新后没有存活的 fetch，不能把 running 永久卡住。
 * V4.45 / A02：v2 旧会话固定迁移为 custom，输入、分析、文案、图片与历史 ID 全部保留，
 * 且不会隐式发起任何新的收费任务；localStorage key 不变，避免读不到历史会话。
 */
function sanitize(raw: any): CreationSession {
  const d = defaults()
  if (!raw || typeof raw !== 'object' || (raw.version !== 2 && raw.version !== SESSION_VERSION)) return d
  const legacy = raw.version === 2
  const merged: CreationSession = {
    ...d, ...raw,
    version: SESSION_VERSION,
    ...(legacy ? {
      mode: 'custom' as const, showAdvanced: true, autoContinue: false,
      recommendation: null, workspaceDefaults: defaultWorkspace(),
    } : {}),
  }
  merged.mode = merged.mode === 'custom' ? 'custom' : 'auto'
  merged.showAdvanced = Boolean(merged.showAdvanced)
  merged.autoContinue = Boolean(merged.autoContinue)
  merged.autoStage = merged.autoStage === 'await_images' ? 'await_images' : 'idle'
  // V4.45：只接受完整策划契约的会话快照；开发期 / 旧的半成品推荐一律丢弃并重新计算，
  // 避免 undefined 的 structured_concepts / quality_gate 让自动面板渲染失败。
  const rec = merged.recommendation
  merged.recommendation = rec && typeof rec === 'object'
    && typeof rec.recommended_visual_summary === 'string'
    && Array.isArray(rec.structured_concepts)
    && rec.quality_gate && Array.isArray(rec.quality_gate.checks)
    && rec.pricing_gate && typeof rec.plan_version === 'string'
    ? rec : null
  merged.workspaceDefaults = {
    ...defaultWorkspace(),
    ...(raw.workspaceDefaults && typeof raw.workspaceDefaults === 'object' ? raw.workspaceDefaults : {}),
  }
  merged.analysis = raw.analysis && typeof raw.analysis === 'object' ? raw.analysis : null
  merged.copy = raw.copy && typeof raw.copy === 'object' ? raw.copy : null
  merged.images = Array.isArray(raw.images) ? raw.images : []
  merged.imageIssues = Array.isArray(raw.imageIssues) ? raw.imageIssues : []
  merged.checked = Array.isArray(raw.checked) ? raw.checked : []
  merged.selectedPlacements = Array.isArray(raw.selectedPlacements) ? raw.selectedPlacements : []
  merged.taskLogs = Array.isArray(raw.taskLogs) ? raw.taskLogs.slice(-MAX_LOGS) : []
  merged.copyEdit = raw.copyEdit && typeof raw.copyEdit === 'object' ? raw.copyEdit : {}
  merged.selectedCopy = raw.selectedCopy && typeof raw.selectedCopy === 'object' ? raw.selectedCopy : {}
  merged.conceptCount = Number.isFinite(raw.conceptCount) ? Math.max(1, Math.min(40, raw.conceptCount)) : 3
  merged.variantsPerConcept = Number.isFinite(raw.variantsPerConcept)
    ? Math.max(1, Math.min(4, raw.variantsPerConcept)) : 1
  merged.assignment = raw.assignment === 'full_cover' ? 'full_cover' : 'round_robin'
  merged.keepDistinctRoles = Boolean(raw.keepDistinctRoles)
  merged.viewer = null
  merged.jobId = typeof raw.jobId === 'string' && raw.jobId ? raw.jobId : null
  merged.jobStatus = typeof raw.jobStatus === 'string' ? raw.jobStatus : ''
  merged.jobSeq = Number.isFinite(raw.jobSeq) ? Math.max(0, Math.floor(raw.jobSeq)) : 0
  if (raw.running) {
    merged.running = false
    if (merged.jobId) {
      // V4.42 / F12：生成与归档在服务端执行，刷新不再意味着任务中断。
      merged.taskLabel = '正在恢复服务端任务'
      merged.taskDetail = `任务 ${merged.jobId} 由服务端继续执行，页面刷新不影响出图与归档；正在查询最新进度。`
      const resumed: TaskLogEntry = {
        at: Date.now(), text: `页面刷新，按服务端 job_id ${merged.jobId} 恢复进度`, kind: 'info',
      }
      merged.taskLogs = [...merged.taskLogs, resumed].slice(-MAX_LOGS)
    } else {
      merged.taskLabel = '上次任务未完成'
      merged.taskDetail = '页面刷新 / 关闭时正在执行的请求被中断；已恢复到中断前的进度，可继续调整或重新执行。'
      const interrupted: TaskLogEntry = {
        at: Date.now(), text: '任务在页面刷新 / 关闭时中断，进度已恢复', kind: 'error',
      }
      merged.taskLogs = [...merged.taskLogs, interrupted].slice(-MAX_LOGS)
    }
  } else {
    merged.running = false
  }
  return merged
}

let currentKey: string | null = null
let state: CreationSession = defaults()
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach(fn => fn())
}

function persist() {
  if (!currentKey) return
  try {
    localStorage.setItem(currentKey, JSON.stringify({ ...state, viewer: null }))
  } catch { /* 超出配额时只保留内存态，不影响正在执行的任务 */ }
}

/** 绑定当前登录用户；切换账号时换成该账号自己的会话快照。 */
export function bindSessionUser(userId: number | null) {
  const key = userId === null ? null : `${STORAGE_PREFIX}${userId}`
  if (key === currentKey) return
  currentKey = key
  if (!key) {
    state = defaults()
  } else {
    try {
      const raw = localStorage.getItem(key)
      state = raw ? sanitize(JSON.parse(raw)) : defaults()
      // V4.45 / A02：旧会话的迁移结果立即落盘。否则用户打开旧会话后直接关页，
      // 下次进来又要迁移一次、重复追加「任务中断」日志，且 custom 未真正固定。
      if (raw) persist()
    } catch { state = defaults() }
  }
  notify()
}

/** 退出登录 / 需要清空当前会话时调用。 */
export function clearSession() {
  if (currentKey) {
    try { localStorage.removeItem(currentKey) } catch { /* ignore */ }
  }
  state = defaults()
  notify()
}

export function getSession(): CreationSession { return state }

export function updateSession(
  patch: Partial<CreationSession> | ((s: CreationSession) => Partial<CreationSession>),
) {
  const p = typeof patch === 'function' ? patch(state) : patch
  state = { ...state, ...p }
  notify()
  persist()
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function useCreationSession(): CreationSession {
  return useSyncExternalStore(subscribe, getSession, getSession)
}

/* ----------------------------- 任务进度 ----------------------------- */

function pushLog(logs: TaskLogEntry[], text: string, kind: TaskLogEntry['kind']): TaskLogEntry[] {
  return [...logs, { at: Date.now(), text, kind }].slice(-MAX_LOGS)
}

export function beginTask(stage: CreationStage, label: string, detail = '') {
  updateSession(s => ({
    stage, running: true, error: '',
    taskLabel: label, taskDetail: detail,
    taskStartedAt: Date.now(), taskUpdatedAt: Date.now(),
    taskLogs: pushLog(s.taskLogs, label, 'info'),
  }))
}

export function logTask(text: string, kind: TaskLogEntry['kind'] = 'info') {
  updateSession(s => ({
    taskDetail: text, taskUpdatedAt: Date.now(),
    taskLogs: pushLog(s.taskLogs, text, kind),
  }))
}

export function endTask(stage: CreationStage, label: string, detail = '') {
  updateSession(s => ({
    stage, running: false,
    taskLabel: label, taskDetail: detail, taskUpdatedAt: Date.now(),
    taskLogs: pushLog(s.taskLogs, detail || label, 'ok'),
  }))
}

export function failTask(message: string) {
  updateSession(s => ({
    stage: 'error', running: false, error: message,
    taskLabel: '任务失败', taskDetail: message, taskUpdatedAt: Date.now(),
    taskLogs: pushLog(s.taskLogs, message, 'error'),
  }))
}

export const STAGE_LABEL: Record<CreationStage, string> = {
  idle: '尚未开始',
  analyzing: '落地页分析中',
  analyzed: '分析完成',
  copy: '广告文案生成中',
  copy_ready: '文案已就绪',
  images: '推广图片生成中',
  images_ready: '图片已生成',
  error: '任务失败',
}

/** 三个里程碑的完成度：分析 → 文案 → 图片 */
export function milestones(s: CreationSession): boolean[] {
  return [!!s.analysis, !!s.copy, s.images.length > 0]
}

export function hasActivity(s: CreationSession): boolean {
  return !!s.analysis || s.stage !== 'idle' || !!s.taskLogs.length
}

/* ----------------------------- V4.38 创意文案选用 ----------------------------- */

/** 把可编辑文案摊平为逐条可勾选的条目；未记录的条目默认视为已选。 */
export function copyItems(s: CreationSession): CopyItem[] {
  if (!s.copy) return []
  const out: CopyItem[] = []
  for (const f of s.copy.schema || []) {
    const raw = s.copyEdit[f.key]
    const arr: any[] = Array.isArray(raw) ? raw : [raw ?? '']
    arr.forEach((v, i) => out.push({
      key: f.key,
      label: f.count > 1 ? `${f.label} ${i + 1}` : f.label,
      index: i,
      text: String(v ?? ''),
      selected: s.selectedCopy[f.key]?.[i] ?? true,
    }))
  }
  return out
}

export function allSelectedCopy(copy: MediaCopyResult, edit?: Record<string, any>): Record<string, boolean[]> {
  const out: Record<string, boolean[]> = {}
  for (const f of copy.schema || []) {
    const v = (edit || copy.fields || {})[f.key]
    const n = Array.isArray(v) ? v.length : 1
    out[f.key] = Array.from({ length: Math.max(1, n) }, () => true)
  }
  return out
}

/**
 * V4.40 / F07：由「勾选的文案」构造概念组合。
 *
 * 旧实现把 description / body / primary_text 混成一个副文案池，再用 `i % len`
 * 与标题取模配对，主标题与证据可能来自不同概念；平台正文也被压到图上。
 * 现在委托 `taskMatrix.buildConcepts`：同一概念的三段来自同一来源位置，
 * 平台正文不进图内文案，字段不足时复用首条而不是回绕错配。
 * 保留本函数名与返回类型，供「素材历史」与旧调用继续使用。
 */
export function buildCopyVariants(s: CreationSession): CopyVariant[] {
  const concepts = buildConcepts({
    copy: s.copy,
    copyEdit: s.copyEdit,
    selectedCopy: s.selectedCopy,
    brand: (s.brandEdit || s.copy?.brand || '').trim(),
    variantsPerConcept: s.variantsPerConcept,
  })
  return toCopyVariants(concepts)
}

export function selectedCount(s: CreationSession): { selected: number; total: number } {
  const items = copyItems(s)
  return { selected: items.filter(x => x.selected).length, total: items.length }
}

/* ----------------------------- V4.45 / D3 自动创作与定制创作 ----------------------------- */

/**
 * 计划版本：由「会影响策划结果」的输入共同决定。
 * 修改产品事实 / 国家 / 概念数 / 定制参数时版本必然变化，下游推荐、覆盖摘要与确认
 * 令牌随之失效（A13）；但分析原文、上传素材与用户输入始终保留，不清空、不重新收费。
 */
export function planVersion(s: CreationSession): string {
  const parts = [
    s.mode,
    s.analysis?.evidence_snapshot_id || s.analysis?.final_url || s.analysis?.url || '',
    s.platform, (s.selectedPlacements || []).join(','),
    s.workspaceDefaults.country, s.workspaceDefaults.language,
    s.workspaceDefaults.os, s.workspaceDefaults.goal,
    String(s.workspaceDefaults.budget_cap), String(s.workspaceDefaults.concept_count),
    s.recommendation?.plan_hash || '',
    s.showAdvanced ? [s.direction, s.styleName, s.colorName, s.assignment,
                      s.conceptCount, s.variantsPerConcept, s.count].join('|') : '',
  ]
  let h = 2166136261
  const text = parts.join('~')
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return `pv${(h >>> 0).toString(36)}`
}

/**
 * 切换创作模式。返回自动模式时只重置「展开 / 自动继续」等视图状态，
 * 不清空用户输入、不删除已生成的素材、不触发任何隐式收费任务（文档 D3）。
 */
export function setCreationMode(mode: 'auto' | 'custom', reason = '') {
  updateSession(s => {
    if (s.mode === mode) return {}
    const text = mode === 'custom'
      ? '已切换到定制创作：保留产品证据与原始素材，可调整概念、文案、版式、版位与预算'
      : '已返回自动创作：保留已输入内容与既有素材，变更项在确认区对比展示；未发起新任务'
    return {
      mode,
      showAdvanced: mode === 'custom',
      autoContinue: false,
      autoStage: 'idle',
      taskLogs: pushLog(s.taskLogs, reason || text, 'info'),
    }
  })
}

/** 关键默认值变化：使推荐结果与覆盖摘要失效，等待重新确认，不自动重新生成。 */
export function updateWorkspaceDefaults(patch: Partial<WorkspaceDefaults>) {
  updateSession(s => ({
    workspaceDefaults: { ...s.workspaceDefaults, ...patch },
    recommendation: null,
    autoContinue: false,
    taskLogs: pushLog(s.taskLogs, '工作区默认值已修改，原推荐与覆盖摘要已失效，请重新确认', 'info'),
  }))
}
