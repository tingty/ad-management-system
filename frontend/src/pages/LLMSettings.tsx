import { useEffect, useRef, useState } from 'react'
import { api, ModelConfig, ModelPreset, ModelTestResult, ModelHealthInfo, ModelTestAllResult } from '../api'

const USAGE_LABEL: Record<string, string> = {
  analysis: '落地页分析 / 框架',
  copy: '文案 / 关键词',
  image: '推广图片',
  video: '视频模型',
}
// 按模态决定「默认勾选」的用途范围：文本模型默认服务分析与文案；图/视频各自独立。
// 注意：下方「用途」勾选区始终展示全部四种用途（含「视频模型」），让用户在任意协议下
// 都能明确勾选「视频模型」，避免模态锁死导致无法新增视频生成模型（V4.68 修复点）。
const USAGE_BY_MODALITY: Record<string, { v: string; label: string }[]> = {
  text: [
    { v: 'analysis', label: '落地页分析 / 框架' },
    { v: 'copy', label: '文案 / 关键词' },
  ],
  image: [{ v: 'image', label: '推广图片' }],
  video: [{ v: 'video', label: '视频模型' }],
}
// 「用途」勾选区始终展示的全部可选项（多选用途：应用到哪些模块 / 功能）。
const ALL_USAGE_OPTIONS: { v: string; label: string }[] = [
  { v: 'analysis', label: '落地页分析 / 框架' },
  { v: 'copy', label: '文案 / 关键词' },
  { v: 'image', label: '推广图片' },
  { v: 'video', label: '视频模型' },
]
const PROTOCOL_LABEL: Record<string, string> = {
  openai: 'OpenAI 兼容', anthropic: 'Anthropic', gemini: 'Google Gemini',
  'openai-image': 'OpenAI 图像', 'generic-image': '通用图像', 'dashscope-maas-image': 'DashScope MaaS',
  'generic-video': '通用视频', 'keling': '可灵 Kling',
}
const MODALITY_LABEL: Record<string, string> = { text: '文本大模型', image: '文生图大模型', video: '文生视频大模型' }

// 「接口协议」选项（替代原「大模型厂商」下拉）：用户只需选择 API 类型，
// 模型版本（Model）、Key、链接均自行填写，不再强制从厂商目录里挑一个“大模型名称”。
// provider 字段直接存储协议串（openai / anthropic / gemini …），后端据此解析鉴权方式。
type ProtocolOption = {
  key: string
  name: string
  modality: 'text' | 'image' | 'video'
  default_base_url: string
  model_placeholder: string
  models: string[]
  api_key_label: string
  api_key_placeholder: string
  notes?: string
  setup_guide?: string
  extra_fields?: { key: string; label: string; placeholder?: string; hint?: string }[]
}
const PROTOCOL_OPTIONS: ProtocolOption[] = [
  { key: 'openai', name: 'OpenAI 兼容（GPT / DeepSeek / 通义 / Kimi / 本地 vLLM …）', modality: 'text',
    default_base_url: 'https://api.openai.com/v1', model_placeholder: 'gpt-4o-mini',
    models: ['gpt-4o', 'gpt-4o-mini', 'o1', 'o3-mini'], api_key_label: 'API Key', api_key_placeholder: 'sk-...',
    notes: '最通用的 OpenAI 兼容协议（/chat/completions），绝大多数第三方网关与自建服务均兼容此格式。' },
  { key: 'anthropic', name: 'Anthropic（Claude）', modality: 'text',
    default_base_url: 'https://api.anthropic.com', model_placeholder: 'claude-3-5-sonnet-latest',
    models: ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest', 'claude-3-opus-latest'],
    api_key_label: 'Anthropic API Key', api_key_placeholder: 'sk-ant-...',
    notes: '使用 Anthropic Messages API（x-api-key 头）。' },
  { key: 'gemini', name: 'Google Gemini', modality: 'text',
    default_base_url: 'https://generativelanguage.googleapis.com/v1beta', model_placeholder: 'gemini-1.5-pro',
    models: ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash'], api_key_label: 'Gemini API Key', api_key_placeholder: 'AIza...',
    notes: '请求地址需带 ?key= 参数，后端自动拼接。' },
  { key: 'openai-image', name: '文生图 · OpenAI 图像（DALL·E 3/2）', modality: 'image',
    default_base_url: 'https://api.openai.com/v1', model_placeholder: 'dall-e-3',
    models: ['dall-e-3', 'dall-e-2'], api_key_label: 'OpenAI API Key', api_key_placeholder: 'sk-...',
    notes: '标准 OpenAI 图像协议，后端自动 POST /images/generations 并裁剪到目标尺寸。' },
  { key: 'dashscope-maas-image', name: '文生图 · 阿里 DashScope（万相 / qwen-image）', modality: 'image',
    default_base_url: 'https://dashscope.aliyuncs.com/api/v1', model_placeholder: 'wanx2.1-t2i-turbo',
    models: ['wanx2.1-t2i-turbo', 'wanx2.1-t2i-plus', 'qwen-image'], api_key_label: 'DashScope API Key', api_key_placeholder: 'sk-...',
    notes: '阿里云 MaaS 多模态生成，请求体为 messages 数组，需立即下载签名 OSS 结果。' },
  { key: 'generic-image', name: '文生图 · 通用兼容（SD / 通义万相 / Replicate …）', modality: 'image',
    default_base_url: 'https://', model_placeholder: 'your-image-model',
    models: [], api_key_label: 'API Key', api_key_placeholder: 'sk-...',
    notes: '通用图像端点，POST {base_url}{endpoint}，默认 /images/generations；不同厂商路径与字段差异大，可在下方填写自定义端点。',
    extra_fields: [{ key: 'endpoint', label: '自定义端点路径（可选）', placeholder: '/images/generations 或 /sdapi/v1/txt2img', hint: '留空使用默认端点；Stable Diffusion 等需填 /sdapi/v1/txt2img。' }] },
  { key: 'generic-video', name: '文生视频 · 通用兼容', modality: 'video',
    default_base_url: 'https://', model_placeholder: 'your-video-model',
    models: [], api_key_label: 'API Key', api_key_placeholder: 'sk-...',
    notes: '通用视频端点，多数视频模型为异步任务，测试仅验证可达性与鉴权。',
    extra_fields: [{ key: 'endpoint', label: '自定义端点路径（可选）', placeholder: '/video/generations', hint: '留空使用默认端点 /video/generations。' }] },
  { key: 'keling', name: '文生视频 · 可灵 Kling（原生异步）', modality: 'video',
    default_base_url: 'https://api.klingai.com', model_placeholder: 'kling-v1',
    models: ['kling-v1', 'kling-v1-6', 'kling-v2-master'], api_key_label: '可灵 API Key（或 Access Key）', api_key_placeholder: 'sk-...',
    notes: '可灵官方 API 采用 JWT（HS256）鉴权，由下方 Access Key / Secret Key 自动签发；若留空则退化为 Bearer 网关模式（兼容 302.ai 等聚合网关）。',
    extra_fields: [
      { key: 'access_key', label: 'Access Key（JWT 鉴权，可选）', placeholder: '可灵控制台获取的 Access Key' },
      { key: 'secret_key', label: 'Secret Key（JWT 鉴权，可选）', placeholder: '可灵控制台获取的 Secret Key', hint: 'access_key + secret_key 同时填写时启用原生 JWT 鉴权，最稳定；仅填 API Key 则走聚合网关模式。' },
    ] },
]

type FormState = {
  name: string
  provider: string
  model: string
  base_url: string
  api_key: string
  is_active: boolean
  usages: string[]
  params: Record<string, string>
}

const emptyForm = (): FormState => ({
  name: '', provider: '', model: '', base_url: '', api_key: '', is_active: true, usages: ['analysis'], params: {},
})

function defaultUsagesFor(modality: string): string[] {
  return (USAGE_BY_MODALITY[modality] || USAGE_BY_MODALITY.text).map(u => u.v)
}

export default function LLMSettings() {
  const [list, setList] = useState<ModelConfig[]>([])
  const [allPresets, setAllPresets] = useState<ModelPreset[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null)

  // 「测试某个已保存配置」：直接从列表对一条已落库配置发起连通测试，无需重新填写/保存。
  const [testTarget, setTestTarget] = useState<ModelConfig | null>(null)
  const [testTargetLoading, setTestTargetLoading] = useState(false)
  const [testTargetResult, setTestTargetResult] = useState<ModelTestResult | null>(null)

  // V4.34 每日连通性健康：运行信息、手动全量测试、失败 log 查看
  const [health, setHealth] = useState<ModelHealthInfo | null>(null)
  const [testAllLoading, setTestAllLoading] = useState(false)
  const [testAllResult, setTestAllResult] = useState<ModelTestAllResult | null>(null)
  const [logTarget, setLogTarget] = useState<ModelConfig | null>(null)

  const load = async () => {
    try {
      const models = await api.models(); setList(models)
    } catch (e: any) { setErr(e.message) }
    try {
      // 与 models() 解耦：其一失败不应导致下拉厂商列表被清空
      const ps = await api.modelPresetsAll(); setAllPresets(ps)
    } catch (e: any) { setErr(e.message) }
    try {
      const h = await api.modelHealth(); setHealth(h)
    } catch { /* 健康检查不可用时不影响主流程 */ }
  }
  useEffect(() => { load() }, [])

  const preset = PROTOCOL_OPTIONS.find(p => p.key === form.provider) || allPresets.find(p => p.key === form.provider)
  const modality = preset?.modality || 'text'
  // 用途勾选区始终展示全部四种（含「视频模型」），不再因模态被锁死
  const usageOptions = ALL_USAGE_OPTIONS

  // 「预设快捷选项」：按当前模态（默认文本）展示主流厂商 / 部署，点击即带出该厂商的默认
  // Base URL 与建议 Model（如「千问文本大模型（MaaS 专属部署）」选中即带出 MaaS 地址 + qwen-plus），
  // 用户只需再填 Key 即可，体验与直接选 GPT / Claude 一致。
  const quickPresets = (allPresets || []).filter(
    p => (p.modality || 'text') === modality && (p.mainstream || p.key === 'qwen-maas')
  )

  const openAdd = () => {
    setEditingId(null); setForm(emptyForm()); setTestResult(null); setErr(''); setOk('')
    setModalOpen(true)
  }
  const closeModal = () => { setModalOpen(false); setErr(''); setOk('') }

  const onPickProvider = (key: string) => {
    const p = PROTOCOL_OPTIONS.find(x => x.key === key)
    setForm(f => {
      // 仅当链接为空或仍为某个协议的默认值（即用户未手动改过）时，才用新协议默认链接覆盖
      const isBlankOrDefault = !f.base_url || PROTOCOL_OPTIONS.some(o => o.default_base_url === f.base_url)
      return {
        ...f,
        provider: key,
        base_url: isBlankOrDefault ? (p?.default_base_url || '') : f.base_url,
        model: f.model, // 模型版本由用户自行填写，切换协议不覆盖
        usages: defaultUsagesFor(p?.modality || 'text'),
        params: Object.fromEntries((p?.extra_fields || []).map(ef => [ef.key, f.params[ef.key] || ''])),
      }
    })
  }

  // 选中某个「预设快捷选项」（如 千问文本大模型 MaaS 部署）：直接把该厂商/部署的默认 Base URL
  // 与建议 Model（qwen-plus）带出，并填入默认用途与主用途，用户只需补填 Key 即可保存并测试。
  const onPickPreset = (p: ModelPreset) => {
    setForm(f => ({
      ...f,
      provider: p.key,                                           // 存厂商/部署 key，后端按目录解析协议
      name: f.name.trim() ? f.name : p.name,                     // 未填名称时默认带出预设名
      base_url: p.default_base_url,                              // 带出该部署专属地址（千问 MaaS）
      model: p.model_placeholder || (p.models && p.models[0]) || '',
      usages: defaultUsagesFor(p.modality || 'text'),
      params: (p.default_params && typeof p.default_params === 'object') ? { ...p.default_params } : {},
    }))
    setTestResult(null); setErr(''); setOk('')
  }

  const toggleUsage = (v: string) => {
    setForm(f => ({
      ...f,
      usages: f.usages.includes(v) ? f.usages.filter(x => x !== v) : [...f.usages, v],
    }))
  }

  const edit = (m: ModelConfig) => {
    const usages = (m.usages && m.usages.length ? m.usages : (m.usage ? [m.usage] : []))
    setEditingId(m.id)
    setForm({
      name: m.name || '',
      provider: m.provider,
      model: m.model || '',
      base_url: m.base_url || '',
      api_key: m.api_key || '',
      is_active: m.is_active,
      usages: usages.length ? usages : defaultUsagesFor(
        // 编辑时按已存用途推断模态，避免目录缺失导致误判
        usages.includes('image') ? 'image' : usages.includes('video') ? 'video' : 'text'
      ),
      params: (m.params && typeof m.params === 'object') ? m.params as Record<string, string> : {},
    })
    setTestResult(null); setErr(''); setOk('')
    setModalOpen(true)
  }

  const buildPayload = () => ({
    name: form.name.trim(),
    usage: form.usages,
    provider: form.provider,
    api_key: form.api_key,
    base_url: form.base_url,
    model: form.model,
    is_active: form.is_active,
    params: form.params,
  })

  const save = async (): Promise<ModelConfig | null> => {
    setErr(''); setOk('')
    if (!form.name.trim()) { setErr('请填写「名称」，便于区分不同配置。'); return null }
    if (!form.provider) { setErr('请选择「接口协议」。'); return null }
    if (form.usages.length === 0) { setErr('请至少选择一个「用途」。'); return null }
    if (!form.api_key?.trim() || !form.model?.trim() || !form.base_url?.trim()) {
      setErr('请先填写 API Key、模型请求链接与模型版本（Model）三项必填内容。')
      return null
    }
    try {
      const payload = buildPayload()
      const saved = editingId ? await api.updateModel(editingId, payload) : await api.createModel(payload)
      setEditingId(saved.id); await load()
      return saved
    } catch (e: any) {
      const msg = e?.message || String(e)
      if (msg.includes('已添加')) {
        // 同一大模型配置（协议 + 链接 + 模型）已存在，给出明确提醒
        setErr('已添加：该大模型配置已存在，请勿重复添加。')
      } else {
        setErr('保存失败：' + msg)
      }
      return null
    }
  }

  const runTest = async (payload: any) => {
    setTesting(true); setTestResult(null)
    try {
      const r = await api.testModel(payload)
      setTestResult(r)
    } catch (e: any) {
      setTestResult({ ok: false, error_type: 'unknown', message: e.message })
    } finally { setTesting(false) }
  }

  const saveAndTest = async () => {
    const saved = await save()
    if (!saved) return
    setOk('已保存配置，正在发起第一次连通测试…')
    setTesting(true); setTestResult(null)
    try {
      // 用落库值测试并写回连通状态/log，保证「测试状态」列立即反映本次结果
      const r = await api.testSavedModel(saved.id)
      setTestResult(r)
      await load()
    } catch (e: any) {
      setTestResult({ ok: false, error_type: 'unknown', message: e.message })
    } finally { setTesting(false) }
  }
  const testOnly = async () => {
    if (!form.api_key?.trim() || !form.model?.trim() || !form.base_url?.trim()) {
      setErr('请先填写 API Key、模型请求链接与模型版本（Model）。'); return
    }
    await runTest({ provider: form.provider, protocol: form.provider, api_key: form.api_key, base_url: form.base_url,
                    model: form.model, endpoint: form.params?.endpoint, params: form.params })
  }

  const del = async (id: number) => {
    if (!confirm('确认删除该模型配置？')) return
    try { await api.deleteModel(id); await load() } catch (e: any) { setErr(e.message) }
  }

  // 打开「测试已保存配置」弹窗（只读展示配置摘要，直接基于落库值发起连通测试）。
  const openTestSaved = (m: ModelConfig) => {
    setTestTarget(m); setTestTargetResult(null); setTestTargetLoading(false)
  }
  const closeTestSaved = () => { setTestTarget(null); setTestTargetResult(null) }
  const runTestSaved = async () => {
    if (!testTarget) return
    setTestTargetLoading(true); setTestTargetResult(null)
    try {
      // 直接用落库值测试，并把成功/失败状态与 log 写回，列表随即刷新
      const r = await api.testSavedModel(testTarget.id)
      setTestTargetResult(r)
      await load()
    } catch (e: any) {
      setTestTargetResult({ ok: false, error_type: 'unknown', message: e.message })
    } finally { setTestTargetLoading(false) }
  }

  const runTestAll = async () => {
    setTestAllLoading(true); setTestAllResult(null); setErr('')
    try {
      const r = await api.testAllModels()
      setTestAllResult(r)
      await load()
    } catch (e: any) { setErr('全量测试失败：' + e.message) }
    finally { setTestAllLoading(false) }
  }

  const fmtTime = (s?: string | null) => {
    if (!s) return '—'
    const d = new Date(s)
    return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
  }
  // 已保存配置的类型展示名（与列表一致：协议选项优先，回退到厂商目录）。
  const testTargetLabel = testTarget
    ? (PROTOCOL_OPTIONS.find(x => x.key === testTarget.provider) || allPresets.find(x => x.key === testTarget.provider))?.name
      || testTarget.provider
    : ''

  // 自定义下拉（替代原生 <select>）：在弹窗/webview 中原生 select 下拉可能被裁剪/不弹出，
  // 这里用绝对定位的浮层渲染，保证选项一定可见、可点选。本组件改为选择「接口协议」而非厂商。
  const ProtocolSelect = ({ value, options, onPick }: {
    value: string; options: ProtocolOption[]; onPick: (key: string) => void
  }) => {
    const [open, setOpen] = useState(false)
    const ref = useRef<HTMLDivElement>(null)
    useEffect(() => {
      const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
      document.addEventListener('mousedown', h)
      return () => document.removeEventListener('mousedown', h)
    }, [])
    const sel = options.find(p => p.key === value) || allPresets.find(p => p.key === value)
    const ordered = [...options].sort((a, b) => (a.modality === b.modality ? 0 : a.modality === 'text' ? -1 : a.modality === 'image' ? 1 : 2))
    return (
      <div className="provider-select" ref={ref}>
        <button type="button" className={'ps-trigger' + (sel ? '' : ' placeholder')} onClick={() => setOpen(o => !o)}>
          <span>{sel ? sel.name : '— 请选择接口协议 —'}</span>
          <span className="ps-caret">▾</span>
        </button>
        {open && (
          <div className="ps-pop">
            <div className="ps-list">
              {ordered.map(p => (
                <button
                  type="button"
                  key={p.key}
                  className={'ps-opt' + (p.key === value ? ' on' : '')}
                  onClick={() => { onPick(p.key); setOpen(false) }}
                >
                  <span className="ps-name">{p.name}</span>
                  <span className="ps-proto">{MODALITY_LABEL[p.modality]}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>已配置模型（{list.length}）</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn ghost" onClick={runTestAll} disabled={testAllLoading || list.length === 0}>
              {testAllLoading ? '全量测试中…' : '⟳ 立即测试全部'}
            </button>
            <button className="btn" onClick={openAdd}>＋ 添加大模型</button>
          </div>
        </div>
        <div className="muted">按用途配置大模型接口，保存即热切换，无需重启后端。未配置 Key 时自动使用内置 Mock 兜底。同一用途仅一个激活配置，新增/编辑同用途配置会停用其它。</div>
        <div className="health-bar">
          <span className="hb-item">
            <span className="hb-dot" />
            {health?.enabled === false
              ? '每日自动连通测试已关闭'
              : `每日自动连通测试：每天 ${String(health?.hour ?? 3).padStart(2, '0')}:00 之后自动执行一次`}
          </span>
          {health?.last_daily_at && <span className="hb-item">上次自动测试：{fmtTime(health.last_daily_at)}</span>}
          <span className="hb-item hb-note">同一用途保存多条时，系统默认采用「测试成功」的配置支撑功能。</span>
        </div>
        {testAllResult && (
          <div className={'alert ' + (testAllResult.failed > 0 ? 'err' : 'ok')} style={{ marginTop: 8 }}>
            全量测试完成（{fmtTime(testAllResult.tested_at)}）：共 {testAllResult.total} 条，
            成功 {testAllResult.ok} 条，失败 {testAllResult.failed} 条。
            {testAllResult.failed > 0 && '失败详情请在下方「连通状态」列点击查看日志。'}
          </div>
        )}
        {list.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无配置，将使用 Mock 兜底。</div> : (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>名称</th><th>大模型</th><th>用途</th><th>模型版本</th><th>请求链接</th><th>状态</th><th>连通状态</th><th>操作</th></tr></thead>
            <tbody>
              {list.map(m => {
                const p = PROTOCOL_OPTIONS.find(x => x.key === m.provider) || allPresets.find(x => x.key === m.provider)
                const us = (m.usages && m.usages.length ? m.usages : (m.usage ? [m.usage] : []))
                return (
                  <tr key={m.id}>
                    <td>{m.name || <span className="muted">未命名</span>}</td>
                    <td>{p?.name || PROTOCOL_LABEL[m.provider] || m.provider}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {us.map(u => <span key={u} className="usage-tag">{USAGE_LABEL[u] || u}</span>)}
                      </div>
                    </td>
                    <td>{m.model}</td>
                    <td className="muted">{m.base_url}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <span className={'pill ' + (m.is_active ? 'ok' : 'off')}>{m.is_active ? '激活' : '停用'}</span>
                        {m.in_use && <span className="pill inuse" title="该用途当前实际由此配置支撑系统功能">系统采用</span>}
                      </div>
                    </td>
                    <td>
                      {m.last_test_ok === null || m.last_test_ok === undefined ? (
                        <span className="conn-tag untested" title="尚未进行连通性测试">未测试</span>
                      ) : m.last_test_ok ? (
                        <div className="conn-cell">
                          <span className="conn-tag ok">成功</span>
                          <span className="conn-meta">HTTP {m.last_test_http_code ?? 200} · {m.last_test_latency_ms ?? '—'}ms</span>
                          <span className="conn-meta">{fmtTime(m.last_test_at)}</span>
                        </div>
                      ) : (
                        <div className="conn-cell">
                          <span className="conn-tag fail">失败</span>
                          <span className="conn-meta">HTTP {m.last_test_http_code || 'N/A'}</span>
                          <button className="btn small ghost" onClick={() => setLogTarget(m)}>查看日志</button>
                          <span className="conn-meta">{fmtTime(m.last_test_at)}</span>
                        </div>
                      )}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn small ghost" onClick={() => edit(m)}>编辑</button>
                        <button className="btn small" onClick={() => openTestSaved(m)}>测试</button>
                        <button className="btn small danger" onClick={() => del(m.id)}>删除</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {modalOpen && (
        <div className="modal-overlay" onMouseDown={closeModal}>
          <div className="modal modal-wide" onMouseDown={e => e.stopPropagation()}>
            <h3>{editingId ? `编辑配置 #${editingId}` : '添加大模型'}</h3>

            <label>名称（自定义，便于区分）</label>
            <input type="text" value={form.name} placeholder="如：阿里通义-主分析 / 自建GPU-文生图"
                   onChange={e => setForm({ ...form, name: e.target.value })} autoFocus />

            <label>预设快捷选项（点击一键带入地址与模型，再填 Key 即可）</label>
            <div className="chip-row" style={{ marginTop: -4, marginBottom: 6 }}>
              {quickPresets.length === 0 ? (
                <span className="muted">（当前协议类型下暂无快捷预设，可手动在下方填写）</span>
              ) : (
                quickPresets.map(p => (
                  <button
                    key={p.key}
                    type="button"
                    className={'chip preset-chip' + (form.provider === p.key ? ' on' : '')}
                    onClick={() => onPickPreset(p)}
                    title={p.notes || p.setup_guide || ''}
                  >
                    {p.name}
                  </button>
                ))
              )}
            </div>

            <label>接口协议（API 类型，非大模型名称）</label>
            <ProtocolSelect
              value={form.provider}
              options={PROTOCOL_OPTIONS}
              onPick={onPickProvider}
            />

            {preset && (
              <div className="provider-line">
                <span className={'proto proto-' + (form.provider.includes('image') ? 'openai-image' : form.provider.includes('video') ? 'generic-video' : form.provider)}>{MODALITY_LABEL[preset.modality]}</span>
                {preset.notes && <span className="muted">{preset.notes}</span>}
              </div>
            )}

            <label>模型版本（公司与版本号，如 gpt-4o-mini / claude-3-5-sonnet-latest / dall-e-3）</label>
            <input type="text" value={form.model} placeholder={preset?.model_placeholder || '如 gpt-4o-mini'}
                   onChange={e => setForm({ ...form, model: e.target.value })} />
            {preset?.models && preset.models.length > 0 && (
              <div className="chip-row">
                {preset.models.map(m => (
                  <button key={m} className="chip" type="button" onClick={() => setForm({ ...form, model: m })}>{m}</button>
                ))}
              </div>
            )}

            <label>用途（可多选：应用到哪些模块 / 功能）</label>
            <div className="usage-checks">
              {usageOptions.map(u => (
                <label key={u.v} className={'usage-check' + (form.usages.includes(u.v) ? ' on' : '')}>
                  <input type="checkbox" checked={form.usages.includes(u.v)} onChange={() => toggleUsage(u.v)} />
                  {u.label}
                </label>
              ))}
            </div>

            <label>模型请求链接（Base URL）</label>
            <input type="text" value={form.base_url}
                   onChange={e => setForm({ ...form, base_url: e.target.value })}
                   placeholder="https://..." />

            <label>{preset?.api_key_label || 'API Key'}</label>
            <input type="password" value={form.api_key}
                   onChange={e => setForm({ ...form, api_key: e.target.value })}
                   placeholder={preset?.api_key_placeholder || 'sk-...'} />

            {/* 协议专属附加字段（如通用图像/视频的自定义端点），按 extra_fields 动态渲染 */}
            {preset?.extra_fields?.map(ef => (
              <div key={ef.key}>
                <label>{ef.label}</label>
                <input type="text" value={form.params[ef.key] || ''}
                       onChange={e => setForm({ ...form, params: { ...form.params, [ef.key]: e.target.value } })}
                       placeholder={ef.placeholder} />
                {ef.hint && <div className="muted" style={{ fontSize: 12 }}>{ef.hint}</div>}
              </div>
            ))}

            {preset?.setup_guide && <div className="guide">📋 {preset.setup_guide}</div>}

            {modality === 'image' && (
              <div className="guide">🖼️ 文生图大模型：保存后生成素材时，将按创意方向 / 风格 / 配色自动产出背景底图。</div>
            )}
            {modality === 'video' && (
              <div className="guide">🎬 文生视频大模型：注意多数视频模型为异步任务，测试仅验证可达性与鉴权。</div>
            )}

            <label style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '14px 0 0' }}>
              <input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />
              设为激活（同用途仅一个激活）
            </label>

            <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button className="btn" onClick={saveAndTest} disabled={testing}>{testing ? '保存并测试中…' : '保存并测试'}</button>
              <button className="btn secondary" onClick={testOnly} disabled={testing}>{testing ? '测试中…' : '仅测试（不保存）'}</button>
              <button className="btn ghost" onClick={closeModal}>取消</button>
            </div>

            {testResult?.ok && (
              <div className="alert ok">✓ 连通成功 ｜ 延迟 {testResult.latency_ms}ms ｜ 模型回复：{testResult.reply}</div>
            )}
            {testResult && !testResult.ok && (
              <div className="alert err">
                <div style={{ fontWeight: 600, marginBottom: 4 }}>✗ 连通失败（{testResult.error_type || 'unknown'}）</div>
                <div>{testResult.message || testResult.error}</div>
                {testResult.hint_url && (
                  <a className="doc-link" href={testResult.hint_url} target="_blank" rel="noreferrer">
                    查看{testResult.hint_url_label || '官方文档'} ↗
                  </a>
                )}
                {testResult.raw && (
                  <details style={{ marginTop: 6 }}>
                    <summary>原始错误</summary>
                    <pre className="raw">{testResult.raw}</pre>
                  </details>
                )}
              </div>
            )}
            {ok && <div className="alert ok">{ok}</div>}
            {err && <div className="alert err">{err}</div>}
          </div>
        </div>
      )}

      {testTarget && (
        <div className="modal-overlay" onMouseDown={closeTestSaved}>
          <div className="modal" onMouseDown={e => e.stopPropagation()}>
            <h3>测试已保存配置：{testTarget.name || '未命名'}</h3>

            <div className="test-saved-summary">
              <div><span className="ts-k">类型</span><span className="ts-v">{testTargetLabel}</span></div>
              <div><span className="ts-k">模型</span><span className="ts-v">{testTarget.model || '—'}</span></div>
              <div><span className="ts-k">请求链接</span><span className="ts-v ts-url">{testTarget.base_url || '—'}</span></div>
            </div>

            <div className="muted" style={{ marginTop: 8 }}>
              将使用配置中保存的 API Key 直接发起一次最小真实调用（与每日自动测试一致），并把成功/失败状态与错误 log 写回；不会改动 Key、链接、模型等配置内容。
            </div>

            <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
              <button className="btn" onClick={runTestSaved} disabled={testTargetLoading}>
                {testTargetLoading ? '测试中…' : '开始测试'}
              </button>
              <button className="btn ghost" onClick={closeTestSaved}>关闭</button>
            </div>

            {testTargetResult?.ok && (
              <div className="alert ok">✓ 连通成功 ｜ 延迟 {testTargetResult.latency_ms}ms ｜ 模型回复：{testTargetResult.reply}</div>
            )}
            {testTargetResult && !testTargetResult.ok && (
              <div className="alert err">
                <div style={{ fontWeight: 600, marginBottom: 4 }}>✗ 连通失败（{testTargetResult.error_type || 'unknown'}）</div>
                <div>{testTargetResult.message || testTargetResult.error}</div>
                {testTargetResult.hint_url && (
                  <a className="doc-link" href={testTargetResult.hint_url} target="_blank" rel="noreferrer">
                    查看{testTargetResult.hint_url_label || '官方文档'} ↗
                  </a>
                )}
                {testTargetResult.raw && (
                  <details style={{ marginTop: 6 }}>
                    <summary>原始错误</summary>
                    <pre className="raw">{testTargetResult.raw}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {logTarget && (
        <div className="modal-overlay" onMouseDown={() => setLogTarget(null)}>
          <div className="modal modal-wide" onMouseDown={e => e.stopPropagation()}>
            <h3>最近一次测试 log：{logTarget.name || '未命名'}</h3>
            <div className="log-summary">
              <div><span className="ts-k">测试状态</span><span className="conn-tag fail">失败</span></div>
              <div><span className="ts-k">HTTP Code</span><span className="log-code">{logTarget.last_test_http_code || 'N/A（网络层未获得响应）'}</span></div>
              <div><span className="ts-k">模型版本</span><span className="ts-v">{logTarget.model || '—'}</span></div>
              <div><span className="ts-k">请求链接</span><span className="ts-v ts-url">{logTarget.base_url || '—'}</span></div>
              <div><span className="ts-k">测试时间</span><span className="ts-v">{fmtTime(logTarget.last_test_at)}</span></div>
            </div>
            <label style={{ marginTop: 12 }}>错误详情（HTTP code + 服务器返回的错误信息）</label>
            <pre className="log-pre">{logTarget.last_test_error || '（本次未记录到错误日志）'}</pre>
            <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
              <button className="btn" onClick={async () => {
                const t = logTarget
                setLogTarget(null)
                setTestTarget(t); setTestTargetResult(null); setTestTargetLoading(false)
              }}>重新测试该配置</button>
              <button className="btn ghost" onClick={() => setLogTarget(null)}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
