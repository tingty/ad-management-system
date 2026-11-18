/**
 * V4.77 素材创作任务常驻状态（跨页面 / 跨组件共享）
 *
 * 背景：创意工作台的素材生成是「前端驱动」的长流程（解析 → 规划 → 图片任务轮询 → 视频任务轮询），
 * 状态原本只活在组件内部；一旦切换菜单，组件被卸载，进度与结果全部丢失。
 *
 * 这里用模块级单例把「当前任务」抽到组件之外：
 * - CreativeWorkbench 写入（begin / update / end）；
 * - CwTaskDock 在任意页面读取并展示，实现「切到别的页面也能看任务跑到哪了」；
 * - App 让创意工作台常驻挂载（切走只隐藏不卸载），任务与结果回来后原样还在。
 *
 * 同时镜像一份到 sessionStorage：刷新页面后仍能告知「上次任务已中断」，而不是假装还在跑。
 */

export type CwTaskStatus = 'idle' | 'running' | 'done' | 'failed' | 'interrupted'
export type CwStageStatus = 'pending' | 'running' | 'done' | 'failed' | 'stopped'

export interface CwTaskStage {
  key: string
  label: string
  status: CwStageStatus
  note?: string
}

export interface CwTaskSnapshot {
  status: CwTaskStatus
  /** 任务标识：切换页面后用于判断是否同一个任务 */
  seq: number
  startedAt: number
  updatedAt: number
  finishedAt: number
  progress: number
  statusText: string
  product: string
  platforms: string[]
  /** V4.92：素材类型组合；both=图片+视频，mixed=含文案的混合，其余为单类型 */
  kind: 'image' | 'video' | 'copy' | 'both' | 'mixed' | ''
  stages: CwTaskStage[]
  imageDone: number
  imageTotal: number
  videoDone: number
  error: string
}

const STORAGE_KEY = 'admb_cw_task_v1'

const EMPTY: CwTaskSnapshot = {
  status: 'idle', seq: 0, startedAt: 0, updatedAt: 0, finishedAt: 0,
  progress: 0, statusText: '', product: '', platforms: [], kind: '',
  stages: [], imageDone: 0, imageTotal: 0, videoDone: 0, error: '',
}

function restore(): CwTaskSnapshot {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...EMPTY }
    const s = JSON.parse(raw) as CwTaskSnapshot
    if (!s || typeof s !== 'object') return { ...EMPTY }
    const base = { ...EMPTY, ...s }
    // 页面刷新 / 关闭后前端流程已不存在，标记为中断，避免误以为还在跑
    if (base.status === 'running') {
      base.status = 'interrupted'
      base.statusText = '任务已中断（页面刷新或关闭）。原始进度可能仍在服务端，请重新生成。'
      base.stages = (base.stages || []).map(st =>
        st.status === 'running' ? { ...st, status: 'stopped' as CwStageStatus } : st)
    }
    return base
  } catch {
    return { ...EMPTY }
  }
}

let snap: CwTaskSnapshot = restore()
// 被用户主动关闭的任务序号：同一任务的后续进度更新不再自动弹出浮窗
let suppressedSeq = -1
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach(fn => fn())
}

function persist() {
  try {
    // 只保留必要字段，避免 sessionStorage 膨胀
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...snap, stages: (snap.stages || []).slice(0, 8),
    }))
  } catch { /* 隐私模式 / 配额满：忽略，不影响内存态 */ }
}

function commit(patch: Partial<CwTaskSnapshot>) {
  snap = { ...snap, ...patch, updatedAt: Date.now() }
  persist()
  emit()
}

export function getCwTask(): CwTaskSnapshot {
  return snap
}

export function subscribeCwTask(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** 开始一个任务：仅当当前不是 running 时重置计时与序号（同一任务内的多次 update 不会重置） */
export function cwTaskBegin(init: Partial<CwTaskSnapshot>): void {
  if (snap.status === 'running') {
    commit(init)
    return
  }
  // 用户手动关掉了这条任务：本轮进度刷新不再自动弹出，避免「关掉又冒出来」
  if (snap.seq === suppressedSeq) return
  commit({
    ...EMPTY,
    status: 'running',
    seq: snap.seq + 1,
    startedAt: Date.now(),
    ...init,
  })
}

/** 任务进行中：只更新进度与阶段，不动 startedAt */
export function cwTaskUpdate(patch: Partial<CwTaskSnapshot>): void {
  if (snap.status !== 'running') {
    cwTaskBegin(patch)
    return
  }
  commit(patch)
}

/** 任务结束：done / failed，记录完成时间用于展示「刚刚完成」 */
export function cwTaskEnd(status: 'done' | 'failed', patch: Partial<CwTaskSnapshot> = {}): void {
  commit({
    ...patch,
    status,
    progress: status === 'done' ? 100 : snap.progress,
    finishedAt: Date.now(),
  })
}

/** 用户关闭任务浮窗（或重置工作台）时清空 */
export function cwTaskDismiss(): void {
  suppressedSeq = snap.seq
  snap = { ...EMPTY, seq: snap.seq }
  try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  emit()
}

/** 新一轮生成开始：解除「已关闭」抑制，让任务栏重新出现 */
export function cwTaskReset(): void {
  suppressedSeq = -1
  snap = { ...EMPTY, seq: snap.seq }
  try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
  emit()
}

export function cwTaskElapsedSec(t: CwTaskSnapshot, now = Date.now()): number {
  const end = t.status === 'running' ? now : (t.finishedAt || t.updatedAt || now)
  if (!t.startedAt) return 0
  return Math.max(0, Math.round((end - t.startedAt) / 1000))
}

export function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return s ? `${m} 分 ${s} 秒` : `${m} 分`
  const h = Math.floor(m / 60)
  return `${h} 小时 ${m % 60} 分`
}

/* 仅开发环境暴露调试入口，便于本地与自动化验证任务栏（生产构建时该分支被摇掉） */
if (typeof window !== 'undefined' && (import.meta as any).env?.DEV) {
  ;(window as any).__cwTask = {
    begin: cwTaskBegin, update: cwTaskUpdate, end: cwTaskEnd,
    dismiss: cwTaskDismiss, reset: cwTaskReset, get: getCwTask,
  }
}
