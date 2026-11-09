import { useEffect, useMemo, useState } from 'react'
import {
  api, PromptConfig, PromptLibraryItem, PromptLibraryResponse, PromptTaxonomy,
} from '../api'

/**
 * V4.35「素材提示词」管理模块
 *
 * 需求 1：把「素材创作」涉及的全部提示词集中展示 —— 13 条系统提示词（含此前硬编码在
 *         media_ad.py 的广告推广文案/图片提示词）+ 62 条创意预设片段，共 75 条。
 * 需求 2：按「功能类型 / 使用类型」两套维度分门别类，支持筛选、搜索、编辑与恢复默认。
 * 需求 3：为直接影响最终结果的「广告推广文案 / 广告推广图片」建立优秀提示词总结库，
 *         按 类型 / 风格 / 场景 / 覆盖对象 四维筛选，一键设为系统默认（保存即生效）。
 */

type View = 'catalog' | 'library'
type DimKey = 'type' | 'style' | 'scene' | 'audience' | 'q'

const USAGE_LABEL: Record<string, string> = {
  system: '系统提示词', user: '用户提示词', constraint: '输出约束',
  fragment: '提示词片段', directive: '生成指令',
}
const PRESET_FUNCS = new Set(['creative_direction', 'content_style', 'color_scheme'])
const EMPTY_DIMS: Record<DimKey, string> = { type: '', style: '', scene: '', audience: '', q: '' }

export default function MaterialPromptLibrary({ isAdmin = false }: { isAdmin?: boolean }) {
  const [view, setView] = useState<View>('catalog')

  // ---------------- 全量提示词目录 ----------------
  const [list, setList] = useState<PromptConfig[]>([])
  const [tax, setTax] = useState<PromptTaxonomy | null>(null)
  const [funcFilter, setFuncFilter] = useState('')
  const [usageFilter, setUsageFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({
    creative_direction: true, content_style: true, color_scheme: true,
  })
  const [editing, setEditing] = useState<PromptConfig | null>(null)
  const [draft, setDraft] = useState('')
  const [editFunc, setEditFunc] = useState('')
  const [editUsage, setEditUsage] = useState('')

  // ---------------- 优秀提示词总结库 ----------------
  const [libKind, setLibKind] = useState('ad_copy')
  const [dims, setDims] = useState<Record<DimKey, string>>({ ...EMPTY_DIMS })
  const [lib, setLib] = useState<PromptLibraryResponse | null>(null)
  const [libBusy, setLibBusy] = useState(false)
  const [viewItem, setViewItem] = useState<PromptLibraryItem | null>(null)

  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadCatalog = async () => {
    setLoading(true)
    try {
      const [items, t] = await Promise.all([api.prompts(), api.promptTaxonomy()])
      setList(items); setTax(t)
    } catch (e: any) { setErr(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { loadCatalog() }, [])

  const loadLibrary = async () => {
    setLibBusy(true)
    try {
      setLib(await api.promptLibrary({ kind: libKind, ...dims }))
    } catch (e: any) { setErr(e.message) } finally { setLibBusy(false) }
  }
  useEffect(() => { loadLibrary() }, [libKind, dims])

  const flash = (msg: string) => { setOk(msg); setErr('') }

  // ---------------- 目录：分组 + 筛选 ----------------
  const groups = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    const filtered = list.filter(p => {
      if (funcFilter && p.func_type !== funcFilter) return false
      if (usageFilter && p.usage_type !== usageFilter) return false
      if (kw) {
        const hay = [p.name, p.key, p.module, p.category, p.description, p.content]
          .filter(Boolean).join(' ').toLowerCase()
        if (!hay.includes(kw)) return false
      }
      return true
    })
    const order = tax?.func_types.map(t => t.key) || []
    return order.map(k => {
      const meta = tax?.func_types.find(t => t.key === k)
      return { key: k, label: meta?.label || k, desc: meta?.desc || '',
               items: filtered.filter(p => p.func_type === k) }
    }).filter(g => g.items.length > 0)
  }, [list, tax, funcFilter, usageFilter, keyword])

  const filteredCount = groups.reduce((n, g) => n + g.items.length, 0)
  const resetFilters = () => { setFuncFilter(''); setUsageFilter(''); setKeyword('') }

  // ---------------- 目录：编辑 / 停用 / 恢复默认 ----------------
  const openEdit = (p: PromptConfig) => {
    setErr(''); setOk('')
    setEditing(p); setDraft(p.content)
    setEditFunc(p.func_type || 'production'); setEditUsage(p.usage_type || 'system')
  }
  const save = async () => {
    if (!editing) return
    setSaving(true); setErr('')
    try {
      await api.updatePrompt(editing.key, {
        content: draft, name: editing.name, description: editing.description,
        func_type: editFunc, usage_type: editUsage,
      })
      flash(`「${editing.name}」已保存，下一次「素材创作」调用时生效`)
      setEditing(null)
      await loadCatalog()
    } catch (e: any) { setErr(e.message) } finally { setSaving(false) }
  }
  const reset = async (p: PromptConfig) => {
    if (!confirm(`确认将「${p.name}」恢复为系统默认提示词？当前自定义内容将被覆盖。`)) return
    setErr(''); setOk('')
    try {
      await api.resetPrompt(p.key)
      flash(`「${p.name}」已恢复为默认提示词`)
      await Promise.all([loadCatalog(), loadLibrary()])
    } catch (e: any) { setErr(e.message) }
  }
  const toggleActive = async (p: PromptConfig) => {
    setErr(''); setOk('')
    try {
      await api.updatePrompt(p.key, {
        content: p.content, name: p.name, description: p.description, is_active: !p.is_active,
      })
      flash(p.is_active ? `「${p.name}」已停用，该环节回退内置默认` : `「${p.name}」已启用`)
      await loadCatalog()
    } catch (e: any) { setErr(e.message) }
  }

  // ---------------- 总结库：设为系统默认 ----------------
  const setDefault = async (id: string | null, name: string, kind: string = libKind) => {
    const kindLabel = kind === 'ad_copy' ? '广告推广文案' : '广告推广图片'
    if (!confirm(id
      ? `确认将「${name}」设为「${kindLabel}」的系统默认提示词？\n此后所有生成都会立即使用此模板。`
      : `确认将「${kindLabel}」恢复为系统内置默认提示词？`)) return
    setErr(''); setOk('')
    try {
      const r = await api.setPromptDefault(kind, id)
      flash(`「${kindLabel}」已设为：${r.name}。生成链路即时生效，无需重启。`)
      setViewItem(null)
      await Promise.all([loadLibrary(), loadCatalog()])
    } catch (e: any) { setErr(e.message) }
  }

  const preview = (s: string, max = 240) => s.length > max ? s.slice(0, max) + ' …' : s
  const currentDefault = lib?.defaults?.[libKind]

  return (
    <div className="mpl-page">
      {/* 顶部视图切换 */}
      <div className="card mpl-topbar">
        <div className="mpl-viewtabs">
          <button className={view === 'catalog' ? 'on' : ''} onClick={() => setView('catalog')}>
            全量提示词目录{tax ? `（${tax.total}）` : ''}
          </button>
          <button className={view === 'library' ? 'on' : ''} onClick={() => setView('library')}>
            优秀提示词总结库{lib ? `（${lib.all_total}）` : ''}
          </button>
        </div>
        <div className="muted" style={{ fontSize: 12.8, lineHeight: 1.65 }}>
          {view === 'catalog'
            ? <>集中展示「素材创作」涉及的<b>全部提示词</b>：落地页分析、广告推广文案 / 图片、视频分镜、通用素材生产，
                以及创意方向 / 内容风格 / 配色三大预设库。按<b>功能类型</b>与<b>使用类型</b>两套维度分类，支持检索与编辑，保存即生效。</>
            : <>收录业界公认的优秀提示词框架，按<b>类型 / 风格 / 场景 / 覆盖对象</b>四维筛选。
                针对直接影响最终结果的「广告推广文案」「广告推广图片」，可一键<b>设为系统默认</b>——
                生成链路即时读取，也可在目录中继续微调。</>}
          {!isAdmin && <span className="pill off" style={{ marginLeft: 8 }}>只读（修改需管理员）</span>}
        </div>
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}
      </div>

      {/* ==================== 视图一：全量提示词目录 ==================== */}
      {view === 'catalog' && (
        <>
          <div className="card mpl-taxcard">
            <div className="mpl-tax-head">
              <h3>按功能类型分类</h3>
              <span className="muted">落在生成链路的哪个环节</span>
            </div>
            <div className="mpl-chips">
              <button className={'mpl-chip ' + (funcFilter === '' ? 'on' : '')} onClick={() => setFuncFilter('')}>
                全部 <b>{tax?.total ?? list.length}</b>
              </button>
              {tax?.func_types.map(t => (
                <button key={t.key}
                  className={'mpl-chip ' + (funcFilter === t.key ? 'on' : '')}
                  onClick={() => setFuncFilter(funcFilter === t.key ? '' : t.key)}
                  title={t.desc}>
                  {t.label} <b>{t.count}</b>
                </button>
              ))}
            </div>
            {funcFilter && tax && (
              <div className="muted mpl-tax-desc">
                {tax.func_types.find(t => t.key === funcFilter)?.desc}
              </div>
            )}

            <div className="mpl-tax-head" style={{ marginTop: 16 }}>
              <h3>按使用类型分类</h3>
              <span className="muted">提示词以何种方式参与生成</span>
            </div>
            <div className="mpl-chips">
              <button className={'mpl-chip alt ' + (usageFilter === '' ? 'on' : '')}
                onClick={() => setUsageFilter('')}>全部</button>
              {tax?.usage_types.map(t => (
                <button key={t.key}
                  className={'mpl-chip alt ' + (usageFilter === t.key ? 'on' : '')}
                  onClick={() => setUsageFilter(usageFilter === t.key ? '' : t.key)}
                  title={t.desc}>
                  {t.label} <b>{t.count}</b>
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="mpl-toolbar">
              <input className="mpl-search" placeholder="搜索名称 / key / 模块 / 提示词正文…"
                value={keyword} onChange={e => setKeyword(e.target.value)} />
              <span className="muted">共 {filteredCount} 条</span>
              {(funcFilter || usageFilter || keyword) && (
                <button className="btn small ghost" onClick={resetFilters}>清空筛选</button>
              )}
            </div>

            {loading ? <div className="muted">加载中…</div> : groups.length === 0 ? (
              <div className="muted">没有匹配的提示词，试试清空筛选条件。</div>
            ) : groups.map(g => {
              const isPreset = PRESET_FUNCS.has(g.key)
              // 用户已明确筛选时自动展开，避免「筛完还要再点一次展开」
              const hasFilter = !!(funcFilter || usageFilter || keyword.trim())
              const collapsed = !!collapsedGroups[g.key] && !hasFilter
              return (
                <div key={g.key} className="mpl-group">
                  <div className="mpl-group-head">
                    <div>
                      <span className="mpl-cat">{g.label}</span>
                      <span className="muted" style={{ marginLeft: 10 }}>{g.desc}</span>
                    </div>
                    <div className="mpl-group-actions">
                      <span className="pill off">{g.items.length} 条</span>
                      {isPreset && !hasFilter && (
                        <button className="btn small ghost"
                          onClick={() => setCollapsedGroups(v => ({ ...v, [g.key]: !v[g.key] }))}>
                          {collapsed ? '展开' : '收起'}
                        </button>
                      )}
                    </div>
                  </div>
                  {!collapsed && (
                    <div className={isPreset ? 'mpl-grid preset' : 'mpl-grid'}>
                      {g.items.map(p => {
                        const isShort = (p.content || '').length <= 240
                        const open = !!expanded[p.key]
                        return (
                          <div key={p.key} className={'card mpl-item' + (p.is_active ? '' : ' inactive')}>
                            <div className="mpl-item-head">
                              <b>{p.name}</b>
                              <span className="pill off mono">{p.key}</span>
                              <span className="mpl-badge">{USAGE_LABEL[p.usage_type || ''] || '未分类'}</span>
                              <span className={'pill ' + (p.is_active ? 'ok' : 'off')}>
                                {p.is_active ? '生效中' : '已停用'}
                              </span>
                            </div>
                            <div className="muted mpl-meta">
                              {p.category && <span>分类：{p.category}</span>}
                              <span>模块：{p.module}</span>
                            </div>
                            {p.description && <div className="muted mpl-desc">{p.description}</div>}
                            <pre className="prompt-pre mpl-pre">
                              {open || isShort ? p.content : preview(p.content)}
                            </pre>
                            <div className="mpl-item-foot">
                              {!isShort && (
                                <button className="btn small ghost"
                                  onClick={() => setExpanded(v => ({ ...v, [p.key]: !v[p.key] }))}>
                                  {open ? '收起' : '展开全文'}
                                </button>
                              )}
                              {isAdmin && (
                                <>
                                  <button className="btn small" onClick={() => openEdit(p)}>编辑</button>
                                  <button className="btn small ghost" onClick={() => toggleActive(p)}>
                                    {p.is_active ? '停用' : '启用'}
                                  </button>
                                  <button className="btn small ghost" onClick={() => reset(p)}>恢复默认</button>
                                </>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* ==================== 视图二：优秀提示词总结库 ==================== */}
      {view === 'library' && (
        <>
          <div className="card mpl-defaults">
            <h3>当前系统默认 · 直接影响最终生成结果</h3>
            <div className="mpl-default-grid">
              {['ad_copy', 'ad_image'].map(k => {
                const d = lib?.defaults?.[k]
                return (
                  <div className="mpl-default-card" key={k}>
                    <div className="muted">{d?.label || (k === 'ad_copy' ? '广告推广文案' : '广告推广图片')}</div>
                    <b>{d?.name || '系统内置默认'}</b>
                    <div className="muted mpl-desc">{d?.source || '内置提示词'}</div>
                    <div className="mpl-default-foot">
                      {d?.customized && <span className="pill off">已在目录中自定义</span>}
                      {d?.builtin ? <span className="pill off">内置默认</span>
                        : <span className="pill ok">总结库模板</span>}
                      {isAdmin && d && !d.builtin && (
                        <button className="btn small ghost"
                          onClick={() => setDefault(null, '内置默认', k)}>
                          恢复内置默认
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="card">
            <div className="mpl-kindtabs">
              {(lib?.kinds || [{ key: 'ad_copy', label: '广告推广文案' }, { key: 'ad_image', label: '广告推广图片' }]).map(k => (
                <button key={k.key} className={libKind === k.key ? 'on' : ''}
                  onClick={() => { setLibKind(k.key); setDims({ ...EMPTY_DIMS }) }}>
                  {k.label}
                </button>
              ))}
              <span className="muted">按维度筛选，选择适合的系统默认提示词类型</span>
            </div>

            <div className="mpl-filters">
              {lib?.dimensions.map(d => (
                <label key={d.key}>
                  <span>{d.label}</span>
                  <select value={dims[d.key as DimKey] || ''}
                    onChange={e => setDims(v => ({ ...v, [d.key]: e.target.value }))}>
                    <option value="">全部</option>
                    {d.options.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                </label>
              ))}
              <label className="mpl-filter-q">
                <span>关键词</span>
                <input placeholder="框架名 / 标签 / 正文…" value={dims.q}
                  onChange={e => setDims(v => ({ ...v, q: e.target.value }))} />
              </label>
              <button className="btn small ghost" onClick={() => setDims({ ...EMPTY_DIMS })}>重置</button>
            </div>

            <div className="muted mpl-result">
              {libBusy ? '加载中…' : `匹配 ${lib?.total ?? 0} 条 / 全库 ${lib?.all_total ?? 0} 条`}
            </div>

            {!libBusy && (lib?.items.length || 0) === 0 && (
              <div className="muted">没有匹配的模板，试试放宽筛选条件。</div>
            )}
            <div className="mpl-lib-grid">
              {lib?.items.map(it => {
                const isDefault = currentDefault?.id === it.id
                return (
                  <div key={it.id} className={'card mpl-lib-card' + (isDefault ? ' is-default' : '')}>
                    <div className="mpl-lib-head">
                      <b>{it.name}</b>
                      {isDefault && <span className="pill ok">当前默认</span>}
                    </div>
                    <div className="mpl-tags">
                      <span className="mpl-tag t1">{it.type}</span>
                      <span className="mpl-tag t2">{it.style}</span>
                      <span className="mpl-tag t3">{it.scene}</span>
                      <span className="mpl-tag t4">{it.audience}</span>
                    </div>
                    <div className="muted mpl-desc">{it.summary}</div>
                    <div className="muted mpl-source">
                      来源：{it.source}<br />
                      适用平台：{it.platforms.join(' / ')}
                    </div>
                    <div className="mpl-item-foot">
                      <button className="btn small ghost" onClick={() => setViewItem(it)}>查看提示词正文</button>
                      {isAdmin && !isDefault && (
                        <button className="btn small" onClick={() => setDefault(it.id, it.name)}>设为系统默认</button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}

      {/* ---------------- 目录编辑弹窗 ---------------- */}
      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>编辑提示词：{editing.name}</h3>
            <div className="prompt-meta">
              <span><b>key：</b>{editing.key}</span>
              <span><b>模块：</b>{editing.module}</span>
            </div>
            {editing.description && <div className="muted" style={{ fontSize: 12.5 }}>{editing.description}</div>}
            <div className="mpl-edit-meta">
              <label>功能类型
                <select value={editFunc} onChange={e => setEditFunc(e.target.value)}>
                  {(tax?.func_types || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
              </label>
              <label>使用类型
                <select value={editUsage} onChange={e => setEditUsage(e.target.value)}>
                  {(tax?.usage_types || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
              </label>
            </div>
            <label>提示词正文</label>
            <textarea value={draft} onChange={e => setDraft(e.target.value)}
              className="prompt-editor" spellCheck={false} />
            <div className="muted" style={{ fontSize: 12.5 }}>
              可用 <code>[[SCHEMA]]</code> / <code>[[LIMITS]]</code> / <code>[[LANGUAGE]]</code> /{' '}
              <code>[[PLATFORM]]</code> 等占位符注入运行时变量；不写占位符时系统会自动追加输出契约。
              保存后即时生效，影响此后所有该环节的调用。
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

      {/* ---------------- 总结库正文弹窗 ---------------- */}
      {viewItem && (
        <div className="modal-overlay" onClick={() => setViewItem(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>{viewItem.name}</h3>
            <div className="mpl-tags">
              <span className="mpl-tag t1">{viewItem.type}</span>
              <span className="mpl-tag t2">{viewItem.style}</span>
              <span className="mpl-tag t3">{viewItem.scene}</span>
              <span className="mpl-tag t4">{viewItem.audience}</span>
            </div>
            <div className="muted" style={{ marginTop: 8 }}>{viewItem.summary}</div>
            <div className="muted mpl-source">方法论来源：{viewItem.source}　｜　标签：{viewItem.tags.join('、')}</div>
            <label style={{ marginTop: 12 }}>提示词正文</label>
            <pre className="prompt-pre mpl-lib-pre">{viewItem.content}</pre>
            <div className="muted" style={{ fontSize: 12.5 }}>
              设为默认后，系统会在生成时自动追加字段结构 / 字数红线 / 语言 / no-text 等输出契约，
              因此本模板只专注角色、方法论与风格约束。
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 14, justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={() => setViewItem(null)}>关闭</button>
              {isAdmin && currentDefault?.id !== viewItem.id && (
                <button className="btn" onClick={() => setDefault(viewItem.id, viewItem.name)}>设为系统默认</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
