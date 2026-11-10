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
  ModelInfo, CopyVariant,
} from './api'
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
}

const STORAGE_PREFIX = 'admb:creationSession:v2:'
const MAX_LOGS = 40

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
  }
}

function defaults(): CreationSession {
  return {
    version: 2,
    urlInput: '', textInput: '', showText: false,
    analysis: null, historyId: null,
    logoMode: 'auto', uploadedLogo: '', error: '', studioError: '',
    stage: 'idle', running: false,
    taskLabel: '', taskDetail: '',
    taskStartedAt: null, taskUpdatedAt: null, taskLogs: [],
    ...studioDefaults(),
  } as CreationSession
}

/** 恢复时清洗：页面刷新后没有存活的 fetch，不能把 running 永久卡住。 */
function sanitize(raw: any): CreationSession {
  const d = defaults()
  if (!raw || typeof raw !== 'object' || raw.version !== 2) return d
  const merged: CreationSession = { ...d, ...raw }
  merged.analysis = raw.analysis && typeof raw.analysis === 'object' ? raw.analysis : null
  merged.copy = raw.copy && typeof raw.copy === 'object' ? raw.copy : null
  merged.images = Array.isArray(raw.images) ? raw.images : []
  merged.imageIssues = Array.isArray(raw.imageIssues) ? raw.imageIssues : []
  merged.checked = Array.isArray(raw.checked) ? raw.checked : []
  merged.selectedPlacements = Array.isArray(raw.selectedPlacements) ? raw.selectedPlacements : []
  merged.taskLogs = Array.isArray(raw.taskLogs) ? raw.taskLogs.slice(-MAX_LOGS) : []
  merged.copyEdit = raw.copyEdit && typeof raw.copyEdit === 'object' ? raw.copyEdit : {}
  merged.selectedCopy = raw.selectedCopy && typeof raw.selectedCopy === 'object' ? raw.selectedCopy : {}
  merged.viewer = null
  if (raw.running) {
    merged.running = false
    merged.taskLabel = '上次任务未完成'
    merged.taskDetail = '页面刷新 / 关闭时正在执行的请求被中断；已恢复到中断前的进度，可继续调整或重新执行。'
    const interrupted: TaskLogEntry = {
      at: Date.now(), text: '任务在页面刷新 / 关闭时中断，进度已恢复', kind: 'error',
    }
    merged.taskLogs = [...merged.taskLogs, interrupted].slice(-MAX_LOGS)
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
 * 由「勾选的文案」拼出创意文案组合，交给后端按版位轮换叠加到图片上。
 * 标题 / 副标 / CTA 各自成池；第 i 个组合取各池第 i % len 条，数量以最长池为准。
 */
export function buildCopyVariants(s: CreationSession): CopyVariant[] {
  const picked = copyItems(s).filter(x => x.selected && x.text.trim())
  const pool = (keys: string[]) => picked.filter(x => keys.includes(x.key)).map(x => x.text.trim())
  const heads = pool(['headline', 'title'])
  const subs = pool(['description', 'body', 'primary_text'])
  const ctas = pool(['cta'])
  const n = Math.max(heads.length, subs.length, ctas.length)
  if (!n) return []
  const brand = (s.brandEdit || s.copy?.brand || '').trim()
  const variants: CopyVariant[] = []
  for (let i = 0; i < n; i++) {
    variants.push({
      headline: heads.length ? heads[i % heads.length] : '',
      sub: subs.length ? subs[i % subs.length] : '',
      cta: ctas.length ? ctas[i % ctas.length] : '',
      brand,
      label: `组合 ${i + 1}`,
    })
  }
  return variants.slice(0, 40)
}

export function selectedCount(s: CreationSession): { selected: number; total: number } {
  const items = copyItems(s)
  return { selected: items.filter(x => x.selected).length, total: items.length }
}
