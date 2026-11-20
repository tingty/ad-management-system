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

const KIND_LABEL: Record<string, string> = { video: '视频', images: '图片', image: '图片', copy: '文案' }

/** V4.115：后端时间统一存 naive UTC 的 ISO 串（无时区标记）。
 *  Date.parse("2026-11-20T02:07:03") 会被浏览器当成本地时区解析，差 8 小时；
 *  这里补 Z 明确按 UTC 解析，得到真实时刻的时间戳，供展示与计时共用同一口径。 */
function parseUtcMs(iso?: string): number {
  if (!iso) return NaN
  const s = String(iso).trim()
  if (!s) return NaN
  // 已经带时区后缀（Z 或 +08:00）的原样解析；否则按 UTC 补 Z。
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(s)) return Date.parse(s)
  return Date.parse(s.replace(' ', 'T') + 'Z')
}

/** V4.115：任务创建时间，按浏览器本地时区显示 YYYY-MM-DD HH:MM。 */
function formatCreatedAt(iso?: string): string {
  const ms = parseUtcMs(iso)
  if (!isFinite(ms)) return '—'
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function elapsedText(iso?: string, finished?: string): string {
  if (!iso) return ''
  const start = parseUtcMs(iso)
  if (!isFinite(start)) return ''
  const end = finished ? parseUtcMs(finished) : Date.now()
  if (!isFinite(end)) return ''
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
  // V4.115：手动停止单独标记，和被动取消区分，方便在「需处理」里检索。
  if (b.status === 'canceled') {
    const subs = b.subtasks || []
    return subs.some(s => s.error_code === 'MANUAL_STOP') ? '手动停止' : '已停止'
  }
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
  onCancel: (batchId: string, jobId?: string, reason?: string) => Promise<void>
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
  const [stopping, setStopping] = useState('')

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

  /** V4.115：进行中任务一键手动停止，落 MANUAL_STOP 标记供日后查询。 */
  async function stopNow(b: CreativeBatch) {
    if (stopping) return
    setStopping(b.batch_id)
    try { await onCancel(b.batch_id, '', 'user') } finally { setStopping('') }
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
                <div className="ctd-row-head" role="button" tabIndex={0}
                  onClick={() => setOpenId(isOpen ? '' : b.batch_id)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setOpenId(isOpen ? '' : b.batch_id) }}>
                  <div className="ctd-row-line1">
                    <span className="ctd-prod">{b.product_name || '未命名创作'}</span>
                    {BUCKET.active.includes(b.status) ? (
                      <button className="ctd-stop" disabled={!!stopping}
                        title="手动停止：后续步骤不再执行；已在厂商渲染的任务仍可能完成并计费"
                        onClick={e => { e.stopPropagation(); stopNow(b) }}>
                        {stopping === b.batch_id ? '停止中…' : '停止'}
                      </button>
                    ) : (
                      <span className={'ctd-badge ' + bucketOf(b.status)}>{stageText(b)}</span>
                    )}
                  </div>
                  <div className="ctd-row-line2">
                    <span title="任务创建时间（本地时区）">创建 {formatCreatedAt(b.created_at)}</span>
                    <span>{kindText(b)}</span>
                    <span>{(b.platforms || []).join('、') || '—'}</span>
                    <span>已等待 {elapsedText(b.created_at, b.finished_at)}</span>
                    <span>成功 {b.success_count}/{b.total_count || 1}</span>
                  </div>
                </div>

                {isOpen && (
                  <div className="ctd-detail">
                    {(detail && detail.batch_id === b.batch_id ? detail.subtasks : b.subtasks).map(s => (
                      <div key={s.job_id} className="ctd-sub">
                        <div className="ctd-sub-head">
                          <b>{KIND_LABEL[s.kind] || s.kind}</b>
                          <span className="ctd-sub-stage">{s.stage_label || s.status}</span>
                          {/* V4.83：时长按实测显示；未达标的原片保留但明确标记，不计合格 */}
                          {s.measured_duration ? (
                            <span className={s.delivery_status === 'noncompliant' ? 'ctd-sub-bad' : 'ctd-sub-ok'}>
                              {s.measured_duration}s 实测{s.requested_duration ? ` / 目标 ${s.requested_duration}s` : ''}
                              {s.delivery_status === 'noncompliant' ? ' · 未达标' : ''}
                            </span>
                          ) : null}
                          {/* V4.84：标准库规格核验（A 官方已核验才标硬结论，B/C 只标待确认） */}
                          {s.spec_ref?.ad_product && (
                            <span className={s.spec_check?.status === 'hard_fail' ? 'ctd-sub-bad' : 'ctd-sub-spec'}
                              title={s.spec_check?.note || `${s.spec_ref.ad_product} · ${s.spec_ref.verification_label || ''}`}>
                              规格 {s.spec_ref.ad_product}
                              {s.spec_check?.status === 'hard_fail' ? ' · 不符'
                                : s.spec_ref.verification === 'A' ? ' · 官方' : ' · 待确认'}
                            </span>
                          )}
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
                        <button className="ctd-link" onClick={() => onCancel(b.batch_id, '', 'user')}
                          title="手动停止：只停止后续步骤；若供应商已在渲染，该任务仍可能完成并计费">
                          手动停止
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
