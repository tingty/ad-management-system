import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  api, type ReleaseNote, type ReleaseNoteChange, type ReleaseNotesResponse,
  type ReleaseCurrent, type ReleaseRoadmap,
} from '../api'

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
          {note.phase_text && (
            <span className="rn-module rn-phase">改造 {note.phase_text}</span>
          )}
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

/** V4.39：当前版本号 + 主要更新内容（顶部高亮卡片） */
function CurrentRelease({ current }: { current: ReleaseCurrent }) {
  const rest = Math.max(0, (current.changes?.length || 0) - (current.highlights?.length || 0))
  return (
    <div className="card rn-current">
      <div className="rn-cur-top">
        <div>
          <div className="rn-cur-kicker">当前更新版本</div>
          <div className="rn-cur-ver">
            {current.version}
            <span className="rn-cur-badge">最新发布</span>
          </div>
          <div className="rn-cur-title">{current.title} · {current.date || '发布日期待补充'}</div>
        </div>
        {current.phase_text && (
          <div className="rn-cur-phase">
            <span>本期改造</span>
            <b>{current.phase_text}</b>
          </div>
        )}
      </div>

      {current.summary && <div className="rn-cur-summary">{current.summary}</div>}

      <div className="rn-cur-block">
        <div className="rn-cur-label">主要更新内容</div>
        {(current.highlights || []).length > 0 ? (
          <ul className="rn-cur-list">
            {current.highlights.map((h, i) => (
              <li key={i}>
                <span className={`rn-ct rn-ct-${typeTone(h.type)}`}>{h.type}</span>
                <b>{[h.module, h.title].filter(Boolean).join(' / ')}</b>
                {h.detail && <span className="muted"> — {h.detail}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <div className="muted">本版本暂无结构化改动条目，可展开下方完整发版记录查看。</div>
        )}
        {rest > 0 && <div className="rn-cur-more muted">另有 {rest} 项改动，见下方版本详情。</div>}
      </div>

      <div className="rn-cur-foot">
        {current.issue_ids?.length > 0 && <span>本期修复问题：{current.issue_ids.join(' / ')}</span>}
        {current.change_types?.length > 0 && <span>变更类型：{current.change_types.join(' / ')}</span>}
      </div>
    </div>
  )
}

const PHASE_LABEL: Record<string, string> = {
  done: '已完成', in_progress: '进行中', planned: '规划中',
}

/** V4.39：每期 3 个问题的改造进度，状态由 CHANGELOG 发版记录自动驱动 */
function RoadmapPanel({ roadmap }: { roadmap: ReleaseRoadmap }) {
  return (
    <div className="card rn-roadmap">
      <div className="rn-rm-head">
        <b>系统改造进度</b>
        <span className="muted">依据《广告素材平台问题诊断与AI改造实施说明书》，每期改造 3 个问题、独立发版并同步版本通知</span>
        <span className="rn-rm-count">{roadmap.done_count} / {roadmap.total} 已完成</span>
      </div>
      <div className="rn-rm-phases">
        {roadmap.phases.map(p => (
          <div className={`rn-rm-phase rn-rm-${p.status}`} key={p.index}>
            <div className="rn-rm-phead">
              <b>第 {p.index} 期 · {p.title}</b>
              <span>{p.version} · {p.done_count}/{p.issues.length} · {PHASE_LABEL[p.status] || p.status}</span>
            </div>
            <div className="rn-rm-goal muted">{p.goal}</div>
            <div className="rn-rm-issues">
              {p.issues.map(i => (
                <div className={`rn-rm-issue ${i.status}`} key={i.id}>
                  <span className="rn-rm-id">{i.id}</span>
                  <span className="rn-rm-name">{i.title}</span>
                  <span className="rn-rm-state">
                    {i.status === 'done' ? `已发布 ${i.released_version}` : '规划中'}
                  </span>
                </div>
              ))}
            </div>
            <div className="rn-rm-scope muted">行业适配：{p.industry_scope}</div>
          </div>
        ))}
      </div>
      <div className="rn-rm-note muted">{roadmap.industry_note}</div>
    </div>
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
          顶部显示当前更新的版本号与主要更新内容；每次优化与更改都按「涉及模块 / 变更类型 / 功能说明 /
          影响范围 / 验证结果」整理成版本条目，发版前校验通过后随代码同步发布。
          系统改造按「每期 3 个问题」分步推进，进度与每一期的版本通知统一在此查阅。
        </p>
      </div>

      {loading && <div className="card">加载中…</div>}
      {error && <div className="card err">{error}</div>}

      {data?.current && <CurrentRelease current={data.current} />}
      {data?.roadmap && <RoadmapPanel roadmap={data.roadmap} />}

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
