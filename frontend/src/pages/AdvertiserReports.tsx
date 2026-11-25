/**
 * V4.135 / P3 · 广告主数据 / 广告主报表。
 * 概览 KPI、明细列表与下钻消费 advertiser-data/reports/* 只读接口；
 * 字段名 / 顺序 / 单位 / 格式 / 枚举翻译读 api_field_label（后端 labels 接口），
 * 前端不硬编码任何业务字段中文名。口径只有佣金收入视角，不展示上游不存在的花费类指标。
 * V4.136：按反馈精简为「KPI + 明细 + 下钻」，顶部只留主标题，移除解释说明与两个图表子模块。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  advertiserApi, ApiConnection, ReportColumn, ReportKpi, ReportDetails, ReportDrilldown,
  ReportFilter,
} from '../api'
import {
  fmtBeijing, reportRange, reportWindow, ReportRangeKey,
} from '../datetime'

const EMPTY_KPI: ReportKpi = {
  net_sale_usd: 0, net_commission_usd: 0, order_count: 0, void_count: 0,
  detail_count: 0, avg_order_value_usd: 0, source_view: '', unavailable_metrics: [],
}

/** V4.141：进入报表默认展示「本月」，首次加载即用该区间。 */
const DEFAULT_RANGE: ReportRangeKey = 'thisMonth'

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
  // V4.137：格式由后端 api_field_label 配置驱动，日期/时间一律按东八区展示。
  if (fmt === 'datetime') return fmtBeijing(String(v), { fallback: String(v) }) + unit
  if (fmt === 'date') return fmtBeijing(String(v), { fallback: String(v) }).slice(0, 10) + unit
  return String(v) + unit
}

function money(v: number): string {
  return Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 原始层 payload_json 可能是「JSON 字符串」而非对象，先反序列化再缩进，避免整行转义不可读。 */
function prettyPayload(v: unknown): string {
  if (typeof v === 'string') {
    try { return JSON.stringify(JSON.parse(v), null, 2) } catch { return v }
  }
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

export default function AdvertiserReports() {
  const [connections, setConnections] = useState<ApiConnection[]>([])
  const [columns, setColumns] = useState<ReportColumn[]>([])
  const [dimensions, setDimensions] = useState<{ key: string; label: string }[]>([])
  // 草稿条件：用户选择后不立即生效，点「查询」才提交到 applied。
  const [connectionId, setConnectionId] = useState<number | ''>('')
  const [rangeKey, setRangeKey] = useState<ReportRangeKey>(DEFAULT_RANGE)
  const initialWindow = useMemo(() => reportRange(DEFAULT_RANGE), [])
  const [dateFrom, setDateFrom] = useState(initialWindow.fromDate)
  const [dateTo, setDateTo] = useState(initialWindow.toDate)
  const [keyword, setKeyword] = useState('')
  const [dimension, setDimension] = useState('')
  const [dimensionValue, setDimensionValue] = useState('')
  const [page, setPage] = useState(1)
  // 已提交条件：首次进入用默认「本月」区间，进入即自动加载一次。
  const [applied, setApplied] = useState<ReportFilter>(() => ({
    date_from: initialWindow.from || undefined,
    date_to: initialWindow.to || undefined,
  }))
  const [kpi, setKpi] = useState<ReportKpi>(EMPTY_KPI)
  const [details, setDetails] = useState<ReportDetails>({
    rows: [], columns: [], total: 0, page: 1, page_size: 20, total_pages: 0, source_table: '',
  })
  const [drill, setDrill] = useState<ReportDrilldown | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 快捷区间与手动日期统一推导为 UTC 时间窗；日期输入框始终显示北京日期。
  const timeWindow = useMemo(() => {
    if (rangeKey) return reportRange(rangeKey)
    return reportWindow(dateFrom, dateTo)
  }, [rangeKey, dateFrom, dateTo])

  // 点「查询」才把草稿固化为已提交条件；选择筛选但不查询不会触发任何请求。
  function commitQuery() {
    setApplied({
      connection_id: connectionId === '' ? undefined : Number(connectionId),
      date_from: timeWindow.from || undefined,
      date_to: timeWindow.to || undefined,
      ...(dimension && dimensionValue ? { [dimension]: dimensionValue } : {}),
      keyword: keyword || undefined,
    })
    setPage(1)
  }

  // 一次性加载配置：连接下拉、字段标签、可选维度
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

  // 仅已提交条件变化 / 翻页才刷新 KPI + 明细；两块共用同一份 applied，口径一致。
  // 首次进入时 applied 已用默认「本月」初始化，因此会自动加载一次默认数据。
  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    Promise.all([
      advertiserApi.reportKpi(applied),
      advertiserApi.reportDetails({ ...applied, page }),
    ]).then(([k, d]) => {
      if (!alive) return
      setKpi(k); setDetails(d)
    }).catch((e) => alive && setError(e?.message || '报表加载失败'))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [applied, page])

  const colBy = (key: string) => columns.find((c) => c.column_key === key)

  return (
    <div className="ad-data-page">
      <div className="ad-sec-head">
        <div>
          <h2 className="ad-sec-title">佣金收入概览</h2>
        </div>
      </div>

      <div className="ad-filter-bar">
        <label>API 连接
          <select value={connectionId} onChange={(e) => {
            setConnectionId(e.target.value ? Number(e.target.value) : '')
          }}>
            <option value="">全部连接</option>
            {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>时间区间
          <select value={rangeKey} onChange={(e) => {
            const key = e.target.value as ReportRangeKey
            setRangeKey(key)
            if (key) {
              const w = reportRange(key)
              setDateFrom(w.fromDate); setDateTo(w.toDate)
            }
          }}>
            <option value="">自定义</option>
            <option value="today">今日</option>
            <option value="yesterday">昨日</option>
            <option value="last7">近七天</option>
            <option value="thisMonth">本月</option>
            <option value="lastMonth">上月（整月）</option>
          </select>
        </label>
        <label>起始日期<input type="date" value={dateFrom} onChange={(e) => {
          setRangeKey(''); setDateFrom(e.target.value)
        }} /></label>
        <label>结束日期<input type="date" value={dateTo} onChange={(e) => {
          setRangeKey(''); setDateTo(e.target.value)
        }} /></label>
        <label>维度
          <select value={dimension} onChange={(e) => {
            setDimension(e.target.value); setDimensionValue('')
          }}>
            <option value="">全部维度</option>
            {dimensions.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
        </label>
        <label>维度值<input value={dimensionValue} placeholder="精确匹配"
          onChange={(e) => { setDimensionValue(e.target.value) }} /></label>
        <label>关键词<input value={keyword} placeholder="订单号 / 佣金ID / 广告主"
          onChange={(e) => { setKeyword(e.target.value) }} /></label>
        {rangeKey === 'today' && <span className="ad-inline-hint">今日截至当前整点</span>}
        <button className="btn primary" onClick={commitQuery} disabled={loading}>查询</button>
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
                <tr><td colSpan={details.columns.length + 1} className="ad-empty">
                  暂无明细数据。报表只展示已落库的订单佣金明细；请到「API对接」对已保存的连接点「立即拉取明细」或「历史回填」完成落库后再查看。
                </td></tr>
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

      {drill && <DrilldownDrawer data={drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

/** 下钻抽屉：事实行 → 商品/扩展子表 → 原始 JSON + 字段映射规则 */
function DrilldownDrawer({ data, onClose }: { data: ReportDrilldown; onClose: () => void }) {
  const colBy = (key: string) => (data.columns || []).find((c) => c.column_key === key)
  const fact = data.fact || {}
  const titleKey = String(fact.order_id || fact.commission_id || '—')
  const chain = (data.chain || []).join(' → ')
  return (
    <div className="ad-drawer-mask" onClick={onClose}>
      <aside className="ad-drawer ad-drawer-wide" onClick={(e) => e.stopPropagation()}>
        <div className="ad-drawer-head">
          <div className="ad-drawer-title">
            <span className="ad-drawer-kicker">Commission drilldown</span>
            <h3>明细下钻 · {titleKey}</h3>
          </div>
          <button className="ad-drawer-x" aria-label="关闭" onClick={onClose}>×</button>
        </div>
        <div className="ad-drawer-body">
          {!data.found && <div className="ad-empty">无权查看该记录或记录不存在</div>}
          {data.found && <>
            <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">01</span>
                <h4>统一事实行</h4><span className="ad-drawer-sec-note">api_unified_fact</span></div>
              <div className="ad-drill-table-wrap">
                <table className="ad-table ad-table-compact">
                  <tbody>
                    {(data.columns || []).map((c) => (
                      <tr key={c.column_key}><th>{c.label}</th><td>{cell(fact[c.column_key], c)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            {(data.items || []).length > 0 && <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">02</span>
                <h4>商品明细</h4><span className="ad-drawer-sec-note">ApiFactItem</span></div>
              <div className="ad-sample-wrap">
                <table className="ad-sample-table">
                  <thead><tr><th>SKU</th><th>数量</th><th>单价</th><th>佣金</th></tr></thead>
                  <tbody>
                    {(data.items || []).map((it, i) => (
                      <tr key={i}><td><code>{String(it.sku ?? '—')}</code></td><td>{String(it.quantity ?? '—')}</td>
                        <td>{String(it.unit_price_usd ?? '—')}</td><td>{String(it.commission_usd ?? '—')}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>}
            {data.ext && Object.keys(data.ext).length > 0 && <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">03</span>
                <h4>扩展字段</h4><span className="ad-drawer-sec-note">api_fact_ext · 可完整滚动查阅</span></div>
              <pre className="ad-json-large">{prettyPayload(data.ext)}</pre>
            </section>}
            {data.source && <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">04</span>
                <h4>原始 JSON（api_source_record）</h4><span className="ad-drawer-sec-note">上游原文 · 可完整滚动查阅</span></div>
              <pre className="ad-json-large">{prettyPayload(data.source.payload_json)}</pre>
            </section>}
            {(data.field_maps || []).length > 0 && <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">05</span>
                <h4>字段来源与转换规则（api_field_map）</h4>
                <span className="ad-drawer-sec-note">展示名由配置提供</span></div>
              <div className="ad-sample-wrap">
                <table className="ad-sample-table">
                  <thead><tr><th>目标字段</th><th>上游字段</th><th>转换</th><th>说明</th></tr></thead>
                  <tbody>
                    {(data.field_maps || []).map((m, i) => (
                      <tr key={i}><td><code>{m.target_field}</code></td><td>{m.source_path}</td><td>{m.transform}</td><td>{m.note}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="ad-drawer-hint">列字段中文名取自展示名配置，例如「订单号」由配置提供（{colBy('order_id')?.column_key || 'order_id'}）。</p>
            </section>}
            <section className="ad-drawer-sec">
              <div className="ad-drawer-sec-head"><span className="ad-step">06</span>
                <h4>下钻链路</h4></div>
              <div className="ad-url-bar"><code>{chain || '—'}</code></div>
            </section>
          </>}
        </div>
        <footer className="ad-drawer-foot">
          <button className="btn primary" onClick={onClose}>关闭</button>
        </footer>
      </aside>
    </div>
  )
}
