/**
 * V4.81 / P3：创作任务抽屉的服务端状态（唯一任务事实）。
 *
 * V4.77 的做法是把「当前任务」放进 cwTask.ts 的单个内存快照：只能管一个任务，刷新后还会
 * 被标成「已中断」。现在任务事实在服务端（`/api/creative-tasks`），本 hook 只做两件事：
 * 1）按需轮询列表（抽屉打开时 4s，收起时 20s 只取「进行中数量」用于顶部角标）；
 * 2）加载某个批次的详情（子任务 / 阶段 / 资产 / 错误）。
 *
 * 刻意不做的事：不在前端算进度百分比（等待时长不是进度），不做本地缓存合并
 * ——服务端返回什么就显示什么，避免出现「界面还在跑、服务端已经结束」。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export type TaskFilter = 'active' | 'done' | 'needs'

export interface CreativeSubtask {
  job_id: string
  batch_id: string
  kind: string            // video / images
  status: string
  stage: string
  stage_label: string
  success_count: number
  provider_task_id?: string
  error_code?: string
  error_stage?: string
  error_message?: string
  error_action?: string
  can_repoll?: boolean
  can_redownload?: boolean
  assets: { asset_id?: string; url: string; caption?: string; kind?: string; size?: string }[]
  duration_sec?: number
  duration_source?: string
  requested_duration?: number
  measured_duration?: number
  delivery_status?: string         // compliant / noncompliant / unverified
  spec_check?: { status?: string; spec_ok?: boolean | null; reasons?: string[]; note?: string; verification?: string; library_version?: string }
  spec_ref?: { ad_product?: string; target_aspect?: string; target_size?: string; duration_min?: number | null; duration_max?: number | null; verification?: string; verification_label?: string; source_url?: string | null }
  retry_of?: string                // 重生成链：同一逻辑资产的旧 attempt
  attempts?: number
  note?: string
  created_at?: string
  finished_at?: string
}

export interface CreativeBatch {
  batch_id: string
  product_name: string
  source_url?: string
  material_types: string[]
  platforms: string[]
  status: string
  draft_id: string
  created_at: string
  updated_at?: string
  finished_at?: string
  success_count: number
  total_count: number
  active_stage?: string
  active_stage_label?: string
  error_code?: string
  error_action?: string
  subtasks: CreativeSubtask[]
}

/** 批次状态 → 抽屉里的三个分组（服务端返回 status，前端只做归类，不另立事实） */
export const BUCKET: Record<TaskFilter, string[]> = {
  active: ['queued', 'running'],
  done: ['done', 'partial'],
  needs: ['needs_attention', 'failed', 'canceled'],
}

export function bucketOf(status: string): TaskFilter {
  const s = String(status || '')
  if (BUCKET.done.includes(s)) return 'done'
  if (BUCKET.needs.includes(s)) return 'needs'
  return 'active'
}

export function useCreativeTasks(enabled = true) {
  const [items, setItems] = useState<CreativeBatch[]>([])
  const [activeCount, setActiveCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const seq = useRef(0)

  const load = useCallback(async (opts: { silent?: boolean } = {}) => {
    const my = ++seq.current
    if (!opts.silent) setLoading(true)
    try {
      // 一次取 30 条（含三个分组），顶部角标用服务端的 active_count，筛选用本地归类
      const r: any = await api.creativeTasks({ limit: 30 })
      if (my !== seq.current) return
      setItems(r?.items || [])
      setActiveCount(Number(r?.active_count || 0))
      setError('')
    } catch (e: any) {
      if (my === seq.current) setError(e?.message || '任务列表加载失败')
    } finally {
      if (my === seq.current && !opts.silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let stop = false
    let timer: number | undefined
    const tick = async (silent: boolean) => {
      await load({ silent })
      if (!stop) timer = window.setTimeout(() => tick(true), silent ? 4000 : 20000)
    }
    tick(true)
    return () => { stop = true; if (timer) window.clearTimeout(timer) }
  }, [enabled, load])

  const detail = useCallback(async (batchId: string): Promise<CreativeBatch | null> => {
    try { return await api.creativeTask(batchId) } catch { return null }
  }, [])

  const retry = useCallback(async (batchId: string, jobId: string,
                                  action: 'repoll' | 'redownload' | 'regenerate') => {
    await api.retryCreativeTask(batchId, jobId, action)
    await load({ silent: true })
  }, [load])

  const cancel = useCallback(async (batchId: string, jobId = '') => {
    await api.cancelCreativeTask(batchId, jobId)
    await load({ silent: true })
  }, [load])

  return { items, activeCount, loading, error, load, detail, retry, cancel }
}
