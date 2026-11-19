import React, { useEffect, useRef, useState } from 'react'
import { api, getToken, type CreativeBrief, type CreativeIntent } from '../api'
import VideoStudio, { VideoState } from './VideoStudio'
import { cwTaskBegin, cwTaskDismiss, cwTaskEnd, cwTaskReset, cwTaskUpdate, getCwTask, type CwStageStatus, type CwTaskStage } from '../cwTask'
import CreativeTasksDrawer from '../CreativeTasksDrawer'
import { useCreativeTasks } from '../useCreativeTasks'

type Route = {
  key: string
  name: string
  description: string
  tags: string[]
  angle: string
  selected: boolean
  framework?: string
  framework_label?: string
  hook?: string
  proof?: string
  visual_hook?: string
  cta_role?: string
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

// V4.101：框架目录未加载时的兜底，仅用于下拉展示；权威来源仍是 /api/creative-frameworks
const FRAMEWORK_FALLBACK = [
  { key: 'aida', label: 'AIDA · 注意→兴趣→欲望→行动' },
  { key: 'pas', label: 'PAS · 痛点→放大→解决' },
  { key: 'bab', label: 'BAB · 现状→理想→桥梁' },
  { key: 'hso', label: 'HSO · 钩子→故事→优惠' },
  { key: '4p', label: '4P · 承诺→画面→证明→推动' },
  { key: 'contrast_proof', label: '对比证明 · 差异→验证→结论' },
  { key: 'scene', label: '场景代入 · 时刻→动作→融入' },
  { key: 'social_proof', label: '社会认同 · 群体→口碑→归因' },
  { key: 'scarcity', label: '稀缺紧迫 · 时机→窗口→行动' },
]

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

/* V4.95：文案展示对齐媒体后台文案面板（截图样式）。
   字段标题按媒体平台的 schema 定义（如 Meta：正文 / 广告标题 / 描述 / CTA 按钮），
   每个字段一个独立描边输入框；字数统计按字段 key 精确匹配，兼容旧数据按 label 匹配。 */
function CopyFieldCards({ c }: { c: any }) {
  const schema: any[] = c.schema || []
  const fields = c.fields || {}
  const charRows: any[] = c.char_table || []
  const labelMap: Record<string, string> = {}
  const maxMap: Record<string, number> = {}
  for (const s of schema) { labelMap[s.key] = s.label; if (s.max) maxMap[s.key] = Number(s.max) }
  // 按 schema 顺序展示，保证 Meta 依次是 正文 → 广告标题 → 描述 → CTA
  const keys = schema.map(s => s.key).filter(k => fields[k] != null && String(fields[k]).trim() !== '')
  for (const k of Object.keys(fields)) {
    if (!keys.includes(k) && fields[k] != null && String(fields[k]).trim() !== '') keys.push(k)
  }
  return (
    <div className="cwb-copy-cards">
      {keys.map(k => {
        const v = fields[k]
        const vals = Array.isArray(v) ? v.filter(Boolean).map(String) : [String(v)]
        const rows = charRows.filter(r => r.key === k || (!r.key && r.field === (labelMap[k] || k)))
        const len = rows.length ? Math.max(...rows.map(r => Number(r.len) || 0)) : 0
        const max = rows.length ? (Number(rows[0].max) || maxMap[k] || 0) : (maxMap[k] || 0)
        const over = rows.some(r => r.over) || (max > 0 && len > max)
        const label = labelMap[k] || k
        const hint = max > 0
          ? `${label}：最多 ${max} 字符，当前 ${len} 字符（按 ${c.ad_product || '媒体平台'} 文案规则）`
          : `${label}：按 ${c.ad_product || '媒体平台'} 文案规则生成`
        return (
          <div className="cwb-copy-card" key={k}>
            <div className="cwb-copy-card-label">
              <b>{label}</b>
              <span className="cwb-copy-info" title={hint} aria-label={hint}>ⓘ</span>
              {max > 0 && <span className={`cwb-copy-card-count ${over ? 'over' : ''}`}>{len}/{max}</span>}
            </div>
            <div className={`cwb-copy-card-box ${over ? 'over' : ''}`}>
              {vals.map((s, i) => <div className="cwb-copy-card-val" key={i}>{s}</div>)}
            </div>
          </div>
        )
      })}
    </div>
  )
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

/* V4.83 / C06：浏览器只存「我在看哪一个草稿 / 批次」的引用，不存任务事实。
   换账号（token 变）自动丢弃；跨账号不串任务。服务端任务始终按 batch_id 查。 */
const CW_SESSION_KEY = 'admb_cw_session_v1'
function newDraftId() { return 'd_' + Math.random().toString(36).slice(2, 10) }
function restoreCwSession(): { draftId: string; pendingBatch: string; submittedBatch: string } {
  const fresh = { draftId: newDraftId(), pendingBatch: '', submittedBatch: '' }
  try {
    const raw = sessionStorage.getItem(CW_SESSION_KEY)
    if (!raw) return fresh
    const s = JSON.parse(raw) || {}
    const acct = String(getToken() || '').slice(0, 40)
    if (s.account && acct && s.account !== acct) return fresh
    return {
      draftId: s.draftId || fresh.draftId,
      pendingBatch: s.pendingBatch || '',
      submittedBatch: s.submittedBatch || s.pendingBatch || '',
    }
  } catch { return fresh }
}
function saveCwSession(s: { draftId: string; pendingBatch: string; submittedBatch: string }) {
  try {
    sessionStorage.setItem(CW_SESSION_KEY, JSON.stringify({ ...s, account: String(getToken() || '').slice(0, 40) }))
  } catch { /* 隐私模式：刷新恢复降级为不可用，不影响本轮生成 */ }
}
/** 从 /files/xxx 或外链取纯文件名（导出 ZIP 用，防目录穿越由后端再做一次） */
function fileOf(a: any): string {
  const u = String(a?.url || a?.file || a?.path || '')
  try {
    if (/^https?:\/\//i.test(u)) return decodeURIComponent(new URL(u).pathname.split('/').pop() || '')
  } catch { /* 退回字符串切分 */ }
  return u.split('?')[0].split('/').pop() || ''
}
function fmtBytes(n: number): string {
  if (!n || n <= 0) return ''
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(n % (1024 ** 3) ? 1 : 0)} GB`
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(n % (1024 ** 2) ? 1 : 0)} MB`
  return `${Math.round(n / 1024)} KB`
}
function specOf(img: any): { dim: string; ratio: string; fmt: string } {
  const w = Number(img?.w) || (img?.size ? parseInt(String(img.size).split('x')[0]) : 0)
  const h = Number(img?.h) || (img?.size ? parseInt(String(img.size).split('x')[1]) : 0)
  const ratio = aspectOf(img)
  // V4.103 / 方案H：优先展示标准库登记的真实格式与容量，不再硬编码 JPG/PNG ≤30MB。
  const sl = img?.meta?.spec_library || img?.spec_library || null
  const formats: string[] = Array.isArray(sl?.formats) ? sl.formats : []
  const maxBytes: number = Number(sl?.max_bytes) || 0
  const registered = !!sl && (sl.verification in { A: 1, B: 1, C: 1 })
  const fmt = registered
    ? `${(formats.length ? formats.join(' / ') : '格式待核验')}${maxBytes ? ` · ≤ ${fmtBytes(maxBytes)}` : ''}`
    : 'JPG / PNG · ≤ 30 MB（标准库未登记，待核验）'
  if (w && h) return { dim: `${w} × ${h} px`, ratio, fmt }
  if (img?.size) return { dim: `${img.size.replace('x', ' × ')} px`, ratio, fmt }
  return { dim: '自适应', ratio, fmt }
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
  // V4.106 / 方案D：参考图角色（风格参考 / 商品保真）+ 投放授权确认
  const [refRole, setRefRole] = useState<'style_reference' | 'product_reference'>('style_reference')
  const [refAuthorized, setRefAuthorized] = useState(false)
  const [referenceName, setReferenceName] = useState('')     // 参考图展示名
  const [refUploading, setRefUploading] = useState(false)   // 参考图上传/下载中
  // V4.61 / B4：品牌名（注入文案生成）
  const [selectedBrand, setSelectedBrand] = useState('')

  // V4.92：素材类型多选（文案 / 图片 / 视频），可任意组合；控制 Step2 规划与 Step3 工作区显隐与生成范围。
  // 默认沿用原 both 行为（图片 + 视频），文案需用户主动勾选后才会生成。
  type MaterialKind = 'copy' | 'image' | 'video'
  const [materialTypes, setMaterialTypes] = useState<MaterialKind[]>(['image', 'video'])
  const [mtOpen, setMtOpen] = useState(false)   // 多选下拉展开状态
  // V4.99：点击下拉外部 / Esc 收起选项；多选时保持展开，选完点空白处即关闭。
  const mtRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!mtOpen) return
    const closeOnOutside = (e: MouseEvent | TouchEvent) => {
      if (mtRef.current && !mtRef.current.contains(e.target as Node)) setMtOpen(false)
    }
    const closeOnEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMtOpen(false) }
    document.addEventListener('mousedown', closeOnOutside)
    document.addEventListener('touchstart', closeOnOutside)
    document.addEventListener('keydown', closeOnEsc)
    return () => {
      document.removeEventListener('mousedown', closeOnOutside)
      document.removeEventListener('touchstart', closeOnOutside)
      document.removeEventListener('keydown', closeOnEsc)
    }
  }, [mtOpen])
  const hasCopy = materialTypes.includes('copy')
  const hasImage = materialTypes.includes('image')
  const hasVideo = materialTypes.includes('video')
  function toggleMaterial(k: MaterialKind) {
    setMaterialTypes(prev => {
      if (prev.includes(k)) {
        // 至少保留一种素材类型，避免空提交
        if (prev.length === 1) return prev
        return prev.filter(x => x !== k)
      }
      const order: MaterialKind[] = ['copy', 'image', 'video']
      return order.filter(x => prev.includes(x) || x === k)
    })
  }
  const materialLabel: Record<MaterialKind, string> = { copy: '文案', image: '图片', video: '视频' }
  // V4.70：品牌 Logo 注入生成链路开关（勾选→作为 brand_logo 传入图片/视频生成）
  const [injectLogo, setInjectLogo] = useState(false)

  const [view, setView] = useState<'input' | 'analyzing' | 'plan' | 'generating' | 'result'>('input')
  const [progressPct, setProgressPct] = useState(0)   // 图片工作区聚合进度
  const [progressText, setProgressText] = useState('')

  const [cw, setCw] = useState<any>(null)        // 设计对齐的产品分析（4 盒 + 简报）
  const [landing, setLanding] = useState<any>(null) // 生成后端所需的 LandingAnalysis
  const [planId, setPlanId] = useState<number | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  // V4.96：图片专用补充创意指令（原绑定 vs.options.prompt_hint 属视频状态，图片链路读不到）
  const [imageSupplement, setImageSupplement] = useState('')
  // V4.105 / 方案C：分析前先确认创作要求——一句话 + 解析后的结构化意图（受众/目标/核心价值/场景/风格/禁止项）
  const [intentText, setIntentText] = useState('')
  const [intent, setIntent] = useState<CreativeIntent | null>(null)
  const [intentSummary, setIntentSummary] = useState('')
  const [intentNotes, setIntentNotes] = useState<string[]>([])
  const [intentConflicts, setIntentConflicts] = useState<string[]>([])
  const [intentParsing, setIntentParsing] = useState(false)
  // V4.105 / 方案C：路线卡就地改一句推荐描述（只改这一条）
  const [editingRoute, setEditingRoute] = useState<{ key: string; text: string; saving?: boolean } | null>(null)
  // V4.101 / P4：三类素材共用的用户提示词补全确认流程
  const [creativeBriefInput, setCreativeBriefInput] = useState('')
  const [creativeBriefFramework, setCreativeBriefFramework] = useState('aida')
  const [creativeBriefDraft, setCreativeBriefDraft] = useState<CreativeBrief | null>(null)
  const [creativeBriefConfirmed, setCreativeBriefConfirmed] = useState(false)
  const [copyVariant, setCopyVariant] = useState(0)
  const copyVariantRef = useRef(0)
  const [creativeFrameworks, setCreativeFrameworks] = useState<Array<{ key: string; label: string; desc: string; requires_evidence: boolean }>>([])
  const [rerouting, setRerouting] = useState(false)
  const [rerouteNote, setRerouteNote] = useState('')
  const [analysisValid, setAnalysisValid] = useState(false)  // V4.70 自检 5.1：分析框架完整性

  const [assets, setAssets] = useState<any[]>([])
  // V4.107 / 方案F：图片结果按 asset_id 从批次详情回填，并按「请求 / 合格 / 待处理」如实计数
  const [imgTally, setImgTally] = useState<{ requested: number; ok: number; failed: number
    pending: number; issues: Array<{ size?: string; status?: string; reason?: string }> } | null>(null)
  const [imgPendingNote, setImgPendingNote] = useState('')
  const [jobs, setJobs] = useState<JobState[]>([])   // 内部用于进度与归档，UI 仅展示聚合进度
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [historyId, setHistoryId] = useState<number | null>(null)

  const [toast, setToast] = useState<string | null>(null)

  /* V4.81 / P3：多任务会话
     - draftId：草稿标识，新建创作只换草稿，不动任何已有任务与结果；
     - pendingBatch：本次提交的视频批次，服务端跑完后按 batch_id 回写结果（旧任务不会污染新草稿）；
     - drawerOpen：任务抽屉开关（任务事实在服务端，见 useCreativeTasks）。 */
  const [draftId, setDraftId] = useState(() => restoreCwSession().draftId)
  const [pendingBatch, setPendingBatch] = useState(() => restoreCwSession().pendingBatch)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [submittedBatch, setSubmittedBatch] = useState(() => restoreCwSession().submittedBatch)
  // V4.83：只记录「已应用过的服务端快照指纹」，相同快照不重复 setState；
  // 快照变化（继续查询从失败转成功、重试出新 attempt）必须重新回填。
  const appliedRef = useRef('')
  const [syncNote, setSyncNote] = useState('')
  const submitKeyRef = useRef<{ sig: string; key: string }>({ sig: '', key: '' })
  const tasks = useCreativeTasks(true)

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
    note: '', modelInfo: null, videoModel: null, outputAspect: '', planning: false, generating: false, error: '', refineInput: '',
  })

  // V4.101：框架目录一次加载，失败时 UI 仍有内置兜底列表。
  useEffect(() => {
    api.creativeFrameworks().then((d: any) => setCreativeFrameworks(d?.frameworks || [])).catch(() => {})
  }, [])

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

  // V4.81：支持 ?tasks=1 直接打开任务抽屉（可做书签 / 从通知里跳回来）
  useEffect(() => {
    try {
      const q = new URLSearchParams(window.location.search)
      if (q.get('tasks') === '1') setDrawerOpen(true)
    } catch { /* 忽略 */ }
  }, [])

  /* V4.83 / C01+C03：按 batch_id 持续订阅服务端任务快照，直到用户新建创作 / 离开页面。
     - 不再「回填一次就清 pending」：从失败续查成功、重试出新 attempt 都会重新应用；
     - 详情读取失败只显示「状态暂未同步」，保留关联并下一轮重试，不把 null 当无任务；
     - 同一 retry 链只展示当前 attempt，多个目标视频全部展示，不再只取第一个子任务。 */
  useEffect(() => {
    if (!pendingBatch) return
    let alive = true
    let timer: number | undefined
    const myDraft = draftId
    const apply = async (first: boolean) => {
      const d = await tasks.detail(pendingBatch)
      if (!alive) return
      if (!d) {
        setSyncNote('状态暂未同步，正在重试读取')
        timer = window.setTimeout(() => { void apply(false) }, 3000)
        return
      }
      setSyncNote('')
      // 草稿已切换：旧批次继续在抽屉里跑，但不能污染当前空白草稿
      if (d.draft_id && myDraft && d.draft_id !== myDraft) return
      const all: any[] = (d.subtasks || []).filter((s: any) => s.kind === 'video')
      const byChain = new Map<string, any>()
      for (const s of all) {
        const chain = String(s.retry_of || s.job_id || Math.random())
        const prev = byChain.get(chain)
        if (!prev || Number(s.attempts || 0) > Number(prev.attempts || 0)
          || String(s.created_at || '') > String(prev.created_at || '')) byChain.set(chain, s)
      }
      const current = [...byChain.values()].filter(s =>
        (s.assets || []).length || s.status === 'succeeded' || !!s.error_code)
      const fp = JSON.stringify(current.map(s => [
        s.job_id, s.status, s.attempts, (s.assets || []).map((a: any) => a.url),
        s.error_code, s.error_message, s.duration_sec, s.delivery_status,
      ]))
      if (fp && fp !== appliedRef.current) {
        const hadApplied = !!appliedRef.current
        appliedRef.current = fp
        const vids = current.flatMap(s => (s.assets || []).filter((a: any) => a.url).map((a: any) => ({
          type: 'video', url: a.url, caption: a.caption || '',
          duration_sec: a.duration_sec ?? s.duration_sec ?? 0,
          duration_source: a.duration_source || s.duration_source || '',
          delivery_status: s.delivery_status || '', file: fileOf(a),
          // V4.94：播放层叠加配置随任务下发，画面本身保持零文字
          text_overlay: s.text_overlay || {},
          // V4.94：成片视觉复核结论（violation / unavailable 如实展示）
          vision_audit: s.vision_audit || {},
        })))
        const failed = current.filter(s => !!s.error_code)
        const fail = failed.length ? {
          code: failed[0].error_code, message: failed[0].error_message || '',
          action: failed[0].error_action || '', stage: failed[0].error_stage || '',
          taskId: failed[0].provider_task_id || '', evidence: null,
        } : null
        setVs(s => ({
          ...s, videos: vids, generating: false,
          note: current.map(s => s.note).filter(Boolean).join('；'), videoFail: fail,
        }))
        if (!hadApplied && vids.length) showToast(`视频已生成 ${vids.length} 个（可在结果区预览下载）`)
        else if (!hadApplied && fail) showToast(`视频未出片（${fail.code}）—— 点顶部「任务」查看原因与处理建议`)
      }
      // V4.107 / 方案F：图片子任务同样从批次详情回填（按 asset_id 去重），
      // 超过轮询窗口、刷新页面、短断网后仍能展示已产出的素材与逐尺寸原因。
      const imgSubs: any[] = (d.subtasks || []).filter((s: any) => s.kind === 'images')
      if (imgSubs.length) {
        const arrived = imgSubs.flatMap((s: any) => (s.assets || []).filter((a: any) => a.url)
          .map((a: any) => ({
            file: fileOf(a), url: a.url, size: a.size || '', placement: a.caption || '',
            __platform: a.caption || '', __fromBatch: true,
          })))
        if (arrived.length) {
          setAssets(prev => {
            const seen = new Set(prev.map((x: any) => String(x.file || x.url || '')))
            const add = arrived.filter((a: any) => !seen.has(String(a.file || a.url || '')))
            return add.length ? [...prev, ...add] : prev
          })
        }
        const t = imgSubs.reduce((acc: any, s: any) => {
          const tt = s.tally || {}
          acc.requested += Number(tt.requested || 0)
          acc.ok += Number(tt.ok || 0)
          acc.failed += Number(tt.failed || 0)
          acc.pending += Number(tt.pending || 0)
          for (const i of (tt.issues || [])) acc.issues.push(i)
          if (!tt.requested && ['queued', 'running', 'submitted', 'processing'].includes(String(s.status || ''))) acc.pending += 1
          return acc
        }, { requested: 0, ok: 0, failed: 0, pending: 0, issues: [] as any[] })
        setImgTally(t)
        // 超时 / 刷新后仍在跑：明确「仍在处理中」，不判失败
        setImgPendingNote(t.pending > 0 ? `仍有 ${t.pending} 张在后台处理中，可稍后在「任务」里查看，不会计为失败` : '')
      }
      // 保持 pendingBatch：刷新后仍按 ID 追踪；终态也维持低频轮询以反映抽屉里的继续查询 / 重新生成。
      timer = window.setTimeout(() => { void apply(false) }, first ? 2500 : 5000)
    }
    void apply(true)
    return () => { alive = false; if (timer) window.clearTimeout(timer) }
  }, [pendingBatch, draftId, tasks.detail])

  /* V4.77 素材创作任务常驻：把「批量生成」的实时进度同步到全局任务栏。
     切换菜单时工作台只是隐藏不卸载（见 App.tsx），请求与状态都在；
     这里再把进度写进 cwTask 存储，用户在其他页面也能看到任务跑到哪一步。 */
  useEffect(() => {
    if (view !== 'generating' && view !== 'result') return
    const imgTotal = jobs.length
    const imgDone = jobs.filter(j => ['succeeded', 'partial_success', 'done'].includes(j.status)).length
    const imgFailed = jobs.filter(j => ['failed', 'canceled'].includes(j.status)).length
    const vidRunning = !!vs.generating
    const vidCount = (vs.videos || []).length

    const stages: CwTaskStage[] = []
    // V4.92：文案阶段（同步模型调用，随任务开始即视为完成）
    if (hasCopy) {
      const copyCount = Object.keys(copiesByPlatform).length
      stages.push({
        key: 'copy',
        label: copyCount > 0 ? `创意文案（${copyCount} 个平台）` : '创意文案',
        status: copyCount > 0 ? 'done' : (view === 'generating' ? 'running' : 'pending'),
      })
    }
    if (hasImage) {
      const st: CwStageStatus = imgTotal === 0
        ? 'running'
        : (imgDone + imgFailed >= imgTotal ? (imgDone > 0 ? 'done' : 'failed') : 'running')
      stages.push({
        key: 'image',
        label: `推广图片（${imgDone}/${imgTotal || 0}）`,
        status: st,
        note: imgFailed ? `${imgFailed} 个任务失败` : '',
      })
    }
    if (hasVideo) {
      stages.push({
        key: 'video',
        label: vidCount > 0 ? `视频成片（${vidCount} 个）` : '视频成片',
        status: vidCount > 0 && !vidRunning ? 'done' : (vidRunning ? 'running' : 'pending'),
      })
    }

    const payload = {
      progress: progressPct,
      statusText: progressText || '正在生成素材…',
      product: String((cw as any)?.title || (cw as any)?.analysis?.product || '').slice(0, 48),
      platforms: selected.slice(0, 3),
      kind: (hasCopy ? (hasImage || hasVideo ? 'mixed' : 'copy')
        : (hasImage && hasVideo ? 'both' : (hasVideo ? 'video' : 'image'))) as 'image' | 'video' | 'copy' | 'both' | 'mixed',
      stages,
      imageDone: imgDone,
      imageTotal: imgTotal,
      videoDone: vidCount,
    }

    if (view === 'generating') {
      cwTaskBegin(payload)
      return
    }
    // V4.83 / C04：旧浮窗只镜像服务端快照，不再按「结果页且还没有视频」猜失败。
    // 视频批次仍排队 / 生成中时保持 running，交给后台任务抽屉给终态。
    if (getCwTask().status !== 'running') return
    const vidBatch = submittedBatch ? tasks.items.find(b => b.batch_id === submittedBatch) : null
    const vidActive = !!vidBatch && ['queued', 'running'].includes(vidBatch.status)
    if (hasVideo && vidActive) {
      cwTaskUpdate({ ...payload, statusText: '图片已出，视频在后台继续' })
      return
    }
    // V4.92：文案也是有效产出；只要任一已选类型有结果即视为完成。
    const copyCount = Object.keys(copiesByPlatform).length
    const ok = imgDone > 0 || vidCount > 0 || (hasCopy && copyCount > 0)
    cwTaskEnd(ok ? 'done' : 'failed', {
      ...payload,
      statusText: ok ? '创作完成' : '本次未生成内容',
      error: ok ? '' : (error || '本次生成未返回内容，请调整媒体或重试'),
    })
  }, [view, progressPct, progressText, jobs, materialTypes, hasCopy, hasImage, hasVideo, copiesByPlatform, vs.generating, vs.videos, assets.length, selected, cw, error, submittedBatch, tasks.items])

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
      const cwRes: any = await api.cwAnalyze({
        url: isUrl(val) ? val : '', text: isUrl(val) ? '' : val, platforms: selected, demo_mode: demoMode,
        // V4.105 / 方案C：创作要求随分析一起进入路线与三类素材
        creative_intent: intent || {}, intent_text: intentText.trim(),
      })
      setCw(cwRes); setPlanId(cwRes?.id ?? null)
      setIntent(cwRes?.intent || null)
      setIntentSummary(cwRes?.intent_summary || '')
      setIntentNotes(cwRes?.intent_notes || [])
      setIntentConflicts(cwRes?.intent_conflicts || [])
      if (intentText.trim() && !imageSupplement) setImageSupplement(intentText.trim())
      setProgressPct(46); setProgressText('47% · 正在提取核心利益点')
      // V4.58 / B2：移除二次模型调用（landingAnalysis）。cwAnalyze 已返回统一分析来源 `analysis`，
      // 路线规划与素材生成均以此为唯一依据，避免「两次模型理解」且 landing 失败被静默 catch 成空。
      // V4.96：创意工作台显式请求 10 条路线；接口默认仍为 3，保持其他调用兼容。
      const routeRes = await api.cwRoutes({ plan_id: cwRes?.id, analysis: cwRes?.analysis || {}, platforms: selected, brief: cwRes?.brief || {}, count: 10, creative_intent: (cwRes?.intent || intent || {}) as CreativeIntent }).catch(() => ({ routes: cwRes?.routes || [] }))
      // V4.96：默认不勾选，由用户按需求选择（与「每条路线各出一组」策略呼应）
      setRoutes((routeRes?.routes || cwRes?.routes || []).map((r: any) => ({ ...r, selected: false })))
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

  /** V4.92：归一化分析 + 注入品牌，供文案 / 图片 / 视频共用同一事实来源 */
  function currentAnalysis() {
    const analysis = normalizeAnalysis(cw?.analysis)
    if (selectedBrand && selectedBrand.trim()) analysis.brand = selectedBrand.trim()
    return analysis
  }

  /** V4.101：只有用户点过「确认使用」的 brief 才允许进入三类生成链路。 */
  function confirmedBrief(): CreativeBrief | null {
    if (!creativeBriefDraft || !creativeBriefConfirmed) return null
    return { ...creativeBriefDraft, confirmed: true, variation: copyVariantRef.current }
  }

  async function previewBrief() {
    if (!creativeBriefInput.trim()) { setError('请先输入你希望强调的创意方向或提示词'); return }
    setError('')
    try {
      const d = await api.previewCreativeBrief({
        raw_input: creativeBriefInput.trim(),
        analysis: currentAnalysis(),
        platform: selectedPlatform || selected[0] || '',
        framework: creativeBriefFramework,
      })
      setCreativeBriefDraft(d)
      setCreativeBriefConfirmed(false)
    } catch (e: any) {
      setError('补全提示词失败：' + (e?.message || '未知错误'))
    }
  }

  /** V4.101：换一批路线只重调规划接口，不重新抓落地页，也不触发出片费用。 */
  async function rerouteRoutes() {
    if (!cw) return
    setRerouting(true); setRerouteNote('')
    try {
      const seed = 'v' + Date.now()
      const excluded = routes.filter(r => r.selected).map(r => r.name).filter(Boolean)
      const res: any = await api.cwRoutes({
        plan_id: cw?.id ?? planId ?? undefined,
        analysis: cw?.analysis || {}, platforms: selected, brief: cw?.brief || {}, count: 10,
        framework: creativeBriefFramework,
        user_brief: confirmedBrief(), seed, exclude_names: excluded,
        creative_intent: (intent || {}) as CreativeIntent,
      })
      setRoutes((res?.routes || []).map((r: any) => ({ ...r, selected: false })))
      setRerouteNote(excluded.length ? `已排除上一批选中的 ${excluded.length} 条路线，重新规划完成` : '已重新规划一批路线')
    } catch (e: any) {
      setError('换一批路线失败：' + (e?.message || '未知错误'))
    } finally { setRerouting(false) }
  }

  /**
   * V4.105 / 方案C：分析前「确认创作要求」——先解析成结构化意图并给出变更摘要 / 冲突提示，
   * 用户看到解析结果后再点开始分析；解析本身不调用大模型，不产生费用。
   */
  async function parseIntent() {
    const text = intentText.trim()
    if (!text) { setIntentNotes([]); setIntentConflicts([]); return }
    setIntentParsing(true)
    try {
      const res = await api.cwIntentParse({ intent: intent || {}, text })
      setIntent(res.intent || null)
      setIntentSummary(res.summary || '')
      setIntentNotes([...(res.changes || []), ...(res.notes || [])])
      setIntentConflicts(res.conflicts || [])
    } catch (e: any) {
      setError('创作要求解析失败：' + (e?.message || '未知错误'))
    } finally { setIntentParsing(false) }
  }

  /** V4.105 / 方案C：路线卡就地改一句推荐描述（保存后只更新这一条，不重规划整批）。 */
  async function saveRouteEdit() {
    if (!editingRoute || !planId) return
    const text = editingRoute.text.trim()
    if (!text) { setEditingRoute(null); return }
    setEditingRoute(er => er ? { ...er, saving: true } : er)
    try {
      const res = await api.patchCwRoute(planId, editingRoute.key, { description: text })
      const next = (res?.routes || []) as Route[]
      setRoutes(rs => rs.map(r => {
        const hit = next.find(n => String(n.key) === String(r.key))
        return hit ? { ...r, ...hit, selected: r.selected } : r
      }))
      setEditingRoute(null)
      showToast('路线描述已更新，仅影响这一条路线')
    } catch (e: any) {
      setEditingRoute(er => er ? { ...er, saving: false } : er)
      setError('保存路线描述失败：' + (e?.message || '未知错误'))
    }
  }

  /**
   * V4.92：为所有选中平台生成广告文案（依据大模型 + 证据门）。
   * 抽成纯数据 helper：文案现在是独立素材类型，不再因「纯图片」叠加模式被跳过。
   * 返回 copiesByPlat（工作区展示）/ variantsByPlat（图片叠加用）/ copyFailures。
   */
  async function buildCopies(analysis: any, targets: string[]): Promise<{
    copiesByPlat: Record<string, any>; variantsByPlat: Record<string, any[]>; copyFailures: Record<string, string>
  }> {
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
      try {
        setProgressText(`正在为 ${p} 生成广告文案…`)
        const cr: any = await api.mediaCopy({ analysis, platform: p, lang: 'en', brief: confirmedBrief() }).catch(() => null)
        if (cr && cr.fields && !copyIsInvalid(cr)) {
          // V4.92：完整保留平台文案规格与校验结果——schema（字段/字数上限）、
          // char_table（逐字段实测字数 vs 上限）、validation（是否符合平台规则）、ad_product（RSA/UAC 等细分）。
          // V4.101：同时保留本次使用的创意 brief 快照，供工作区回显。
          copiesByPlat[p] = { fields: cr.fields, schema: cr.schema, char_table: cr.char_table, ad_product: cr.ad_product, brand: cr.brand, model_info: cr.model_info, validation: cr.validation, creative_brief: cr.creative_brief }
          const f = cr.fields
          variantsByPlat[p] = [{ headline: firstNonEmpty(f.headline ?? f.title), sub: pickFirstField(f.description, f.body, f.primary_text), cta: firstNonEmpty(f.cta), brand: firstNonEmpty(cr.brand), label: p }]
        } else {
          copyFailures[p] = !cr ? '文案生成失败（mediaCopy 未返回结果）' : `文案校验未通过（${cr?.validation?.status || 'invalid'}）：${cr?.validation?.message || '请调整分析或文案后重试'}`
        }
      } catch { copyFailures[p] = '文案生成发生异常' }
    }
    return { copiesByPlat, variantsByPlat, copyFailures }
  }

  /** V4.92：独立文案生成流程——「确认并批量生成」后按用户选择执行，结果写入文案工作区。 */
  async function generateCopy(analysis: any): Promise<{ okCount: number; errs: string[]; data: any }> {
    const data = await buildCopies(analysis, selected)
    setCopiesByPlatform(data.copiesByPlat)
    const brandSet = new Set<string>()
    if (selectedBrand && selectedBrand.trim()) brandSet.add(selectedBrand.trim())
    for (const p of Object.keys(data.copiesByPlat)) { const b = data.copiesByPlat[p]?.brand; if (b && String(b).trim()) brandSet.add(String(b).trim()) }
    for (const b of brandSet) { api.addCwLibrary({ kind: 'brand', title: b, meta: { platforms: Object.keys(data.copiesByPlat) } }).catch(() => {}) }
    const okCount = Object.keys(data.copiesByPlat).length
    const errs = Object.entries(data.copyFailures).map(([p, m]) => `${p}：${m}`)
    return { okCount, errs, data }
  }

  /** V4.101：对当前文案规划不满意时换一批；不重新分析落地页，只重生成文案。 */
  async function regenerateCopy() {
    if (running) return
    setRunning(true)
    setProgressText('正在换一批文案方向…')
    try {
      copyVariantRef.current += 1
      setCopyVariant(copyVariantRef.current)
      await generateCopy(currentAnalysis())
    } finally { setRunning(false) }
  }

  async function generateImages(hid: number | null, batchId = '', prebuilt?: Awaited<ReturnType<typeof buildCopies>>): Promise<{ okImages: number; anyFailed: boolean; errs: string[]; pending: number }> {
    const errs: string[] = []
    // V4.60 / B3：归一化为合法 LandingAnalysis（channels 转成 [{platform,reason}]），否则文案 / 出图端点会 422。
    const analysis = currentAnalysis()
    // V4.92：文案数据优先复用「确认并批量生成」阶段已生成的结果，避免重复调用大模型。
    const { copiesByPlat, variantsByPlat, copyFailures } = prebuilt || await buildCopies(analysis, selected)
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
    if (refPath) { api.addCwLibrary({ kind: 'reference', title: referenceName || '参考图', file: refPath, meta: { from: 'creative_workbench', role: refRole, authorized: refRole === 'product_reference' ? refAuthorized : false } }).catch(() => {}) }
    const activeRoutes = routes.filter(r => r.selected)
    const collected: any[] = []
    const finalStates: string[] = []
    const capturedErrors: string[] = []
    let pendingJobs = 0   // V4.107：轮询窗口结束仍在后台处理的任务数（不按失败计）
    const targets = selected   // V4.92：重构文案 helper 后补回，图片任务矩阵仍按选中平台生成
    const totalJobs = targets.length * Math.max(1, activeRoutes.length)
    let done = 0
    try {
      const rules: any = await api.mediaRules().catch(() => ({}))
      const allowed: Record<string, string[]> = rules?.platforms || {}
      // V4.103 / 方案H：拉取服务端标准库，按 平台+尺寸 取稳定 spec_id，交给后端精确解析。
      let specEntries: any[] = []
      try {
        const specLib: any = await api.mediaSpecLibrary()
        specEntries = Array.isArray(specLib?.entries) ? specLib.entries : []
      } catch { /* 规格库不可用时退回展示名匹配（兼容） */ }
      const specIdFor = (platform: string, size: string): string => {
        const norm = (s: string) => String(s || '').toLowerCase().replace('×', 'x').trim()
        const hit = specEntries.find((e: any) =>
          e.media === 'image' && norm(e.platform) === norm(platform)
          && (Array.isArray(e.sizes) ? e.sizes : []).some((sz: string) => norm(sz) === norm(size)))
        return hit?.spec_id || ''
      }
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
          // V4.104 / 方案B：每条路线完全独立生成——slots 携带本组路线标识，
          // 供后端把 concept_id/concept_key 绑定到该路线，不再跨路线共享概念。
          const slots = sizes.map(size => ({ size, placement: p, spec_id: specIdFor(p, size),
            route_key: route?.key || '' }))
          // V4.104 / 方案B：废弃「主干 + 其余路线做修饰」的多路线融合，
          // 每组只传当前路线一条，价值切入 / 主体 / 证据互不混用。
          const style_opts: any = {
            creative_direction: '',
            content_style: '',
            color_scheme: '',
            creative_plan: {
              routes: (route ? [route] : []).map(r => ({
                key: r.key, name: r.name, angle: r.angle,
                description: r.description, tags: r.tags || [],
                framework: r.framework || '', framework_label: r.framework_label || '',
                hook: r.hook || '', proof: r.proof || '',
                visual_hook: r.visual_hook || '', cta_role: r.cta_role || '',
              })),
              supplement: imageSupplement || '',
              platform: p,
              overlay_mode: overlayMode,
              brief: confirmedBrief(),
            },
          }
          if (refPath) {
            style_opts.reference_image = refPath
            // V4.106 / 方案D：角色与授权随请求下发；商品保真由后端在调用前做能力闸门
            style_opts.reference_role = refRole
            style_opts.reference_authorized = refRole === 'product_reference' ? refAuthorized : false
          }
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
            batch_id: batchId || undefined,   // V4.81：并入同一次「创作」批次
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
          // V4.107 / 方案F：轮询窗口结束但任务未到终态 → 只是「仍在处理中」，不判失败。
          const TERMINAL = ['succeeded', 'partial_success', 'failed', 'canceled']
          const stillRunning = !TERMINAL.includes(String(st?.status || ''))
          if (stillRunning) {
            pendingJobs++
            setJobs(j => j.map(x => x.platform === p && x.route === route
              ? { ...x, status: 'processing', error: '' } : x))
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
    // V4.107：仍在后台的任务既不算成功也不算失败，交给批次回填继续更新
    if (pendingJobs) setImgPendingNote(`仍有 ${pendingJobs} 个图片任务在后台处理中，结果会在完成后自动回填，不会计为失败`)
    return { okImages, anyFailed, errs, pending: pendingJobs }
  }

  /** V4.83 / C02：所有视频入口（批量生成 / 单独生成 / 微调）唯一提交实现。 */
  async function generateVideo(hid: number | null, batchId = '',
    override?: { plan: any; options: any; refinement?: string })
    : Promise<{ ok: boolean; fail: any; submitted?: boolean }> {
    const plan = override?.plan || vs.plan
    const options = override?.options || vs.options
    if (!plan?.shots?.length) return { ok: false, fail: null }
    const analysis = normalizeAnalysis(cw?.analysis)
    if (selectedBrand && selectedBrand.trim()) analysis.brand = selectedBrand.trim()
    setVs(s => ({ ...s, generating: true, error: '', videos: [], note: '', videoFail: null }))
    try {
      // V4.81 / P3：提交即返回，页面不再等 1–6 分钟；进度看顶部「任务」抽屉。
      // V4.83：幂等键绑定本次「草稿 + 批次 + 冻结的分镜/参数 + 是否微调」，网络重试复用同一键；
      // 真正换创意（新分镜 / 新微调）才算新的收费执行。
      const sig = JSON.stringify([draftId, batchId || submittedBatch, plan.shots,
        options?.duration, options?.aspect, options?.mode, options?.prompt_hint,
        override?.refinement || ''])
      if (submitKeyRef.current.sig !== sig) {
        submitKeyRef.current = {
          sig, key: `cwvid_${draftId}_${Math.abs(hashCode(sig)).toString(36)}_${Date.now().toString(36)}`,
        }
      }
      const job: any = await api.submitVideoJob({
        analysis, platform: selectedPlatform,
        reference_image: referenceImage || '',
        brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
        plan, options: { ...options, prompt_hint: options.prompt_hint },
      }, {
        idempotencyKey: submitKeyRef.current.key,
        draftId, batchId,
      })
      setVs(s => ({ ...s, generating: false }))
      const bid = job?.batch_id || batchId
      if (bid) {
        setPendingBatch(bid); setSubmittedBatch(bid)
        saveCwSession({ draftId, pendingBatch: bid, submittedBatch: bid })
      }
      return { ok: false, fail: null, submitted: true }
    } catch (e: any) {
      const fail = { code: 'CLIENT_ERROR', message: e?.message || '', action: '稍后重试；连续失败请展开「诊断视频配置」核对链路。' }
      setVs(s => ({ ...s, generating: false, error: '视频提交失败：' + (e?.message || ''), videoFail: fail }))
      return { ok: false, fail }
    }
  }

  /** 稳定字符串哈希：只为生成幂等键，不用于安全用途 */
  function hashCode(s: string): number {
    let h = 0
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0
    return h
  }

  /** VideoStudio 的「生成 / 微调」统一走上面的持久任务提交；界面与按钮位置不变。 */
  async function submitVideoFromStudio(payload: { plan: any; options: any; refinement?: string }): Promise<boolean> {
    if (!hasVideo) return false
    if (imgBusy) {
      setError('图片任务正在生成，请等图片完成后再提交视频')
      return false
    }
    let bid = submittedBatch
    if (!bid) {
      // 从第二步直接生成、或结果页微调：补一个批次头，让图片 / 视频 / 结果订阅仍指向同一创作。
      const bh: any = await api.createCreativeTask({
        product_name: String((cw as any)?.title || (cw as any)?.analysis?.product || '').slice(0, 120),
        source_url: String((cw as any)?.snapshot?.final_url || input || ''),
        material_types: ['video'], platforms: selected, draft_id: draftId,
      }).catch(() => null)
      bid = bh?.batch_id || ''
      if (bid) { setSubmittedBatch(bid); saveCwSession({ draftId, pendingBatch: pendingBatch || bid, submittedBatch: bid }) }
    }
    const r = await generateVideo(null, bid, payload)
    return !!r.submitted
  }

  async function batchGenerate() {
    // V4.92：素材类型多选——文案 / 图片 / 视频可任意组合，按用户选择生成对应内容。
    const doCopy = hasCopy
    const doImg = hasImage
    const doVid = hasVideo
    if (!doCopy && !doImg && !doVid) { setError('请至少选择一种素材类型（文案 / 图片 / 视频）'); return }
    if (doImg && !routes.some(r => r.selected)) { setError('请至少选择一条图片创意路线'); return }
    if (doVid && (!vs.plan || !vs.plan.shots?.length)) { setError('请先在第二步完成视频分镜规划'); return }
    // V4.101：用户自定义提示词必须先补全并确认，未确认不进入任何生成链路。
    if (creativeBriefDraft && !creativeBriefConfirmed) { setError('请先在「创意提示词方案」中确认补全后的提示词，再开始生成'); return }
    setError(''); setView('generating'); setAssets([]); setJobs([]); setChecked({}); setCopiesByPlatform({}); setProgressPct(0); setProgressText('正在创建素材任务…')
    cwTaskReset()   // V4.77：新一轮生成，任务常驻浮窗重新出现（此前手动关闭的抑制解除）
    setImgTally(null); setImgPendingNote('')   // V4.107：新一轮生成重置「请求 / 合格 / 待处理」计数
    let hid: number | null = null
    try { const h: any = await api.createCreationHistory({ analysis: cw?.analysis || {}, platform: selected[0] || '', lang: 'en' }).catch(() => null); hid = h?.id ?? null; setHistoryId(hid) } catch { /* 历史可选 */ }
    if (planId) await api.updateCreativePlan(planId, { status: 'generating', history_id: hid ?? undefined }).catch(() => {})
    // V4.81 + V4.92：先建批次头，文案 / 图片 / 视频子任务挂在同一次「创作」下
    let batchId = ''
    {
      const bh: any = await api.createCreativeTask({
        product_name: String((cw as any)?.title || (cw as any)?.analysis?.product || '').slice(0, 120),
        source_url: String((cw as any)?.snapshot?.final_url || input || ''),
        material_types: [...(doCopy ? ['copy'] : []), ...(doImg ? ['image'] : []), ...(doVid ? ['video'] : [])],
        platforms: selected,
        draft_id: draftId,
      }).catch(() => null)
      batchId = bh?.batch_id || ''
      if (batchId) {
        setSubmittedBatch(batchId)
        // V4.107 / 方案F：建批次即订阅——图片与视频都按 batch_id 从服务端回填，
        // 不再只依赖浏览器 120s 轮询窗口。
        setPendingBatch(batchId)
        saveCwSession({ draftId, pendingBatch: batchId, submittedBatch: batchId })
      }
    }
    const analysis = currentAnalysis()
    // V4.92：文案先行（用户勾选时）——依据大模型 + 证据门生成，写入文案工作区；
    // 生成结果复用给图片叠加，避免同一批重复调用文案模型。
    let copyData: Awaited<ReturnType<typeof buildCopies>> | undefined
    let copyOk = 0
    const copyErrs: string[] = []
    if (doCopy) {
      setProgressPct(8)
      const cr = await generateCopy(analysis)
      copyOk = cr.okCount; copyErrs.push(...cr.errs); copyData = cr.data
      setProgressPct(doImg ? 25 : 60)
    }
    const imgRes = doImg ? await generateImages(hid, batchId, copyData) : { okImages: 0, anyFailed: false, errs: [], pending: 0 }
    setProgressPct(70)
    const vid = doVid ? await generateVideo(hid, batchId) : { ok: true, fail: null }
    const vidOk = doVid && !!vid.ok        // 提交成功 ≠ 出片成功：成片与否只认服务端任务结果
    // V4.92：成功 = 任一已选类型有真实产出（文案成条 / 图片有图 / 视频有成片）。
    const totalOk = copyOk > 0 || imgRes.okImages > 0 || vidOk
    const vidQueued = doVid && !!vid.submitted
    setProgressPct(100)
    setProgressText(vidQueued ? '图片已出，视频在后台继续' : (totalOk ? '创作完成' : '未生成内容'))
    if (totalOk) {
      const parts: string[] = []
      if (copyOk > 0) parts.push(`文案 ${copyOk} 组`)
      if (imgRes.okImages > 0) parts.push(`图片 ${imgRes.okImages} 张`)
      showToast(vidQueued
        ? `已加入后台：${parts.join('、') || '内容已生成'}，视频在「任务」里继续生成`
        : `创作完成：${parts.join('、')}`)
      if (planId) await api.updateCreativePlan(planId, { status: 'done', asset_count: imgRes.okImages, history_id: hid ?? undefined }).catch(() => {})
      setView('result')
    } else if (vidQueued && copyOk === 0 && imgRes.okImages === 0) {
      // 只有视频且已转入后台：不是失败，是「还没出片」，交给任务抽屉呈现真实阶段
      setError('')
      setView('result')
    } else if (imgRes.pending > 0 && !copyErrs.length && !imgRes.errs.length) {
      // V4.107 / 方案F：还没出图但任务仍在后台跑 —— 不判失败，进结果区等回填
      setError('')
      setProgressText('图片仍在后台处理中，完成后会自动回填到结果区')
      setView('result')
    } else {
      const msgs = [...copyErrs, ...imgRes.errs]
      if (doVid && !vidOk && !vidQueued) {
        const f = vid.fail
        msgs.push(f ? `出片失败（${f.code}）：${f.message}`
          : '视频未提交成功（未配置视频模型，可改出分镜脚本）')
        if (f?.action) msgs.push('建议：' + f.action)
      }
      setError(msgs.join('；') || '本次生成未返回内容，请调整媒体或重试')
      setView('result')
    }
  }
  function download(file: string) { window.open(api.mediaFileDownloadUrl(file), '_blank') }
  function selectedFiles() { return assets.filter(a => checked[a.file]).map(a => a.file) }
  const selectedCount = selectedFiles().length
  function downloadSelected() {
    const f = selectedFiles(); if (f.length) window.open(api.mediaZipUrl(f, '创意工作台素材'), '_blank')
  }
  // B5 + V4.83 / C06：历史导出包含文案 / 分析 / 生成信息，并带上当前批次的视频；
  // 没有 historyId 时用素材 ZIP，图片 + 视频都在，不再遗漏只在批次里的成片。
  function downloadAll() {
    if (historyId) {
      // 横幅被点掉后 submittedBatch 会清空，但追踪引用仍在 pendingBatch——导出仍带上批次视频。
      window.open(api.historyItemZipUrl(historyId, submittedBatch || pendingBatch), '_blank')
      return
    }
    const f = [...new Set([
      ...assets.filter(a => a.file).map(a => a.file),
      ...(vs.videos || []).map(fileOf).filter(Boolean),
    ])]
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
  // V4.92：文案一键复制（优先剪贴板 API，失败回退隐藏 textarea，兼容非安全上下文）
  function copyText(text: string, okMsg = '已复制到剪贴板') {
    const fallback = () => {
      try {
        const ta = document.createElement('textarea')
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta); ta.select(); document.execCommand('copy')
        document.body.removeChild(ta); showToast(okMsg)
      } catch { showToast('复制失败，请手动选择文本复制') }
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => showToast(okMsg)).catch(fallback)
    } else fallback()
  }
  function copyCopyPlatform(p: string) {
    const c = copiesByPlatform[p]; if (!c) return
    copyText(copyToText(p, c), `${p} 文案已复制`)
  }
  function copyAllCopy() {
    const blocks = Object.entries(copiesByPlatform).map(([p, c]) => copyToText(p, c))
    if (!blocks.length) return
    copyText(blocks.join('\n\n' + '='.repeat(40) + '\n\n'), '全部文案已复制')
  }
  function toggleSelectAll() {
    if (selectedCount > 0) setChecked({})
    else setChecked(Object.fromEntries(assets.map(a => [a.file, true])))
  }
  function resetAll() {
    cwTaskDismiss()   // V4.77：重置工作台同时收起常驻任务栏
    setView('input'); setCw(null); setLanding(null); setRoutes([]); setPlanId(null); setAssets([]); setJobs([])
    setHistoryId(null); setError(''); setProgressPct(0); setChecked({}); setDemoMode(false)
    // V4.60 / B3 + B4：清空文案缓存、参考图与品牌选择
    setCopiesByPlatform({}); setReferenceImage(''); setReferenceName(''); setSelectedBrand('')
    // V4.92：清空素材类型（回到默认图片+视频）/ 视频状态 / 品牌 Logo
    setMaterialTypes(['image', 'video']); setMtOpen(false); setInjectLogo(false)
    setVs({ messages: [], plan: null, videos: [], options: {
      mode: referenceImage ? 'image_to_video' : 'text_to_video',
      voiceover: 'narration', duration: 15, aspect: '9:16', lang: 'zh', prompt_hint: '' },
      note: '', modelInfo: null, videoModel: null, outputAspect: '', planning: false, generating: false, error: '', refineInput: '' })
    setBrandLogo(''); setBrandLogoName('')
    // V4.101：清空用户提示词补全状态，避免新创作沿用上一版未确认/已确认方案
    setCreativeBriefInput(''); setCreativeBriefFramework('aida'); setCreativeBriefDraft(null)
    setCreativeBriefConfirmed(false); setCopyVariant(0); copyVariantRef.current = 0
    setRerouteNote(''); setImageSupplement('')
    setAnalysisValid(false)
  }
  /** V4.81 / P3 + V4.83：新建创作只创建空白草稿，不删除任何已有任务与结果；后台任务继续执行。 */
  function startNewCreation() {
    resetAll()
    const d = newDraftId()
    setDraftId(d)
    setPendingBatch('')
    setSubmittedBatch('')
    setSyncNote('')
    appliedRef.current = ''
    submitKeyRef.current = { sig: '', key: '' }
    saveCwSession({ draftId: d, pendingBatch: '', submittedBatch: '' })
    showToast('已开始新的创作；后台任务仍在继续，可随时点「任务」查看进度与结果')
  }
  // 图片任务仍在前端等待返回：此时重置会把在跑的图片任务与界面状态断开，因此先拦住
  const imgBusy = jobs.some(j => ['submitting', 'queued', 'running'].includes(String(j.status)))
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
      {/* ① 顶部：标题 + 一句话介绍 + 两个常驻入口（新建创作 / 任务），不新增一级导航 */}
      <div className="cwb-top">
        <div>
          <h2 className="cwb-title-only">创意工作台</h2>
          <p className="cwb-intro">输入产品链接并选择投放平台，AI 自动完成产品分析、创意规划与素材生成。</p>
        </div>
        <div className="cwb-top-actions">
          <button className="cwb-new-btn" onClick={startNewCreation} disabled={imgBusy}
            title={imgBusy ? '图片任务正在生成，完成后再开始新的创作（视频等待期间可随时新建）' : '新建一次空白创作，不会删除已有任务或结果'}>
            ＋ 新建创作
          </button>
          <button className={'cwb-task-btn' + (tasks.activeCount ? ' on' : '')}
            onClick={() => { setDrawerOpen(true); tasks.load({ silent: true }) }}
            title="查看后台创作任务：进行中 / 已完成 / 需处理">
            任务{tasks.activeCount ? ` ${tasks.activeCount}` : ''}
          </button>
        </div>
      </div>

      {/* 提交后的引导：任务在服务端继续，页面可以继续用（不是假进度，也不阻塞输入） */}
      {submittedBatch && (
        <div className="cwb-submitted">
          <span>任务已加入后台，可继续创作。图片先完成即可预览下载，视频在后台继续生成。{syncNote ? ` · ${syncNote}` : ''}</span>
          <button className="cwb-link" onClick={() => setDrawerOpen(true)}>查看任务</button>
          <button className="cwb-link" onClick={startNewCreation} disabled={imgBusy}>开始新创作</button>
          <button className="cwb-link ghost" onClick={() => setSubmittedBatch('')}>知道了</button>
        </div>
      )}

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
              {/* V4.92 素材类型：多选下拉（文案 / 图片 / 视频），可任意组合，逐一勾选 */}
              <div className="cwb-form-row">
                <label className="cwb-field-label" id="cwb-mt-label">素材类型</label>
                <div className="cwb-mt" ref={mtRef}>
                  <button type="button" id="cwb-mt" className="cwb-mt-trigger" aria-haspopup="listbox"
                    aria-expanded={mtOpen} aria-labelledby="cwb-mt-label" onClick={() => setMtOpen(o => !o)}>
                    <span className="cwb-mt-values">
                      {materialTypes.length ? materialTypes.map(k => (
                        <span className="cwb-mt-chip" key={k}>{materialLabel[k]}</span>
                      )) : <span className="cwb-mt-ph">请选择素材类型</span>}
                    </span>
                    <span className="cwb-mt-caret">{mtOpen ? '▴' : '▾'}</span>
                  </button>
                  {mtOpen && (
                    <div className="cwb-mt-menu" role="listbox" aria-multiselectable="true">
                      {(['copy', 'image', 'video'] as MaterialKind[]).map(k => (
                        <label className={`cwb-mt-option ${materialTypes.includes(k) ? 'on' : ''}`} key={k}>
                          <input type="checkbox" checked={materialTypes.includes(k)} onChange={() => toggleMaterial(k)} />
                          <span className="cwb-mt-box">{materialTypes.includes(k) ? '✓' : ''}</span>
                          <span>{materialLabel[k]}</span>
                        </label>
                      ))}
                      <div className="cwb-mt-hint">可多选；按所选择生成对应内容，点击空白处收起</div>
                    </div>
                  )}
                </div>
              </div>
              {/* 素材图片选择：下拉单选（默认 纯图片），开始分析即按此要求出图（仅勾选图片时展示） */}
              <div className="cwb-form-row" style={{ display: hasImage ? undefined : 'none' }}>
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
                  <span className="cwb-field-hint">{overlayMode === 'pure' ? '纯图片：无字、无按钮、无 Logo，满版真实场景且无预留空白' : overlayMode === 'text' ? '图片+文字：保留文案区并叠加文字' : '图片+文字+按钮：保留文案区并叠加文字与按钮'}</span>
                </div>
              </div>
              {/* 参考图（upload / URL）：仅用于学习风格与配色，不直接使用原图 */}
              {/* V4.99：说明文字必须放在控件列内，否则作为表单网格的第三个子元素会掉进 84px 标签列被折成窄条，撑高整行 */}
              <div className="cwb-form-row">
                <label className="cwb-field-label">参考图</label>
                <div className="cwb-ov-col">
                  <div className="cwb-ref-row cwb-ref-row2">
                    <label className="cwb-ref-upload" title="上传风格参考图：AI 只学习配色与画面质感，生成全新推广图，不会直接使用或合成原图">
                      <input type="file" accept="image/png,image/jpeg,image/webp" onChange={onRefFile} disabled={refUploading} />
                      <span>{refUploading ? '处理中…' : (referenceImage ? '更换图片' : '上传图片')}</span>
                    </label>
                    {referenceImage && <span className="cwb-ref-name" title={referenceImage}>{referenceName || '已上传'}</span>}
                    {referenceImage && <button className="cwb-ref-clear" onClick={() => { setReferenceImage(''); setReferenceName('') }} title="移除参考图">移除</button>}
                    <input className="cwb-ref-url" value={referenceImage.startsWith('http') ? referenceImage : ''}
                      onChange={e => { setReferenceImage(e.target.value.trim()); setReferenceName('') }}
                      placeholder="或粘贴图片 URL（自动下载）" disabled={refUploading} />
                  </div>
                  {/* V4.106 / 方案D：参考图角色。风格参考只学配色；商品参考要求按参考图保真编辑 */}
                  <div className="cwb-intent-row">
                    <select className="cwb-select cwb-ref-role" value={refRole}
                      onChange={e => setRefRole(e.target.value as 'style_reference' | 'product_reference')}>
                      <option value="style_reference">风格参考（只学配色 / 质感）</option>
                      <option value="product_reference">商品参考（保真：型号 / 颜色 / 材质 / 结构）</option>
                    </select>
                    {refRole === 'product_reference' && (
                      <label className="cwb-demo-toggle" title="商品保真必须使用创作者提供且获得投放授权的商品素材">
                        <input type="checkbox" checked={refAuthorized} onChange={e => setRefAuthorized(e.target.checked)} />
                        <span>我确认拥有该商品素材的投放授权</span>
                      </label>
                    )}
                  </div>
                  <span className="cwb-field-hint">{refRole === 'product_reference'
                    ? '商品参考：按参考图编辑，保留商品型号 / 颜色 / 材质 / 结构，只改背景与场景；需模型支持参考编辑，否则生成前会被拦截并提示补齐'
                    : '仅学习配色与画面质感，AI 生成全新画面；原图主体 / 文字 / Logo 不会出现在素材中'}</span>
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
                    <label className="cwb-inject-toggle" title="图片叠加模式会合成 Logo；视频仅作品牌主体参考，不叠加 Logo 图层">
                      <input type="checkbox" checked={injectLogo} onChange={e => setInjectLogo(e.target.checked)} />
                      <span>注入生成链路（图片叠加模式合成 Logo；视频仅作品牌主体参考）</span>
                    </label>
                  </div>
                )}
              </div>
            </div>
            {/* V4.105 / 方案C：分析前确认一次创作要求；解析结果会随分析一起进入路线与三类素材 */}
            <div className="cwb-form-row">
              <label className="cwb-field-label">创作要求</label>
              <div className="cwb-ov-col">
                <textarea className="cwb-supplement-input" maxLength={300}
                  placeholder="面向谁、重点讲什么、不要什么。例如：面向首次装修业主，不做全息，重点看清家具布局"
                  value={intentText}
                  onChange={e => setIntentText(e.target.value)} />
                <div className="cwb-intent-row">
                  <button type="button" className="cwb-link-btn" onClick={parseIntent}
                    disabled={intentParsing || !intentText.trim()}>
                    {intentParsing ? '解析中…' : '确认创作要求'}
                  </button>
                  {intentSummary && <span className="cwb-intent-chip">{intentSummary}</span>}
                </div>
                {intentNotes.length > 0 && <span className="cwb-field-hint">{intentNotes.join('；')}</span>}
                {intentConflicts.length > 0 && <span className="cwb-intent-warn">{intentConflicts.join('；')}</span>}
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
                {/* V4.101 / P4：三类素材共用的「用户输入 → 系统补全 → 查阅确认」入口 */}
                <div className="cwb-plan-block cwb-brief-block">
                  <div className="cwb-sub-row">
                    <h3 className="cwb-sub">创意提示词方案（可选 · 文案 / 图片 / 视频共用）</h3>
                    <span className="cwb-tag-reco">系统补全 · 确认后生效</span>
                  </div>
                  <p className="cwb-reco-note">输入你希望强调的方向（例如「突出真实续航，用前后对比，结尾引导了解」）。系统补全为钩子 → 证据 → CTA 的完整方案并展示，确认后才进入生成；未确认不会调用生成链路。</p>
                  <div className="cwb-brief-form">
                    <select className="cwb-brief-framework" value={creativeBriefFramework}
                      onChange={e => { setCreativeBriefFramework(e.target.value); setCreativeBriefDraft(null); setCreativeBriefConfirmed(false) }}>
                      {(creativeFrameworks.length ? creativeFrameworks : FRAMEWORK_FALLBACK).map(f => (
                        <option key={f.key} value={f.key}>{f.label}</option>
                      ))}
                    </select>
                    <input className="cwb-brief-input" value={creativeBriefInput}
                      placeholder="输入你自己的创意提示词 / 想强调的方向"
                      onChange={e => { setCreativeBriefInput(e.target.value); setCreativeBriefDraft(null); setCreativeBriefConfirmed(false) }} />
                    <button type="button" className="cwb-link-btn" onClick={previewBrief}>补全并预览</button>
                  </div>
                  {creativeBriefDraft && (
                    <div className="cwb-brief-preview">
                      <pre>{creativeBriefDraft.prompt_text}</pre>
                      {!!creativeBriefDraft.warnings?.length && (
                        <div className="cwb-brief-warnings">{creativeBriefDraft.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}</div>
                      )}
                      <div className="cwb-brief-actions">
                        <button type="button" className="cwb-link-btn"
                          onClick={() => { setCreativeBriefDraft({ ...creativeBriefDraft, confirmed: true }); setCreativeBriefConfirmed(true) }}>确认使用</button>
                        <button type="button" className="cwb-link-btn"
                          onClick={() => { setCreativeBriefDraft(null); setCreativeBriefConfirmed(false) }}>放弃</button>
                        <span className={creativeBriefConfirmed ? 'cwb-brief-ok' : 'cwb-brief-pending'}>
                          {creativeBriefConfirmed ? '已确认 · 将进入文案 / 图片 / 视频生成' : '未确认 · 不会进入生成'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
                {hasCopy && (
                  <div className="cwb-plan-block cwb-plan-copy">
                    <div className="cwb-sub-row">
                      <h3 className="cwb-sub">创意文案规划</h3>
                      <span className="cwb-tag-reco">依据大模型 + 网站分析</span>
                    </div>
                    <p className="cwb-reco-note">确认后将为所选平台（{selected.join('、') || '—'}）逐一生成广告文案，生成后可在「文案工作区」查阅与一键复制。文案中的数字与承诺均经过证据校验。</p>
                  </div>
                )}
                {hasImage && (
                  <div className="cwb-plan-block">
                    <div className="cwb-sub-row">
                      <h3 className="cwb-sub">图片创意规划（{routes.length} 条路线）</h3>
                      <span className="cwb-tag-reco">基于网站分析</span>
                    </div>
                    <div className="cwb-route-toolbar">
                      <p className="cwb-reco-note">已按 {selectedPlatform || '所选媒体'} 的素材规格自动适配，每条勾选路线各出一组图</p>
                      <div className="cwb-route-actions">
                        <span className="cwb-route-count">已选 {routes.filter(r => r.selected).length} / {routes.length}</span>
                        <button type="button" className="cwb-link-btn" onClick={rerouteRoutes} disabled={rerouting || !cw}>
                          {rerouting ? '重新规划中…' : '换一批路线'}
                        </button>
                        <button type="button" className="cwb-link-btn" onClick={() => setRoutes(rs => rs.map(r => ({ ...r, selected: true })))}>全选</button>
                        <button type="button" className="cwb-link-btn" onClick={() => setRoutes(rs => rs.map(r => ({ ...r, selected: false })))}>清空</button>
                      </div>
                    </div>
                    {rerouteNote && <p className="cwb-reroute-note">{rerouteNote}</p>}
                    {intentSummary && <p className="cwb-reroute-note">本次创作要求：{intentSummary}</p>}
                    {intentConflicts.length > 0 && <p className="cwb-intent-warn">{intentConflicts.join('；')}</p>}
                    <div className="cwb-routes">
                      {routes.map((r, i) => (
                        <div className={`cwb-route ${r.selected ? 'on' : ''}`} key={i} onClick={() => updateRoute(i, 'selected', !r.selected)}>
                          <div className="cwb-route-head">
                            <span className="cwb-route-key">{r.key || String.fromCharCode(65 + i)}</span>
                            <b>{r.name || '未命名路线'}</b>
                            <span className={`cwb-check ${r.selected ? 'on' : ''}`} />
                          </div>
                          {r.angle && <p className="cwb-route-angle">切入角度：{r.angle}</p>}
                          {editingRoute && editingRoute.key === (r.key || String.fromCharCode(65 + i)) ? (
                            <div className="cwb-route-edit" onClick={e => e.stopPropagation()}>
                              <textarea className="cwb-supplement-input" maxLength={200}
                                value={editingRoute.text}
                                onChange={e => setEditingRoute(er => er ? { ...er, text: e.target.value } : er)} />
                              <div className="cwb-intent-row">
                                <button type="button" className="cwb-link-btn" onClick={saveRouteEdit}
                                  disabled={!!editingRoute.saving || !planId}>
                                  {editingRoute.saving ? '保存中…' : '保存这一条'}
                                </button>
                                <button type="button" className="cwb-link-btn" onClick={() => setEditingRoute(null)}>取消</button>
                              </div>
                            </div>
                          ) : (
                            <p>{r.description}</p>
                          )}
                          {planId && !(editingRoute && editingRoute.key === (r.key || String.fromCharCode(65 + i))) && (
                            <button type="button" className="cwb-link-btn cwb-route-edit-btn"
                              onClick={e => { e.stopPropagation(); setEditingRoute({ key: r.key || String.fromCharCode(65 + i), text: r.description || '' }) }}>
                              改一句
                            </button>
                          )}
                          {(r.framework_label || r.hook || r.visual_hook) && (
                            <div className="cwb-route-framework">
                              {r.framework_label && <span className="cwb-rtag fw">框架：{r.framework_label}</span>}
                              {r.hook && <p>钩子：{r.hook}</p>}
                              {r.visual_hook && <p>视觉钩子：{r.visual_hook}</p>}
                              {r.proof && <p>证据表达：{r.proof}</p>}
                            </div>
                          )}
                          <div className="cwb-route-tags">
                            {(r.tags || []).map((t: string, j: number) => <span key={j} className="cwb-rtag">{t}</span>)}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="cwb-supplement">
                      <label className="cwb-field-label">补充创意指令（可选）</label>
                      <textarea className="cwb-supplement-input" maxLength={500}
                        placeholder="例如：强调续航卖点、采用生活方式叙事、突出价格优势…（仅调整构图 / 光线 / 色调 / 场景 / 镜头语言等视觉表达，不会绘制到画面中）"
                        value={imageSupplement}
                        onChange={e => setImageSupplement(e.target.value)} />
                      <p className="cwb-supplement-hint">仅作用于图片视觉表达，与所选路线合并为统一提示词规则；不生成画面文字，不编造商品事实与数字。</p>
                    </div>
                  </div>
                )}

                {hasVideo && (
                  <div className="cwb-plan-block">
                    <VideoStudio mode="plan" analysis={cw?.analysis} platform={selectedPlatform}
                      referenceImage={referenceImage} brandLogo={brandLogo} injectLogo={injectLogo}
                      creativeBrief={confirmedBrief()} framework={creativeBriefFramework}
                      state={vs} setState={setVs} />
                  </div>
                )}

                {hasVideo && (vs.plan?.generation_blocked || vs.plan?.asset_gate?.status === 'asset_missing') && (
                  <div className="cwb-plan-warn">
                    {vs.plan?.generation_blocked
                      ? `分镜中有 ${vs.plan.claim_audit?.violations?.length || 0} 处文案未通过证据校验，请回到分镜规划修改后再生成（当前提交会被拦截，不产生费用）。`
                      : vs.plan?.asset_gate?.note}
                  </div>
                )}
                {hasImage && routes.some(r => r.selected) && (
                  <p className="cwb-gen-note">本次将创建 {selected.length * routes.filter(r => r.selected).length} 个图片任务（{selected.length} 个平台 × {routes.filter(r => r.selected).length} 条路线）。</p>
                )}
                <div className="cwb-confirm">
                  <button className="cwb-gen-btn" onClick={batchGenerate}
                    disabled={materialTypes.length === 0
                      || !!(creativeBriefDraft && !creativeBriefConfirmed)
                      || (hasImage && !routes.some(r => r.selected))
                      || (hasVideo && !(vs.plan && vs.plan.shots?.length && !vs.plan.generation_blocked && vs.plan.asset_gate?.status !== 'asset_missing'))}>
                    确认并批量生成{materialTypes.length ? `（${materialTypes.map(k => materialLabel[k]).join(' + ')}）` : ''}
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
              {assets.length > 0 && hasImage && (
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

            {/* V4.92 创意文案工作区：独立、可查阅、可一键复制（文案作为一等素材类型） */}
            {hasCopy && (
              <div className="cwb-work-area cwb-copy-workspace">
                <div className="cwb-work-area-head">
                  <h4 className="cwb-area-title">✍️ 创意文案工作区</h4>
                  {view === 'generating' && <span className="cwb-area-status">{progressText || '文案生成中…'}</span>}
                  {view === 'result' && Object.keys(copiesByPlatform).length > 0 && (
                    <span className="cwb-area-status ok">已生成 {Object.keys(copiesByPlatform).length} 个平台</span>
                  )}
                  {Object.keys(copiesByPlatform).length > 0 && (
                    <div className="cwb-copy-actions">
                      <button className="cwb-link-btn sm" onClick={regenerateCopy} disabled={running}>换一批文案{copyVariant ? `（第 ${copyVariant + 1} 版）` : ''}</button>
                      <button className="cwb-link-btn sm" onClick={copyAllCopy}>复制全部</button>
                      <button className="cwb-link-btn sm" onClick={downloadAllCopy}>下载 JSON</button>
                    </div>
                  )}
                </div>
                {view === 'generating' && Object.keys(copiesByPlatform).length === 0 && (
                  <div className="cwb-results-empty">正在依据网站分析生成广告文案，请稍候…</div>
                )}
                {Object.entries(copiesByPlatform).map(([p, c]) => {
                  const specOk = c.validation?.valid !== false && c.validation?.status !== 'invalid'
                  return (
                    <div className="cwb-copy-platform" key={p}>
                      <div className="cwb-copy-pl">
                        <b>{p}</b>
                        {c.ad_product && <span className="cwb-copy-spec-tag">规格：{c.ad_product}</span>}
                        <span className={`cwb-copy-spec-badge ${specOk ? 'ok' : 'warn'}`}>
                          {specOk ? '✓ 符合平台文案规则' : '⚠ 未完全符合平台规则'}
                        </span>
                        {c.model_info?.provider && (
                          <span className="cwb-copy-model">{c.model_info.provider}/{c.model_info.model}</span>
                        )}
                        {c.creative_brief?.brief_hash && (
                          <span className="cwb-copy-spec-tag">创意 brief：{c.creative_brief.framework || '自定义'} · {c.creative_brief.brief_hash}</span>
                        )}
                        <div className="cwb-copy-actions">
                          <button className="cwb-link-btn sm" onClick={() => copyCopyPlatform(p)}>复制</button>
                          <button className="cwb-link-btn sm" onClick={() => downloadCopy(p)}>下载</button>
                        </div>
                      </div>
                      {(c.validation?.issues || []).filter((i: any) => i.level === 'error' || i.level === 'warning').slice(0, 3).map((i: any, ii: number) => (
                        <div className="cwb-copy-issue" key={ii}>{i.message}</div>
                      ))}
                      {/* V4.95：按媒体平台字段定义 + 截图样式展示 */}
                      <CopyFieldCards c={c} />
                    </div>
                  )
                })}
                {view === 'result' && Object.keys(copiesByPlatform).length === 0 && (
                  <div className="err" style={{ marginTop: 8 }}>文案未生成成功，请检查模型配置或重新生成。</div>
                )}
              </div>
            )}

            {/* 图片工作区：基于网站分析 + 媒体平台规格生成，保持原有素材展示样式 */}
            {hasImage && (
              <div className="cwb-work-area">
                <div className="cwb-work-area-head">
                  <h4 className="cwb-area-title">🖼️ 图片素材工作区</h4>
                  {view === 'generating' && <span className="cwb-area-status">{progressText || '图片生成中…'}</span>}
                  {view === 'result' && assets.length > 0 && <span className="cwb-area-status ok">已生成 {assets.length} 份</span>}
                </div>
                {view === 'generating' && (
                  <div className="cwb-bar"><div className="cwb-bar-fill" style={{ width: `${progressPct}%` }} /></div>
                )}

                {!hasCopy && Object.keys(copiesByPlatform).length > 0 && (
                  <div className="cwb-copy-section">
                    <div className="cwb-sub-row">
                      <h3 className="cwb-sub">广告文案（图片叠加用）</h3>
                      <button className="cwb-link-btn" onClick={copyAllCopy}>复制全部</button>
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
                        {/* V4.95：与文案工作区一致，按平台字段定义 + 截图样式展示 */}
                        <CopyFieldCards c={c} />
                      </div>
                    ))}
                  </div>
                )}

                {/* V4.107 / 方案F：请求 N / 合格 M / 待处理 K —— 成功数只按可用资产计 */}
                {hasImage && (imgTally || imgPendingNote) && (
                  <div className="cwb-tally">
                    {imgTally && (
                      <span className="cwb-tally-main">
                        请求 {imgTally.requested} / 合格 {imgTally.ok} / 待处理 {imgTally.pending || 0}
                        {imgTally.failed > 0 && <em className="warn"> · 待核实 {imgTally.failed}</em>}
                      </span>
                    )}
                    {imgPendingNote && <span className="cwb-tally-note">{imgPendingNote}</span>}
                  </div>
                )}
                {hasImage && imgTally && imgTally.issues.length > 0 && (
                  <div className="cwb-tally-issues">
                    {imgTally.issues.slice(0, 6).map((i, k) => (
                      <p key={k}>{i.size ? `${i.size}：` : ''}{i.reason || `未产出（${i.status || '未知'}）`}</p>
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
                            {!vid && a.quality_status === 'unverified' &&
                              <span className="cw-quality-unverified" title="视觉模型不可用或未执行，未做质量核验">质量未核验</span>}
                            {!vid && a.quality_status === 'fail' &&
                              <span className="cw-quality-fail" title="扩展质检发现明显质量问题">质量待核实</span>}
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
            {hasVideo && (
              <div className="cwb-work-area">
                <VideoStudio mode="work" analysis={cw?.analysis} platform={selectedPlatform}
                  referenceImage={referenceImage} brandLogo={brandLogo} injectLogo={injectLogo}
                  state={vs} setState={setVs} onSubmitJob={submitVideoFromStudio} />
              </div>
            )}

            {view === 'result' && (assets.length > 0 || vs.videos.length > 0 || (hasCopy && Object.keys(copiesByPlatform).length > 0)) && (
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

      {/* V4.81 / P3：任务抽屉（右侧 400px）。任务在服务端执行，关闭抽屉/切模块/刷新都不影响 */}
      <CreativeTasksDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        items={tasks.items}
        activeCount={tasks.activeCount}
        loading={tasks.loading}
        error={tasks.error}
        loadDetail={tasks.detail}
        onRetry={async (batchId, jobId, action) => {
          try {
            await tasks.retry(batchId, jobId, action)
            showToast(action === 'regenerate' ? '已重新生成（会产生一次新的模型费用）'
              : action === 'repoll' ? '已按原厂商任务号继续查询' : '已重新下载并校验')
          } catch (e: any) { showToast('操作失败：' + (e?.message || '')) }
        }}
        onCancel={async (batchId, jobId) => {
          try { await tasks.cancel(batchId, jobId); showToast('已停止后续步骤（在途任务仍可能完成并计费）') }
          catch (e: any) { showToast('操作失败：' + (e?.message || '')) }
        }}
        onReuse={(b) => {
          setDrawerOpen(false)
          const url = String(b.source_url || '')
          if (url) { setInput(url); setView('input'); showToast('已把该任务的产品链接填回输入区，可直接重新分析') }
          else showToast('该任务没有保存产品链接，请手动输入后重新分析')
        }}
      />

      {toast && <div className="cwb-toast">{toast}</div>}
    </div>
  )
}
