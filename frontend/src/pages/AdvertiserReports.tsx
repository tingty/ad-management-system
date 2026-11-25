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
  const [connectionId, setConnectionId] = useState<number | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [kpi, setKpi] = useState<ReportKpi>(EMPTY_KPI)
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

  // 一次性加载配置：连接下拉、字段标签
  useEffect(() => {
    let alive = true
    Promise.all([
      advertiserApi.connections(),
      advertiserApi.reportLabels('fact'),
    ]).then(([conns, labels]) => {
      if (!alive) return
      setConnections(conns || [])
      setColumns(labels?.columns || [])
    }).catch((e) => alive && setError(e?.message || '配置加载失败'))
    return () => { alive = false }
  }, [])

  // 筛选变化即刷新 KPI + 明细；任何一块失败都不伪装成空数据
  useEffect(() => {
    let alive = true
    setLoading(true); setError(null)
    Promise.all([
      advertiserApi.reportKpi(filter),
      advertiserApi.reportDetails({ ...filter, keyword: keyword || undefined, page }),
    ]).then(([k, d]) => {
      if (!alive) return
      setKpi(k); setDetails(d)
    }).catch((e) => alive && setError(e?.message || '报表加载失败'))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [filter, keyword, page])

  function resetFilter() {
    setConnectionId(''); setDateFrom(''); setDateTo(''); setKeyword(''); setPage(1)
  }

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
            setConnectionId(e.target.value ? Number(e.target.value) : ''); setPage(1)
          }}>
            <option value="">全部连接</option>
            {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>起始日期<input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1) }} /></label>
        <label>结束日期<input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1) }} /></label>
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
