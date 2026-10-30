import { useEffect, useState } from 'react'
import { api, ModelConfig } from '../api'
import AdminUsers from '../components/AdminUsers'

const USAGES = [
  { v: 'analysis', label: '落地页分析 / 框架' },
  { v: 'copy', label: '文案 / 关键词' },
  { v: 'image', label: '推广图片' },
  { v: 'video', label: '推广视频' },
]
const empty = { usage: 'analysis', provider: 'openai', api_key: '', base_url: 'https://api.openai.com/v1', model: '', is_active: true }

export default function Settings() {
  const [list, setList] = useState<ModelConfig[]>([])
  const [form, setForm] = useState<any>({ ...empty })
  const [editingId, setEditingId] = useState<number | null>(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [testMsg, setTestMsg] = useState('')
  const [testing, setTesting] = useState(false)

  const load = async () => {
    try { setList(await api.models()) } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    setErr(''); setOk('')
    try {
      if (editingId) { await api.updateModel(editingId, form); setOk('已更新配置') }
      else { await api.createModel(form); setOk('已创建配置') }
      setForm({ ...empty }); setEditingId(null); await load()
    } catch (e: any) { setErr(e.message) }
  }

  const edit = (m: ModelConfig) => {
    setEditingId(m.id)
    setForm({ usage: m.usage, provider: m.provider, api_key: m.api_key || '', base_url: m.base_url || '', model: m.model || '', is_active: m.is_active })
  }

  const del = async (id: number) => {
    if (!confirm('确认删除该模型配置？')) return
    try { await api.deleteModel(id); await load() } catch (e: any) { setErr(e.message) }
  }

  const test = async () => {
    setTesting(true); setTestMsg('')
    try {
      const r = await api.testModel(form)
      if (r.ok) setTestMsg(`✓ 连通成功 ｜ 延迟 ${r.latency_ms}ms ｜ 回复：${r.reply}`)
      else setTestMsg(`✗ 连通失败：${r.error}`)
    } catch (e: any) { setTestMsg('✗ ' + e.message) } finally { setTesting(false) }
  }

  return (
    <div>
      <div className="card">
        <h2>AI 模型 API 配置</h2>
        <div className="muted">
          按用途（分析 / 文案 / 图片 / 视频）配置大模型接口。支持 OpenAI 兼容协议（含本地模型 / 第三方网关），
          <b>保存即热切换</b>，无需重启后端。未配置 Key 时自动使用内置 Mock 兜底，保证工具可运行。
        </div>
      </div>

      <div className="card">
        <h2>{editingId ? '编辑配置 #' + editingId : '新增配置'}</h2>
        <div className="row">
          <div>
            <label>用途</label>
            <select value={form.usage} onChange={e => setForm({ ...form, usage: e.target.value })}>
              {USAGES.map(u => <option key={u.v} value={u.v}>{u.label}</option>)}
            </select>
          </div>
          <div>
            <label>Provider</label>
            <input type="text" value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })} placeholder="openai / anthropic / ollama" />
          </div>
        </div>
        <div className="row">
          <div>
            <label>Base URL</label>
            <input type="text" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com/v1" />
          </div>
          <div>
            <label>Model</label>
            <input type="text" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} placeholder="gpt-4o-mini / qwen / ..." />
          </div>
        </div>
        <label>API Key</label>
        <input type="text" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="sk-..." />
        <div style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', margin: 0 }}>
            <input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />
            设为激活（同用途仅一个激活）
          </label>
          <button className="btn" onClick={save}>{editingId ? '保存修改' : '创建配置'}</button>
          <button className="btn secondary" onClick={test} disabled={testing}>{testing ? '测试中…' : '测试连通性'}</button>
          {editingId && <button className="btn ghost" onClick={() => { setEditingId(null); setForm({ ...empty }) }}>取消</button>}
        </div>
        {testMsg && <div className={'alert ' + (testMsg.startsWith('✓') ? 'ok' : 'err')}>{testMsg}</div>}
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}
      </div>

      <div className="card">
        <h2>已配置模型（{list.length}）</h2>
        {list.length === 0 ? <div className="muted">暂无配置，将使用 Mock 兜底。</div> : (
          <table>
            <thead><tr><th>用途</th><th>Provider</th><th>Base URL</th><th>Model</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {list.map(m => (
                <tr key={m.id}>
                  <td>{USAGES.find(u => u.v === m.usage)?.label || m.usage}</td>
                  <td>{m.provider}</td>
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
              ))}
            </tbody>
          </table>
        )}
      </div>

      <AdminUsers />
    </div>
  )
}
