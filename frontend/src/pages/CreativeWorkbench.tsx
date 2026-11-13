import React, { useEffect, useState } from 'react'
import { api } from '../api'
import VideoStudio, { VideoState } from './VideoStudio'

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
// 规范平台名统一为 Meta（Facebook / fb / instagram / ig 为兼容别名），避免 Meta/Facebook 不一致
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

// V4.60 / B3：把 CW 的「统一分析来源」归一化为合法 LandingAnalysis，
// 重点是把 channels（平台名字符串列表）转成 [{platform, reason}]，避免 media-campaign/copy
// 与 generation-jobs 因 channels 类型不符 422（前端 mediaCopy 调用被 .catch 静默吞掉 → 文案为空）。
function normalizeAnalysis(a: any): any {
  const x = a || {}
  const raw = (Array.isArray(x.channels) && x.channels.length)
    ? x.channels
    : (Array.isArray(x.recommendedPlatforms) ? x.recommendedPlatforms : [])
  const channels = raw
    .map((c: any) => (c && typeof c === 'object' && c.platform) ? c : { platform: String(c || ''), reason: '' })
    .filter((c: any) => c.platform)
  return { ...x, channels }
}

// V4.70 自检 5.1：校验网站分析是否产出应有的结果框架，缺失则不自动进入第二步
function isFrameOk(a: any): boolean {
  if (!a) return false
  const b = a.boxes || {}
  const br = a.brief || {}
  const titleOk = !!a.title
  const summaryOk = !!a.summary
  const boxesOk = !!(b.industry && b.coreAudience && b.purchaseMotivation && b.priceBand)
  const briefOk = !!(br.promotionGoal && Array.isArray(br.targetAudience) && br.targetAudience.length
    && Array.isArray(br.sellingPoints) && br.sellingPoints.length)
  return !!(titleOk && summaryOk && boxesOk && briefOk)
}

/**
 * 创意工作台 · V4.65 布局优化（仅界面排版，不涉及功能 / 处理流程 / 输出结果）
 * ① 顶部：标题 + 一句话介绍，不堆叠其他内容；
 * ② 输入模块：统一表单行（产品链接 / 投放平台[下拉单选] / 参考图 / 品牌[文字或导入Logo]），非必要子模块收进「更多选项」；
 * ③ 工作流处理模块：解析产品 → 规划创意 → 批量生成 三步可视化（done/cur/pending），进度条展示当前进度与待处理内容，结果汇总于此；
 * ④ 分析结果（产品摘要 / 行业·人群·动机·价格带 / 来源徽标）统一收进右侧「项目简报」面板；
 * ⑤ 创意路线交互选择保留在正文；⑥ 素材创作输出结果保持既有样式不变（可批量下载 / 单独放大灯箱）。
 */
export default function CreativeWorkbench() {
  const [platforms, setPlatforms] = useState<string[]>([])
  const [selected, setSelected] = useState<string[]>([])

  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [demoMode, setDemoMode] = useState(false)   // V4.59 / B1：演示模式开关（默认关闭）
  const [copiesByPlatform, setCopiesByPlatform] = useState<Record<string, any>>({})  // V4.60 / B3：各平台生成的广告文案
  const [referenceImage, setReferenceImage] = useState('')   // V4.60 / B3：商品/品牌参考图（/files/<name> 或 URL）
  const [referenceName, setReferenceName] = useState('')     // 参考图展示名
  const [refUploading, setRefUploading] = useState(false)   // 参考图上传/下载中
  // V4.61 / B4：品牌名（注入文案生成）
  const [selectedBrand, setSelectedBrand] = useState('')

  // V4.70：素材类型（图片 / 视频 / 图片和视频），控制 Step2 规划与 Step3 工作区显隐与生成范围
  const [materialType, setMaterialType] = useState<'image' | 'video' | 'both'>('both')
  // V4.70：品牌 Logo 注入生成链路开关（勾选→作为 brand_logo 传入图片/视频生成）
  const [injectLogo, setInjectLogo] = useState(false)

  const [view, setView] = useState<'input' | 'analyzing' | 'plan' | 'generating' | 'result'>('input')
  const [progressPct, setProgressPct] = useState(0)   // 图片工作区聚合进度
  const [progressText, setProgressText] = useState('')

  const [cw, setCw] = useState<any>(null)        // 设计对齐的产品分析（4 盒 + 简报）
  const [landing, setLanding] = useState<any>(null) // 生成后端所需的 LandingAnalysis
  const [planId, setPlanId] = useState<number | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  const [analysisValid, setAnalysisValid] = useState(false)  // V4.70 自检 5.1：分析框架完整性

  const [assets, setAssets] = useState<any[]>([])
  const [jobs, setJobs] = useState<JobState[]>([])   // 内部用于进度与归档，UI 仅展示聚合进度
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [historyId, setHistoryId] = useState<number | null>(null)

  const [toast, setToast] = useState<string | null>(null)

  // V4.55 新增：单独放大查阅（灯箱）
  const [lightbox, setLightbox] = useState<any>(null)

  // V4.56 新增：右侧「项目简报」面板（仅展示分析结果 / 可收缩）
  const [briefOpen, setBriefOpen] = useState(true)

  const [brandLogo, setBrandLogo] = useState('')           // 品牌 Logo 文件（UI 预览 + 可注入生成）
  const [brandLogoName, setBrandLogoName] = useState('')
  const [brandUploading, setBrandUploading] = useState(false)
  // V4.62：素材图叠加模式。默认「纯图片」：生成素材时不含文字 / 按钮 / logo。
  const [overlayMode, setOverlayMode] = useState<'pure' | 'text' | 'text_button'>('pure')

  // V4.70：视频状态切片（由 VideoStudio 受控托管，Step2 规划 / Step3 工作区共享分镜方案）
  const [vs, setVs] = useState<VideoState>({
    messages: [], plan: null, videos: [], options: {
      mode: referenceImage ? 'image_to_video' : 'text_to_video',
      voiceover: 'narration', duration: 15, aspect: '9:16', lang: 'zh', prompt_hint: '',
    },
    note: '', modelInfo: null, planning: false, generating: false, error: '', refineInput: '',
  })

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
  // V4.59 / B1：把来源快照 + 模型信息渲染成可追溯徽标（真实抓取 / 演示 / 手动文本 / 抓取失败）
  function srcLabel(s?: string) {
    return ({ real_fetch: '真实抓取', demo: '演示样例', pasted: '手动文本', fetch_failed: '抓取失败', local: '本地' } as any)[s || 'local'] || s || '—'
  }
  function renderSrcBadges() {
    const snap: any = cw?.snapshot || {}
    const mi: any = cw?.model_info || {}
    const items: [string, string][] = []
    items.push(['数据来源', srcLabel(snap.source)])
    if (snap.final_url) items.push(['落地页', snap.final_url])
    if (snap.fetched_at) items.push(['抓取时间', (snap.fetched_at || '').replace('T', ' ').slice(0, 19) + ' UTC'])
    if (snap.fetch_quality) items.push(['抓取质量', snap.fetch_quality])
    if (mi?.provider || mi?.model) items.push(['分析模型', `${mi.provider || ''}/${mi.model || ''}${mi.fallback ? '（兜底）' : ''}`])
    if (!items.length) return null
    return (
      <div className="cwb-src-badges">
        {items.map(([k, v], i) => (
          <span key={i} className={`cwb-src-badge src-${snap.source || 'local'}`}><i>{k}</i>{v}</span>
        ))}
      </div>
    )
  }
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
      const cwRes: any = await api.cwAnalyze({ url: isUrl(val) ? val : '', text: isUrl(val) ? '' : val, platforms: selected, demo_mode: demoMode })
      setCw(cwRes); setPlanId(cwRes?.id ?? null)
      setProgressPct(46); setProgressText('47% · 正在提取核心利益点')
      // V4.58 / B2：移除二次模型调用（landingAnalysis）。cwAnalyze 已返回统一分析来源 `analysis`，
      // 路线规划与素材生成均以此为唯一依据，避免「两次模型理解」且 landing 失败被静默 catch 成空。
      const routeRes = await api.cwRoutes({ plan_id: cwRes?.id, analysis: cwRes?.analysis || {}, platforms: selected, brief: cwRes?.brief || {} }).catch(() => ({ routes: cwRes?.routes || [] }))
      setRoutes((routeRes?.routes || cwRes?.routes || []).map((r: any) => ({ ...r, selected: r.selected !== false })))
      setProgressPct(100); setProgressText('分析完成')
      // V4.70 自检 5.1：分析框架不完整时不进入第二步，提示重新分析
      if (!isFrameOk(cwRes)) {
        setAnalysisValid(false)
        setError('分析框架不完整（缺少产品定位 / 核心人群 / 购买动机 / 卖点或推广目标等关键内容），请重新分析或调整链接 / 产品信息后重试。')
        setView('input')
        return
      }
      setAnalysisValid(true)
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

  async function generateImages(hid: number | null): Promise<{ okImages: number; anyFailed: boolean; errs: string[] }> {
    const errs: string[] = []
    // V4.60 / B3：归一化为合法 LandingAnalysis（channels 转成 [{platform,reason}]），否则文案 / 出图端点会 422。
    const analysis = normalizeAnalysis(cw?.analysis)
    // V4.61 / B4：若用户指定品牌，注入分析，使文案生成沿用该品牌（避免模型随意起名）
    if (selectedBrand && selectedBrand.trim()) analysis.brand = selectedBrand.trim()
    // V4.60 / B3：先为每个平台生成广告文案（修复「文案为空」），并把参考图归一成 /files/ 本地路径。
    const targets = selected
    const copiesByPlat: Record<string, any> = {}
    const variantsByPlat: Record<string, any[]> = {}
    const copyFailures: Record<string, string> = {}
    const firstNonEmpty = (v: any): string => {
      if (Array.isArray(v)) { const hit = v.find((x: any) => typeof x === 'string' && x.trim()); return (hit as string)?.trim() || '' }
      return typeof v === 'string' ? v.trim() : ''
    }
    const pickFirstField = (...fields: any[]): string => { for (const fld of fields) { const v = firstNonEmpty(fld); if (v) return v } return '' }
    const copyIsInvalid = (cr: any): boolean => !!(cr?.validation && cr.validation.status === 'invalid')
    for (const p of targets) {
      if (overlayMode === 'pure') { variantsByPlat[p] = []; continue }
      try {
        setProgressText(`正在为 ${p} 生成广告文案…`)
        const cr: any = await api.mediaCopy({ analysis, platform: p, lang: 'en' }).catch(() => null)
        if (cr && cr.fields && !copyIsInvalid(cr)) {
          copiesByPlat[p] = { fields: cr.fields, schema: cr.schema, brand: cr.brand, model_info: cr.model_info, validation: cr.validation }
          const f = cr.fields
          variantsByPlat[p] = [{ headline: firstNonEmpty(f.headline ?? f.title), sub: pickFirstField(f.description, f.body, f.primary_text), cta: firstNonEmpty(f.cta), brand: firstNonEmpty(cr.brand), label: p }]
        } else {
          copyFailures[p] = !cr ? '文案生成失败（mediaCopy 未返回结果）' : `文案校验未通过（${cr?.validation?.status || 'invalid'}）：${cr?.validation?.message || '请调整分析或文案后重试'}`
        }
      } catch { copyFailures[p] = '文案生成发生异常' }
    }
    setCopiesByPlatform(copiesByPlat)
    const brandSet = new Set<string>()
    if (selectedBrand && selectedBrand.trim()) brandSet.add(selectedBrand.trim())
    for (const p of Object.keys(copiesByPlat)) { const b = copiesByPlat[p]?.brand; if (b && String(b).trim()) brandSet.add(String(b).trim()) }
    for (const b of brandSet) { api.addCwLibrary({ kind: 'brand', title: b, meta: { platforms: Object.keys(copiesByPlat) } }).catch(() => {}) }
    let refPath = ''
    if (referenceImage && referenceImage.trim()) {
      const raw = referenceImage.trim()
      if (raw.startsWith('http')) { setRefUploading(true); try { const fr: any = await api.fetchAssetUrl(raw); refPath = fr?.url || '' } catch { refPath = '' } setRefUploading(false) }
      else refPath = raw
    }
    if (refPath) { api.addCwLibrary({ kind: 'reference', title: referenceName || '参考图', file: refPath, meta: { from: 'creative_workbench' } }).catch(() => {}) }
    const activeRoutes = routes.filter(r => r.selected)
    const collected: any[] = []
    const finalStates: string[] = []
    const capturedErrors: string[] = []
    const totalJobs = targets.length * Math.max(1, activeRoutes.length)
    let done = 0
    try {
      const rules: any = await api.mediaRules().catch(() => ({}))
      const allowed: Record<string, string[]> = rules?.platforms || {}
      let genIdx = 0
      for (let i = 0; i < targets.length; i++) {
        const p = targets[i]
        const sizes = allowed[p] || ['1080x1080']
        const routeList = activeRoutes.length ? activeRoutes : [null]
        for (const route of routeList) {
          genIdx++
          if (copyFailures[p]) {
            const reason = copyFailures[p]
            const tag = `${p}${route?.name ? '·' + route.name : ''}`
            capturedErrors.push(`${tag}：${reason}`)
            setJobs(j => [...j, { platform: p, jobId: null, status: 'failed', progress: 0, images: [], route, error: reason }])
            finalStates.push('failed'); done++; setProgressPct(Math.round(done / totalJobs * 100)); continue
          }
          setProgressText(`正在为 ${p} · ${route?.name || '默认'} 生成推广图片…`)
          const slots = sizes.map(size => ({ size, placement: p }))
          const style_opts: any = {
            creative_direction: `${route?.name || ''}（${route?.angle || ''}）`.replace(/[（）\s]+$/, ''),
            content_style: `${route?.description || ''}；${((route?.tags) || []).join('、')}`.replace(/^[；\s]+|[；\s]+$/g, ''),
            color_scheme: '',
          }
          if (refPath) style_opts.reference_image = refPath
          // V4.70：品牌 Logo 注入生成链路（勾选时）
          if (injectLogo && brandLogo) style_opts.brand_logo = brandLogo
          const payload = {
            images_request: {
              analysis, platform: p, lang: 'en',
              copy_fields: {}, copy_variants: variantsByPlat[p] || [], style_opts, slots,
              spec_version: rules?.spec_version || '',
              total_pixels: sizes.reduce((n: number, s: string) => { const [w, h] = s.split('x').map(Number); return n + (w * h || 0) }, 0),
              overlay_mode: overlayMode,
              logo: (injectLogo && brandLogo) ? brandLogo : '',
            },
            archive: hid ? { history_id: hid, platform: p, lang: 'en' } : undefined,
            idempotency_key: `cw_${p}_${genIdx}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          }
          setJobs(j => [...j, { platform: p, jobId: null, status: 'submitting', progress: 0, images: [], route }])
          let job: any
          try { job = await api.createGenerationJob(payload) }
          catch (e: any) {
            const msg = e?.message || '创建失败'
            setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: 'failed', error: msg } : x))
            capturedErrors.push(`${p}${route?.name ? '·' + route.name : ''}：${msg}`); finalStates.push('failed'); done++; setProgressPct(Math.round(done / totalJobs * 100)); continue
          }
          const jobId = job?.job_id
          setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, jobId, status: job?.status || 'queued' } : x))
          let st: any = job
          for (let k = 0; k < 80; k++) {
            await sleep(1500)
            try { st = await api.generationJob(jobId) } catch { continue }
            setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: st?.status || x.status, progress: st?.progress ?? x.progress, error: st?.error || x.error } : x))
            if (['succeeded', 'partial_success', 'failed', 'canceled'].includes(st?.status)) break
          }
          let imgs: any[] = (st?.result?.images || []).slice()
          if (st?.status === 'failed' && st?.error) capturedErrors.push(`${p}${route?.name ? '·' + route.name : ''}：${st.error}`)
          if (!imgs.length) { try { const got: any = await api.creativeAssets({ job_id: jobId }); imgs = (got?.items || []).slice() } catch { /* 兜底 */ } }
          setJobs(j => j.map(x => x.platform === p && x.route === route ? { ...x, status: st?.status || x.status, images: imgs } : x))
          for (const im of imgs) { im.__route = route; im.__platform = p }
          collected.push(...imgs); setAssets(a => [...a, ...imgs])
          if (imgs.length) showToast(`图片已生成 ${imgs.length} 张（${p} · ${route?.name || '默认'}）`)
          finalStates.push(st?.status || 'unknown'); done++; setProgressPct(Math.round(done / totalJobs * 100))
        }
      }
      if (hid) {
        const primary = Object.keys(copiesByPlat)[0] || selected[0] || ''
        const primaryCopy = primary ? copiesByPlat[primary] : undefined
        const copyPayload: any = {
          platform: primary, lang: 'en',
          fields: primaryCopy ? primaryCopy.fields : {}, schema: primaryCopy ? primaryCopy.schema : [],
          brand: primaryCopy ? primaryCopy.brand : '', model_info: primaryCopy ? primaryCopy.model_info : {},
          copy_variants: primaryCopy ? variantsByPlat[primary] : [], platform_copies: copiesByPlat,
        }
        await api.updateCreationHistory(hid, { copy: copyPayload }).catch(() => {})
      }
    } catch (e: any) {
      errs.push((e?.message || '图片生成失败') + '（可重试或调整媒体后继续）')
    }
    const okImages = collected.length
    const anyFailed = finalStates.some(s => s === 'failed' || s === 'canceled')
    if (okImages > 0 && planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: okImages, history_id: hid ?? undefined }).catch(() => {})
    const seen = new Set<string>()
    const uniqErrs = capturedErrors.filter(Boolean).filter(e => { const k = e.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true })
    if (uniqErrs.length) errs.push(...uniqErrs)
    else if (!okImages && anyFailed) errs.push('部分平台未返回素材，请调整媒体或重试')
    return { okImages, anyFailed, errs }
  }

  async function generateVideo(hid: number | null): Promise<boolean> {
    if (!vs.plan || !vs.plan.shots?.length) return false
    const analysis = normalizeAnalysis(cw?.analysis)
    if (selectedBrand && selectedBrand.trim()) analysis.brand = selectedBrand.trim()
    setVs(s => ({ ...s, generating: true, error: '', videos: [], note: '' }))
    try {
      const r: any = await api.cwVideoGenerate({
        analysis, platform: selectedPlatform,
        reference_image: referenceImage || '',
        brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
        plan: vs.plan, options: { ...vs.options, prompt_hint: vs.options.prompt_hint },
      })
      setVs(s => ({ ...s, videos: r?.videos || [], note: r?.note || '', modelInfo: r?.model_info || s.modelInfo, generating: false, plan: r?.storyboard || s.plan, error: '' }))
      return (r?.videos || []).length > 0
    } catch (e: any) {
      setVs(s => ({ ...s, generating: false, error: '视频生成失败：' + (e?.message || '') }))
      return false
    }
  }

  async function batchGenerate() {
    const doImg = materialType !== 'video'
    const doVid = materialType !== 'image'
    if (doImg && !routes.some(r => r.selected)) { setError('请至少选择一条图片创意路线'); return }
    if (doVid && (!vs.plan || !vs.plan.shots?.length)) { setError('请先在第二步完成视频分镜规划'); return }
    setError(''); setView('generating'); setAssets([]); setJobs([]); setChecked({}); setProgressPct(0); setProgressText('正在创建素材任务…')
    let hid: number | null = null
    try { const h: any = await api.createCreationHistory({ analysis: cw?.analysis || {}, platform: selected[0] || '', lang: 'en' }).catch(() => null); hid = h?.id ?? null; setHistoryId(hid) } catch { /* 历史可选 */ }
    if (planId) await api.updateCreativePlan(planId, { status: 'generating', history_id: hid ?? undefined }).catch(() => {})
    setProgressPct(10)
    const imgRes = doImg ? await generateImages(hid) : { okImages: 0, anyFailed: false, errs: [] }
    setProgressPct(70)
    const vidOk = doVid ? await generateVideo(hid) : true
    setProgressPct(100); setProgressText('创作完成')
    const totalOk = imgRes.okImages > 0 || vidOk
    if (totalOk) {
      showToast(`创作完成：图片 ${imgRes.okImages} 张${vidOk ? '，视频已生成' : ''}`)
      if (planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: imgRes.okImages, history_id: hid ?? undefined }).catch(() => {})
      setView('result')
    } else {
      const msgs = [...imgRes.errs]
      if (!vidOk && doVid) msgs.push('视频生成未返回成片（可能未配置视频模型，已回退分镜脚本）')
      setError(msgs.join('；') || '本次生成未返回素材，请调整媒体或重试')
      setView('result')
    }
  }
  function download(file: string) { window.open(api.mediaFileDownloadUrl(file), '_blank') }
  function selectedFiles() { return assets.filter(a => checked[a.file]).map(a => a.file) }
  const selectedCount = selectedFiles().length
  function downloadSelected() {
    const f = selectedFiles(); if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  // B5：优先用历史导出包（含图片/视频 + ad_copy.csv + delivery_notes.md + 文案/分析）；
  // 仅在缺少 historyId 时回退到纯素材 ZIP（理论上 generate 后必有 historyId）。
  function downloadAll() {
    if (historyId) { window.open(api.historyItemZipUrl(historyId), '_blank'); return }
    const f = assets.filter(a => a.file).map(a => a.file)
    if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  // V4.60 / B3：文案下载（单平台 TXT / 全部 JSON）
  function downloadBlob(filename: string, content: string, mime: string) {
    const blob = new Blob([content], { type: mime })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function copyToText(p: string, c: any): string {
    const lines = [`广告推广文案 · ${p} · ${c.model_info?.provider || ''}/${c.model_info?.model || ''}`, '-'.repeat(40)]
    for (const [k, v] of Object.entries(c.fields || {})) {
      if (v == null || v === '') continue
      lines.push(`${k}：${Array.isArray(v) ? (v as any[]).filter(Boolean).join(' / ') : String(v)}`)
    }
    return lines.join('\n')
  }
  function downloadCopy(p: string) {
    const c = copiesByPlatform[p]; if (!c) return
    downloadBlob(`ad_copy_${p}.txt`, copyToText(p, c), 'text/plain;charset=utf-8')
  }
  function downloadAllCopy() {
    downloadBlob('ad_copy_all.json', JSON.stringify(copiesByPlatform, null, 2), 'application/json')
  }
  function toggleSelectAll() {
    if (selectedCount > 0) setChecked({})
    else setChecked(Object.fromEntries(assets.map(a => [a.file, true])))
  }
  function resetAll() {
    setView('input'); setCw(null); setLanding(null); setRoutes([]); setPlanId(null); setAssets([]); setJobs([])
    setHistoryId(null); setError(''); setProgressPct(0); setChecked({}); setDemoMode(false)
    // V4.60 / B3 + B4：清空文案缓存、参考图与品牌选择
    setCopiesByPlatform({}); setReferenceImage(''); setReferenceName(''); setSelectedBrand('')
    // V4.70：清空素材类型 / 视频状态 / 品牌 Logo
    setMaterialType('both'); setInjectLogo(false)
    setVs({ messages: [], plan: null, videos: [], options: {
      mode: referenceImage ? 'image_to_video' : 'text_to_video',
      voiceover: 'narration', duration: 15, aspect: '9:16', lang: 'zh', prompt_hint: '' },
      note: '', modelInfo: null, planning: false, generating: false, error: '', refineInput: '' })
    setBrandLogo(''); setBrandLogoName('')
    setAnalysisValid(false)
  }
  async function onRefFile(e: any) {
    const file = e.target.files?.[0]; if (!file) return
    setRefUploading(true)
    try {
      const r: any = await api.uploadAsset(file)
      setReferenceImage(r?.url || ''); setReferenceName(r?.name || file.name)
    } catch (err: any) { setError('参考图上传失败：' + (err?.message || '')) }
    finally { setRefUploading(false); e.target.value = '' }
  }
  // V4.65：品牌 Logo 上传（UI 预览；勾选「注入生成链路」时作为 brand_logo 传入图片/视频生成）
  async function onBrandLogo(e: any) {
    const file = e.target.files?.[0]; if (!file) return
    setBrandUploading(true)
    try {
      const r: any = await api.uploadAsset(file)
      setBrandLogo(r?.url || ''); setBrandLogoName(r?.name || file.name)
    } catch (err: any) { setError('品牌 Logo 上传失败：' + (err?.message || '')) }
    finally { setBrandUploading(false); e.target.value = '' }
  }
  function clearBrandLogo() { setBrandLogo(''); setBrandLogoName('') }
  // V4.65：投放平台改为下拉单选（内部仍保持 [platform] 数组，下游生成逻辑不变）
  function onPlatformChange(e: any) { setSelected([e.target.value]) }
  const selectedPlatform = selected[0] || ''
  const activeStep = view === 'input' || view === 'analyzing' ? 1 : view === 'plan' ? 2 : 3
  const briefBoxes = cw?.boxes || {}
  const brief = cw?.brief || {}

  // V4.65 工作流步骤状态（仅 UI 展示，不涉及功能）：done / cur(进行中) / pending(待处理)
  const wf: Record<number, string> = ((
    { analyzing:  { 1: 'cur', 2: 'pending', 3: 'pending' },
      plan:       { 1: 'done', 2: 'cur', 3: 'pending' },
      generating: { 1: 'done', 2: 'done', 3: 'cur' },
      result:     { 1: 'done', 2: 'done', 3: 'done' },
      input:      { 1: 'cur', 2: 'pending', 3: 'pending' } } as any
  )[view]) || { 1: 'cur', 2: 'pending', 3: 'pending' }
  const wfStatus: string = (
    { input: '准备开始', analyzing: '正在分析产品', plan: '分析完成 · 待规划',
      generating: '正在生成素材', result: '创作完成' } as any
  )[view] || ''

  return (
    <div className="cwb">
      {/* ① 顶部：标题 + 一句话介绍，不堆叠其他内容 */}
      <div className="cwb-top">
        <div>
          <h2 className="cwb-title-only">创意工作台</h2>
          <p className="cwb-intro">输入产品链接并选择投放平台，AI 自动完成产品分析、创意规划与素材生成。</p>
        </div>
      </div>

      <div className="cwb-body">
        <div className="cwb-main">
          {/* ② 输入模块常驻：展示用户链接 / 产品信息 */}
          <div className="cwb-input-card">
            {/* ② 输入模块：4 个主模块，组件一致；非必要子模块收进「更多选项」 */}
            <div className="cwb-form">
              {/* 链接输入框 */}
              <div className="cwb-form-row">
                <label className="cwb-field-label">产品链接</label>
                <div className="cwb-url">
                  <span className="cwb-link-ic">🔗</span>
                  <input value={input} onChange={e => setInput(e.target.value)} placeholder="https://soundora.com/products/air-pro"
                    onKeyDown={e => { if (e.key === 'Enter' && !running) analyze() }} />
                </div>
              </div>
              {/* 投放平台：下拉单选 */}
              <div className="cwb-form-row">
                <label className="cwb-field-label" htmlFor="cwb-pl">投放平台</label>
                <div className="cwb-select-wrap">
                  <select id="cwb-pl" className="cwb-select" value={selectedPlatform} onChange={onPlatformChange}>
                    {platforms.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
              </div>
              {/* 素材类型：控制 Step2 规划与 Step3 工作区范围（图片 / 视频 / 图片和视频） */}
              <div className="cwb-form-row">
                <label className="cwb-field-label" htmlFor="cwb-mt">素材类型</label>
                <div className="cwb-select-wrap">
                  <select id="cwb-mt" className="cwb-select" value={materialType}
                    onChange={e => setMaterialType(e.target.value as 'image' | 'video' | 'both')}>
                    <option value="image">图片</option>
                    <option value="video">视频</option>
                    <option value="both">图片和视频</option>
                  </select>
                </div>
              </div>
              {/* 素材图片选择：下拉单选（默认 纯图片），开始分析即按此要求出图（仅图片 / 图片和视频时展示） */}
              <div className="cwb-form-row" style={{ display: materialType === 'video' ? 'none' : undefined }}>
                <label className="cwb-field-label" htmlFor="cwb-ov">素材图片选择</label>
                <div className="cwb-ov-col">
                  <div className="cwb-select-wrap">
                    <select id="cwb-ov" className="cwb-select" value={overlayMode}
                      onChange={e => setOverlayMode(e.target.value as 'pure' | 'text' | 'text_button')}>
                      <option value="pure">纯图片</option>
                      <option value="text">图片+文字</option>
                      <option value="text_button">图片+文字+按钮</option>
                    </select>
                  </div>
                  <span className="cwb-field-hint">默认「纯图片」：生成素材不含文字 / 按钮 / logo</span>
                </div>
              </div>
              {/* 参考图（upload / URL） */}
              <div className="cwb-form-row">
                <label className="cwb-field-label">参考图</label>
                <div className="cwb-ref-row cwb-ref-row2">
                  <label className="cwb-ref-upload" title="上传商品/品牌图，注入出图链路参考真实外观">
                    <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onRefFile} disabled={refUploading} />
                    <span>{refUploading ? '处理中…' : (referenceImage ? '更换图片' : '上传图片')}</span>
                  </label>
                  {referenceImage && <span className="cwb-ref-name" title={referenceImage}>{referenceName || '已上传'}</span>}
                  {referenceImage && <button className="cwb-ref-clear" onClick={() => { setReferenceImage(''); setReferenceName('') }} title="移除参考图">移除</button>}
                  <input className="cwb-ref-url" value={referenceImage.startsWith('http') ? referenceImage : ''}
                    onChange={e => { setReferenceImage(e.target.value.trim()); setReferenceName('') }}
                    placeholder="或粘贴图片 URL（自动下载）" disabled={refUploading} />
                </div>
              </div>
              {/* 品牌：输入框 + 右侧 Logo 上传按钮；上传后 Logo 预览显示在品牌标题下方 */}
              <div className="cwb-form-row">
                <label className="cwb-field-label">品牌</label>
                <div className="cwb-brand-row">
                  <input className="cwb-input" value={selectedBrand}
                    onChange={e => setSelectedBrand(e.target.value.trim())}
                    placeholder="品牌名称（可留空让模型推断）" />
                  <label className="cwb-ref-upload" title="导入品牌 Logo 文件">
                    <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={onBrandLogo} disabled={brandUploading} />
                    <span>{brandUploading ? '上传中…' : (brandLogo ? '更换Logo' : '导入Logo')}</span>
                  </label>
                  {brandLogo && <button className="cwb-ref-clear" onClick={clearBrandLogo}>移除</button>}
                </div>
                {brandLogo && (
                  <div className="cwb-brand-logo-preview">
                    <img src={api.mediaFileDownloadUrl(brandLogo)} alt={brandLogoName} title={brandLogoName} />
                    <label className="cwb-inject-toggle" title="勾选后将品牌 Logo 融入图片 / 视频素材">
                      <input type="checkbox" checked={injectLogo} onChange={e => setInjectLogo(e.target.checked)} />
                      <span>注入生成链路（将 Logo 融入图片/视频素材）</span>
                    </label>
                  </div>
                )}
              </div>
            </div>
            <div className="cwb-input-foot">
              <label className="cwb-demo-toggle" title="开启后返回样例数据（标注为演示，非真实分析）">
                <input type="checkbox" checked={demoMode} onChange={e => setDemoMode(e.target.checked)} />
                <span>演示模式</span>
              </label>
              <button className="cwb-start" onClick={analyze} disabled={running}>
                {running ? '分析中…' : (cw ? '重新分析 →' : '开始分析 →')}
              </button>
            </div>
            {/* V4.70：已移除「更多选项 / 复用产品·参考图·品牌 / 历史 / 新建项目」；演示模式上移至此处，复用沉淀改为后台自动 */}
          </div>

          {/* ③ 工作流处理模块：流程步骤 + 进度 + 结果（突出当前进度与待处理内容） */}
          <div className="cwb-workflow">
            <div className="cwb-wf-head">
              <b>创作流程</b>
              <span className={`cwb-wf-status ${view === 'result' ? 'ok' : (view === 'analyzing' || view === 'generating' ? 'run' : '')}`}>{wfStatus}</span>
            </div>
            <div className="cwb-wf-steps">
              {STEPS.map(s => {
                const st = wf[s.n]
                return (
                  <div className={`cwb-wf-step ${st}`} key={s.n}>
                    <div className="cwb-wf-dot">{st === 'done' ? '✓' : s.n}</div>
                    <div className="cwb-wf-txt">
                      <b>{s.label}</b>
                      <small>{s.sub}</small>
                      <span className="cwb-wf-tag">{st === 'done' ? '已完成' : st === 'cur' ? '进行中' : '待处理'}</span>
                    </div>
                  </div>
                )
              })}
            </div>
            {(view === 'analyzing' || view === 'generating') && (
              <>
                <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
                <div className="cwb-bar-txt">{progressText}</div>
              </>
            )}
            {view === 'result' && assets.length > 0 && (
              <div className="cwb-wf-result">✓ 已生成 {assets.length} 份素材，通过平台合规预检</div>
            )}
          </div>

          {/* 第二步：规划创意——图片创意（路线 + 补充指令）与视频创意（对话规划）分别输入 */}
          <section className="cwb-section">
            {cw && view !== 'analyzing' && (
              <>
                {materialType !== 'video' && (
                  <div className="cwb-plan-block">
                    <div className="cwb-sub-row">
                      <h3 className="cwb-sub">图片创意规划（{routes.length} 条路线）</h3>
                      <span className="cwb-tag-reco">基于网站分析</span>
                    </div>
                    <p className="cwb-reco-note">已按 {selectedPlatform || '所选媒体'} 的素材规格自动适配，勾选要生成的路线</p>
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
                    <div className="cwb-supplement">
                      <label className="cwb-field-label">补充创意指令（可选）</label>
                      <textarea className="cwb-supplement-input" placeholder="例如：强调续航卖点、采用生活方式叙事、突出价格优势…"
                        value={vs.options.prompt_hint || ''}
                        onChange={e => setVs(s => ({ ...s, options: { ...s.options, prompt_hint: e.target.value } }))} />
                    </div>
                  </div>
                )}

                {materialType !== 'image' && (
                  <div className="cwb-plan-block">
                    <VideoStudio mode="plan" analysis={cw?.analysis} platform={selectedPlatform}
                      referenceImage={referenceImage} brandLogo={brandLogo} injectLogo={injectLogo}
                      state={vs} setState={setVs} />
                  </div>
                )}

                <div className="cwb-confirm">
                  <button className="cwb-gen-btn" onClick={batchGenerate}
                    disabled={!((materialType !== 'image' || routes.some(r => r.selected)) && (materialType !== 'video' || (vs.plan && vs.plan.shots?.length)))}>
                    确认并批量生成
                  </button>
                </div>
              </>
            )}
            {!cw && view !== 'analyzing' && (
              <div className="cwb-drawer-empty">
                <div className="cwb-empty-ic"><span className="spark" /></div>
                <p>输入产品链接并选择媒体平台，点击「开始分析」后，这里将展示产品分析与创意路线。</p>
              </div>
            )}
          </section>

          {/* ④ 生成成果：展示在「创意路线」下方（图片 / 视频 + 尺寸规格 + 文案内容） */}
          {/* 第三步：批量生成——图片与视频两个工作区，仅展示生成进度与结果（不暴露内部流程细节） */}
          <section className="cwb-results">
            <div className="cwb-results-head">
              <div className="cwb-results-title">
                <h3 className="cwb-sub">批量生成工作区</h3>
              </div>
              {assets.length > 0 && materialType !== 'video' && (
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

            {/* 图片工作区：基于网站分析 + 媒体平台规格生成，保持原有素材展示样式 */}
            {materialType !== 'video' && (
              <div className="cwb-work-area">
                <div className="cwb-work-area-head">
                  <h4 className="cwb-area-title">🖼️ 图片素材工作区</h4>
                  {view === 'generating' && <span className="cwb-area-status">{progressText || '图片生成中…'}</span>}
                  {view === 'result' && assets.length > 0 && <span className="cwb-area-status ok">已生成 {assets.length} 份</span>}
                </div>
                {view === 'generating' && (
                  <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
                )}

                {Object.keys(copiesByPlatform).length > 0 && (
                  <div className="cwb-copy-section">
                    <div className="cwb-sub-row">
                      <h3 className="cwb-sub">广告文案</h3>
                      <button className="cwb-link-btn" onClick={downloadAllCopy}>下载全部文案（JSON）</button>
                    </div>
                    {Object.entries(copiesByPlatform).map(([p, c]) => (
                      <div className="cwb-copy-platform" key={p}>
                        <div className="cwb-copy-pl">
                          <b>{p}</b>
                          {c.model_info?.provider && (
                            <span className="cwb-copy-model">{c.model_info.provider}/{c.model_info.model}</span>
                          )}
                          <button className="cwb-link-btn sm" onClick={() => downloadCopy(p)}>下载 {p}</button>
                        </div>
                        <div className="cwb-copy-fields">
                          {Object.entries(c.fields || {}).filter(([, v]) => v != null && v !== '').map(([k, v]) => (
                            <div className="cwb-copy-field" key={k}>
                              <span className="cwb-copy-k">{k}</span>
                              <span className="cwb-copy-v">{Array.isArray(v) ? (v as any[]).filter(Boolean).join(' / ') : String(v)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
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
                  {assets.length === 0 && view === 'generating' && (
                    <div className="cwb-results-empty">正在生成图片素材，请稍候…</div>
                  )}
                </div>

                {jobs.some(j => j.status === 'failed') && view === 'result' && (
                  <div className="err" style={{ marginTop: 10 }}>部分图片任务生成失败，请调整媒体或重试。</div>
                )}
              </div>
            )}

            {/* 视频工作区：基于网站分析 + 媒体平台规则 + 视频参数生成，并支持生成后微调 */}
            {materialType !== 'image' && (
              <div className="cwb-work-area">
                <VideoStudio mode="work" analysis={cw?.analysis} platform={selectedPlatform}
                  referenceImage={referenceImage} brandLogo={brandLogo} injectLogo={injectLogo}
                  state={vs} setState={setVs} />
              </div>
            )}

            {view === 'result' && (assets.length > 0 || vs.videos.length > 0) && (
              <div className="cwb-confirm">
                <button className="cwb-link-btn" onClick={resetAll}>新的创作</button>
                <button className="cwb-gen-btn sm" onClick={downloadAll}>导出交付包</button>
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
                  {(() => { const s: any = cw?.snapshot || {}; if (!s.source) return null; return (
                    <span className={`cwb-src-pill src-${s.source}`}>{srcLabel(s.source)}</span>
                  )})()}
                </div>
                {/* 产品摘要 + 来源徽标（从正文移入，分析结果统一展示在右侧面板） */}
                <p className="cwb-brief-summary">{cw.summary || '（暂无分析摘要）'}</p>
                {renderSrcBadges()}
                <div className="cwb-boxes cwb-boxes-sm">
                  {[['行业', briefBoxes.industry], ['核心人群', briefBoxes.coreAudience],
                    ['购买动机', briefBoxes.purchaseMotivation], ['价格带', briefBoxes.priceBand]].map(([k, v]) => (
                    <div className="cwb-box" key={k as string}><span>{k as string}</span><b>{v || '—'}</b></div>
                  ))}
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

      {/* V4.70：历史弹窗已移除（历史 / 新建项目功能已取消） */}

      {toast && <div className="cwb-toast">{toast}</div>}
    </div>
  )
}
