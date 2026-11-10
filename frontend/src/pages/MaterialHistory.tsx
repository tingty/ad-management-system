import { useEffect, useMemo, useState } from 'react'
import { api, CreationHistory, MediaImageItem } from '../api'
import type { CreativeAssetList } from '../api'
import { REUSE_HISTORY_KEY, REUSE_HISTORY_EVENT } from './MaterialCreation'

function fmt(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function fieldLabel(h: CreationHistory, key: string): string {
  const s = (h.copy?.schema || []).find(x => x.key === key)
  return s?.label || key
}

/** 历史里图片路径可能是纯文件名（新数据）或旧的绝对路径，统一下载用的纯文件名。 */
function fname(im: MediaImageItem): string {
  return im.file || (im.url || '').split('/').pop() || ''
}

function renderValue(v: any): string {
  if (Array.isArray(v)) return v.filter(x => x !== '' && x != null).join(' / ') || '—'
  if (v == null || v === '') return '—'
  return String(v)
}

const ANALYSIS_FIELDS: { key: string; label: string }[] = [
  { key: 'language', label: '语言' }, { key: 'industry', label: '行业' },
  { key: 'type', label: '类型' }, { key: 'audience', label: '对象' },
]

type Viewer = { list: MediaImageItem[]; index: number } | null

/** V4.42 / F12：分页读取不可变资产记录；历史超过 80 张仍能查到早期素材（T16）。 */
function AssetPager({ historyId }: { historyId: number }) {
  const size = 24
  const [page, setPage] = useState(0)
  const [data, setData] = useState<CreativeAssetList | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let alive = true
    setErr('')
    api.creativeAssets({ history_id: historyId, limit: size, offset: page * size })
      .then(r => { if (alive) setData(r) })
      .catch(e => { if (alive) setErr(e?.message || '资产查询失败') })
    return () => { alive = false }
  }, [historyId, page])
  if (!data && !err) return null
  const pages = Math.max(1, Math.ceil((data?.total || 0) / size))
  return (
    <div className="asset-pager">
      <div className="asset-pager-head">
        <b>完整素材归档 · {data?.total ?? 0} 张（不可变记录）</b>
        <span className="muted">上方列表只缓存最近 80 张；这里按页读取全部历史素材</span>
        <button className="btn small ghost" disabled={page <= 0}
          onClick={() => setPage(p => Math.max(0, p - 1))}>上一页</button>
        <span>{page + 1} / {pages}</span>
        <button className="btn small ghost" disabled={page + 1 >= pages}
          onClick={() => setPage(p => p + 1)}>下一页</button>
      </div>
      {err && <p className="muted">{err}</p>}
      <div className="asset-grid">
        {(data?.items || []).map(a => (
          <div className="asset-cell" key={a.asset_id}>
            <a href={api.mediaFileDownloadUrl(a.file)} title={a.file}>
              <img src={api.fileUrl(a.file)} alt={a.size} loading="lazy" />
            </a>
            <div className="ac-meta">
              {a.size || '—'} · {a.placement || '—'}<br />
              {a.concept_id || '—'} · 规则 {a.spec_version || '—'}
            </div>
          </div>
        ))}
      </div>
      <p className="muted">{data?.retention_policy || ''}</p>
    </div>
  )
}

export default function MaterialHistory() {
  const [items, setItems] = useState<CreationHistory[]>([])
  const [total, setTotal] = useState(0)
  const [limit, setLimit] = useState(60)
  const [q, setQ] = useState('')
  const [kw, setKw] = useState('')            // 已提交的搜索词（避免每次输入都请求）
  const [platform, setPlatform] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [open, setOpen] = useState<number | null>(null)
  const [viewer, setViewer] = useState<Viewer>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const load = async (lim = limit) => {
    setLoading(true); setErr('')
    try {
      const r = await api.creationHistory({ q: kw, platform, limit: lim })
      setItems(r.items); setTotal(r.total); setLimit(lim)
    } catch (e: any) { setErr(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load(60) }, [kw, platform])

  const platforms = useMemo(
    () => Array.from(new Set(items.map(i => i.platform).filter(Boolean))).sort(),
    [items],
  )
  const allSelected = items.length > 0 && items.every(i => selected.includes(i.id))
  const flash = (s: string) => { setOk(s); setTimeout(() => setOk(''), 5000) }

  // 放大预览键盘操作
  useEffect(() => {
    if (!viewer) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setViewer(null)
      else if (e.key === 'ArrowRight') setViewer(v => v ? { ...v, index: (v.index + 1) % v.list.length } : null)
      else if (e.key === 'ArrowLeft') setViewer(v => v ? { ...v, index: (v.index - 1 + v.list.length) % v.list.length } : null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewer])

  const toggleSel = (id: number) =>
    setSelected(v => v.includes(id) ? v.filter(x => x !== id) : [...v, id])
  const toggleAll = () => setSelected(allSelected ? [] : items.map(i => i.id))

  const del = async (ids: number[]) => {
    if (!ids.length) return
    const pick = items.filter(i => ids.includes(i.id))
    const imgs = pick.reduce((n, i) => n + (i.image_count || 0), 0)
    if (!confirm(
      `确认删除选中的 ${ids.length} 条素材历史？\n` +
      `将一并清理约 ${imgs} 张关联推广图片文件，删除后不可恢复。\n` +
      `（若只需素材，建议先「打包下载」）`
    )) return
    setBusy(true); setErr('')
    try {
      const r = await api.deleteCreationHistory(ids)
      setSelected([])
      if (open && ids.includes(open)) setOpen(null)
      await load(limit)
      flash(`已删除 ${r.deleted} 条历史、${r.deleted_files} 个图片文件。`)
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  /** 复用已保存的分析结论：不重新抓站 / 不重复调用大模型，直接进入推广设置。 */
  const reuse = async (h: CreationHistory) => {
    if (!h.analysis) { setErr('该记录未保存落地页分析结论，无法复用'); return }
    setBusy(true); setErr('')
    try {
      const created = await api.createCreationHistory({
        analysis: h.analysis, platform: h.platform, lang: h.lang, source_id: h.id,
      })
      sessionStorage.setItem(REUSE_HISTORY_KEY, JSON.stringify({
        analysis: h.analysis, historyId: created.id,
      }))
      location.hash = '#/creation'
      window.dispatchEvent(new Event(REUSE_HISTORY_EVENT))
      flash('已复用分析结论并新建历史会话，正在跳转「素材创作」…')
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="ch-page">
      <div className="card ch-intro">
        <div className="ch-intro-head">
          <b>素材历史 · 已分析网站与已生成素材的归档库</b>
          <span className="muted">共 {total} 条记录</span>
        </div>
        <p className="muted">
          每次在「素材创作」完成落地页分析即自动建立一条历史；生成的广告文案与推广图片会增量归档。
          这里可直接查阅分析结论、放大图片、单张或打包再下载，也可用「复用分析继续创作」跳过重复抓站与大模型推理，
          只做新的推广设置，从而节约时间并降低重复素材的产生。
        </p>
      </div>

      <div className="card ch-filters">
        <div className="ch-filter-row">
          <input
            type="text" value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') setKw(q.trim()) }}
            placeholder="搜索网站 / 域名 / 行业 / 平台 / 创建人"
          />
          <select value={platform} onChange={e => { setPlatform(e.target.value); setSelected([]) }}>
            <option value="">全部平台</option>
            {platforms.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
          <button className="btn" onClick={() => { setKw(q.trim()); setSelected([]) }}>搜索</button>
          <button className="btn ghost" onClick={() => { setQ(''); setKw(''); setPlatform(''); load(60) }}>重置</button>
          <button className="btn ghost" onClick={() => load(limit)} disabled={loading}>
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
        <div className="ch-bulk">
          <label className="ch-check-all">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} /> 全选当前页
          </label>
          <span className="muted">已选 {selected.length} 条</span>
          {selected.length > 0 && (
            <a className="btn small" href={api.historyBatchZipUrl(selected)}>⬇ 打包下载所选 ZIP</a>
          )}
          {selected.length > 0 && (
            <button className="btn small danger" onClick={() => del(selected)} disabled={busy}>
              批量删除所选
            </button>
          )}
          {selected.length > 0 && (
            <button className="btn small ghost" onClick={() => setSelected([])}>取消选择</button>
          )}
        </div>
        {ok && <div className="alert ok">{ok}</div>}
        {err && <div className="alert err">{err}</div>}
      </div>

      {!items.length && !loading && (
        <div className="card ch-empty">
          <b>暂无素材历史</b>
          <p className="muted">
            {kw || platform ? '当前筛选条件下没有记录，试试重置筛选。'
              : '前往「素材创作」完成一次落地页分析后，这里会自动归档分析结果、广告文案与推广图片。'}
          </p>
        </div>
      )}

      <div className="ch-list">
        {items.map(h => {
          const a = h.analysis
          const imgs = h.images || []
          const expanded = open === h.id
          return (
            <div className={`card ch-item ${expanded ? 'open' : ''}`} key={h.id}>
              <div className="ch-item-head">
                <label className="ch-item-check" title="选择以批量下载 / 删除">
                  <input type="checkbox" checked={selected.includes(h.id)} onChange={() => toggleSel(h.id)} />
                </label>
                <div className="ch-item-main">
                  <div className="ch-title-line">
                    <b className="ch-title">{h.title || '未命名素材会话'}</b>
                    {h.platform && <span className="pill img">{h.platform}</span>}
                    {h.lang && <span className="pill off">{h.lang.toUpperCase()}</span>}
                    {h.has_copy && <span className="pill ok">含文案</span>}
                    <span className="pill off">{h.image_count} 张图片</span>
                    {h.source_id && <span className="pill off">复用自 #{h.source_id}</span>}
                  </div>
                  <div className="ch-sub muted">
                    {h.url
                      ? <a href={h.url} target="_blank" rel="noreferrer">{h.url}</a>
                      : '（直接输入正文分析）'}
                    <span> · {fmt(h.created_at)}</span>
                    {h.owner_name && <span> · {h.owner_name}</span>}
                    {a?.model_info?.provider && (
                      <span> · 分析模型 {a.model_info.provider}/{a.model_info.model}</span>
                    )}
                  </div>
                  <div className="ch-summary muted">
                    {a ? [
                      a.industry && `行业：${a.industry}`,
                      a.type && `类型：${a.type}`,
                      a.audience && `对象：${a.audience}`,
                    ].filter(Boolean).join('　|　') || '（分析结论为空）' : '（未保存分析结论）'}
                  </div>
                </div>
                <div className="ch-item-actions">
                  <button className="btn small ghost" onClick={() => setOpen(expanded ? null : h.id)}>
                    {expanded ? '收起详情' : '查看详情'}
                  </button>
                  <a className="btn small" href={api.historyItemZipUrl(h.id)}>⬇ 打包下载</a>
                  {h.has_copy && (
                    <a className="btn small ghost" href={api.historyCopyUrl(h.id)}>下载文案</a>
                  )}
                  {a && (
                    <button className="btn small primary" onClick={() => reuse(h)} disabled={busy}>
                      复用分析继续创作
                    </button>
                  )}
                  <button className="btn small danger" onClick={() => del([h.id])} disabled={busy}>删除</button>
                </div>
              </div>

              {imgs.length > 0 && (
                <div className="ch-thumbs">
                  {imgs.slice(0, 5).map((im, i) => (
                    <button key={im.file || i} className="ch-thumb" title="点击放大查看"
                      onClick={() => setViewer({ list: imgs, index: i })}>
                      <img src={api.fileUrl(im.file || im.url)} alt={im.size} loading="lazy" />
                      <span>{im.size}</span>
                    </button>
                  ))}
                  {imgs.length > 5 && <span className="ch-thumb-more muted">+{imgs.length - 5} 张</span>}
                </div>
              )}

              {expanded && (
                <div className="ch-detail">
                  <div className="ch-detail-grid">
                    <div className="ch-block">
                      <h4>落地页分析结论</h4>
                      {a ? (
                        <>
                          <div className="ch-kv"><span>网站地址</span><b>{a.url || '—'}</b></div>
                          {ANALYSIS_FIELDS.map(f => (
                            <div className="ch-kv" key={f.key}>
                              <span>{f.label}</span><b>{(a as any)[f.key] || '—'}</b>
                            </div>
                          ))}
                          <div className="ch-kv"><span>竞品</span><b>{(a.competitors || []).join('、') || '—'}</b></div>
                          <div className="ch-kv"><span>优势</span><b>{(a.advantages || []).join('、') || '—'}</b></div>
                          <div className="ch-kv">
                            <span>推广途径</span>
                            <b>{(a.channels || []).map(c => `${c.platform}：${c.reason}`).join('；') || '—'}</b>
                          </div>
                        </>
                      ) : <p className="muted">未保存分析结论</p>}
                    </div>

                    <div className="ch-block">
                      <h4>广告推广文案</h4>
                      {h.copy?.fields ? (
                        <>
                          {h.copy.brand && (
                            <div className="ch-kv"><span>品牌名</span><b>{h.copy.brand}</b></div>
                          )}
                          {Object.entries(h.copy.fields).map(([k, v]) => (
                            <div className="ch-kv" key={k}>
                              <span>{fieldLabel(h, k)}</span><b>{renderValue(v)}</b>
                            </div>
                          ))}
                          <div className="ch-block-foot muted">
                            平台 {h.platform || '—'} · 语言 {h.lang || '—'} ·
                            文案模型 {h.copy.model_info?.provider || '—'} / {h.copy.model_info?.model || '—'}
                          </div>
                        </>
                      ) : <p className="muted">本次会话未生成广告文案</p>}
                    </div>
                  </div>

                  <div className="ch-block">
                    <h4>推广图片素材（{imgs.length}） <span className="muted">点击放大，可单张下载</span></h4>
                    {imgs.length ? (
                      <div className="ch-img-grid">
                        {imgs.map((im, i) => (
                          <div className="ch-img-card" key={im.file || i}>
                            <div className="ch-img-preview" onClick={() => setViewer({ list: imgs, index: i })}>
                              <img src={api.fileUrl(im.file || im.url)} alt={im.size} loading="lazy" />
                            </div>
                            <div className="ch-img-meta">
                              <span className="pill img">{im.size}</span>
                              <span className="muted">{im.placement || '—'}</span>
                            </div>
                            <div className="ch-img-actions">
                              <button className="btn small ghost" onClick={() => setViewer({ list: imgs, index: i })}>放大</button>
                              <a className="btn small" href={api.mediaFileDownloadUrl(fname(im))}>下载</a>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <p className="muted">本次会话未生成推广图片</p>}
                    {h.note && <p className="muted ch-note">{h.note}</p>}
                    {h.retention_policy && <p className="muted ch-note">{h.retention_policy}</p>}
                    <AssetPager historyId={h.id} />
                  </div>

                  <div className="ch-detail-foot">
                    <span className="muted">
                      创建 {fmt(h.created_at)} · 最后更新 {fmt(h.updated_at)} ·
                      图片模型 {h.image_model?.provider || '—'} / {h.image_model?.model || '—'}
                    </span>
                    <div>
                      {imgs.length > 0 && (
                        <a className="btn small ghost"
                          href={api.mediaZipUrl(imgs.map(fname), '历史推广图片')}>
                          ⬇ 仅打包图片
                        </a>
                      )}
                      <a className="btn small primary" href={api.historyItemZipUrl(h.id)}>
                        ⬇ 打包全部（图片 + 文案 + 分析）
                      </a>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {items.length < total && (
        <div className="ch-more">
          <button className="btn" onClick={() => load(limit + 60)} disabled={loading}>
            加载更多（已显示 {items.length} / {total}）
          </button>
        </div>
      )}

      {/* 放大预览（与「素材创作」共用 .lightbox 样式） */}
      {viewer && viewer.list[viewer.index] && (
        <div className="lightbox" onClick={() => setViewer(null)}>
          <div className="lb-inner" onClick={e => e.stopPropagation()}>
            <button className="lb-close" onClick={() => setViewer(null)} title="关闭（ESC）">×</button>
            {viewer.list.length > 1 && (
              <>
                <button className="lb-nav prev" title="上一张"
                  onClick={() => setViewer(v => v ? { ...v, index: (v.index - 1 + v.list.length) % v.list.length } : null)}>‹</button>
                <button className="lb-nav next" title="下一张"
                  onClick={() => setViewer(v => v ? { ...v, index: (v.index + 1) % v.list.length } : null)}>›</button>
              </>
            )}
            <img className="lb-img"
              src={api.fileUrl(viewer.list[viewer.index].file || viewer.list[viewer.index].url)}
              alt={viewer.list[viewer.index].size} />
            <div className="lb-foot">
              <span>{viewer.index + 1} / {viewer.list.length} · {viewer.list[viewer.index].size} · {viewer.list[viewer.index].placement || '—'}</span>
              <div className="lb-btns">
                <a className="btn small" href={api.mediaFileDownloadUrl(fname(viewer.list[viewer.index]))}>下载此图</a>
                <button className="btn small ghost" onClick={() => setViewer(null)}>关闭</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
