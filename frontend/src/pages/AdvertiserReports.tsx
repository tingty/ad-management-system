/**
 * V4.124 广告主数据模块 · 「广告主报表」独立页面骨架。
 * 报表主体（KPI / 趋势 / 维度排行 / 明细下钻）在 P3 版本实现，
 * 本版仅建立独立路由与占位，表头届时统一读 api_field_label 配置。
 */
export default function AdvertiserReports() {
  return (
    <div className="ad-data-page">
      <div className="ad-sec-head">
        <div>
          <h2 className="ad-sec-title">佣金收入概览</h2>
          <p className="ad-sec-desc">数据来自已启用的广告主 API 连接，按订单佣金明细聚合。将在 P3 版本实现。</p>
        </div>
      </div>
      <div className="ad-kpi-grid">
        <div className="card ad-kpi"><span>总佣金（USD）</span><b>—</b></div>
        <div className="card ad-kpi"><span>总销售额（USD）</span><b>—</b></div>
        <div className="card ad-kpi"><span>订单数</span><b>—</b></div>
        <div className="card ad-kpi"><span>取消单</span><b>—</b></div>
      </div>
      <div className="card muted ad-placeholder">趋势 / 维度排行 / 明细下钻（规划中 · P3）。表头与字段名由 api_field_label 配置驱动，不在前端硬编码。</div>
      <div className="ad-msg">说明：CJ 接口不返回花费 / 曝光 / 点击，ROAS / ROI / CTR / CVR 无法由本 API 计算，报表仅呈现佣金收入视角。</div>
    </div>
  )
}
