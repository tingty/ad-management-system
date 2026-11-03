import { useEffect, useState } from 'react'
import { api, ModelConfig, ModelPreset, ModelTestResult } from '../api'

const USAGES = [
  { v: 'analysis', label: '落地页分析 / 框架' },
  { v: 'copy', label: '文案 / 关键词' },
  { v: 'image', label: '推广图片' },
  { v: 'video', label: '推广视频' },
]
const PROTOCOL_LABEL: Record<string, string> = {
  openai: 'OpenAI 兼容', anthropic: 'Anthropic', gemini: 'Google Gemini',
}

const empty = {
  usage: 'analysis', provider: 'custom', api_key: '', base_url: '', model: '', is_active: true,
}

export default function LLMSettings() {
  const [list, setList] = useState<ModelConfig[]>([])
  const [presets, setPresets] = useState<ModelPreset[]>([])
  const [form, setForm] = useState<any>({ ...empty })
  const [editingId, setEditingId] = useState<number | null>(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const [pickerOpen, setPickerOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null)

  const load = async () => {
    try {
      const [models, ps] = await Promise.all([api.models(), api.modelPresets()])
      setList(models); setPresets(ps)
    } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const preset = presets.find(p => p.key === form.provider)

  const openAdd = () => {
    setEditingId(null); setForm({ ...empty }); setTestResult(null); setErr(''); setOk('')
    setPickerOpen(true)
  }
  const choosePreset = (p: ModelPreset) => {
    setForm({
      ...form,
      provider: p.key,
      base_url: p.default_base_url,
      model: p.models[0] || '',
      is_active: true,
    })
    setPickerOpen(false); setTestResult(null); setErr(''); setOk('')
  }
  const edit = (m: ModelConfig) => {
    setEditingId(m.id); setPickerOpen(false); setTestResult(null)
    setForm({ usage: m.usage, provider: m.provider, api_key: m.api_key || '', base_url: m.base_url || '', model: m.model || '', is_active: m.is_active })
  }

  const save = async (): Promise<ModelConfig | null> => {
    setErr(''); setOk('')
    if (!form.api_key?.trim() || !form.model?.trim() || !form.base_url?.trim()) {
      setErr('请先填写 API Key、Base URL 与 Model 三项必填内容。')
      return null
    }
    try {
      const payload = { usage: form.usage, provider: form.provider, api_key: form.api_key,
                        base_url: form.base_url, model: form.model, is_active: form.is_active }
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

  // 主流程：保存配置 → 立即第一次真实调用
  const saveAndTest = async () => {
    const saved = await save()
    if (!saved) return
    setOk('已保存配置，正在发起第一次连通测试…')
    await runTest({ provider: saved.provider, api_key: saved.api_key, base_url: saved.base_url, model: saved.model })
  }
  // 便捷：仅测试当前填写（不落库）
  const testOnly = async () => {
    if (!form.api_key?.trim() || !form.model?.trim() || !form.base_url?.trim()) {
      setErr('请先填写 API Key、Base URL 与 Model。'); return
    }
    await runTest({ provider: form.provider, api_key: form.api_key, base_url: form.base_url, model: form.model })
  }

  const del = async (id: number) => {
    if (!confirm('确认删除该模型配置？')) return
    try { await api.deleteModel(id); await load() } catch (e: any) { setErr(e.message) }
  }

  const filtered = presets.filter(p =>
    !search.trim() || (p.name + p.key).toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <div>
      {/* 新增表单 */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>{editingId ? '编辑配置 #' + editingId : '新增配置'}</h2>
          {!pickerOpen && <button className="btn secondary" onClick={openAdd}>＋ 添加大模型</button>}
        </div>

        {pickerOpen && (
          <div className="model-picker">
            <div className="muted" style={{ marginBottom: 8 }}>选择要接入的大模型（含默认地址与常见模型名，选中后自动带出字段）：</div>
            <input className="filter-input" placeholder="搜索厂商 / 模型，如 openai、千问、claude、gemini…"
                   value={search} onChange={e => setSearch(e.target.value)} autoFocus />
            <div className="preset-grid">
              {filtered.map(p => (
                <button key={p.key} className="preset-card" onClick={() => choosePreset(p)}>
                  <div className="preset-name">{p.name}</div>
                  <div className="preset-meta">
                    <span className={'proto proto-' + p.protocol}>{PROTOCOL_LABEL[p.protocol] || p.protocol}</span>
                    <span className="muted">{p.models[0] || '自定义 Model'}</span>
                  </div>
                </button>
              ))}
              {filtered.length === 0 && <div className="muted">无匹配厂商。</div>}
            </div>
          </div>
        )}

        {!pickerOpen && (
          <>
            <div className="row">
              <div>
                <label>用途</label>
                <select value={form.usage} onChange={e => setForm({ ...form, usage: e.target.value })}>
                  {USAGES.map(u => <option key={u.v} value={u.v}>{u.label}</option>)}
                </select>
              </div>
              <div>
                <label>大模型</label>
                <div className="provider-line">
                  <span className="provider-name">{preset ? preset.name : (form.provider || '自定义')}</span>
                  {preset && <span className={'proto proto-' + preset.protocol}>{PROTOCOL_LABEL[preset.protocol] || preset.protocol}</span>}
                  <button className="btn small ghost" onClick={() => setPickerOpen(true)}>更换</button>
                </div>
              </div>
            </div>

            <label>{preset?.api_key_label || 'API Key'}</label>
            <input type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })}
                   placeholder={preset?.api_key_placeholder || 'sk-...'} />

            <label>Model {preset?.models && preset.models.length ? '（点击建议快速填入）' : ''}</label>
            <input type="text" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })}
                   placeholder={preset?.model_placeholder || '模型名'} />
            {preset?.models && preset.models.length > 0 && (
              <div className="chip-row">
                {preset.models.map(m => (
                  <button key={m} className="chip" onClick={() => setForm({ ...form, model: m })}>{m}</button>
                ))}
              </div>
            )}

            <label>Base URL {preset && !preset.base_url_editable && '（该厂商标定，不可改）'}</label>
            <input type="text" value={form.base_url}
                   onChange={e => setForm({ ...form, base_url: e.target.value })}
                   disabled={!!preset && !preset.base_url_editable}
                   placeholder="https://.../v1" />

            {preset?.setup_guide && <div className="guide">📋 {preset.setup_guide}</div>}
            {preset?.docs_url && <a className="doc-link" href={preset.docs_url} target="_blank" rel="noreferrer">查看官方配置文档 ↗</a>}

            <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', margin: 0 }}>
                <input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />
                设为激活（同用途仅一个激活）
              </label>
              <button className="btn" onClick={saveAndTest} disabled={testing}>{testing ? '保存并测试中…' : '保存并测试'}</button>
              <button className="btn secondary" onClick={testOnly} disabled={testing}>{testing ? '测试中…' : '仅测试（不保存）'}</button>
              {editingId && <button className="btn ghost" onClick={() => { setEditingId(null); setForm({ ...empty }); setTestResult(null) }}>取消</button>}
            </div>

            {/* 测试结果：成功 / 失败引导 */}
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
          </>
        )}
      </div>

      {/* 已配置列表 */}
      <div className="card">
        <h2>已配置模型（{list.length}）</h2>
        <div className="muted">按用途配置大模型接口，保存即热切换，无需重启后端。未配置 Key 时自动使用内置 Mock 兜底。</div>
        {list.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无配置，将使用 Mock 兜底。</div> : (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>用途</th><th>大模型</th><th>Base URL</th><th>Model</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {list.map(m => {
                const p = presets.find(x => x.key === m.provider)
                return (
                  <tr key={m.id}>
                    <td>{USAGES.find(u => u.v === m.usage)?.label || m.usage}</td>
                    <td>{p?.name || m.provider}</td>
                    <td className="muted">{m.base_url}</td>
                    <td>{m.model}</td>
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
    </div>
  )
}
