import { useState } from 'react'
import { api, Framework, Meta } from '../api'

export default function Analyze({ meta, onFramework, onNext }: {
  meta: Meta | null
  onFramework: (fw: Framework) => void
  onNext: () => void
}) {
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [fw, setFw] = useState<Framework | null>(null)

  const run = async () => {
    setLoading(true); setErr(''); setFw(null)
    try {
      const res = await api.analyze(url, text)
      setFw(res); onFramework(res)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="card">
        <h2>落地页分析 → 综合推广框架</h2>
        <div className="muted">粘贴落地页 URL 或产品说明文本，系统抽取产品/卖点/人群/地区/语言，并给出各投放平台策略侧重。</div>
        <label>落地页 URL（可选）</label>
        <input type="text" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/landing" />
        <label>落地页内容 / 产品说明</label>
        <textarea value={text} onChange={e => setText(e.target.value)} placeholder="例如：SuperSave 自动比价省钱购物 App，支持多平台优惠券聚合，覆盖欧美与拉美市场。" />
        <div style={{ marginTop: 14 }}>
          <button className="btn" onClick={run} disabled={loading || (!url && !text)}>
            {loading ? '分析中…' : '分析落地页'}
          </button>
        </div>
        {err && <div className="alert err">{err}</div>}
      </div>

      {fw && (
        <div className="card">
          <h2>推广框架 · {fw.product}</h2>
          <div className="kv">
            <div className="k">品类</div><div>{fw.category || '—'}</div>
            <div className="k">目标人群</div><div>{fw.audience || '—'}</div>
            <div className="k">地区</div><div>{fw.geo || '—'}</div>
            <div className="k">语言</div><div>{(fw.languages || []).join('、') || '—'}</div>
            <div className="k">卖点矩阵</div><div>{(fw.selling_points || []).join(' / ') || '—'}</div>
          </div>
          <h3>各平台综合分析</h3>
          <table>
            <thead><tr><th style={{ width: 130 }}>平台</th><th>策略侧重</th></tr></thead>
            <tbody>
              {Object.entries(fw.platform_analysis || {}).map(([p, v]) => (
                <tr key={p}><td><b>{p}</b></td><td>{v}</td></tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 14 }}>
            <button className="btn" onClick={onNext}>下一步：生成广告素材 →</button>
          </div>
        </div>
      )}
    </div>
  )
}
