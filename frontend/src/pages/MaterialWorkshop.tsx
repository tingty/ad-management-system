import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type WorkshopCopy,
  type WorkshopImageJob,
  type WorkshopOptions,
} from '../api'

/**
 * V4.108 素材工作坊（独立一级模块）
 *
 * 定位：把「链接 → 素材」这条链路压到三步以内。不暴露路线规划、brief 确认、
 * 版位矩阵等专业步骤；系统提示、模型说明、校验细节一律不进正文，只在真正需要
 * 用户处理时用一行话说清楚。
 *
 * 三条来自产品要求的界面约束：
 * 1. 简洁：组件统一高度，说明性文字默认隐藏；
 * 2. 上下布局：输入 → 进度 → 结果，单列自上而下；
 * 3. 结果分类：图片按平台分组、每张标尺寸比例，文案按平台分卡，均带预览 / 下载。
 *
 * 模型来源：只调用后端 `/workshop/*`，后端只用「大模型配置」里当前生效且测试通过的
 * 配置；未就绪时本页不发起任何付费调用。
 */

type ImgItem = {
  url: string
  file: string
  platform: string
  size: string
  label: string
  placement: string
  fallback: boolean
  /** 图内文字是否被自动收敛（完整文案仍在文案素材里） */
  fit?: string
}

type Phase = '' | 'analyzing' | 'copying' | 'imaging'
type JobPhase = 'queued' | 'running' | 'done' | 'failed'
/** V4.120：首页两种创作模式，默认流程保持原样不动。 */
type Mode = 'default' | 'template'

const LS_KEY = 'admb_workshop_v1'

/** 读取上次会话快照（同步读取后作为 state 初值，避免「先写空值再恢复」的竞态）。 */
function readSession(): any {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) || {}) : {}
  } catch { return {} }
}

/** 1080x1350 → "4:5 · 1080×1350"（与后端 workshop.size_label 同口径） */
function sizeLabel(size: string): string {
  const m = String(size || '').toLowerCase().match(/^(\d+)\s*[x×]\s*(\d+)$/)
  if (!m) return size || ''
  const w = Number(m[1]), h = Number(m[2])
  const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a)
  const g = gcd(w, h) || 1
  return `${w / g}:${h / g} · ${w}×${h}`
}

function downloadBlob(name: string, text: string, mime: string) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

export default function MaterialWorkshop({ canManageModels, onOpenModels }: {
  canManageModels: boolean
  onOpenModels: () => void
}) {
  // 刷新 / 重进页面时直接带着上次的输入与结果启动（只读一次本地快照）
  const session = useRef<any>(readSession())
  const [opt, setOpt] = useState<WorkshopOptions | null>(null)
  const [input, setInput] = useState<string>(session.current.input || '')
  /** 平台 → 已选尺寸 */
  const [sel, setSel] = useState<Record<string, string[]>>(session.current.sel || {})
  const [phase, setPhase] = useState<Phase>('')
  const [copies, setCopies] = useState<WorkshopCopy[]>(session.current.copies || [])
  const [jobs, setJobs] = useState<WorkshopImageJob[]>(session.current.jobs || [])
  const [jobPhase, setJobPhase] = useState<Record<string, JobPhase>>({})
  const [images, setImages] = useState<ImgItem[]>([])
  const [title, setTitle] = useState<string>(session.current.title || '')
  const [error, setError] = useState('')
  // V4.111：出图任务失败时把真实原因显示出来。此前只在轮询里记录 jobPhase，
  // 任务 failed 后界面只是「没有图片」，用户无法判断是尺寸、模型还是内容体检。
  const [jobNote, setJobNote] = useState('')
  const [toast, setToast] = useState('')
  const [preview, setPreview] = useState<ImgItem | null>(null)
  const timer = useRef<number | null>(null)

  // V4.120 按模板创作：模板只驱动图片，文案仍走下面同一条 run() 链路。
  const [mode, setMode] = useState<Mode>('default')
  const [templates, setTemplates] = useState<any[]>([])
  const [templateId, setTemplateId] = useState<number | null>(null)
  const [tplLoading, setTplLoading] = useState(false)
  const [templateSource, setTemplateSource] = useState('')

  /* ---------------- 启动参数（模型就绪状态 + 标准库尺寸） ---------------- */
  useEffect(() => {
    let alive = true
    api.workshopOptions()
      .then((d) => {
        if (!alive) return
        setOpt(d)
        // V4.111：尺寸清单会随标准库 / 规则口径收敛。旧会话里选过、现在已不可用的
        // 尺寸必须剔除，否则会被后端判「未登记」而整单 422。
        setSel(s => {
          const valid: Record<string, string[]> = {}
          for (const p of d.platforms || []) {
            const keep = (s[p.platform] || []).filter(x => p.sizes.some(y => y.size === x))
            if (keep.length) valid[p.platform] = keep
          }
          if (Object.keys(valid).length) return valid
          const first = (d.platforms || []).find(p => p.platform === 'Meta') || (d.platforms || [])[0]
          return first ? { [first.platform]: first.sizes.slice(0, 2).map(x => x.size) } : {}
        })
      })
      .catch((e: any) => { if (alive) setError(e?.message || '初始化失败') })
    return () => { alive = false }
  }, [])

  /* ---------------- 按模板创作的模板清单 ---------------- */
  useEffect(() => {
    if (mode !== 'template' || templates.length) return
    let alive = true
    setTplLoading(true)
    api.workshopTemplates()
      .then((list) => {
        if (!alive) return
        setTemplates(Array.isArray(list) ? list : [])
        const first = (Array.isArray(list) ? list : []).find((t: any) => t.usable)
        if (first) setTemplateId(first.id)
      })
      .catch((e: any) => { if (alive) setError(e?.message || '模板清单加载失败') })
      .finally(() => { if (alive) setTplLoading(false) })
    return () => { alive = false }
  }, [mode, templates.length])

  /* ---------------- 会话持久化：刷新后仍能接着看结果 ---------------- */
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ input, sel, title, copies, jobs }))
    } catch { /* 超配额时不影响主流程 */ }
  }, [input, sel, title, copies, jobs])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(''), 2200)
    return () => window.clearTimeout(t)
  }, [toast])

  /* ---------------- 出图任务轮询：刷新 / 关页后按 job_id 取回 ---------------- */
  useEffect(() => {
    if (!jobs.length) return
    let alive = true
    const tick = async () => {
      const nextPhase: Record<string, JobPhase> = {}
      const found: ImgItem[] = []
      const notes: string[] = []
      let pending = false
      await Promise.all(jobs.map(async (j) => {
        try {
          const st: any = await api.generationJob(j.job_id)
          const status = String(st?.status || '')
          const terminal = !!st?.terminal
          const imgs: any[] = st?.result?.images || []
          nextPhase[j.job_id] = terminal
            ? (status === 'succeeded' || status === 'partial_success' ? 'done' : 'failed')
            : (status === 'queued' ? 'queued' : 'running')
          if (!terminal) pending = true
          // 失败时把真实原因带出来（任务级 error 优先，其次子任务说明），不再静默
          if (terminal && status !== 'succeeded' && status !== 'partial_success') {
            const subs: any[] = Array.isArray(st?.subtasks) ? st.subtasks : []
            const sub = subs.find(x => x && x.status && x.status !== 'ok')
            const reason = String(st?.error || sub?.outcome_note || sub?.reason || '').trim()
            notes.push(`${j.platform}：${reason || '出图任务未返回可用图片'}`)
          }
          for (const im of imgs) {
            if (!im?.url && !im?.file) continue
            found.push({
              // 任务结果里的 url 是服务端文件路径，渲染时统一走 api.fileUrl
              url: im.url || '',
              file: im.file || '',
              platform: j.platform,
              size: im.size || '',
              label: sizeLabel(im.size || ''),
              placement: im.placement || '',
              fallback: !!im.fallback,
              fit: im.overlay_fit || '',
            })
          }
        } catch {
          nextPhase[j.job_id] = 'failed'
          notes.push(`${j.platform}：任务结果读取失败`)
        }
      }))
      if (!alive) return
      setJobPhase(prev => ({ ...prev, ...nextPhase }))
      if (found.length) {
        setImages(prev => {
          const have = new Set(prev.map(x => x.file || x.url))
          const add = found.filter(x => !have.has(x.file || x.url))
          return add.length ? [...prev, ...add] : prev
        })
      }
      setJobNote(notes.length ? [...new Set(notes)].join('；').slice(0, 400) : '')
      setPhase(pending ? 'imaging' : '')
      if (pending) timer.current = window.setTimeout(tick, 3000)
    }
    tick()
    return () => {
      alive = false
      if (timer.current) { window.clearTimeout(timer.current); timer.current = null }
    }
  }, [jobs])

  /* ---------------- 选择逻辑 ---------------- */
  const selectedCount = useMemo(
    () => Object.values(sel).reduce((n, arr) => n + arr.length, 0), [sel])
  const maxImages = opt?.limits?.max_images || 6
  const activePlatforms = useMemo(
    () => (opt?.platforms || []).filter(p => (sel[p.platform] || []).length > 0), [opt, sel])

  function togglePlatform(platform: string) {
    const sizes = opt?.platforms.find(p => p.platform === platform)?.sizes || []
    setSel(prev => {
      if ((prev[platform] || []).length) {
        const next = { ...prev }; delete next[platform]; return next
      }
      const pick = sizes.slice(0, 2).map(s => s.size)
      if (selectedCount + pick.length > maxImages) { setToast(`一次最多 ${maxImages} 张`); return prev }
      return { ...prev, [platform]: pick }
    })
  }

  function toggleSize(platform: string, size: string) {
    setSel(prev => {
      const cur = prev[platform] || []
      if (cur.includes(size)) {
        const next = cur.filter(s => s !== size)
        const out = { ...prev }
        if (next.length) out[platform] = next; else delete out[platform]
        return out
      }
      if (selectedCount >= maxImages) { setToast(`一次最多 ${maxImages} 张`); return prev }
      return { ...prev, [platform]: [...cur, size] }
    })
  }

  /* ---------------- 主流程 ---------------- */
  async function run() {
    const text = input.trim()
    if (!text || phase) return
    if (imageReady && !selectedCount) { setError('请至少选择一个尺寸'); return }
    // 按模板创作必须先选一条可用模板，不静默退回默认模式。
    const chosenTpl = mode === 'template' ? templates.find(t => t.id === templateId && t.usable) : null
    if (mode === 'template' && !chosenTpl) {
      setError('请选择一条可用的素材模板')
      return
    }
    setError(''); setToast('')
    setCopies([]); setJobs([]); setImages([]); setJobPhase({}); setTitle(''); setJobNote('')
    setTemplateSource(chosenTpl?.name || '')
    try {
      setPhase('analyzing')
      const a = await api.workshopAnalyze({
        input: text,
        platforms: Object.keys(sel),
      })
      setTitle(a.title || '')
      setPhase('copying')
      const platforms = Object.keys(sel).length ? Object.keys(sel)
        : [(opt?.platforms || [])[0]?.platform].filter(Boolean) as string[]
      const targets = imageReady
        ? Object.entries(sel).map(([platform, sizes]) => ({ platform, sizes }))
        : platforms.map(platform => ({ platform, sizes: [] as string[] }))
      const g = await api.workshopGenerate({
        analysis: a.analysis, plan_id: a.plan_id, targets,
        template_id: chosenTpl ? chosenTpl.id : null,
      })
      if (g.template_name) setTemplateSource(g.template_name)
      setCopies(g.copies || [])
      setJobs(g.image_jobs || [])
      if (g.warnings?.length) setError(g.warnings.join('；'))
      if (!g.image_jobs?.length) setPhase('')
    } catch (e: any) {
      setError(e?.message || '创作失败，请重试')
      setPhase('')
    }
  }

  function downloadImage(it: ImgItem) {
    window.open(api.mediaFileDownloadUrl(it.file), '_blank')
  }

  async function copyText(text: string) {
    try { await navigator.clipboard.writeText(text); setToast('已复制') }
    catch { setToast('复制失败，请手动选择') }
  }

  const models = opt?.models?.items || []
  const modelReady = (usage: string) => !!models.find(m => m.usage === usage)?.ready
  // V4.109：未就绪要带上具体原因（未配置 / 已停用 / 要素不全 / 未测试 / 测试失败），
  // 否则真实环境里「配了图片模型但没点测试」会被读成「系统看不到这条配置」。
  const modelReason = (usage: string) => models.find(m => m.usage === usage)?.reason || ''
  const copyReady = modelReady('analysis') && modelReady('copy')
  const imageReady = modelReady('image')
  // 图片模型缺失时降级为「只出文案」：不阻断工作坊，也不假装出图
  const ready = copyReady
  const stepIndex = phase === 'analyzing' ? 0 : phase === 'copying' ? 1
    : phase === 'imaging' ? 2 : (images.length || copies.length ? 3 : -1)
  const pendingCount = Object.values(jobPhase).filter(v => v === 'queued' || v === 'running').length

  const imageGroups = useMemo(() => {
    const order = (opt?.platforms || []).map(p => p.platform)
    const map = new Map<string, ImgItem[]>()
    for (const it of images) {
      if (!map.has(it.platform)) map.set(it.platform, [])
      map.get(it.platform)!.push(it)
    }
    return [...map.entries()]
      .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
      .map(([platform, items]) => ({ platform, items }))
  }, [images, opt])

  const selectedTpl = mode === 'template' ? templates.find(t => t.id === templateId) : null

  return (
    <div className="ws">
      {/* V4.120：首页 Tab — 默认流程原样保留，按模板创作只影响图片 */}
      <div className="ws-modebar">
        <button type="button" className={`ws-mode ${mode === 'default' ? 'active' : ''}`}
          onClick={() => { setMode('default'); setError(''); setTemplateSource('') }}>
          默认创作
        </button>
        <button type="button" className={`ws-mode ${mode === 'template' ? 'active' : ''}`}
          onClick={() => { setMode('template'); setError('') }}>
          按模板创作
          <span className="ws-mode-note">模板只影响图片</span>
        </button>
      </div>

      {mode === 'template' && (
        <section className="card ws-tpl-card">
          <div className="tl-section-title">选择素材模板</div>
          <div className="muted" style={{ fontSize: 12, margin: '4px 0 10px' }}>
            模板只复用图片版式与视觉表达骨架；文案、产品事实与证据仍由本次输入的分析生成。
          </div>
          {tplLoading ? <div className="muted">加载模板中…</div> : templates.length === 0 ? (
            <div className="muted">暂无模板。请先在「素材创意模板库 → 分类归并 · 模板沉淀」沉淀一条模板。</div>
          ) : (
            <select value={templateId ?? ''} onChange={e => {
              setTemplateId(e.target.value ? Number(e.target.value) : null)
              setTemplateSource('')
            }}>
              <option value="">请选择模板</option>
              {templates.map(t => (
                <option key={t.id} value={t.id} disabled={!t.usable}>
                  {t.name}{t.usable ? '' : `（不可用：${t.reason}）`}
                </option>
              ))}
            </select>
          )}
          {selectedTpl && (
            <div className="ws-tpl-detail">
              <div className="ws-tpl-meta">
                <b>{selectedTpl.primary_category || '未分类'}</b>
                {(selectedTpl.purpose || []).map((p: string) => <span key={p} className="chip">{p}</span>)}
                <span className="muted" style={{ fontSize: 11 }}>版本 v{selectedTpl.version || 1}</span>
              </div>
              {Object.keys(selectedTpl.skeleton_preview || {}).length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  骨架：{Object.entries(selectedTpl.skeleton_preview).map(([k, v]) =>
                    `${k}=${String(v)}`).join(' · ')}
                </div>
              )}
              {!selectedTpl.usable && (
                <div className="tl-warn">模板暂不可用：{selectedTpl.reason}。{selectedTpl.required_action}</div>
              )}
            </div>
          )}
        </section>
      )}

      {/* ① 输入 */}
      <section className="card ws-input-card">
        <textarea
          className="ws-input"
          rows={2}
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="粘贴落地页链接，或描述要推广的产品"
          disabled={!!phase}
        />
        <div className="ws-chips">
          {(opt?.platforms || []).map(p => (
            <button key={p.platform} type="button"
              className={`chip ${(sel[p.platform] || []).length ? 'on' : ''}`}
              onClick={() => togglePlatform(p.platform)} disabled={!!phase}>
              {p.platform}
            </button>
          ))}
        </div>
        {imageReady && activePlatforms.length > 0 && (
          <div className="ws-chips ws-chips-size">
            {activePlatforms.map(p => p.sizes.map(s => (
              <button key={`${p.platform}-${s.size}`} type="button"
                className={`chip chip-sm ${(sel[p.platform] || []).includes(s.size) ? 'on' : ''}`}
                onClick={() => toggleSize(p.platform, s.size)} disabled={!!phase}>
                {p.platform} {s.label}
              </button>
            )))}
          </div>
        )}

        {opt && !copyReady && (
          <div className="ws-notice">
            <span>
              {(opt.models.items || []).filter(m => !m.ready)
                .map(m => `${m.label}未就绪（${m.reason}）`).join('；')}
            </span>
            {canManageModels
              ? <button type="button" className="btn ghost small" onClick={onOpenModels}>大模型配置</button>
              : <span className="ws-muted">请联系管理员</span>}
          </div>
        )}
        {opt && copyReady && !imageReady && (
          <div className="ws-notice">
            <span>图片模型未就绪（{modelReason('image') || '未配置'}），本次只出文案</span>
            {canManageModels
              ? <button type="button" className="btn ghost small" onClick={onOpenModels}>配置图片模型</button>
              : <span className="ws-muted">请联系管理员</span>}
          </div>
        )}

        <div className="ws-foot">
          <span className="ws-models">
            {models.map(m => (
              <span key={m.usage} className={m.ready ? 'ws-dot ok' : 'ws-dot bad'} title={m.reason || m.model}>
                {m.label}
              </span>
            ))}
          </span>
          <button type="button" className="btn ws-run" onClick={run}
            disabled={!input.trim() || !ready || !!phase || (imageReady && !selectedCount)
              || (mode === 'template' && !selectedTpl?.usable)}>
            {phase === 'analyzing' ? '解析中…' : phase === 'copying' ? '写文案…'
              : phase === 'imaging' ? `出图 ${pendingCount || ''}`.trim() + '…'
              : imageReady
                ? `${mode === 'template' ? '按模板创作' : '开始创作'}${selectedCount ? ` · ${selectedCount} 张` : ''}`
                : '生成文案'}
          </button>
        </div>
      </section>

      {/* ② 进度（只在运行时出现，结束时收起，避免留下说明性内容） */}
      {phase !== '' && stepIndex >= 0 && (
        <div className="ws-steps">
          {['解析', '文案', '图片'].map((label, i) => (
            <span key={label} className={`ws-step ${stepIndex > i ? 'done' : stepIndex === i ? 'now' : ''}`}>
              {label}
            </span>
          ))}
        </div>
      )}

      {mode === 'template' && templateSource && (
        <div className="ws-template-source">
          本批图片由模板「{templateSource}」驱动（仅影响图片版式与视觉表达；文案与产品事实由本次输入生成）
        </div>
      )}
      {error && <div className="ws-error">{error}</div>}
      {jobNote && <div className="ws-error">{jobNote}</div>}
      {toast && <div className="ws-toast">{toast}</div>}

      {/* ③ 结果：分类展示 */}
      {images.length > 0 && (
        <section className="ws-block">
          <header className="ws-block-head">
            <h2>图片素材</h2>
            <span className="ws-count">{images.length}</span>
          </header>
          {images.some(it => it.fit) && (
            <div className="ws-muted">图内文字已按版式收敛，完整文案见下方文案素材</div>
          )}
          {imageGroups.map(g => (
            <div key={g.platform} className="ws-group">
              <div className="ws-group-head">
                <b>{g.platform}</b>
                <span className="ws-muted">{g.items.length} 张</span>
              </div>
              <div className="ws-grid">
                {g.items.map(it => (
                  <figure key={it.file || it.url} className="ws-card">
                    <button type="button" className="ws-thumb" onClick={() => setPreview(it)}
                      title="预览">
                      <img src={api.fileUrl(it.url || it.file)} alt={it.label} loading="lazy" />
                      {it.fallback && <span className="ws-flag">模板兜底</span>}
                    </button>
                    <figcaption>
                      <span className="ws-size">{it.label}</span>
                      <span className="ws-actions">
                        <button type="button" onClick={() => setPreview(it)}>预览</button>
                        <button type="button" onClick={() => downloadImage(it)}>下载</button>
                      </span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {copies.length > 0 && (
        <section className="ws-block">
          <header className="ws-block-head">
            <h2>文案素材</h2>
            <span className="ws-count">{copies.filter(c => c.status !== 'failed').length}</span>
          </header>
          <div className="ws-copies">
            {copies.map(c => (
              <article key={c.platform} className="ws-copy">
                <div className="ws-copy-head">
                  <b>{c.platform}</b>
                  {c.status === 'failed'
                    ? <span className="ws-flag">{c.reason}</span>
                    : (
                      <span className="ws-actions">
                        <button type="button" onClick={() => copyText(c.text)}>复制</button>
                        <button type="button" onClick={() => downloadBlob(
                          `${c.platform}_copy.txt`, c.text, 'text/plain;charset=utf-8')}>下载</button>
                      </span>
                    )}
                </div>
                {c.status !== 'failed' && c.rows.map(r => (
                  <div key={r.key} className="ws-line">
                    <span className="ws-line-label">{r.label}</span>
                    <span className="ws-line-value">{r.values.join(' ｜ ')}</span>
                  </div>
                ))}
              </article>
            ))}
          </div>
        </section>
      )}

      {/* ④ 预览 */}
      {preview && (
        <div className="ws-lightbox" onClick={() => setPreview(null)}>
          <div className="ws-lightbox-inner" onClick={e => e.stopPropagation()}>
            <img src={api.fileUrl(preview.url || preview.file)} alt={preview.label} />
            <div className="ws-lightbox-bar">
              <span>{preview.platform} · {preview.label}</span>
              <span className="ws-actions">
                <button type="button" className="btn ghost small" onClick={() => downloadImage(preview)}>下载</button>
                <button type="button" className="btn ghost small" onClick={() => setPreview(null)}>关闭</button>
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
