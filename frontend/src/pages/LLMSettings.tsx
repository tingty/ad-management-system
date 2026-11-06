import { useEffect, useState } from 'react'
import { api, ModelConfig, ModelPreset, ModelTestResult } from '../api'

const USAGE_LABEL: Record<string, string> = {
  analysis: '落地页分析 / 框架',
  copy: '文案 / 关键词',
  image: '推广图片',
  video: '推广视频',
}
// 按模态决定可选的「用途」范围：文本模型可同时服务分析与文案；图/视频各自独立。
const USAGE_BY_MODALITY: Record<string, { v: string; label: string }[]> = {
  text: [
    { v: 'analysis', label: '落地页分析 / 框架' },
    { v: 'copy', label: '文案 / 关键词' },
  ],
  image: [{ v: 'image', label: '推广图片' }],
  video: [{ v: 'video', label: '推广视频' }],
}
const PROTOCOL_LABEL: Record<string, string> = {
  openai: 'OpenAI 兼容', anthropic: 'Anthropic', gemini: 'Google Gemini',
  'openai-image': 'OpenAI 图像', 'generic-image': '通用图像', 'dashscope-maas-image': 'DashScope MaaS',
  'generic-video': '通用视频',
}
const MODALITY_LABEL: Record<string, string> = { text: '文本大模型', image: '文生图大模型', video: '文生视频大模型' }

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

  const load = async () => {
    try {
      const [models, ps] = await Promise.all([api.models(), api.modelPresetsAll()])
      setList(models); setAllPresets(ps)
    } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const preset = allPresets.find(p => p.key === form.provider)
  const modality = preset?.modality || 'text'
  const usageOptions = USAGE_BY_MODALITY[modality] || USAGE_BY_MODALITY.text

  const openAdd = () => {
    setEditingId(null); setForm(emptyForm()); setTestResult(null); setErr(''); setOk('')
    setModalOpen(true)
  }
  const closeModal = () => { setModalOpen(false); setErr(''); setOk('') }

  const onPickProvider = (key: string) => {
    const p = allPresets.find(x => x.key === key)
    setForm(f => ({
      ...f,
      provider: key,
      base_url: p?.default_base_url || '',
      model: p?.models?.[0] || '',
      // 切换厂商后用途按模态重置为默认选项
      usages: defaultUsagesFor(p?.modality || 'text'),
      // 重置附加字段占位（保留已填值以便再次切换回填）
      params: Object.fromEntries((p?.extra_fields || []).map(ef => [ef.key, f.params[ef.key] || ''])),
    }))
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
    if (!form.provider) { setErr('请选择「大模型」。'); return null }
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
    } catch (e: any) { setErr('保存失败：' + e.message); return null }
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
    await runTest({ provider: saved.provider, api_key: saved.api_key, base_url: saved.base_url,
                    model: saved.model, endpoint: form.params?.endpoint })
  }
  const testOnly = async () => {
    if (!form.api_key?.trim() || !form.model?.trim() || !form.base_url?.trim()) {
      setErr('请先填写 API Key、模型请求链接与模型版本（Model）。'); return
    }
    await runTest({ provider: form.provider, api_key: form.api_key, base_url: form.base_url,
                    model: form.model, endpoint: form.params?.endpoint })
  }

  const del = async (id: number) => {
    if (!confirm('确认删除该模型配置？')) return
    try { await api.deleteModel(id); await load() } catch (e: any) { setErr(e.message) }
  }

  // 预设按模态分组，供下拉展示；(p.modality || 'text') 兜底，避免个别预设缺字段时整组消失
  const grouped = [
    { modality: 'text', label: MODALITY_LABEL.text, items: allPresets.filter(p => (p.modality || 'text') === 'text') },
    { modality: 'image', label: MODALITY_LABEL.image, items: allPresets.filter(p => (p.modality || 'text') === 'image') },
    { modality: 'video', label: MODALITY_LABEL.video, items: allPresets.filter(p => (p.modality || 'text') === 'video') },
  ].filter(g => g.items.length > 0)

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>已配置模型（{list.length}）</h2>
          <button className="btn" onClick={openAdd}>＋ 添加大模型</button>
        </div>
        <div className="muted">按用途配置大模型接口，保存即热切换，无需重启后端。未配置 Key 时自动使用内置 Mock 兜底。同一用途仅一个激活配置，新增/编辑同用途配置会停用其它。</div>
        {list.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无配置，将使用 Mock 兜底。</div> : (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>名称</th><th>大模型</th><th>用途</th><th>模型版本</th><th>请求链接</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {list.map(m => {
                const p = allPresets.find(x => x.key === m.provider)
                const us = (m.usages && m.usages.length ? m.usages : (m.usage ? [m.usage] : []))
                return (
                  <tr key={m.id}>
                    <td>{m.name || <span className="muted">未命名</span>}</td>
                    <td>{p?.name || m.provider}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {us.map(u => <span key={u} className="usage-tag">{USAGE_LABEL[u] || u}</span>)}
                      </div>
                    </td>
                    <td>{m.model}</td>
                    <td className="muted">{m.base_url}</td>
                    <td><span className={'pill ' + (m.is_active ? 'ok' : 'off')}>{m.is_active ? '激活' : '停用'}</span></td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn small ghost" onClick={() => edit(m)}>编辑</button>
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

            <label>大模型（下拉选择厂商）</label>
            <select value={form.provider} onChange={e => onPickProvider(e.target.value)}>
              <option value="">— 请选择大模型 —</option>
              {grouped.map(g => (
                <optgroup key={g.modality} label={g.label}>
                  {g.items.map(p => (
                    <option key={p.key} value={p.key}>{p.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>

            {preset && (
              <div className="provider-line">
                <span className={'proto proto-' + preset.protocol}>{PROTOCOL_LABEL[preset.protocol] || preset.protocol}</span>
                {preset.notes && <span className="muted">{preset.notes}</span>}
              </div>
            )}

            <label>模型版本（公司与版本号，如 qwen-max / dall-e-3）</label>
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
                   placeholder="https://..." disabled={!!preset && preset.base_url_editable === false} />
            {preset && preset.base_url_editable === false && (
              <div className="muted" style={{ fontSize: 12 }}>该厂商标定地址，不可修改。</div>
            )}

            <label>{preset?.api_key_label || 'API Key'}</label>
            <input type="password" value={form.api_key}
                   onChange={e => setForm({ ...form, api_key: e.target.value })}
                   placeholder={preset?.api_key_placeholder || 'sk-...'} />

            {/* 厂商专属附加字段（如自定义端点），按 preset.extra_fields 动态渲染 */}
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
            {preset?.docs_url && <a className="doc-link" href={preset.docs_url} target="_blank" rel="noreferrer">查看官方配置文档 ↗</a>}

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
    </div>
  )
}
