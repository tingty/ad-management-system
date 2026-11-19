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
}

type Phase = '' | 'analyzing' | 'copying' | 'imaging'
type JobPhase = 'queued' | 'running' | 'done' | 'failed'

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
  const [toast, setToast] = useState('')
  const [preview, setPreview] = useState<ImgItem | null>(null)
  const timer = useRef<number | null>(null)

  /* ---------------- 启动参数（模型就绪状态 + 标准库尺寸） ---------------- */
  useEffect(() => {
    let alive = true
    api.workshopOptions()
      .then((d) => {
        if (!alive) return
        setOpt(d)
        const first = d.platforms?.find(p => p.platform === 'Meta') || d.platforms?.[0]
        if (first) {
          setSel(s => (Object.keys(s).length ? s : { [first.platform]: first.sizes.slice(0, 2).map(x => x.size) }))
        }
      })
      .catch((e: any) => { if (alive) setError(e?.message || '初始化失败') })
    return () => { alive = false }
  }, [])

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
      let pending = false
      await Promise.all(jobs.map(async (j) => {
        try {
          const st: any = await api.generationJob(j.job_id)
          const status = String(st?.status || '')
          const terminal = !!st?.terminal
          nextPhase[j.job_id] = terminal
            ? (status === 'succeeded' || status === 'partial_success' ? 'done' : 'failed')
            : (status === 'queued' ? 'queued' : 'running')
          if (!terminal) pending = true
          for (const im of (st?.result?.images || [])) {
            if (!im?.url) continue
            found.push({
              url: im.url,
              file: im.file || '',
              platform: j.platform,
              size: im.size || '',
              label: sizeLabel(im.size || ''),
              placement: im.placement || '',
              fallback: !!im.fallback,
            })
          }
        } catch {
          nextPhase[j.job_id] = 'failed'
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
    setError(''); setToast('')
    setCopies([]); setJobs([]); setImages([]); setJobPhase({}); setTitle('')
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
      })
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

  return (
    <div className="ws">
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
            <span>{(opt.models.missing || []).join('、')} 未就绪</span>
            {canManageModels
              ? <button type="button" className="btn ghost small" onClick={onOpenModels}>大模型配置</button>
              : <span className="ws-muted">请联系管理员</span>}
          </div>
        )}
        {opt && copyReady && !imageReady && (
          <div className="ws-notice">
            <span>图片模型未就绪，本次只出文案</span>
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
            disabled={!input.trim() || !ready || !!phase || (imageReady && !selectedCount)}>
            {phase === 'analyzing' ? '解析中…' : phase === 'copying' ? '写文案…'
              : phase === 'imaging' ? `出图 ${pendingCount || ''}`.trim() + '…'
              : imageReady
                ? `开始创作${selectedCount ? ` · ${selectedCount} 张` : ''}`
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

      {error && <div className="ws-error">{error}</div>}
      {toast && <div className="ws-toast">{toast}</div>}

      {/* ③ 结果：分类展示 */}
      {images.length > 0 && (
        <section className="ws-block">
          <header className="ws-block-head">
            <h2>图片素材</h2>
            <span className="ws-count">{images.length}</span>
          </header>
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
                      <img src={it.url} alt={it.label} loading="lazy" />
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
            <img src={preview.url} alt={preview.label} />
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
