import { useEffect, useState } from 'react'
import { api, PromptConfig } from '../api'

export default function Prompts() {
  const [list, setList] = useState<PromptConfig[]>([])
  const [editing, setEditing] = useState<PromptConfig | null>(null)
  const [draft, setDraft] = useState('')
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [saving, setSaving] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = async () => {
    try { setList(await api.prompts()) } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const openEdit = (p: PromptConfig) => {
    setErr(''); setOk('')
    setEditing(p)
    setDraft(p.content)
  }

  const save = async () => {
    if (!editing) return
    setSaving(true); setErr('')
    try {
      await api.updatePrompt(editing.key, { content: draft, name: editing.name, description: editing.description })
      setOk(`「${editing.name}」已保存，下一次调用「${editing.module}」时生效`)
      setEditing(null)
      await load()
    } catch (e: any) { setErr(e.message) } finally { setSaving(false) }
  }

  const reset = async (p: PromptConfig) => {
    if (!confirm(`确认将「${p.name}」恢复为系统默认提示词？当前自定义内容将被覆盖。`)) return
    setErr(''); setOk('')
    try {
      await api.resetPrompt(p.key)
      setOk(`「${p.name}」已恢复为默认提示词`)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const toggleActive = async (p: PromptConfig) => {
    setErr(''); setOk('')
    try {
      await api.updatePrompt(p.key, { content: p.content, name: p.name, description: p.description, is_active: !p.is_active })
      setOk(p.is_active ? `「${p.name}」已停用，该模块将回退内置默认提示词` : `「${p.name}」已启用`)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const preview = (p: PromptConfig, max = 220) =>
    p.content.length > max ? p.content.slice(0, max) + ' …' : p.content

  return (
    <div>
      <div className="card">
        <h2>系统提示词（{list.length}）</h2>
        <div className="muted">
          统一管理各功能模块使用的大模型提示词。<b>保存即生效</b>：下一次调用对应模块时即使用新提示词，无需重启。
          编辑时请保留结尾的 MARKER 标记（Mock 兜底与日志定位依赖它）；修改有风险时可用「恢复默认」一键回退。
          所有修改都会写入审计日志。
        </div>
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}

        {list.length === 0 ? <div className="muted">加载中…</div> : (
          <div className="prompt-list">
            {list.map(p => (
              <div key={p.key} className="card prompt-item">
                <div className="prompt-head">
                  <div className="prompt-title">
                    <b>{p.name}</b>
                    <span className="pill off">{p.key}</span>
                    <span className={'pill ' + (p.is_active ? 'ok' : 'off')}>{p.is_active ? '生效中' : '已停用'}</span>
                    {!p.is_active && <span className="muted" style={{ fontSize: 12 }}>（运行时使用内置默认）</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn small" onClick={() => openEdit(p)}>编辑</button>
                    <button className="btn small ghost" onClick={() => toggleActive(p)}>{p.is_active ? '停用' : '启用'}</button>
                    <button className="btn small ghost" onClick={() => reset(p)}>恢复默认</button>
                  </div>
                </div>
                <div className="prompt-meta">
                  <span><b>功能模块：</b>{p.module}</span>
                  <span className="muted">更新于 {p.updated_at ? new Date(p.updated_at).toLocaleString() : '内置默认'}</span>
                </div>
                {p.description && <div className="muted" style={{ fontSize: 12.5 }}>{p.description}</div>}
                <div className="prompt-content">
                  <pre className="prompt-pre">{expanded === p.key ? p.content : preview(p)}</pre>
                </div>
                <div style={{ marginTop: 6 }}>
                  <button className="btn small ghost" onClick={() => setExpanded(expanded === p.key ? null : p.key)}>
                    {expanded === p.key ? '收起' : '展开全文'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>编辑提示词：{editing.name}</h3>
            <div className="prompt-meta">
              <span><b>key：</b>{editing.key}</span>
              <span><b>功能模块：</b>{editing.module}</span>
            </div>
            {editing.description && <div className="muted" style={{ fontSize: 12.5 }}>{editing.description}</div>}
            <label>提示词正文（系统提示词）</label>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              className="prompt-editor"
              spellCheck={false}
            />
            <div className="muted" style={{ fontSize: 12.5 }}>
              注意：① 保留结尾 MARKER 标记；② 占位符与输出 JSON 结构需与调用方解析逻辑匹配；
              ③ 保存后即时生效，影响此后所有该模块的模型调用。
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 14, justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={() => setEditing(null)}>取消</button>
              <button className="btn" onClick={save} disabled={saving || !draft.trim()}>
                {saving ? '保存中…' : '保存并生效'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
