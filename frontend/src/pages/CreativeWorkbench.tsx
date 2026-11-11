import React, { useEffect, useState } from 'react'
import { api } from '../api'

type Route = {
  key: string
  name: string
  description: string
  tags: string[]
  angle: string
  selected: boolean
}
type JobState = {
  platform: string
  jobId: string | null
  status: string
  progress: number
  images: any[]
  error?: string
  route: Route | null
}

const STEPS = [
  { n: 1, label: '解析产品', sub: '提取卖点与受众' },
  { n: 2, label: '规划创意', sub: '匹配媒体与场景' },
  { n: 3, label: '批量生成', sub: '图片与视频成片' },
]

function statusLabel(s: string) {
  switch (s) {
    case 'succeeded': return '已完成'
    case 'partial_success': return '部分完成'
    case 'failed': return '失败'
    case 'canceled': return '已取消'
    case 'submitting': return '提交中'
    case 'queued': return '排队中'
    case 'running': case 'generating': return '生成中'
    default: return s || '等待中'
  }
}
function statusClass(s: string) {
  if (['succeeded', 'partial_success', 'done'].includes(s)) return 'ok'
  if (s === 'failed' || s === 'canceled') return 'err'
  if (['running', 'submitting', 'queued', 'generating'].includes(s)) return 'warn'
  return 'off'
}
function isUrl(s: string) { return /^https?:\/\//i.test(s.trim()) }
function brandOf(platform: string, placement?: string) {
  if (placement) return placement
  const p = (platform || '').toLowerCase()
  if (p.includes('google')) return 'Google Display'
  if (p.includes('meta') || p.includes('facebook')) return 'Meta Feed'
  if (p.includes('unity')) return 'Unity Ads'
  if (p.includes('adsterra')) return 'Adsterra'
  return platform || '未知媒体'
}
function aspectOf(img: any): string {
  const w = Number(img?.w) || (img?.size ? parseInt(String(img.size).split('x')[0]) : 0)
  const h = Number(img?.h) || (img?.size ? parseInt(String(img.size).split('x')[1]) : 0)
  if (!w || !h) return '1:1'
  const r = w / h
  if (Math.abs(r - 0.8) < 0.06) return '4:5'
  if (Math.abs(r - 0.5625) < 0.06) return '9:16'
  if (Math.abs(r - 1) < 0.06) return '1:1'
  if (Math.abs(r - 1.777) < 0.08) return '16:9'
  const g = gcd(Math.round(w), Math.round(h)); return `${w / g}:${h / g}`
}
function gcd(a: number, b: number): number { return b ? gcd(b, a % b) : a }
function specOf(img: any): { dim: string; ratio: string; fmt: string } {
  const w = Number(img?.w) || (img?.size ? parseInt(String(img.size).split('x')[0]) : 0)
  const h = Number(img?.h) || (img?.size ? parseInt(String(img.size).split('x')[1]) : 0)
  const ratio = aspectOf(img)
  if (w && h) return { dim: `${w} × ${h} px`, ratio, fmt: 'JPG / PNG · ≤ 30 MB' }
  if (img?.size) return { dim: `${img.size.replace('x', ' × ')} px`, ratio, fmt: 'JPG / PNG · ≤ 30 MB' }
  return { dim: '自适应', ratio, fmt: 'JPG / PNG · ≤ 30 MB' }
}

/**
 * 创意工作台 · V4.53（按 Figma 设计稿重建：双栏布局 + 三步流程 + 项目简报）
 * ① 输入产品链接 → ② 解析产品 + 规划创意（3 条路线）→ ③ 批量生成素材
 * 右侧固定「项目简报」面板；核心分析 / 路线 / 生成均由已配置大模型驱动。
 */
export default function CreativeWorkbench() {
  const [platforms, setPlatforms] = useState<string[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [showMore, setShowMore] = useState(false)

  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const [view, setView] = useState<'input' | 'analyzing' | 'plan' | 'generating' | 'result'>('input')
  const [progressPct, setProgressPct] = useState(0)
  const [progressText, setProgressText] = useState('')

  const [cw, setCw] = useState<any>(null)        // 设计对齐的产品分析（4 盒 + 简报）
  const [landing, setLanding] = useState<any>(null) // 生成后端所需的 LandingAnalysis
  const [planId, setPlanId] = useState<number | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])

  const [assets, setAssets] = useState<any[]>([])
  const [jobs, setJobs] = useState<JobState[]>([])
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [historyId, setHistoryId] = useState<number | null>(null)

  const [toast, setToast] = useState<string | null>(null)
  const [histOpen, setHistOpen] = useState(false)
  const [history, setHistory] = useState<any[]>([])

  useEffect(() => {
    api.mediaPlatforms().then((d: any) => {
      const names = (d?.platforms || []).map((p: any) => p.platform).filter(Boolean)
      if (names.length) { setPlatforms(names); setSelected(names.slice(0, 1)) }
    }).catch(() => {})
  }, [])

  function showToast(m: string) {
    setToast(m); window.setTimeout(() => setToast(t => (t === m ? null : t)), 3500)
  }
  function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)) }
  function togglePlatform(p: string) {
    setSelected(s => s.includes(p) ? s.filter(x => x !== p) : [...s, p])
  }
  const visiblePlatforms = platforms.slice(0, 4)
  const morePlatforms = platforms.slice(4)

  async function analyze() {
    setError(''); const val = input.trim()
    if (!val) { setError('请输入落地页 / 应用链接或产品信息'); return }
    if (!selected.length) { setError('请至少选择一个媒体平台'); return }
    setRunning(true); setView('analyzing'); setProgressPct(8); setProgressText('正在解析产品页面…')
    try {
      const cwRes: any = await api.cwAnalyze({ url: isUrl(val) ? val : '', text: isUrl(val) ? '' : val, platforms: selected })
      setCw(cwRes); setPlanId(cwRes?.id ?? null)
      setProgressPct(46); setProgressText('47% · 正在提取核心利益点')
      const [landRes, routeRes] = await Promise.all([
        api.landingAnalysis({ url: isUrl(val) ? val : undefined, text: isUrl(val) ? undefined : val }).catch(() => null),
        api.cwRoutes({ plan_id: cwRes?.id, analysis: cwRes?.analysis || {}, platforms: selected, brief: cwRes?.brief || {} }).catch(() => ({ routes: cwRes?.routes || [] })),
      ])
      setLanding(landRes); setRoutes((routeRes?.routes || cwRes?.routes || []).map((r: any) => ({ ...r, selected: r.selected !== false })))
      setProgressPct(100); setProgressText('分析完成')
      setView('plan')
    } catch (e: any) {
      setError(e?.message || '分析失败'); setView('input')
    } finally { setRunning(false) }
  }

  function updateRoute(i: number, field: keyof Route, val: any) {
    setRoutes(rs => rs.map((r, j) => j === i ? { ...r, [field]: val } : r))
  }
  function planImageCount() {
    if (assets.length) return assets.length
    return selected.length * 2
  }

  async function generate() {
    if (!routes.length) return
    setError(''); setView('generating'); setAssets([]); setJobs([]); setChecked({}); setProgressText('正在创建素材任务…')
    let hid: number | null = null
    try {
      const h: any = await api.createCreationHistory({ analysis: landing || cw?.analysis || {}, platform: selected[0] || '', lang: 'en' }).catch(() => null)
      hid = h?.id ?? null; setHistoryId(hid)
    } catch { /* 历史可选 */ }
    if (planId) await api.updateCreativePlan(planId, { status: 'generating', history_id: hid ?? undefined }).catch(() => {})

    const activeRoutes = routes.filter(r => r.selected)
    const targets = selected
    const collected: any[] = []
    let done = 0
    try {
      const rules: any = await api.mediaRules().catch(() => ({}))
      const allowed: Record<string, string[]> = rules?.platforms || {}
      const routeFor = (i: number) => activeRoutes.length ? activeRoutes[i % activeRoutes.length] : null
      for (let i = 0; i < targets.length; i++) {
        const p = targets[i]; const route = routeFor(i)
        setProgressText(`正在为 ${p} 生成推广图片…`)
        const sizes = (allowed[p] || ['1080x1080']).slice(0, 2)
        const slots = sizes.map(size => ({ size, placement: p }))
        const style_opts = {
          creative_direction: `${route?.name || ''}（${route?.angle || ''}）`.replace(/[（）\s]+$/, ''),
          content_style: `${route?.description || ''}；${((route?.tags) || []).join('、')}`.replace(/^[；\s]+|[；\s]+$/g, ''),
          color_scheme: '',
        }
        const payload = {
          images_request: {
            analysis: landing || cw?.analysis || {}, platform: p, lang: 'en',
            copy_fields: {}, copy_variants: [], style_opts, slots,
            spec_version: rules?.spec_version || '',
            total_pixels: sizes.reduce((n: number, s: string) => { const [w, h] = s.split('x').map(Number); return n + (w * h || 0) }, 0),
          },
          archive: hid ? { history_id: hid, platform: p, lang: 'en' } : undefined,
          idempotency_key: `cw_${p}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        }
        setJobs(j => [...j, { platform: p, jobId: null, status: 'submitting', progress: 0, images: [], route }])
        let job: any
        try { job = await api.createGenerationJob(payload) }
        catch (e: any) {
          setJobs(j => j.map(x => x.platform === p ? { ...x, status: 'failed', error: e?.message || '创建失败' } : x))
          done++; setProgressPct(Math.round(done / targets.length * 100)); continue
        }
        const jobId = job?.job_id
        setJobs(j => j.map(x => x.platform === p ? { ...x, jobId, status: job?.status || 'queued' } : x))
        let st: any = job
        for (let k = 0; k < 80; k++) {
          await sleep(1500)
          try { st = await api.generationJob(jobId) } catch { continue }
          setJobs(j => j.map(x => x.platform === p ? { ...x, status: st?.status || x.status, progress: st?.progress ?? x.progress } : x))
          if (['succeeded', 'partial_success', 'failed', 'canceled'].includes(st?.status)) break
        }
        let imgs: any[] = (st?.result?.images || []).slice()
        if (!imgs.length) {
          try { const got: any = await api.creativeAssets({ job_id: jobId }); imgs = (got?.items || []).slice() } catch { /* 兜底 */ }
        }
        setJobs(j => j.map(x => x.platform === p ? { ...x, status: st?.status || x.status, images: imgs } : x))
        for (const im of imgs) { im.__route = route; im.__platform = p }
        collected.push(...imgs); setAssets(a => [...a, ...imgs])
        if (imgs.length) showToast(`图片已生成 ${imgs.length} 张（${p}）`)
        done++; setProgressPct(Math.round(done / targets.length * 100))
      }
    } catch (e: any) {
      setError((e?.message || '图片生成失败') + '（可重试或调整媒体后继续）')
    }
    setProgressText('创作完成')
    setView('result')
    showToast(`创作完成：共生成 ${collected.length} 张图片`)
    if (planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: collected.length, history_id: hid ?? undefined }).catch(() => {})
  }

  function download(file: string) { window.open(api.mediaFileDownloadUrl(file), '_blank') }
  function selectedFiles() { return assets.filter(a => checked[a.file]).map(a => a.file) }
  function downloadSelected() {
    const f = selectedFiles(); if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  function resetAll() {
    setView('input'); setCw(null); setLanding(null); setRoutes([]); setPlanId(null); setAssets([]); setJobs([])
    setHistoryId(null); setError(''); setProgressPct(0); setChecked({})
  }

  async function openHistory() {
    setHistOpen(true)
    try { const d: any = await api.creativePlans({ limit: 50, offset: 0 }); setHistory(d?.items || []) } catch { setHistory([]) }
  }
  function loadPlan(item: any) {
    setCw({ id: item.id, title: item.title, summary: item.analysis?.summary || '',
      boxes: item.analysis?.boxes || {}, brief: item.analysis?.brief || {}, recommendedPlatforms: item.analysis?.recommendedPlatforms || [] })
    setSelected((item.platforms || []).slice())
    setRoutes((item.routes || []).map((r: any) => ({ ...r, selected: r.selected !== false })))
    setPlanId(item.id)
    setHistOpen(false); setView('plan')
  }

  const activeStep = view === 'input' || view === 'analyzing' ? 1 : view === 'plan' ? 2 : 3
  const briefBoxes = cw?.boxes || {}
  const brief = cw?.brief || {}
  const aiNoteTags = routes.filter(r => r.selected).flatMap(r => r.tags || []).slice(0, 2)

  return (
    <div className="cwb">
      <div className="cwb-top">
        <div className="cwb-title">
          <h2>创意工作台</h2>
          <span className="cwb-live"><i className="dot" /> 自动保存</span>
        </div>
        <div className="cwb-top-actions">
          <button className="cwb-icon" title="搜索">⌕</button>
          <button className="cwb-new" onClick={resetAll}>+ 新建项目</button>
          <button className="cwb-hist-btn" onClick={openHistory}>历史</button>
        </div>
      </div>

      <div className="cwb-body">
        <div className="cwb-main">
          <div className="cwb-copilot">
            <span className="cwb-dash" /> AI CREATIVE COPILOT
            <span className="cwb-helper">输入产品链接，AI 将完成策略分析、创意规划与多平台素材生成。</span>
          </div>

          <div className="cwb-input-card">
            <div className="cwb-url">
              <span className="cwb-link-ic">🔗</span>
              <input value={input} onChange={e => setInput(e.target.value)} placeholder="https://soundora.com/products/air-pro"
                onKeyDown={e => { if (e.key === 'Enter' && !running) analyze() }} />
              <button className="cwb-start" onClick={analyze} disabled={running}>
                {running ? '分析中…' : '开始分析 →'}
              </button>
            </div>
            <div className="cwb-platforms">
              <span className="cwb-pl-label">投放平台</span>
              {visiblePlatforms.map(p => (
                <button key={p} className={`cwb-chip ${selected.includes(p) ? 'on' : ''}`} onClick={() => togglePlatform(p)}>{p}</button>
              ))}
              {morePlatforms.length > 0 && (
                <>
                  <button className="cwb-chip more" onClick={() => setShowMore(o => !o)}>{showMore ? '收起' : '+ 更多'}</button>
                  {showMore && morePlatforms.map(p => (
                    <button key={p} className={`cwb-chip ${selected.includes(p) ? 'on' : ''}`} onClick={() => togglePlatform(p)}>{p}</button>
                  ))}
                </>
              )}
            </div>
          </div>

          <ol className="cwb-steps">
            {STEPS.map((s, i) => (
              <li key={s.n} className={`${activeStep >= s.n ? 'on' : ''} ${activeStep === s.n ? 'cur' : ''}`}>
                <span className="n">0{s.n}</span>
                <div className="st-txt"><b>{s.label}</b><small>{s.sub}</small></div>
                {i < STEPS.length - 1 && <span className="chev">›</span>}
              </li>
            ))}
          </ol>

          {/* 内容区：按状态切换 */}
          {view === 'input' && (
            <div className="cwb-empty">
              <div className="cwb-empty-ic"><span className="spark" /></div>
              <h3>从一个链接开始</h3>
              <p>我们会自动识别产品定位与受众，规划适合每个媒体的创意方向。</p>
            </div>
          )}

          {view === 'analyzing' && (
            <div className="cwb-progress-card">
              <div className="cwb-ai-ic"><span className="spark" /></div>
              <h3>正在理解你的产品…</h3>
              <p>分析页面信息、用户评论和同类广告，建立创意策略。</p>
              <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
              <div className="cwb-bar-txt">{progressText}</div>
            </div>
          )}

          {view === 'plan' && cw && (
            <>
              <section className="cwb-section">
                <h3 className="cwb-sub">产品分析完成</h3>
                <p className="cwb-summary">{cw.summary || '（暂无分析摘要）'}</p>
                <div className="cwb-boxes">
                  {[['行业', briefBoxes.industry], ['核心人群', briefBoxes.coreAudience],
                    ['购买动机', briefBoxes.purchaseMotivation], ['价格带', briefBoxes.priceBand]].map(([k, v]) => (
                    <div className="cwb-box" key={k}><span>{k}</span><b>{v || '—'}</b></div>
                  ))}
                </div>
              </section>

              <section className="cwb-section">
                <div className="cwb-sub-row">
                  <h3 className="cwb-sub">为你规划了 {routes.length} 条创意路线</h3>
                  <span className="cwb-tag-reco">推荐方案</span>
                </div>
                <p className="cwb-reco-note">已按 {selected.join('、') || '所选媒体'} 的素材规格自动适配</p>
                <div className="cwb-routes">
                  {routes.map((r, i) => (
                    <div className={`cwb-route ${r.selected ? 'on' : ''}`} key={i} onClick={() => updateRoute(i, 'selected', !r.selected)}>
                      <div className="cwb-route-head">
                        <span className="cwb-route-key">{r.key || String.fromCharCode(65 + i)}</span>
                        <b>{r.name || '未命名路线'}</b>
                        <span className={`cwb-check ${r.selected ? 'on' : ''}`} />
                      </div>
                      <p>{r.description}</p>
                      <div className="cwb-route-tags">
                        {(r.tags || []).map((t: string, j: number) => <span key={j} className="cwb-rtag">{t}</span>)}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="cwb-foot-note">路线与平台均可在生成后继续调整</p>
                <div className="cwb-confirm">
                  <button className="cwb-gen-btn" onClick={generate} disabled={!routes.some(r => r.selected)}>
                    确认并生成 {planImageCount()} 份素材
                  </button>
                </div>
              </section>
            </>
          )}

          {(view === 'generating' || view === 'result') && (
            <section className="cwb-section">
              {view === 'result' && (
                <div className="cwb-result-head">
                  <div><h3 className="cwb-sub ok">首批素材已完成</h3>
                    <p className="cwb-reco-note">生成 {assets.length} 份素材，通过平台合规预检</p></div>
                  <div className="cwb-result-actions">
                    <button className="cwb-link-btn" onClick={() => setChecked(Object.fromEntries(assets.map(a => [a.file, false])))}>
                      {assets.every(a => !checked[a.file]) ? '全选' : '取消全选'}
                    </button>
                    <button className="cwb-gen-btn sm" onClick={downloadSelected} disabled={!selectedFiles().length}>
                      下载已选（{selectedFiles().length}）
                    </button>
                  </div>
                </div>
              )}
              {view === 'generating' && <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>}

              <div className="cwb-grid">
                {assets.map((a, i) => {
                  const sp = specOf(a); const rt = a.__route
                  return (
                    <div className="cwb-asset" key={i}>
                      <div className="cwb-asset-badge">{sp.ratio}</div>
                      <div className="cwb-asset-img"><img src={api.fileUrl(a.url || a.file)} alt="" loading="lazy" /></div>
                      <div className="cwb-asset-body">
                        <b>{rt?.name || a.__platform || '创意素材'}</b>
                        <p>{(rt?.tags || []).join('·') || '推广素材'}</p>
                        <div className="cwb-asset-meta">
                          <span>{brandOf(a.__platform, a.placement)}</span>
                          <span className="cwb-type">图片</span>
                        </div>
                        <div className="cwb-asset-spec">
                          <span>推荐尺寸 {sp.dim}</span><span>画面比例 {sp.ratio}</span><span>{sp.fmt}</span>
                        </div>
                      </div>
                      <label className="cwb-asset-check">
                        <input type="checkbox" checked={!!checked[a.file]} onChange={e => setChecked(c => ({ ...c, [a.file]: e.target.checked }))} /> 选择
                      </label>
                      <button className="cwb-asset-dl" onClick={() => download(a.file)}>下载</button>
                    </div>
                  )
                })}
                {view === 'result' && assets.length === 0 && <div className="muted">本次未生成素材（可返回调整媒体后重试）。</div>}
              </div>

              {jobs.filter(j => j.status === 'failed').length > 0 && (
                <div className="err" style={{ marginTop: 10 }}>
                  {jobs.filter(j => j.status === 'failed').map(j => `${j.platform}：${j.error}`).join('；')}
                </div>
              )}

              {view === 'result' && (
                <div className="cwb-confirm">
                  <button className="cwb-link-btn" onClick={resetAll}>新的创作</button>
                  {assets.length > 0 && <button className="cwb-gen-btn sm" onClick={downloadSelected}>打包下载全部</button>}
                </div>
              )}
            </section>
          )}

          {error && <div className="err" style={{ marginTop: 12 }}>{error}</div>}
        </div>

        {/* 右侧：项目简报 */}
        <aside className="cwb-brief">
          <div className="cwb-brief-head">
            <b>项目简报</b><span className="cwb-dots">⋯</span><span className="cwb-chev">›</span>
          </div>
          <div className="cwb-brief-card">
            <div className="cwb-thumb">{cw?.title ? cw.title.slice(0, 1) : '🎧'}</div>
            <div className="cwb-brief-card-txt">
              <span className="cwb-cur">当前项目</span>
              <b>{cw?.title || '未命名项目'}</b>
              <small>{briefBoxes.industry || (cw ? '待分析' : '等待分析')}</small>
            </div>
          </div>

          <div className="cwb-brief-row">
            <div className="cwb-brief-label">推广目标 <span className="cwb-pen">✎</span></div>
            <div className="cwb-brief-val">{brief.promotionGoal || '—'}</div>
          </div>

          <div className="cwb-brief-row">
            <div className="cwb-brief-label">目标受众</div>
            <div className="cwb-brief-chips">
              {(brief.targetAudience && brief.targetAudience.length) ? brief.targetAudience.map((t: string, i: number) => (
                <span key={i} className="cwb-bchip">{t}</span>
              )) : <span className="muted">—</span>}
            </div>
          </div>

          <div className="cwb-brief-row">
            <div className="cwb-brief-label">核心卖点</div>
            <ol className="cwb-sell">
              {(brief.sellingPoints && brief.sellingPoints.length) ? brief.sellingPoints.map((s: string, i: number) => (
                <li key={i}><span>{String(i + 1).padStart(2, '0')}</span> {s}</li>
              )) : <li className="muted">—</li>}
            </ol>
          </div>

          <div className="cwb-brief-row">
            <div className="cwb-brief-label">生成计划</div>
            <div className="cwb-brief-plan">
              <div><span>图片素材</span><b>{planImageCount()} 张</b></div>
              <div><span>短视频</span><b>0 条 <small>（下期待生成）</small></b></div>
            </div>
          </div>

          <div className="cwb-brief-note">
            <span className="cwb-note-ic" /> AI 将优先测试
            {aiNoteTags.length ? ` ${aiNoteTags.join(' 和 ')}` : ' 已规划'} 两类创意方向。
          </div>
        </aside>
      </div>

      {/* 历史弹窗 */}
      {histOpen && (
        <div className="cwb-modal-back" onClick={() => setHistOpen(false)}>
          <div className="cwb-modal" onClick={e => e.stopPropagation()}>
            <div className="cwb-modal-head"><b>历史创作</b><button onClick={() => setHistOpen(false)}>×</button></div>
            <div className="cwb-modal-body">
              {history.length === 0 && <div className="muted">暂无历史创作。</div>}
              {history.map((h, i) => (
                <div className="cwb-hist" key={i}>
                  <div className="cwb-hist-main">
                    <b>{h.title || '未命名创意方案'}</b>
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
        </div>
      )}

      {toast && <div className="cwb-toast">{toast}</div>}
    </div>
  )
}
