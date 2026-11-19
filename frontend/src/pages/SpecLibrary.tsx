import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

/**
 * V4.84 · 素材标准库（创意工作台二级菜单）
 *
 * 这是媒体素材规格的只读查阅视图，数据来自后端 /api/media-spec-library——
 * 与图片/视频生成链路共用同一份标准库（单一事实来源）。本页不做任何本地规格数字，
 * 每条规则展示核验分级（A 官方已核验 / B 内部制作基准 / C 待确认）、来源与核验日期，
 * 让投放与研发能统一核对、纠错：改规则只改后端标准库一处，页面与生成同时生效。
 */
type Entry = {
  spec_id: string
  platform: string; ad_product: string; asset_role: string; media: string
  verification: string; verification_label: string; source_url: string | null
  verified_on: string | null; sizes: string[]; min_sizes: string[]
  aspect_ratios: string[]; formats: string[]; max_bytes: number | null
  duration_min: number | null; duration_max: number | null; fps_min: number | null
  codec: string | null; companions: string[]; note: string; library_version: string
}

const VERIFY_COLOR: Record<string, { bg: string; fg: string }> = {
  A: { bg: '#e7f6ec', fg: '#137333' },   // 官方已核验 → 绿
  B: { bg: '#eef2f7', fg: '#3c5a7a' },   // 内部基准 → 蓝灰
  C: { bg: '#fff4e5', fg: '#a15c00' },   // 待确认 → 橙
}

function fmtBytes(n: number | null): string {
  if (!n) return '—'
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(n % 1024 ** 3 ? 1 : 0)} GB`
  if (n >= 1024 ** 1024) return `${(n / 1024 ** 1024).toFixed(n % 1024 ** 1024 ? 1 : 0)} MB`
  if (n >= 1024) return `${Math.round(n / 1024)} KB`
  return `${n} B`
}

function range(e: Entry): string {
  const dmin = e.duration_min, dmax = e.duration_max
  if (dmin != null && dmax != null) return `${dmin}–${dmax}s`
  if (dmin != null) return `≥${dmin}s`
  if (dmax != null) return `≤${dmax}s`
  return '—'
}

const th: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', fontSize: 12, color: 'var(--muted)', fontWeight: 600, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 10px', fontSize: 12.5, verticalAlign: 'top' }

export default function SpecLibrary() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [meta, setMeta] = useState<{ library_version: string; reviewed_on: string }>({ library_version: '', reviewed_on: '' })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [platform, setPlatform] = useState('全部')
  const [media, setMedia] = useState<'all' | 'image' | 'video'>('all')
  const [verify, setVerify] = useState<'all' | 'A' | 'B' | 'C'>('all')
  const [query, setQuery] = useState('')

  useEffect(() => {
    let alive = true
    api.mediaSpecLibrary()
      .then((d: any) => {
        if (!alive) return
        setEntries(Array.isArray(d.entries) ? d.entries : [])
        setMeta({ library_version: d.library_version || '', reviewed_on: d.reviewed_on || '' })
      })
      .catch((e: any) => { if (alive) setError(e?.message || '标准库加载失败') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  const platforms = useMemo(() => ['全部', ...Array.from(new Set(entries.map(e => e.platform)))], [entries])

  const filtered = useMemo(() => entries.filter(e => {
    if (platform !== '全部' && e.platform !== platform) return false
    if (media !== 'all' && e.media !== media) return false
    if (verify !== 'all' && e.verification !== verify) return false
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      return [e.platform, e.ad_product, e.asset_role, e.note, ...e.sizes, ...e.aspect_ratios]
        .join(' ').toLowerCase().includes(q)
    }
    return true
  }), [entries, platform, media, verify, query])

  const grouped = useMemo(() => {
    const m = new Map<string, Entry[]>()
    for (const e of filtered) {
      const k = e.platform
      if (!m.has(k)) m.set(k, [])
      m.get(k)!.push(e)
    }
    return Array.from(m.entries())
  }, [filtered])

  const counts = useMemo(() => ({
    A: entries.filter(e => e.verification === 'A').length,
    B: entries.filter(e => e.verification === 'B').length,
    C: entries.filter(e => e.verification === 'C').length,
  }), [entries])

  return (
    <div className="page">
      <div className="page-head">
        <h2>素材标准库</h2>
        <p className="muted">
          图片与视频素材规格的唯一标准来源。创意工作台生成图片/视频时直接引用本库规则，
          展示与生成始终一致；修改规格只需更新后端标准库一处。
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16, padding: '14px 16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', fontSize: 12.5 }}>
          <span>库版本 <b>{meta.library_version || '—'}</b></span>
          <span>核验日期 <b>{meta.reviewed_on || '—'}</b></span>
          <span style={{ color: VERIFY_COLOR.A.fg }}>● 官方已核验 {counts.A}</span>
          <span style={{ color: VERIFY_COLOR.B.fg }}>● 内部基准 {counts.B}</span>
          <span style={{ color: VERIFY_COLOR.C.fg }}>● 待确认 {counts.C}</span>
        </div>
        <p className="muted" style={{ margin: '10px 0 0', fontSize: 12 }}>
          说明：A 级来自各平台官方帮助文档并经联网核验，可作硬规则；B 级为内部制作基准，非官方上限；
          C 级为官方访问受限、入口冲突或账户能力待确认，不自动判定合规。所有未知项留空，不编造最大值。
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16, padding: '12px 16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <label style={{ fontSize: 12.5 }}>
            平台{' '}
            <select value={platform} onChange={e => setPlatform(e.target.value)}>
              {platforms.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 12.5 }}>
            类型{' '}
            <select value={media} onChange={e => setMedia(e.target.value as any)}>
              <option value="all">全部</option>
              <option value="image">图片</option>
              <option value="video">视频</option>
            </select>
          </label>
          <label style={{ fontSize: 12.5 }}>
            核验{' '}
            <select value={verify} onChange={e => setVerify(e.target.value as any)}>
              <option value="all">全部</option>
              <option value="A">官方已核验</option>
              <option value="B">内部基准</option>
              <option value="C">待确认</option>
            </select>
          </label>
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索产品 / 尺寸 / 比例" style={{ minWidth: 200 }} />
          <span className="muted" style={{ fontSize: 12 }}>共 {filtered.length} 条规则</span>
        </div>
      </div>

      {loading && <div className="card muted">标准库加载中…</div>}
      {error && <div className="card" style={{ color: '#b42318' }}>{error}</div>}
      {!loading && !error && grouped.length === 0 && <div className="card muted">没有符合条件的规格规则。</div>}

      {grouped.map(([plat, rows]) => (
        <div className="card" key={plat} style={{ marginBottom: 16, padding: '4px 0', overflowX: 'auto' }}>
          <div style={{ padding: '12px 16px 8px', fontWeight: 700, fontSize: 14 }}>{plat}</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={th}>广告产品 / 角色</th>
                <th style={th}>类型</th>
                <th style={th}>核验</th>
                <th style={th}>尺寸 / 比例</th>
                <th style={th}>格式 / 大小</th>
                <th style={th}>时长 / 帧率</th>
                <th style={th}>伴随素材</th>
                <th style={th}>来源</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => {
                const vc = VERIFY_COLOR[e.verification] || VERIFY_COLOR.C
                return (
                  <tr key={e.spec_id || i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{e.ad_product}</div>
                      <div className="muted" style={{ fontSize: 11 }}>{e.asset_role}</div>
                    </td>
                    <td style={td}>{e.media === 'video' ? '视频' : '图片'}</td>
                    <td style={td}>
                      <span style={{ background: vc.bg, color: vc.fg, padding: '2px 7px', borderRadius: 6, fontSize: 11, whiteSpace: 'nowrap' }}
                        title={e.verification_label}>{e.verification} · {e.verification_label}</span>
                    </td>
                    <td style={td}>
                      <div>{e.sizes?.length ? e.sizes.join('、') : (e.min_sizes?.length ? '最低 ' + e.min_sizes.join('、') : '—')}</div>
                      <div className="muted" style={{ fontSize: 11 }}>{e.aspect_ratios?.length ? e.aspect_ratios.join(' / ') : ''}</div>
                    </td>
                    <td style={td}>
                      <div>{e.formats?.length ? e.formats.join('/') : '—'}</div>
                      <div className="muted" style={{ fontSize: 11 }}>{fmtBytes(e.max_bytes)}</div>
                    </td>
                    <td style={td}>
                      <div>{range(e)}</div>
                      <div className="muted" style={{ fontSize: 11 }}>{e.fps_min ? `≥${e.fps_min}fps` : ''}{e.codec ? ` · ${e.codec}` : ''}</div>
                    </td>
                    <td style={td}>{e.companions?.length ? e.companions.join('、') : '—'}</td>
                    <td style={td}>
                      {e.source_url ? (
                        <a href={e.source_url} target="_blank" rel="noreferrer" style={{ fontSize: 11 }}>官方文档</a>
                      ) : <span className="muted" style={{ fontSize: 11 }}>—</span>}
                      {e.verified_on && <div className="muted" style={{ fontSize: 10 }}>{e.verified_on}</div>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.some(e => e.note) && (
            <div style={{ padding: '10px 16px 12px' }}>
              {rows.filter(e => e.note).map((e, i) => (
                <div key={i} className="muted" style={{ fontSize: 11.5, marginBottom: 4 }}>
                  <b style={{ color: 'var(--text)' }}>{e.ad_product}：</b>{e.note}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
