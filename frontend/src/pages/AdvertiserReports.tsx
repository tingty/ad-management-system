/**
 * V4.135 / P3 · 广告主数据 / 广告主报表。
 * 概览 KPI、趋势、维度排行、明细列表与下钻全部消费 advertiser-data/reports/* 只读接口；
 * 字段名 / 顺序 / 单位 / 格式 / 枚举翻译读 api_field_label（后端 labels 接口），
 * 前端不硬编码任何业务字段中文名。口径只有佣金收入视角，不展示上游不存在的花费类指标。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  advertiserApi, ApiConnection, ReportColumn, ReportKpi, ReportTrend,
  ReportRankings, ReportDetails, ReportDrilldown,
} from '../api'

const EMPTY_KPI: ReportKpi = {
  net_sale_usd: 0, net_commission_usd: 0, order_count: 0, void_count: 0,
  detail_count: 0, avg_order_value_usd: 0, source_view: '', unavailable_metrics: [],
}

/** 按后端 format + enum_map + unit 渲染单元格，前端不做任何字段语义判断 */
function cell(v: unknown, col?: ReportColumn): string {
  if (v === null || v === undefined || v === '') return '—'
  const fmt = col?.format || 'text'
  const map = col?.enum_map || {}
  const unit = col?.unit ? ' ' + col.unit : ''
  if (fmt === 'enum' || fmt === 'bool') {
    const key = fmt === 'bool' ? (v === true || v === 1 || v === '1' ? '1' : '0') : String(v)
    if (map[key] !== undefined) return map[key]
  }
  if (fmt === 'decimal2') {
    const n = Number(v)
    return (isNaN(n) ? String(v) : n.toFixed(2)) + unit
  }
  if (fmt === 'int') return String(v) + unit
  return String(v) + unit
}

function money(v: number): string {
  return Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function AdvertiserReports() {
  const [connections, setConnections] = useState<ApiConnection[]>([])
  const [columns, setColumns] = useState<ReportColumn[]>([])
  const [dimensions, setDimensions] = useState<{ key: string; label: string }[]>([])
  const [connectionId, setConnectionId] = useState<number | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [dimension, setDimension] = useState('advertiser_name')
  const [dimValue, setDimValue] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [kpi, setKpi] = useState<ReportKpi>(EMPTY_KPI)
  const [trend, setTrend] = useState<ReportTrend>({ points: [], metric_labels: {}, total: 0 })
  const [rankings, setRankings] = useState<ReportRankings>({
    dimension: 'advertiser_name', dimension_label: '', items: [], metric_labels: {},
  })
  const [details, setDetails] = useState<ReportDetails>({
    rows: [], columns: [], total: 0, page: 1, page_size: 20, total_pages: 0, source_table: '',
  })
  const [drill, setDrill] = useState<ReportDrilldown | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const filter = useMemo(() => ({
    connection_id: connectionId === '' ? undefined : Number(connectionId),
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  }), [connectionId, dateFrom, dateTo])

  // 一次性加载配置：连接下拉、字段标签、维度白名单
  useEffect(() => {
    let alive = true
    Promise.all([
      advertiserApi.connections(),
      advertiserApi.reportLabels('fact'),
      advertiserApi.reportDimensions(),
    ]).then(([conns, labels, dims]) => {
      if (!alive) return
      setConnections(conns || [])
      setColumns(labels?.columns || [])
      setDimensions(dims?.dimensions || [])
    }).catch((e) => alive && setError(e?.message || '配置加载失败'))
    return () => { alive = false }
  }, [])

  // 筛选变化即刷新四块报表数据；任何一块失败都不伪装成空数据
  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    const trendFilter = { ...filter, dimension, dimension_value: dimValue || undefined }
    Promise.all([
      advertiserApi.reportKpi(filter),
      advertiserApi.reportTrend(trendFilter),
      advertiserApi.reportRankings({ ...filter, dimension }),
      advertiserApi.reportDetails({ ...filter, keyword: keyword || undefined, page }),
    ]).then(([k, t, r, d]) => {
      if (!alive) return
      setKpi(k); setTrend(t); setRankings(r); setDetails(d)
    }).catch((e) => alive && setError(e?.message || '报表加载失败'))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [filter, dimension, dimValue, keyword, page])

  function resetFilter() {
    setConnectionId(''); setDateFrom(''); setDateTo(''); setDimValue('')
    setKeyword(''); setPage(1)
  }

  const colBy = (key: string) => columns.find((c) => c.column_key === key)
  const saleLabel = rankings.metric_labels?.net_sale_usd || colBy('sale_amount_usd')?.label || '销售额'
  const commLabel = rankings.metric_labels?.net_commission_usd || colBy('commission_amount_usd')?.label || '佣金金额'

  return (
    <div className="ad-data-page">
      <div className="ad-sec-head">
        <div>
          <h2 className="ad-sec-title">佣金收入概览</h2>
          <p className="ad-sec-desc">
            数据来自已落库的广告主 API 订单佣金明细，按订单最终口径聚合
            {kpi.source_view ? `（${kpi.source_view}）` : ''}；表头与字段名由展示名配置驱动。
          </p>
        </div>
      </div>

      <div className="ad-filter-bar">
        <label>API 连接
          <select value={connectionId} onChange={(e) => {
            setConnectionId(e.target.value ? Number(e.target.value) : ''); setPage(1)
          }}>
            <option value="">全部连接</option>
            {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>起始日期<input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1) }} /></label>
        <label>结束日期<input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1) }} /></label>
        <label>维度
          <select value={dimension} onChange={(e) => { setDimension(e.target.value); setDimValue(''); setPage(1) }}>
            {dimensions.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
        </label>
        <label>维度值<input value={dimValue} placeholder="精确匹配（可空）"
          onChange={(e) => { setDimValue(e.target.value); setPage(1) }} /></label>
        <label>关键词<input value={keyword} placeholder="订单号 / 佣金ID / 广告主"
          onChange={(e) => { setKeyword(e.target.value); setPage(1) }} /></label>
        <button className="ad-btn ad-btn-ghost" onClick={resetFilter}>重置</button>
        {loading && <span className="ad-inline-hint">加载中…</span>}
      </div>

      {error && <div className="ad-msg ad-msg-error">报表加载失败：{error}</div>}

      <div className="ad-kpi-grid">
        <div className="card ad-kpi"><span>{colBy('sale_amount_usd')?.label || '销售额'}（{colBy('sale_amount_usd')?.unit || 'USD'}）</span><b>{money(kpi.net_sale_usd)}</b></div>
        <div className="card ad-kpi"><span>{colBy('commission_amount_usd')?.label || '佣金'}</span><b>{money(kpi.net_commission_usd)}</b></div>
        <div className="card ad-kpi"><span>订单数</span><b>{kpi.order_count}</b></div>
        <div className="card ad-kpi"><span>取消单</span><b>{kpi.void_count}</b></div>
        <div className="card ad-kpi"><span>平均客单价</span><b>{money(kpi.avg_order_value_usd)}</b></div>
      </div>

      <div className="ad-report-grid">
        <div className="card ad-panel">
          <div className="ad-panel-head"><h3>趋势</h3><span className="muted">按事件日期 · 订单最终口径</span></div>
          <TrendChart trend={trend} saleLabel={saleLabel} commLabel={commLabel} />
        </div>
        <div className="card ad-panel">
          <div className="ad-panel-head">
            <h3>{rankings.dimension_label || '维度'}排行</h3>
            <span className="muted">点击项可筛选趋势</span>
          </div>
          {rankings.items.length === 0 && <div className="ad-empty">暂无数据</div>}
          <div className="ad-rank-list">
            {rankings.items.map((it, i) => {
              const max = rankings.items[0]?.net_commission_usd || 1
              const pct = Math.max(2, Math.round((it.net_commission_usd / (max || 1)) * 100))
              return (
                <button key={`${it.name}-${i}`} className="ad-rank-row"
                  onClick={() => { setDimValue(it.name); setPage(1) }}>
                  <span className="ad-rank-name" title={it.name}>{it.name}</span>
                  <span className="ad-rank-bar"><i style={{ width: `${pct}%` }} /></span>
                  <span className="ad-rank-val">{money(it.net_commission_usd)} · {it.order_count} 单</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <div className="card ad-panel">
        <div className="ad-panel-head">
          <h3>佣金明细</h3>
          <span className="muted">共 {details.total} 条 · 点击行查看下钻链路</span>
        </div>
        <div className="ad-table-wrap">
          <table className="ad-table">
            <thead>
              <tr>
                {details.columns.map((c) => <th key={c.column_key}>{c.label}{c.unit ? ` (${c.unit})` : ''}</th>)}
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {details.rows.length === 0 && (
                <tr><td colSpan={details.columns.length + 1} className="ad-empty">暂无明细数据</td></tr>
              )}
              {details.rows.map((row, i) => (
                <tr key={i} onClick={() => advertiserApi.reportDrilldown(Number(row.id))
                  .then(setDrill).catch((e) => setError(e?.message || '下钻失败'))}>
                  {details.columns.map((c) => (
                    <td key={c.column_key}>{cell(row[c.column_key], c)}</td>
                  ))}
                  <td><button className="ad-link-btn">下钻</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {details.total_pages > 1 && (
          <div className="ad-pager">
            <button className="ad-btn ad-btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
            <span>第 {page} / {details.total_pages} 页</span>
            <button className="ad-btn ad-btn-ghost" disabled={page >= details.total_pages} onClick={() => setPage((p) => p + 1)}>下一页</button>
          </div>
        )}
      </div>

      <div className="ad-msg">
        说明：上游接口不返回花费 / 曝光 / 点击，因此不提供投资回报与转化率类指标；报表仅呈现佣金收入视角。
      </div>

      {drill && <DrilldownDrawer data={drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

/** 纯 SVG 双线趋势图（无外部图表依赖）：销售 / 佣金按事件日期 */
function TrendChart({ trend, saleLabel, commLabel }: {
  trend: ReportTrend; saleLabel: string; commLabel: string
}) {
  const pts = trend.points || []
  if (pts.length === 0) return <div className="ad-empty">暂无趋势数据</div>
  const W = 680, H = 220, L = 64, R = 16, T = 18, B = 34
  const max = Math.max(1, ...pts.flatMap((p) => [p.net_sale_usd, p.net_commission_usd]))
  const x = (i: number) => L + (pts.length === 1 ? (W - L - R) / 2 : i * (W - L - R) / (pts.length - 1))
  const y = (v: number) => T + (H - T - B) * (1 - v / max)
  const line = (key: 'net_sale_usd' | 'net_commission_usd') =>
    pts.map((p, i) => `${x(i)},${y(p[key])}`).join(' ')
  const ticks = [0, 0.5, 1].map((f) => ({ v: max * f, yy: y(max * f) }))
  const labelEvery = Math.max(1, Math.ceil(pts.length / 8))
  return (
    <div className="ad-chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="销售与佣金趋势">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={t.yy} y2={t.yy} stroke="var(--border, #e2e8f0)" strokeWidth={1} />
            <text x={L - 8} y={t.yy + 4} textAnchor="end" fontSize={10} fill="var(--muted, #64748b)">{money(t.v)}</text>
          </g>
        ))}
        <polyline fill="none" stroke="#2563eb" strokeWidth={2} points={line('net_sale_usd')} />
        <polyline fill="none" stroke="#059669" strokeWidth={2} points={line('net_commission_usd')} />
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(p.net_sale_usd)} r={2.5} fill="#2563eb" />
            <circle cx={x(i)} cy={y(p.net_commission_usd)} r={2.5} fill="#059669" />
            {i % labelEvery === 0 && (
              <text x={x(i)} y={H - 10} textAnchor="middle" fontSize={10} fill="var(--muted, #64748b)">{p.event_date}</text>
            )}
          </g>
        ))}
      </svg>
      <div className="ad-chart-legend">
        <span><i style={{ background: '#2563eb' }} />{saleLabel}</span>
        <span><i style={{ background: '#059669' }} />{commLabel}</span>
      </div>
    </div>
  )
}

/** 下钻抽屉：事实行 → 商品/扩展子表 → 原始 JSON + 字段映射规则 */
function DrilldownDrawer({ data, onClose }: { data: ReportDrilldown; onClose: () => void }) {
  const colBy = (key: string) => (data.columns || []).find((c) => c.column_key === key)
  const fact = data.fact || {}
  return (
    <div className="ad-drawer-mask" onClick={onClose}>
      <aside className="ad-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="ad-drawer-head">
          <h3>明细下钻 · {String(fact.order_id || fact.commission_id || '—')}</h3>
          <button className="ad-btn ad-btn-ghost" onClick={onClose}>关闭</button>
        </div>
        <div className="ad-drawer-body">
          {!data.found && <div className="ad-empty">无权查看该记录或记录不存在</div>}
          {data.found && <>
            <h4>统一事实行</h4>
            <table className="ad-table ad-table-compact">
              <tbody>
                {(data.columns || []).map((c) => (
                  <tr key={c.column_key}><th>{c.label}</th><td>{cell(fact[c.column_key], c)}</td></tr>
                ))}
              </tbody>
            </table>
            {(data.items || []).length > 0 && <>
              <h4>商品明细</h4>
              <table className="ad-table ad-table-compact">
                <thead><tr><th>SKU</th><th>数量</th><th>单价</th><th>佣金</th></tr></thead>
                <tbody>
                  {(data.items || []).map((it, i) => (
                    <tr key={i}><td>{String(it.sku ?? '—')}</td><td>{String(it.quantity ?? '—')}</td>
                      <td>{String(it.unit_price_usd ?? '—')}</td><td>{String(it.commission_usd ?? '—')}</td></tr>
                  ))}
                </tbody>
              </table>
            </>}
            {data.ext && Object.keys(data.ext).length > 0 && <>
              <h4>扩展字段</h4><pre className="ad-json">{JSON.stringify(data.ext, null, 2)}</pre>
            </>}
            {data.source && <>
              <h4>原始 JSON（api_source_record）</h4>
              <pre className="ad-json">{JSON.stringify(data.source.payload_json, null, 2)}</pre>
            </>}
            {(data.field_maps || []).length > 0 && <>
              <h4>字段来源与转换规则（api_field_map）</h4>
              <table className="ad-table ad-table-compact">
                <thead><tr><th>目标字段</th><th>上游字段</th><th>转换</th><th>说明</th></tr></thead>
                <tbody>
                  {(data.field_maps || []).map((m, i) => (
                    <tr key={i}><td>{m.target_field}</td><td>{m.source_path}</td><td>{m.transform}</td><td>{m.note}</td></tr>
                  ))}
                </tbody>
              </table>
            </>}
            <div className="ad-msg">下钻链路：{(data.chain || []).join(' → ')}</div>
            <div className="ad-msg">列字段中文名取自展示名配置，例如「订单号」由配置提供（{colBy('order_id')?.column_key || 'order_id'}）。</div>
          </>}
        </div>
      </aside>
    </div>
  )
}
