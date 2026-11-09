import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type ReleaseNote, type ReleaseNoteChange, type ReleaseNotesResponse } from '../api'

const SEEN_KEY = 'admb_lastRelease'

/* 轻量 Markdown 渲染：支持「**加粗**」、整行加粗小标题、「- 列表项」与段落分段。
   纯前端、无额外依赖，用于展开查看完整发版记录。 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) {
      return <strong key={`${keyPrefix}-${i}`}>{p.slice(2, -2)}</strong>
    }
    return <span key={`${keyPrefix}-${i}`}>{p}</span>
  })
}

function ReleaseBody({ body }: { body: string }) {
  const lines = body.split('\n')
  const out: ReactNode[] = []
  let list: string[] = []
  const flushList = () => {
    if (list.length) {
      const items = list
      out.push(
        <ul key={`ul-${out.length}`} className="rn-list">
          {items.map((t, i) => (
            <li key={i}>{inline(t, `li-${out.length}-${i}`)}</li>
          ))}
        </ul>,
      )
      list = []
    }
  }
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { flushList(); continue }
    if (line.startsWith('- ') || line.startsWith('* ')) { list.push(line.slice(2)); continue }
    flushList()
    const sec = line.match(/^\*\*(.+)\*\*$/)
    if (sec) {
      out.push(<div key={`sec-${out.length}`} className="rn-section">{sec[1]}</div>)
      continue
    }
    out.push(<p key={`p-${out.length}`}>{inline(line, `p-${out.length}`)}</p>)
  }
  flushList()
  return <div className="rn-body">{out}</div>
}

function typeTone(t: string): string {
  if (/删除|下线|移除/.test(t)) return 'del'
  if (/新增|发布/.test(t)) return 'add'
  if (/修复/.test(t)) return 'fix'
  if (/重构/.test(t)) return 'refactor'
  return 'opt'
}

function ChangeRow({ item, i }: { item: ReleaseNoteChange; i: number }) {
  return (
    <div className="rn-change" key={i}>
      <span className={`rn-ct rn-ct-${typeTone(item.type)}`}>{item.type}</span>
      <div className="rn-change-main">
        <div className="rn-change-title">
          {item.module && <span className="rn-change-module">{item.module}</span>}
          {item.module && item.title && <span className="rn-change-sep">/</span>}
          <b>{item.title || '变更说明'}</b>
        </div>
        {item.detail && <div className="rn-change-detail">{item.detail}</div>}
      </div>
    </div>
  )
}

function NoteCard({ note, isNew }: { note: ReleaseNote; isNew: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <article className={`rn-card card ${isNew ? 'rn-card-new' : ''}`}>
      <header className="rn-head">
        <div className="rn-head-main">
          <span className="rn-ver">{note.version}</span>
          <span className="rn-title">{note.title}</span>
        </div>
        <div className="rn-head-meta">
          {isNew && <span className="rn-tag-new">新</span>}
          {!note.has_structured && <span className="rn-tag-history">历史记录</span>}
          {note.date && <span className="rn-date">{note.date}</span>}
        </div>
      </header>

      {(note.modules.length > 0 || note.change_types.length > 0) && (
        <div className="rn-tags">
          {note.change_types.map(t => (
            <span key={t} className={`rn-ct rn-ct-${typeTone(t)}`}>{t}</span>
          ))}
          {note.modules.map(m => (
            <span key={m} className="rn-module">{m}</span>
          ))}
        </div>
      )}

      {note.summary && <div className="rn-summary">{note.summary}</div>}

      {note.changes.length > 0 && (
        <div className="rn-block">
          <div className="rn-block-title">
            {note.has_structured ? '本次优化与更改的功能 / 模块' : '版本要点（历史记录自动摘要）'}
            <span className="rn-count">{note.changes.length}</span>
          </div>
          <div className="rn-changes">
            {note.changes.map((c, i) => <ChangeRow key={i} item={c} i={i} />)}
          </div>
        </div>
      )}

      {(note.impact.length > 0 || note.verification.length > 0) && (
        <div className="rn-grid">
          {note.impact.length > 0 && (
            <div className="rn-block">
              <div className="rn-block-title">影响范围</div>
              <ul className="rn-plain-list">
                {note.impact.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            </div>
          )}
          {note.verification.length > 0 && (
            <div className="rn-block">
              <div className="rn-block-title">验证结果</div>
              <ul className="rn-plain-list">
                {note.verification.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      <button className="rn-toggle" onClick={() => setOpen(v => !v)}>
        {open ? '收起完整发版记录' : '查看完整发版记录'}
        <span className={`rn-toggle-arrow ${open ? 'up' : ''}`}>⌄</span>
      </button>
      {open && <ReleaseBody body={note.body} />}
    </article>
  )
}

export default function ReleaseNotes() {
  const [data, setData] = useState<ReleaseNotesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [module, setModule] = useState<string>('')
  const [kind, setKind] = useState<string>('')

  useEffect(() => {
    let alive = true
    api.releaseNotes()
      .then((d) => {
        if (!alive) return
        setData(d)
        // 打开即视为已读：记录最新版本号，清除「新版通知」红点
        if (d.latest) {
          localStorage.setItem(SEEN_KEY, d.latest)
          window.dispatchEvent(new Event('admb:releaseSeen'))
        }
      })
      .catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [])

  const notes = data?.notes || []
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return notes.filter(n => {
      if (module && !n.modules.includes(module)) return false
      if (kind && !n.change_types.includes(kind)) return false
      if (q) {
        const hay = [n.version, n.title, n.summary, n.body,
          ...n.modules, ...n.change_types,
          ...n.changes.map(c => `${c.type}${c.module}${c.title}${c.detail}`)].join(' ').toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [notes, query, module, kind])

  const activeFilter = !!query || !!module || !!kind

  return (
    <div className="page rn-page">
      <div className="page-head">
        <h2>新版通知</h2>
        <p className="page-sub">
          每次优化与更改都会按「涉及模块 / 变更类型 / 功能说明 / 影响范围 / 验证结果」整理成一个版本条目，
          发版前校验通过后随代码同步发布；历史版本自动降级为要点摘要，完整记录可展开查阅。
        </p>
      </div>

      {loading && <div className="card">加载中…</div>}
      {error && <div className="card err">{error}</div>}

      {data && (
        <div className="card rn-toolbar">
          <div className="rn-stats">
            <span><b>{data.total}</b> 个版本</span>
            <span><b>{data.structured_count}</b> 个结构化版本</span>
            <span>最新 <b>{data.latest || '—'}</b></span>
          </div>
          <div className="rn-filters">
            <input
              className="rn-search"
              placeholder="搜索版本号、模块、功能或改动内容…"
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            <div className="rn-chips">
              <button className={`rn-chip ${!module ? 'on' : ''}`} onClick={() => setModule('')}>全部模块</button>
              {data.modules.map(m => (
                <button key={m} className={`rn-chip ${module === m ? 'on' : ''}`} onClick={() => setModule(m)}>{m}</button>
              ))}
            </div>
            <div className="rn-chips">
              <button className={`rn-chip ${!kind ? 'on' : ''}`} onClick={() => setKind('')}>全部类型</button>
              {data.change_types.map(t => (
                <button key={t} className={`rn-chip rn-chip-${typeTone(t)} ${kind === t ? 'on' : ''}`} onClick={() => setKind(t)}>{t}</button>
              ))}
            </div>
            {activeFilter && (
              <button className="rn-reset" onClick={() => { setQuery(''); setModule(''); setKind('') }}>
                清除筛选（当前 {filtered.length} 条）
              </button>
            )}
          </div>
        </div>
      )}

      {!loading && !error && notes.length === 0 && <div className="card">暂无发布记录。</div>}
      {!loading && !error && notes.length > 0 && filtered.length === 0 && (
        <div className="card">没有匹配的版本通知，试试清除筛选条件。</div>
      )}

      {!loading && !error && filtered.map((n) => (
        <NoteCard key={n.version} note={n} isNew={n.version === data?.latest} />
      ))}

      {!loading && !error && activeFilter && filtered.length > 0 && (
        <div className="rn-footnote">
          按模块 / 变更类型筛选仅对 V4.37 起的结构化版本生效；历史版本可用关键词搜索或清除筛选查看。
        </div>
      )}
    </div>
  )
}
