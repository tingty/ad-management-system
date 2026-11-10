import { useCallback, useEffect, useState } from 'react'
import { api, type ReleaseNote, type ReleaseNotesResponse } from '../api'

const SEEN_KEY = 'admb_lastRelease'
const VISIBLE_COUNT = 8          // 默认只展示最近的版本，从最新一次开始
const REFRESH_MS = 60_000        // 系统更新后，停留在页面上也能自动看到新版本

/** V4.43：每个版本只展示「版本号 + 一句话总结 + 总结式更新要点」。 */
export function NoteCard({ note, isLatest }: { note: ReleaseNote; isLatest: boolean }) {
  return (
    <article className={`card rn-card ${isLatest ? 'rn-card-latest' : ''}`}>
      <header className="rn-head">
        <div className="rn-head-main">
          <span className="rn-ver">{note.version}</span>
          {isLatest && <span className="rn-latest">当前版本</span>}
          {note.auto_generated && <span className="rn-auto">自动同步</span>}
        </div>
        {note.date && <span className="rn-date">{note.date}</span>}
      </header>

      {note.title && <div className="rn-title">{note.title}</div>}
      {note.summary && <p className="rn-summary">{note.summary}</p>}

      {note.points.length > 0 && (
        <ul className="rn-points">
          {note.points.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      )}

      {note.auto_generated && (
        <div className="rn-hint muted">
          该版本由系统按当前运行版本自动同步；正式更新说明以 CHANGELOG 补写为准。
        </div>
      )}
    </article>
  )
}

export default function ReleaseNotes() {
  const [data, setData] = useState<ReleaseNotesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async (silent = false) => {
    try {
      const d = await api.releaseNotes()
      setData(d)
      setError('')
      // 打开即视为已读：记录最新版本号，清除「新版通知」红点
      if (d.latest) {
        localStorage.setItem(SEEN_KEY, d.latest)
        window.dispatchEvent(new Event('admb:releaseSeen'))
      }
    } catch (e) {
      if (!silent) setError(String((e as any)?.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const refresh = () => load(true)
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(refresh, REFRESH_MS)
    return () => {
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', onVisible)
      window.clearInterval(timer)
    }
  }, [load])

  const notes = data?.notes || []
  const visible = showAll ? notes : notes.slice(0, VISIBLE_COUNT)
  const hidden = Math.max(0, notes.length - VISIBLE_COUNT)

  return (
    <div className="page rn-page">
      {loading && <div className="card">加载中…</div>}
      {error && <div className="card err">{error}</div>}
      {!loading && !error && notes.length === 0 && <div className="card">暂无版本更新记录。</div>}

      {visible.map((n, i) => (
        <NoteCard key={n.version} note={n} isLatest={i === 0} />
      ))}

      {hidden > 0 && (
        <button className="rn-more" onClick={() => setShowAll(v => !v)}>
          {showAll ? '收起更早版本' : `查看更早的 ${hidden} 个版本`}
        </button>
      )}
    </div>
  )
}
