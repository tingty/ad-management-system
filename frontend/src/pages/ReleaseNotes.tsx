import { useEffect, useState, type ReactNode } from 'react'
import { api, type ReleaseNote } from '../api'

const SEEN_KEY = 'admb_lastRelease'

// 轻量 Markdown 渲染：仅支持「**加粗**」、**小标题**（整行加粗）、「- 列表项」与段落/空行分段。
// 纯前端、无额外依赖，足以呈现 CHANGELOG 的发布内容。
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
    if (!line.trim()) {
      flushList()
      continue
    }
    if (line.startsWith('- ')) {
      list.push(line.slice(2))
      continue
    }
    flushList()
    const sec = line.match(/^\*\*(.+)\*\*$/)
    if (sec) {
      out.push(
        <div key={`sec-${out.length}`} className="rn-section">
          {sec[1]}
        </div>,
      )
      continue
    }
    out.push(
      <p key={`p-${out.length}`}>{inline(line, `p-${out.length}`)}</p>,
    )
  }
  flushList()
  return <div className="rn-body">{out}</div>
}

function NoteCard({ note, isNew }: { note: ReleaseNote; isNew: boolean }) {
  return (
    <article className="rn-card card">
      <header className="rn-head">
        <div className="rn-head-main">
          <span className="rn-ver">{note.version}</span>
          <span className="rn-title">{note.title}</span>
        </div>
        <div className="rn-head-meta">
          {isNew && <span className="rn-tag-new">新</span>}
          {note.date && <span className="rn-date">{note.date}</span>}
        </div>
      </header>
      <ReleaseBody body={note.body} />
    </article>
  )
}

export default function ReleaseNotes() {
  const [notes, setNotes] = useState<ReleaseNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api
      .releaseNotes()
      .then((d) => {
        if (!alive) return
        setNotes(d.notes || [])
        // 打开即视为已读：记录最新版本号，清除「新版通知」红点
        if (d.latest) {
          localStorage.setItem(SEEN_KEY, d.latest)
          window.dispatchEvent(new Event('admb:releaseSeen'))
        }
      })
      .catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="page rn-page">
      <div className="page-head">
        <h2>新版通知</h2>
        <p className="page-sub">每次版本发布的更新内容都会在此汇总展示；数据来自发版记录，发版即更新。</p>
      </div>

      {loading && <div className="card">加载中…</div>}
      {error && <div className="card err">{error}</div>}
      {!loading && !error && notes.length === 0 && (
        <div className="card">暂无发布记录。</div>
      )}
      {!loading &&
        !error &&
        notes.map((n, i) => (
          <NoteCard key={n.version} note={n} isNew={i === 0} />
        ))}
    </div>
  )
}
