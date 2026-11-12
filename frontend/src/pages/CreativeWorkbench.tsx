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
// 媒体平台兜底清单：当接口未返回（或返回结构异常）时，保证投放平台选择器始终可见
const DEFAULT_PLATFORMS = ['Meta', 'Google', 'Unity', 'Adsterra']
function isUrl(s: string) { return /^https?:\/\//i.test(s.trim()) }
function isVideo(a: any) {
  const u = a?.url || a?.file || ''
  return a?.type === 'video' || /\.(mp4|webm|mov|m4v)$/i.test(u)
}
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
function copyOf(a: any): { headline: string; sub: string; cta: string } | null {
  const c = a?.copy || a?.meta?.copy
  if (!c) return null
  const has = c.headline || c.sub || c.cta
  return has ? c : null
}

/**
 * 创意工作台 · V4.56（进度条归位 + 右侧「项目简报」结果面板）
 * ① 顶部仅保留菜单标题；② 输入模块常驻展示链接 / 产品信息；
 * ③ 分析进度条直接显示在输入框下方（不在任何面板内）；
 * ④ 产品分析「产品分析完成」+「为你规划了 N 条创意路线」收进正文，紧接输入框下方、素材上方，分析完成后一直显示，便于直观选择路线；
 * ⑤ 右侧「项目简报」面板仅展示分析结果（推广目标 / 目标受众 / 核心卖点 / 产品定位），可收缩，不展示进度 / 选项 / 操作；
 * ⑥ 生成成果（图片 / 视频 + 尺寸规格 + 文案）展示在「创意路线」下方；⑦ 素材可批量下载，也可单独放大查阅（灯箱）。
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

  // V4.55 新增：单独放大查阅（灯箱）
  const [lightbox, setLightbox] = useState<any>(null)

  // V4.56 新增：右侧「项目简报」面板（仅展示分析结果 / 可收缩）
  const [briefOpen, setBriefOpen] = useState(true)

  useEffect(() => {
    function applyNames(names: string[]) {
      const list = names.length ? names : DEFAULT_PLATFORMS.slice()
      setPlatforms(list)
      // 默认预选第一个平台，避免空选触发「请至少选择一个媒体平台」
      setSelected(s => (s.length ? s : list.slice(0, 1)))
    }
    api.mediaPlatforms()
      .then((d: any) => {
        // 接口返回的是平台数组（非 { platforms: [...] }），需兼容两种结构
        const raw = Array.isArray(d) ? d : (d?.platforms || [])
        const names = (raw || [])
          .map((p: any) => (typeof p === 'string' ? p : p?.platform))
          .filter(Boolean)
        applyNames(names)
      })
      .catch(() => { applyNames([]) })
  }, [])

  // 滑出面板 / 灯箱 的 ESC 关闭
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setLightbox(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
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
    setRunning(true)                            // 分析进度在正文分析区展示
    setView('analyzing'); setProgressPct(8); setProgressText('正在解析产品页面…')
    try {
      const cwRes: any = await api.cwAnalyze({ url: isUrl(val) ? val : '', text: isUrl(val) ? '' : val, platforms: selected })
      setCw(cwRes); setPlanId(cwRes?.id ?? null)
      setProgressPct(46); setProgressText('47% · 正在提取核心利益点')
      // V4.58 / B2：移除二次模型调用（landingAnalysis）。cwAnalyze 已返回统一分析来源 `analysis`，
      // 路线规划与素材生成均以此为唯一依据，避免「两次模型理解」且 landing 失败被静默 catch 成空。
      const routeRes = await api.cwRoutes({ plan_id: cwRes?.id, analysis: cwRes?.analysis || {}, platforms: selected, brief: cwRes?.brief || {} }).catch(() => ({ routes: cwRes?.routes || [] }))
      setRoutes((routeRes?.routes || cwRes?.routes || []).map((r: any) => ({ ...r, selected: r.selected !== false })))
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
      const h: any = await api.createCreationHistory({ analysis: cw?.analysis || {}, platform: selected[0] || '', lang: 'en' }).catch(() => null)
      hid = h?.id ?? null; setHistoryId(hid)
    } catch { /* 历史可选 */ }
    if (planId) await api.updateCreativePlan(planId, { status: 'generating', history_id: hid ?? undefined }).catch(() => {})

    const activeRoutes = routes.filter(r => r.selected)
    const targets = selected
    const collected: any[] = []
    const finalStates: string[] = []
    // A2（V4.57）：总任务数 = 平台数 × 选中路线数，进度分母据此计算（不再按平台数）。
    const totalJobs = targets.length * Math.max(1, activeRoutes.length)
    let done = 0
    try {
      const rules: any = await api.mediaRules().catch(() => ({}))
      const allowed: Record<string, string[]> = rules?.platforms || {}
      let genIdx = 0
      for (let i = 0; i < targets.length; i++) {
        const p = targets[i]
        // A2：去掉 slice(0, 2) 静默截断，按媒体平台返回的全部规格生成。
        const sizes = allowed[p] || ['1080x1080']
        const routeList = activeRoutes.length ? activeRoutes : [null]
        // A2：每个平台 × 每条选中路线各生成一组，保证多选路线都被覆盖（单平台也不会只用第一条）。
        for (const route of routeList) {
          genIdx++
          setProgressText(`正在为 ${p} · ${route?.name || '默认'} 生成推广图片…`)
          const slots = sizes.map(size => ({ size, placement: p }))
          const style_opts = {
            creative_direction: `${route?.name || ''}（${route?.angle || ''}）`.replace(/[（）\s]+$/, ''),
            content_style: `${route?.description || ''}；${((route?.tags) || []).join('、')}`.replace(/^[；\s]+|[；\s]+$/g, ''),
            color_scheme: '',
          }
          const payload = {
            images_request: {
              analysis: cw?.analysis || {}, platform: p, lang: 'en',
              copy_fields: {}, copy_variants: [], style_opts, slots,
              spec_version: rules?.spec_version || '',
              total_pixels: sizes.reduce((n: number, s: string) => { const [w, h] = s.split('x').map(Number); return n + (w * h || 0) }, 0),
            },
            archive: hid ? { history_id: hid, platform: p, lang: 'en' } : undefined,
            idempotency_key: `cw_${p}_${genIdx}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          }
          setJobs(j => [...j, { platform: p, jobId: null, status: 'submitting', progress: 0, images: [], route }])
          let job: any
          try { job = await api.createGenerationJob(payload) }
          catch (e: any) {
            setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: 'failed', error: e?.message || '创建失败' } : x))
            finalStates.push('failed'); done++; setProgressPct(Math.round(done / totalJobs * 100)); continue
          }
          const jobId = job?.job_id
          setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, jobId, status: job?.status || 'queued' } : x))
          let st: any = job
          for (let k = 0; k < 80; k++) {
            await sleep(1500)
            try { st = await api.generationJob(jobId) } catch { continue }
            setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: st?.status || x.status, progress: st?.progress ?? x.progress } : x))
            if (['succeeded', 'partial_success', 'failed', 'canceled'].includes(st?.status)) break
          }
          let imgs: any[] = (st?.result?.images || []).slice()
          if (!imgs.length) {
            try { const got: any = await api.creativeAssets({ job_id: jobId }); imgs = (got?.items || []).slice() } catch { /* 兜底 */ }
          }
          setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: st?.status || x.status, images: imgs } : x))
          for (const im of imgs) { im.__route = route; im.__platform = p }
          collected.push(...imgs); setAssets(a => [...a, ...imgs])
          if (imgs.length) showToast(`图片已生成 ${imgs.length} 张（${p} · ${route?.name || '默认'}）`)
          finalStates.push(st?.status || 'unknown')
          done++; setProgressPct(Math.round(done / totalJobs * 100))
        }
      }
    } catch (e: any) {
      setError((e?.message || '图片生成失败') + '（可重试或调整媒体后继续）')
    }
    // A3（V4.57）：依据真实终态裁决完成态，不再无条件标记成功 / 写 status=done。
    const okImages = collected.length
    const anyFailed = finalStates.some(s => s === 'failed' || s === 'canceled')
    setProgressText('创作完成')
    if (okImages > 0) {
      setView('result')
      showToast(`创作完成：共生成 ${okImages} 张图片`)
      if (planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: okImages, history_id: hid ?? undefined }).catch(() => {})
    } else {
      // 零图 / 全失败：进入结果区以便重试，但不宣称完成、不写 status=done。
      setError((anyFailed ? '本次生成失败（部分平台未返回素材）' : '本次生成超时或未返回素材')
        + '，请调整媒体或重试（可重试或调整媒体后继续）')
      setView('result')
    }
  }

  function download(file: string) { window.open(api.mediaFileDownloadUrl(file), '_blank') }
  function selectedFiles() { return assets.filter(a => checked[a.file]).map(a => a.file) }
  const selectedCount = selectedFiles().length
  function downloadSelected() {
    const f = selectedFiles(); if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  // A5（V4.57）：独立「下载全部」，与「下载已选」解耦，未勾选也能打包全部素材。
  function downloadAll() {
    const f = assets.filter(a => a.file).map(a => a.file)
    if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  function toggleSelectAll() {
    if (selectedCount > 0) setChecked({})
    else setChecked(Object.fromEntries(assets.map(a => [a.file, true])))
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
    // A4（V4.57）：先清理上一项目的残留（landing / assets / jobs / historyId），避免跨项目旧数据参与生成。
    setLanding(null); setAssets([]); setJobs([]); setHistoryId(null); setError('')
    setCw({ id: item.id, title: item.title, summary: item.analysis?.summary || '',
      boxes: item.analysis?.boxes || {}, brief: item.analysis?.brief || {}, recommendedPlatforms: item.analysis?.recommendedPlatforms || [],
      analysis: (item.analysis && item.analysis.analysis) || {} })
    setSelected((item.platforms || []).slice())
    setRoutes((item.routes || []).map((r: any) => ({ ...r, selected: r.selected !== false })))
    setPlanId(item.id)
    if (item.history_id) setHistoryId(item.history_id)   // 还原历史归属，便于后续再下载 / 复用
    if (item.input) setInput(item.input)                 // 还原输入链接 / 文本（若存在）
    setHistOpen(false); setView('plan')
  }

  const activeStep = view === 'input' || view === 'analyzing' ? 1 : view === 'plan' ? 2 : 3
  const briefBoxes = cw?.boxes || {}
  const brief = cw?.brief || {}

  return (
    <div className="cwb">
      {/* ① 顶部仅保留菜单标题，其他文案已删除 */}
      <div className="cwb-top">
        <h2 className="cwb-title-only">创意工作台</h2>
      </div>

      <div className="cwb-body">
        <div className="cwb-main">
          {/* ② 输入模块常驻：展示用户链接 / 产品信息 */}
          <div className="cwb-input-card">
            <div className="cwb-url">
              <span className="cwb-link-ic">🔗</span>
              <input value={input} onChange={e => setInput(e.target.value)} placeholder="https://soundora.com/products/air-pro"
                onKeyDown={e => { if (e.key === 'Enter' && !running) analyze() }} />
              <button className="cwb-start" onClick={analyze} disabled={running}>
                {running ? '分析中…' : (cw ? '重新分析 →' : '开始分析 →')}
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
            <div className="cwb-input-actions">
              <button className="cwb-ghost-btn" onClick={openHistory}>历史</button>
              <button className="cwb-ghost-btn" onClick={resetAll}>新建项目</button>
            </div>
          </div>

          {/* ① 分析进度条：直接显示在输入框下方（不在右侧面板，也不在正文路线区） */}
          {view === 'analyzing' && (
            <div className="cwb-progress-card">
              <div className="cwb-ai-ic"><span className="spark" /></div>
              <h3>正在理解你的产品…</h3>
              <p>分析页面信息、用户评论和同类广告，建立创意策略。</p>
              <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
              <div className="cwb-bar-txt">{progressText}</div>
            </div>
          )}

          {/* 分析结果 + 创意路线：常驻展示在输入框下方，分析完成后一直显示，便于直观查看 分析 / 路线 / 成品 */}
          <div className="cwb-strategy">
            {cw && view !== 'analyzing' && (
              <>
                <section className="cwb-section">
                  <h3 className="cwb-sub">产品分析完成</h3>
                  <p className="cwb-summary">{cw.summary || '（暂无分析摘要）'}</p>
                  <div className="cwb-boxes">
                    {[['行业', briefBoxes.industry], ['核心人群', briefBoxes.coreAudience],
                      ['购买动机', briefBoxes.purchaseMotivation], ['价格带', briefBoxes.priceBand]].map(([k, v]) => (
                      <div className="cwb-box" key={k as string}><span>{k as string}</span><b>{v || '—'}</b></div>
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

            {!cw && view !== 'analyzing' && (
              <div className="cwb-drawer-empty">
                <div className="cwb-empty-ic"><span className="spark" /></div>
                <p>输入产品链接并选择媒体平台，点击「开始分析」后，这里将展示产品分析与创意路线。</p>
              </div>
            )}
          </div>

          {/* ④ 生成成果：展示在「创意路线」下方（图片 / 视频 + 尺寸规格 + 文案内容） */}
          <section className="cwb-results">
            <div className="cwb-results-head">
              <div className="cwb-results-title">
                {view === 'result' && <h3 className="cwb-sub ok">首批素材已完成</h3>}
                {view === 'generating' && <h3 className="cwb-sub">正在生成素材…</h3>}
                {assets.length > 0 && (
                  <p className="cwb-reco-note">
                    已生成 {assets.length} 份素材{view === 'result' ? '，通过平台合规预检' : ''}
                  </p>
                )}
              </div>
              {assets.length > 0 && (
                <div className="cwb-result-actions">
                  <button className="cwb-link-btn" onClick={toggleSelectAll}>
                    {selectedCount > 0 ? '取消全选' : '全选'}
                  </button>
                  <button className="cwb-gen-btn sm" onClick={downloadSelected} disabled={!selectedCount}>
                    下载已选（{selectedCount}）
                  </button>
                </div>
              )}
            </div>

            {view === 'generating' && (
              <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
            )}

            <div className="cwb-grid">
              {assets.map((a, i) => {
                const sp = specOf(a); const rt = a.__route; const cp = copyOf(a); const vid = isVideo(a)
                return (
                  <div className="cwb-asset" key={a.file || i}>
                    <div className="cwb-asset-badge">{sp.ratio}</div>
                    <div className="cwb-asset-img" onClick={() => setLightbox(a)} title="点击放大">
                      {vid
                        ? <video src={api.fileUrl(a.url || a.file)} controls preload="metadata" />
                        : <img src={api.fileUrl(a.url || a.file)} alt="" loading="lazy" />}
                    </div>
                    <div className="cwb-asset-body">
                      <b>{rt?.name || a.__platform || '创意素材'}</b>
                      <p>{(rt?.tags || []).join('·') || '推广素材'}</p>
                      <div className="cwb-asset-meta">
                        <span>{brandOf(a.__platform, a.placement)}</span>
                        <span className="cwb-type">{vid ? '视频' : '图片'}</span>
                      </div>
                      <div className="cwb-asset-spec">
                        <span>推荐尺寸 {sp.dim}</span><span>画面比例 {sp.ratio}</span><span>{sp.fmt}</span>
                      </div>
                      {cp && (
                        <div className="cwb-copy">
                          {cp.headline && <div className="cwb-copy-h">{cp.headline}</div>}
                          {cp.sub && <div className="cwb-copy-s">{cp.sub}</div>}
                          {cp.cta && <div className="cwb-copy-c">CTA：{cp.cta}</div>}
                        </div>
                      )}
                    </div>
                    <label className="cwb-asset-check">
                      <input type="checkbox" checked={!!checked[a.file]} onChange={e => setChecked(c => ({ ...c, [a.file]: e.target.checked }))} /> 选择
                    </label>
                    <div className="cwb-asset-foot">
                      <button className="cwb-asset-zoom" onClick={() => setLightbox(a)}>放大</button>
                      <button className="cwb-asset-dl" onClick={() => download(a.file)}>下载</button>
                    </div>
                  </div>
                )
              })}
              {assets.length === 0 && (
                <div className="cwb-results-empty">
                  {view === 'analyzing' && '正在分析产品，请稍候…'}
                  {view === 'generating' && '正在生成素材，请稍候…'}
                  {!['analyzing', 'generating'].includes(view) &&
                    '输入产品链接并选择媒体平台，点击「开始分析」后，生成的图片 / 视频素材将展示在这里。'}
                </div>
              )}
            </div>

            {jobs.filter(j => j.status === 'failed').length > 0 && (
              <div className="err" style={{ marginTop: 10 }}>
                {jobs.filter(j => j.status === 'failed').map(j => `${j.platform}：${j.error}`).join('；')}
              </div>
            )}

            {view === 'result' && assets.length > 0 && (
              <div className="cwb-confirm">
                <button className="cwb-link-btn" onClick={resetAll}>新的创作</button>
                <button className="cwb-gen-btn sm" onClick={downloadAll}>打包下载全部</button>
              </div>
            )}
          </section>

          {error && <div className="err" style={{ marginTop: 12 }}>{error}</div>}
        </div>

        {/* 右侧「项目简报」面板：仅展示分析结果（推广目标 / 受众 / 卖点 / 产品定位），可收缩；不展示进度 / 选项 / 操作 */}
        {cw && (
          briefOpen ? (
            <aside className="cwb-brief">
              <div className="cwb-brief-head">
                <b>项目简报</b>
                <button className="cwb-brief-toggle" onClick={() => setBriefOpen(false)} title="收起面板">›</button>
              </div>
              <div className="cwb-brief-body">
                <div className="cwb-brief-card">
                  <div className="cwb-brief-card-txt">
                    <b>{cw.title || '未命名项目'}</b>
                    <small>{view === 'analyzing' ? '分析中' : view === 'plan' ? '分析完成' : assets.length ? '素材已生成' : '已分析'}</small>
                  </div>
                </div>
                <div className="cwb-brief-row">
                  <div className="cwb-brief-label">推广目标</div>
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
                  <div className="cwb-brief-label">产品定位</div>
                  <div className="cwb-brief-pos">
                    <span>行业：{briefBoxes.industry || '—'}</span>
                    <span>价格带：{briefBoxes.priceBand || '—'}</span>
                    <span>购买动机：{briefBoxes.purchaseMotivation || '—'}</span>
                  </div>
                </div>
              </div>
            </aside>
          ) : (
            <button className="cwb-brief-tab" onClick={() => setBriefOpen(true)} title="展开项目简报">项目简报 ›</button>
          )
        )}
      </div>

      {/* ⑤ 单独放大查阅（灯箱） */}
      {lightbox && (
        <div className="cwb-lightbox" onClick={() => setLightbox(null)}>
          <div className="cwb-lightbox-inner" onClick={e => e.stopPropagation()}>
            <button className="cwb-lightbox-x" onClick={() => setLightbox(null)}>×</button>
            <div className="cwb-lightbox-media">
              {isVideo(lightbox)
                ? <video src={api.fileUrl(lightbox.url || lightbox.file)} controls autoPlay />
                : <img src={api.fileUrl(lightbox.url || lightbox.file)} alt="" />}
            </div>
            <div className="cwb-lightbox-info">
              <b>{lightbox.__route?.name || lightbox.__platform || '创意素材'}</b>
              <div className="cwb-asset-spec">
                {(() => { const sp = specOf(lightbox); return (<>
                  <span>推荐尺寸 {sp.dim}</span><span>画面比例 {sp.ratio}</span><span>{sp.fmt}</span>
                  <span>媒体 {brandOf(lightbox.__platform, lightbox.placement)}</span>
                  <span>类型 {isVideo(lightbox) ? '视频' : '图片'}</span>
                </>) })()}
              </div>
              {(() => { const cp = copyOf(lightbox); return cp ? (
                <div className="cwb-copy">
                  {cp.headline && <div className="cwb-copy-h">{cp.headline}</div>}
                  {cp.sub && <div className="cwb-copy-s">{cp.sub}</div>}
                  {cp.cta && <div className="cwb-copy-c">CTA：{cp.cta}</div>}
                </div>
              ) : null })()}
              <button className="cwb-gen-btn sm" onClick={() => download(lightbox.file)}>下载该素材</button>
            </div>
          </div>
        </div>
      )}

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
