import { useEffect, useMemo, useState } from 'react'
import { api, CreativePreset } from '../api'
import { DIRECTIONS, STYLES, COLORS, appliesTo } from '../materialPresets'

type Filter = 'all' | 'image' | 'video' | 'common'
type TabKey = 'direction' | 'style' | 'color'

const FILTERS: [Filter, string][] = [
  ['all', '全部'],
  ['image', '图片可用'],
  ['video', '视频可用'],
  ['common', '通用'],
]

// 后端为单一数据源；拉取失败时回退到本地内置常量，保证页面始终可渲染。
const FALLBACK: Record<TabKey, CreativePreset[]> = {
  direction: DIRECTIONS,
  style: STYLES,
  color: COLORS,
}

function filterLabel(f: Filter) {
  return f === 'all' ? '全部' : f === 'image' ? '图片可用' : f === 'video' ? '视频可用' : '通用'
}

export default function MaterialPrompts() {
  const [tab, setTab] = useState<TabKey>('direction')
  const [filter, setFilter] = useState<Filter>('all')
  const [q, setQ] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [data, setData] = useState<Record<TabKey, CreativePreset[]>>({
    direction: DIRECTIONS, style: STYLES, color: COLORS,
  })
  const [fromServer, setFromServer] = useState(false)

  useEffect(() => {
    let alive = true
    api.creativePresets()
      .then(res => {
        if (!alive) return
        setData({
          direction: res.directions as CreativePreset[],
          style: res.styles as CreativePreset[],
          color: res.colors as CreativePreset[],
        })
        setFromServer(true)
      })
      .catch(() => { /* 保留本地回退 */ })
    return () => { alive = false }
  }, [])

  const source = data[tab]

  const list = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return source.filter(p =>
      appliesTo(p, filter) &&
      (!kw ||
        p.name.toLowerCase().includes(kw) ||
        p.id.toLowerCase().includes(kw) ||
        p.desc.toLowerCase().includes(kw) ||
        p.prompt.toLowerCase().includes(kw)),
    )
  }, [source, filter, q])

  const toggle = (id: string) =>
    setExpanded(s => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  return (
    <div>
      <div className="card">
        <h2>素材创作 · 提示词库</h2>
        <div className="muted" style={{ fontSize: 12.8, lineHeight: 1.62 }}>
          本模块集中展示「素材创作」功能所使用的大模型提示词内容，包含 <b>创意方向库</b>、<b>创意内容风格库</b>、<b>配色方案库</b> 三套预设。
          每条预设均给出<b>适用画像</b>（图片 / 视频 / 通用）与注入生成时的<b>提示词指令</b>。
          {fromServer
            ? '数据来自后端接口（便于运营在后台扩充）。'
            : '当前为内置常量（P0 阶段），后端未返回时回退展示。'}
        </div>

        <div className="mp-toolbar">
          <div className="mp-tabs">
            {(['direction', 'style', 'color'] as TabKey[]).map(k => (
              <button
                key={k}
                className={'mp-tab' + (tab === k ? ' on' : '')}
                onClick={() => { setTab(k); setExpanded(new Set()) }}
              >
                {k === 'direction' ? '创意方向库' : k === 'style' ? '内容风格库' : '配色方案库'}（{data[k].length}）
              </button>
            ))}
          </div>
          <input
            className="mp-search"
            placeholder="搜索方向 / 风格 / 配色名称或提示词…"
            value={q}
            onChange={e => setQ(e.target.value)}
          />
          <div className="mp-filters">
            {FILTERS.map(([k, l]) => (
              <button
                key={k}
                className={'chip' + (filter === k ? ' on' : '')}
                onClick={() => setFilter(k)}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="muted" style={{ marginBottom: 12 }}>
          共 <b>{list.length}</b> 条
          {filter !== 'all' && `（筛选：${filterLabel(filter)}）`}
          {q.trim() && ` · 关键词「${q.trim()}」`}
        </div>
        <div className="mp-grid">
          {list.map(p => {
            const open = expanded.has(p.id)
            return (
              <div key={p.id} className="mp-card">
                <div className="mp-card-head">
                  <span className="mp-id">{p.id}</span>
                  <b>{p.name}</b>
                  <span className={'pill ' + (p.applies === '通用' ? 'off' : p.applies.includes('图') ? 'img' : 'vid')}>
                    {p.applies}
                  </span>
                </div>
                <div className="mp-desc">{p.desc}</div>
                <button className="linkbtn" onClick={() => toggle(p.id)}>
                  {open ? '收起提示词' : '查看提示词'}
                </button>
                {open && <pre className="mp-prompt">{p.prompt}</pre>}
              </div>
            )
          })}
          {list.length === 0 && <div className="muted">没有匹配的提示词，试试调整筛选或关键词。</div>}
        </div>
      </div>
    </div>
  )
}
