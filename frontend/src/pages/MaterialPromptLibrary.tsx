import { useEffect, useState } from 'react'
import { api, PromptConfig } from '../api'

// 与后端 services.py 中的 LANDING_MODULE 保持一致（提示词按此模块过滤）
const MODULE = '素材创作（落地页分析）'

// 按 category 分组（保持列表顺序），用于在「素材提示词」里分门别类展示
function groupByCategory(list: PromptConfig[]): [string, PromptConfig[]][] {
  const order: string[] = []
  const map: Record<string, PromptConfig[]> = {}
  for (const p of list) {
    const cat = p.category || '其他'
    if (!map[cat]) { map[cat] = []; order.push(cat) }
    map[cat].push(p)
  }
  return order.map(c => [c, map[c]])
}

export default function MaterialPromptLibrary() {
  const [list, setList] = useState<PromptConfig[]>([])
  const [groups, setGroups] = useState<[string, PromptConfig[]][]>([])
  const [editing, setEditing] = useState<PromptConfig | null>(null)
  const [draft, setDraft] = useState('')
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [saving, setSaving] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = async () => {
    try {
      const data = await api.prompts(MODULE)
      setList(data)
      setGroups(groupByCategory(data))
    } catch (e: any) { setErr(e.message) }
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
      await api.updatePrompt(editing.key, {
        content: draft, name: editing.name, description: editing.description,
      })
      setOk(`「${editing.name}」已保存，下一次落地页分析时生效`)
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
      await api.updatePrompt(p.key, {
        content: p.content, name: p.name, description: p.description, is_active: !p.is_active,
      })
      setOk(p.is_active ? `「${p.name}」已停用，该环节将回退内置默认` : `「${p.name}」已启用`)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const preview = (p: PromptConfig, max = 200) =>
    p.content.length > max ? p.content.slice(0, max) + ' …' : p.content

  return (
    <div>
      <div className="card">
        <h2>素材创作 · 提示词</h2>
        <div className="muted" style={{ fontSize: 12.8, lineHeight: 1.62 }}>
          以下提示词共同构成「素材创作 → 落地页分析」的推理框架，按环节分门别类展示。
          编辑保存即生效：下一次落地页分析时使用新提示词，无需重启。所有修改都会写入审计日志。
        </div>
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}

        {list.length === 0 ? (
          <div className="muted">加载中…</div>
        ) : (
          groups.map(([cat, items]) => (
            <div key={cat} className="mpl-group">
              <div className="mpl-cat">{cat}</div>
              <div className="prompt-list">
                {items.map(p => (
                  <div key={p.key} className="card prompt-item">
                    <div className="prompt-head">
                      <div className="prompt-title">
                        <b>{p.name}</b>
                        <span className="pill off">{p.key}</span>
                        <span className={'pill ' + (p.is_active ? 'ok' : 'off')}>
                          {p.is_active ? '生效中' : '已停用'}
                        </span>
                        {!p.is_active && <span className="muted" style={{ fontSize: 12 }}>（运行时使用内置默认）</span>}
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn small" onClick={() => openEdit(p)}>编辑</button>
                        <button className="btn small ghost" onClick={() => toggleActive(p)}>
                          {p.is_active ? '停用' : '启用'}
                        </button>
                        <button className="btn small ghost" onClick={() => reset(p)}>恢复默认</button>
                      </div>
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
            </div>
          ))
        )}
      </div>

      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>编辑提示词：{editing.name}</h3>
            <div className="prompt-meta">
              <span><b>key：</b>{editing.key}</span>
              <span><b>功能模块：</b>{editing.module}</span>
              {editing.category && <span><b>分类：</b>{editing.category}</span>}
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
              保存后即时生效，影响此后所有该模块的模型调用。
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
