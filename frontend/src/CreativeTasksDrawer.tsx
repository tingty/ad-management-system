/**
 * V4.81 / P3：右侧「任务」抽屉（400px）。
 *
 * 设计取舍（对应需求里的「可用性优先、不增加界面复杂度」）：
 * - 不新增一级导航，不加搜索以外的控件；筛选只有三格（进行中 / 已完成 / 需处理）；
 * - 单行只给决策必需的信息：产品名、类型、媒体、真实阶段、已等待、成功数量；
 * - 阶段用「排队中 / 提交中 / 模型生成中 / 下载校验中」描述真实状态，**不换算成百分比**
 *   ——等待时长不是进度，假进度会让人误判还要等多久；
 * - 需处理的每一行只给一个主按钮（继续查询 / 重新下载 / 重新生成），三者语义严格区分：
 *   前两个不会再次收费，第三个才会。
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { BUCKET, bucketOf, type CreativeBatch, type CreativeSubtask, type TaskFilter } from './useCreativeTasks'

const FILTERS: { key: TaskFilter; label: string }[] = [
  { key: 'active', label: '进行中' },
  { key: 'done', label: '已完成' },
  { key: 'needs', label: '需处理' },
]

const KIND_LABEL: Record<string, string> = { video: '视频', images: '图片', image: '图片' }

function elapsedText(iso?: string, finished?: string): string {
  if (!iso) return ''
  const start = Date.parse(iso)
  if (!start) return ''
  const end = finished ? Date.parse(finished) : Date.now()
  const sec = Math.max(0, Math.round((end - start) / 1000))
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  if (m < 60) return `${m} 分${sec % 60 ? ' ' + (sec % 60) + ' 秒' : ''}`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

function kindText(b: CreativeBatch): string {
  const ks = (b.material_types || []).map(k => KIND_LABEL[k] || k)
  return ks.length > 1 ? '混合' : (ks[0] || '—')
}

function stageText(b: CreativeBatch): string {
  if (BUCKET.active.includes(b.status)) return b.active_stage_label || '排队中'
  if (b.status === 'done') return '已完成'
  if (b.status === 'partial') return '部分完成'
  if (b.status === 'needs_attention') return '待核实'
  if (b.status === 'failed') return '失败'
  if (b.status === 'canceled') return '已停止'
  return b.status || '—'
}

interface Props {
  open: boolean
  onClose: () => void
  items: CreativeBatch[]
  activeCount: number
  loading: boolean
  error: string
  loadDetail: (batchId: string) => Promise<CreativeBatch | null>
  onRetry: (batchId: string, jobId: string, action: 'repoll' | 'redownload' | 'regenerate') => Promise<void>
  onCancel: (batchId: string, jobId?: string) => Promise<void>
  onReuse: (b: CreativeBatch) => void
}

export default function CreativeTasksDrawer(props: Props) {
  const { open, onClose, items, activeCount, loading, error, loadDetail, onRetry, onCancel, onReuse } = props
  const [filter, setFilter] = useState<TaskFilter>('active')
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState('')
  const [detail, setDetail] = useState<CreativeBatch | null>(null)
  const [busy, setBusy] = useState('')
  const [picked, setPicked] = useState(false)

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 打开抽屉时若「进行中」为空但「需处理」有内容，自动切过去 —— 否则用户会以为任务丢了
  useEffect(() => {
    if (!open || picked) return
    const active = items.filter(b => bucketOf(b.status) === 'active').length
    const needs = items.filter(b => bucketOf(b.status) === 'needs').length
    if (filter === 'active' && active === 0 && needs > 0) setFilter('needs')
  }, [open, items, picked, filter])

  // 抽屉打开时把已展开的详情刷新一次（列表轮询不带子任务明细）
  useEffect(() => {
    if (!open || !openId) return
    let alive = true
    loadDetail(openId).then(d => { if (alive && d) setDetail(d) })
    return () => { alive = false }
  }, [open, openId, items, loadDetail])

  const shown = useMemo(() => {
    const kw = search.trim().toLowerCase()
    return items
      .filter(b => bucketOf(b.status) === filter)
      .filter(b => {
        if (!kw) return true
        const hay = [b.product_name, b.batch_id, ...(b.subtasks || []).map(s => s.provider_task_id || '')]
          .join(' ').toLowerCase()
        return hay.includes(kw)
      })
  }, [items, filter, search])

  if (!open) return null

  const counts: Record<TaskFilter, number> = {
    active: activeCount,
    done: items.filter(b => bucketOf(b.status) === 'done').length,
    needs: items.filter(b => bucketOf(b.status) === 'needs').length,
  }

  async function act(b: CreativeBatch, s: CreativeSubtask, action: 'repoll' | 'redownload' | 'regenerate') {
    setBusy(s.job_id + action)
    try { await onRetry(b.batch_id, s.job_id, action) } finally { setBusy('') }
  }

  return (
    <>
      <div className="ctd-mask" onClick={onClose} />
      <aside className="ctd">
        <header className="ctd-head">
          <div className="ctd-title">创作任务</div>
          <button className="ctd-close" onClick={onClose} title="关闭抽屉（任务不受影响）">×</button>
        </header>

        <div className="ctd-filters">
          {FILTERS.map(f => (
            <button key={f.key}
              className={'ctd-chip' + (filter === f.key ? ' on' : '')}
              onClick={() => { setFilter(f.key); setPicked(true) }}>
              {f.label}{counts[f.key] ? ` ${counts[f.key]}` : ''}
            </button>
          ))}
          <input className="ctd-search" value={search} placeholder="搜索产品名 / 任务号"
            onChange={e => setSearch(e.target.value)} />
        </div>

        <div className="ctd-body">
          {error && <div className="ctd-err">{error}</div>}
          {loading && !items.length && <div className="ctd-empty">加载中…</div>}
          {!loading && !shown.length && (
            <div className="ctd-empty">
              {filter === 'active' ? '当前没有进行中的任务。提交创作后会出现在这里，可以随时离开页面。'
                : filter === 'done' ? '还没有已完成的任务。' : '没有需要处理的任务。'}
            </div>
          )}
          {shown.map(b => {
            const isOpen = openId === b.batch_id
            return (
              <div key={b.batch_id} className={'ctd-row' + (isOpen ? ' open' : '')}>
                <button className="ctd-row-head" onClick={() => setOpenId(isOpen ? '' : b.batch_id)}>
                  <div className="ctd-row-line1">
                    <span className="ctd-prod">{b.product_name || '未命名创作'}</span>
                    <span className={'ctd-badge ' + bucketOf(b.status)}>{stageText(b)}</span>
                  </div>
                  <div className="ctd-row-line2">
                    <span>{kindText(b)}</span>
                    <span>{(b.platforms || []).join('、') || '—'}</span>
                    <span>已等待 {elapsedText(b.created_at, b.finished_at)}</span>
                    <span>成功 {b.success_count}/{b.total_count || 1}</span>
                  </div>
                </button>

                {isOpen && (
                  <div className="ctd-detail">
                    {(detail && detail.batch_id === b.batch_id ? detail.subtasks : b.subtasks).map(s => (
                      <div key={s.job_id} className="ctd-sub">
                        <div className="ctd-sub-head">
                          <b>{KIND_LABEL[s.kind] || s.kind}</b>
                          <span className="ctd-sub-stage">{s.stage_label || s.status}</span>
                          {s.success_count > 0 && <span className="ctd-sub-ok">成功 {s.success_count}</span>}
                        </div>
                        {(s.assets || []).length > 0 && (
                          <div className="ctd-assets">
                            {(s.assets || []).slice(0, 6).map((a, i) => (
                              <a key={i} href={api.fileUrl(a.url)} target="_blank" rel="noreferrer" download>
                                {String(a.kind || s.kind) === 'video'
                                  ? <video src={api.fileUrl(a.url)} preload="metadata" muted />
                                  : <img src={api.fileUrl(a.url)} alt={a.caption || ''} />}
                              </a>
                            ))}
                          </div>
                        )}
                        {s.error_code && (
                          <div className="ctd-sub-err">
                            <div><b>{s.error_code}</b>{s.error_stage ? ` · ${s.error_stage}` : ''}</div>
                            {s.error_message && <div className="ctd-sub-msg">{s.error_message}</div>}
                            {s.error_action && <div className="ctd-sub-act">👉 {s.error_action}</div>}
                            {s.provider_task_id && <div className="ctd-sub-task">厂商任务号 {s.provider_task_id}</div>}
                          </div>
                        )}
                        {s.note && !s.error_code && <div className="ctd-sub-note">{s.note}</div>}
                        <div className="ctd-sub-actions">
                          {s.can_repoll && (
                            <button className="btn small" disabled={!!busy}
                              onClick={() => act(b, s, 'repoll')} title="按原厂商任务号继续查询，不会重复收费">
                              继续查询
                            </button>
                          )}
                          {s.can_redownload && s.status !== 'succeeded' && (
                            <button className="btn small ghost" disabled={!!busy}
                              onClick={() => act(b, s, 'redownload')} title="只重新下载并校验，不会重新生成">
                              重新下载
                            </button>
                          )}
                          {s.status !== 'succeeded' && (
                            <button className="btn small ghost" disabled={!!busy}
                              onClick={() => act(b, s, 'regenerate')} title="重新调用模型生成（会产生一次新费用）">
                              重新生成
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                    <div className="ctd-detail-foot">
                      {BUCKET.active.includes(b.status) && (
                        <button className="ctd-link" onClick={() => onCancel(b.batch_id)}
                          title="只停止后续步骤；若供应商已在渲染，该任务仍可能完成并计费">
                          停止后续步骤
                        </button>
                      )}
                      {b.status !== 'canceled' && (
                        <button className="ctd-link" onClick={() => onReuse(b)}>基于此任务再创作</button>
                      )}
                      <span className="ctd-bid">批次 {b.batch_id.slice(0, 10)}</span>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <footer className="ctd-foot">
          任务在服务端执行：关闭抽屉、切换模块、刷新页面都不会取消。图片先完成即可预览下载，视频继续在后台生成。
        </footer>
      </aside>
    </>
  )
}
