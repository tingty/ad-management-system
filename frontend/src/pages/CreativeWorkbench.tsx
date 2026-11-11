import React, { useEffect, useState } from 'react'
import { api } from '../api'

type Route = {
  platform: string
  concept?: string
  angle?: string
  visual_style?: string
  copy_direction?: string
  image_prompt?: string
  notes?: string
}
type JobState = {
  platform: string
  jobId: string | null
  status: string
  progress: number
  images: any[]
  error?: string
  route?: Route
}

const DEFAULT_PLATFORMS = ['Facebook', 'Google Search', 'Unity', 'Adsterra', '移动应用广告位', '激励视频']
const STEPS = [
  { key: 1, label: '输入' },
  { key: 2, label: '产品分析' },
  { key: 3, label: '创意策略' },
  { key: 4, label: '生成成果' },
]

function statusLabel(s: string) {
  switch (s) {
    case 'succeeded': return '已完成'
    case 'partial_success': return '部分完成'
    case 'failed': return '失败'
    case 'canceled': return '已取消'
    case 'submitting': return '提交中'
    case 'queued': return '排队中'
    case 'running': return '生成中'
    case 'generating': return '生成中'
    default: return s || '等待中'
  }
}
function statusClass(s: string) {
  if (['succeeded', 'partial_success', 'done'].includes(s)) return 'ok'
  if (s === 'failed' || s === 'canceled') return 'err'
  if (['running', 'submitting', 'queued', 'generating'].includes(s)) return 'warn'
  return 'off'
}

/**
 * 创意工作台 · V4.52 重构（四步引导流程 + 历史库）
 * ① 输入（产品链接/信息 + 媒体平台 + 图片/视频）
 * ② 产品分析（大模型 8 字段框架）
 * ③ 创意策略（大模型为每平台规划创意路线）
 * ④ 生成成果（自动出图 + 素材画廊）
 * 分析/创作过程在右侧滑出面板展示；「历史」子标签查看过往创作。
 */
export default function CreativeWorkbench() {
  const [tab, setTab] = useState<'create' | 'history'>('create')
  const [step, setStep] = useState<number>(1)
  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS)
  const [selected, setSelected] = useState<string[]>(['Facebook'])
  const [genImage, setGenImage] = useState(true)
  const [genVideo, setGenVideo] = useState(false)

  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [planning, setPlanning] = useState(false)
  const [error, setError] = useState('')

  const [analysis, setAnalysis] = useState<any>(null)
  const [planId, setPlanId] = useState<number | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])

  const [progress, setProgress] = useState('')
  const [assets, setAssets] = useState<any[]>([])
  const [historyId, setHistoryId] = useState<number | null>(null)
  const [jobs, setJobs] = useState<JobState[]>([])

  const [drawerOpen, setDrawerOpen] = useState(true)
  const [toast, setToast] = useState<string | null>(null)

  // 历史库
  const [history, setHistory] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  useEffect(() => {
    api.mediaPlatforms().then((d: any) => {
      const names = (d?.platforms || []).map((p: any) => p.platform).filter(Boolean)
      if (names.length) {
        setPlatforms(names)
        setSelected(names.slice(0, 1))
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab === 'history') loadHistory()
  }, [tab])

  function togglePlatform(p: string) {
    setSelected(s => s.includes(p) ? s.filter(x => x !== p) : [...s, p])
  }
  function showToast(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(t => (t === msg ? null : t)), 3500)
  }
  function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)) }

  async function loadHistory() {
    setHistoryLoading(true)
    try {
      const d: any = await api.creativePlans({ limit: 50, offset: 0 })
      setHistory(d?.items || [])
    } catch { setHistory([]) }
    finally { setHistoryLoading(false) }
  }

  async function analyze() {
    setError('')
    const url = input.trim()
    if (!url) { setError('请输入落地页 / 应用链接或产品信息'); return }
    if (!selected.length) { setError('请至少选择一个媒体平台'); return }
    setRunning(true)
    try {
      const res: any = await api.landingAnalysis({ url: url.startsWith('http') ? url : undefined,
        text: url.startsWith('http') ? undefined : input })
      setAnalysis(res)
      setStep(2)
      setDrawerOpen(true)
    } catch (e: any) {
      setError(e?.message || '分析失败')
    } finally {
      setRunning(false)
    }
  }

  async function planStrategy() {
    if (!analysis) return
    setError(''); setPlanning(true)
    try {
      const r: any = await api.creativePlan({
        analysis, platforms: selected, gen_image: genImage, gen_video: genVideo,
      })
      setPlanId(r?.id ?? null)
      setRoutes(r?.routes || selected.map(p => ({ platform: p })))
      setStep(3)
      if (r?.id) await api.updateCreativePlan(r.id, { status: 'draft' }).catch(() => {})
    } catch (e: any) {
      setError(e?.message || '创意策略规划失败')
    } finally {
      setPlanning(false)
    }
  }

  function updateRoute(i: number, field: keyof Route, val: string) {
    setRoutes(rs => rs.map((r, j) => j === i ? { ...r, [field]: val } : r))
  }

  async function generate() {
    if (!routes.length) return
    setError(''); setStep(4); setAssets([]); setJobs([]); setProgress('正在创建历史会话…')
    let hid: number | null = null
    try {
      const h: any = await api.createCreationHistory({ analysis, platform: routes[0]?.platform, lang: 'en' }).catch(() => null)
      hid = h?.id ?? null; setHistoryId(hid)
    } catch { /* 历史可选 */ }
    if (planId) await api.updateCreativePlan(planId, { status: 'generating', history_id: hid ?? undefined }).catch(() => {})

    const targets = routes.filter(r => selected.includes(r.platform))
    const collected: any[] = []
    if (genImage && targets.length) {
      try {
        const rules: any = await api.mediaRules().catch(() => ({}))
        const allowed: Record<string, string[]> = rules?.platforms || {}
        for (const r of targets) {
          setProgress(`正在为 ${r.platform} 生成推广图片…`)
          const sizes = (allowed[r.platform] || ['1080x1080']).slice(0, 2)
          const slots = sizes.map(size => ({ size, placement: r.platform }))
          const style_opts = {
            creative_direction: `${r.concept || ''}（${r.angle || ''}）`.replace(/[（）\s]+$/, ''),
            content_style: `${r.visual_style || ''}；${r.copy_direction || ''}`.replace(/^[；\s]+|[；\s]+$/g, ''),
            color_scheme: '',
          }
          const payload = {
            images_request: {
              analysis, platform: r.platform, lang: 'en',
              copy_fields: {}, copy_variants: [], style_opts, slots,
              spec_version: rules?.spec_version || '',
              total_pixels: sizes.reduce((n: number, s: string) => {
                const [w, h] = s.split('x').map(Number); return n + (w * h || 0)
              }, 0),
            },
            archive: hid ? { history_id: hid, platform: r.platform, lang: 'en' } : undefined,
            idempotency_key: `cw_${r.platform}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          }
          setJobs(j => [...j, { platform: r.platform, jobId: null, status: 'submitting', progress: 0, images: [], route: r }])
          let job: any
          try { job = await api.createGenerationJob(payload) }
          catch (e: any) {
            setJobs(j => j.map(x => x.platform === r.platform ? { ...x, status: 'failed', error: e?.message || '创建失败' } : x))
            continue
          }
          const jobId = job?.job_id
          setJobs(j => j.map(x => x.platform === r.platform ? { ...x, jobId, status: job?.status || 'queued' } : x))
          let st: any = job
          for (let i = 0; i < 80; i++) {
            await sleep(1500)
            try { st = await api.generationJob(jobId) } catch { continue }
            setJobs(j => j.map(x => x.platform === r.platform ? { ...x, status: st?.status || x.status, progress: st?.progress ?? x.progress } : x))
            if (['succeeded', 'partial_success', 'failed', 'canceled'].includes(st?.status)) break
          }
          let imgs: any[] = (st?.result?.images || []).slice()
          if (!imgs.length) {
            try { const got: any = await api.creativeAssets({ job_id: jobId }); imgs = (got?.items || []).slice() } catch { /* 兜底失败不阻断 */ }
          }
          setJobs(j => j.map(x => x.platform === r.platform ? { ...x, status: st?.status || x.status, images: imgs } : x))
          collected.push(...imgs)
          setAssets(a => [...a, ...imgs])
          if (imgs.length) showToast(`图片已生成 ${imgs.length} 张（${r.platform}）`)
        }
      } catch (e: any) {
        setError((e?.message || '图片生成失败') + '（可重试或调整媒体后继续）')
      }
    }
    setProgress(genVideo ? '视频生成将在下期待生成，本期已生成图片。' : '创作完成。')
    setStep(5)
    showToast(`创作完成：共生成 ${collected.length} 张图片`)
    if (planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: collected.length, history_id: hid ?? undefined }).catch(() => {})
  }

  function download(file: string) { window.open(api.mediaFileDownloadUrl(file), '_blank') }
  function downloadZip() {
    if (historyId) window.open(api.historyItemZipUrl(historyId), '_blank')
    else if (assets.length) window.open(api.mediaZipUrl(assets.map(a => a.file)), '_blank')
  }
  function resetAll() {
    setStep(1); setAnalysis(null); setRoutes([]); setPlanId(null); setAssets([]); setJobs([])
    setHistoryId(null); setProgress(''); setError('')
  }
  function loadPlan(item: any) {
    setAnalysis(item.analysis || {})
    setSelected((item.platforms || []).slice())
    setRoutes(item.routes || [])
    setPlanId(item.id)
    setGenImage(item.gen_image !== false)
    setGenVideo(!!item.gen_video)
    setTab('create'); setStep(3)
  }

  const totalImages = assets.length

  return (
    <div className="page">
      <div className="page-head">
        <h2>创意工作台</h2>
        <p className="muted">面向落地页 / 官网 / 应用的自动化创意素材创作。输入产品信息 → 大模型分析 → 规划创意路线 → 自动出图。全流程由已配置大模型驱动。</p>
      </div>

      <div className="cw-tabs">
        <button className={`cw-tab ${tab === 'create' ? 'on' : ''}`} onClick={() => setTab('create')}>创作</button>
        <button className={`cw-tab ${tab === 'history' ? 'on' : ''}`} onClick={() => setTab('history')}>历史库</button>
      </div>

      {tab === 'create' && (
        <>
          <button className="cw-toggle" onClick={() => setDrawerOpen(o => !o)}>
            {drawerOpen ? '隐藏过程面板' : '分析 & 创作过程'}
          </button>

          <ol className="cw-steps">
            {STEPS.map(s => (
              <li key={s.key} className={`${step >= s.key ? 'on' : ''} ${step === s.key ? 'cur' : ''}`}>
                <span className="num">{s.key}</span><span className="lbl">{s.label}</span>
              </li>
            ))}
          </ol>

          <div className="card">
            {step === 1 && (
              <div className="cw-pane">
                <label className="field">
                  <span className="label">产品链接 / 应用链接 / 产品信息</span>
                  <textarea value={input} onChange={e => setInput(e.target.value)} rows={4}
                    placeholder="粘贴落地页网址（https://…）或直接描述产品信息" />
                </label>
                <div className="field">
                  <span className="label">推广媒体平台（可多选）</span>
                  <div className="cw-chips">
                    {platforms.map(p => (
                      <button key={p} className={`chip ${selected.includes(p) ? 'on' : ''}`} onClick={() => togglePlatform(p)}>{p}</button>
                    ))}
                  </div>
                </div>
                <div className="field cw-inline">
                  <label><input type="checkbox" checked={genImage} onChange={e => setGenImage(e.target.checked)} /> 生成图片</label>
                  <label><input type="checkbox" checked={genVideo} onChange={e => setGenVideo(e.target.checked)} /> 生成视频</label>
                </div>
                <div className="cw-actions">
                  <button className="btn primary" onClick={analyze} disabled={running}>{running ? '分析中…' : '开始分析'}</button>
                </div>
              </div>
            )}

            {step === 2 && analysis && (
              <div className="cw-pane">
                <h3 className="cw-sub">产品分析框架</h3>
                <div className="kv cw-kv">
                  <div><span>行业</span><b>{analysis.industry || '—'}</b></div>
                  <div><span>类型</span><b>{analysis.type || '—'}</b></div>
                  <div><span>对象</span><b>{analysis.audience || '—'}</b></div>
                  <div><span>优势</span><b>{(analysis.advantages || []).join('、') || '—'}</b></div>
                  <div><span>语言</span><b>{analysis.language || '—'}</b></div>
                  <div><span>竞品</span><b>{(analysis.competitors || []).join('、') || '—'}</b></div>
                </div>
                {(analysis.channels || []).length > 0 && (
                  <div className="cw-channels">
                    {(analysis.channels || []).map((c: any, i: number) => (
                      <div key={i} className="cw-channel"><b>{c.platform}</b><span>{c.reason}</span></div>
                    ))}
                  </div>
                )}
                <div className="cw-actions">
                  <button className="btn" onClick={() => { setStep(1) }}>上一步</button>
                  <button className="btn primary" onClick={planStrategy} disabled={planning}>{planning ? '规划中…' : '生成创意策略'}</button>
                </div>
              </div>
            )}

            {step === 3 && routes.length > 0 && (
              <div className="cw-pane">
                <h3 className="cw-sub">创意策略路线（每平台一条，可微调后生成）</h3>
                <div className="cw-routes">
                  {routes.map((r, i) => (
                    <div className="cw-route" key={i}>
                      <div className="cw-route-head"><b>{r.platform}</b></div>
                      <div className="cw-route-grid">
                        <label><span>创意概念</span><input value={r.concept || ''} onChange={e => updateRoute(i, 'concept', e.target.value)} /></label>
                        <label><span>切入角度</span><input value={r.angle || ''} onChange={e => updateRoute(i, 'angle', e.target.value)} /></label>
                        <label><span>视觉风格</span><input value={r.visual_style || ''} onChange={e => updateRoute(i, 'visual_style', e.target.value)} /></label>
                        <label><span>文案方向</span><input value={r.copy_direction || ''} onChange={e => updateRoute(i, 'copy_direction', e.target.value)} /></label>
                      </div>
                      <label className="cw-route-prompt"><span>文生图方向 / 提示词</span>
                        <textarea value={r.image_prompt || ''} rows={2} onChange={e => updateRoute(i, 'image_prompt', e.target.value)} />
                      </label>
                      {r.notes && <div className="muted" style={{ fontSize: 12 }}>{r.notes}</div>}
                    </div>
                  ))}
                </div>
                <div className="cw-actions">
                  <button className="btn" onClick={() => setStep(2)}>上一步</button>
                  <button className="btn primary" onClick={generate}>确认并生成素材</button>
                </div>
              </div>
            )}

            {(step === 4 || step === 5) && (
              <div className="cw-pane">
                <div className="cw-gen-head">
                  <b>{step === 4 ? '生成中…' : `创作完成（共 ${totalImages} 张）`}</b>
                  <span className="muted">{progress}</span>
                </div>
                {step === 5 && (
                  <>
                    <div className="cw-gallery">
                      {assets.map((a, i) => (
                        <div className="cw-asset" key={i}>
                          <img src={api.fileUrl(a.url || a.file)} alt="" loading="lazy" />
                          <button className="btn tiny" onClick={() => download(a.file)}>下载</button>
                        </div>
                      ))}
                      {totalImages === 0 && <div className="muted">本次未生成素材（可返回调整媒体后重试）。</div>}
                    </div>
                    <div className="cw-actions">
                      <button className="btn" onClick={resetAll}>新的创作</button>
                      {totalImages > 0 && <button className="btn" onClick={downloadZip}>打包下载全部</button>}
                    </div>
                  </>
                )}
              </div>
            )}
            {error && <div className="err" style={{ marginTop: 10 }}>{error}</div>}
          </div>
        </>
      )}

      {tab === 'history' && (
        <div className="card">
          <div className="cw-hist-head">
            <h3 className="cw-sub" style={{ margin: 0 }}>历史创作（共 {history.length} 条）</h3>
            <button className="btn" onClick={loadHistory} disabled={historyLoading}>{historyLoading ? '刷新中…' : '刷新'}</button>
          </div>
          {history.length === 0 && <div className="muted" style={{ marginTop: 10 }}>暂无历史创作。在「创作」标签完成一次流程后会出现在这里。</div>}
          <div className="cw-hist-list">
            {history.map((h, i) => (
              <div className="cw-hist" key={i}>
                <div className="cw-hist-main">
                  <b>{h.title || '未命名创意策略'}</b>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {(h.platforms || []).join('、') || '—'} · {h.asset_count || 0} 张 · {h.created_at?.slice(0, 10) || ''}
                  </div>
                </div>
                <span className={`pill ${statusClass(h.status)}`}>{statusLabel(h.status)}</span>
                <button className="btn tiny" onClick={() => loadPlan(h)}>查看 / 复用</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 右侧滑出过程面板 */}
      <div className={`cw-backdrop ${drawerOpen ? 'open' : ''}`} onClick={() => setDrawerOpen(false)} />
      <aside className={`cw-drawer ${drawerOpen ? 'open' : ''}`}>
        <div className="cw-drawer-head">
          <span>分析 &amp; 创作过程</span>
          <button className="cw-close" onClick={() => setDrawerOpen(false)} title="收起（ESC）">×</button>
        </div>
        <div className="cw-drawer-body">
          <section className="cw-sec">
            <h4>分析过程</h4>
            {analysis ? (
              <>
                <div className="kv">
                  <div><span>行业</span><b>{analysis.industry || '—'}</b></div>
                  <div><span>类型</span><b>{analysis.type || '—'}</b></div>
                  <div><span>对象</span><b>{analysis.audience || '—'}</b></div>
                  <div><span>优势</span><b>{(analysis.advantages || []).join('、') || '—'}</b></div>
                </div>
                {(analysis.channels || []).length > 0 && (
                  <div className="cw-channels">
                    {(analysis.channels || []).map((c: any, i: number) => (
                      <div key={i} className="cw-channel"><b>{c.platform}</b><span>{c.reason}</span></div>
                    ))}
                  </div>
                )}
              </>
            ) : <div className="muted">输入产品并分析后展示产品框架与推荐媒体。</div>}
          </section>

          <section className="cw-sec">
            <h4>创意策略</h4>
            {routes.length > 0 ? (
              <div className="cw-route-mini">
                {routes.map((r, i) => (
                  <div key={i} className="cw-rm">
                    <b>{r.platform}</b>
                    <span>{r.concept || '—'} · {r.angle || '—'}</span>
                  </div>
                ))}
              </div>
            ) : <div className="muted">规划创意策略后展示每平台路线。</div>}
          </section>

          <section className="cw-sec">
            <h4>创作过程{totalImages > 0 ? ` · 共 ${totalImages} 张` : ''}</h4>
            {jobs.length === 0 && step !== 4 && step !== 5 && (
              <div className="muted">开始创作后展示各媒体生成进度与素材。</div>
            )}
            {jobs.map(j => (
              <div className="cw-job" key={j.platform}>
                <div className="cw-job-head">
                  <b>{j.platform}</b>
                  <span className={`pill ${statusClass(j.status)}`}>{statusLabel(j.status)}</span>
                </div>
                {!['succeeded', 'partial_success', 'failed', 'canceled', 'done'].includes(j.status) && (
                  <div className="cw-progress"><div className="cw-bar" style={{ width: `${j.progress || 0}%` }} /></div>
                )}
                {j.error && <div className="err">{j.error}</div>}
                {j.images.length > 0 && (
                  <div className="cw-thumbs">
                    {j.images.map((im, i) => (
                      <div className="cw-thumb" key={i}>
                        <img src={api.fileUrl(im.url || im.file)} alt={j.platform} loading="lazy" />
                        <button className="btn tiny" onClick={() => download(im.file)}>下载</button>
                      </div>
                    ))}
                  </div>
                )}
                {['succeeded', 'partial_success', 'done'].includes(j.status) && j.images.length === 0 && (
                  <div className="muted">无素材返回。</div>
                )}
              </div>
            ))}
            {genVideo && (
              <div className="reserved" style={{ marginTop: 12 }}>
                🎬 视频生成（下期待生成）：本期聚焦图片，视频节点已预留，将在下期接入文生视频模型后打通。
              </div>
            )}
          </section>
        </div>
      </aside>

      {toast && <div className="cw-toast">{toast}</div>}
    </div>
  )
}
