import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Logs() {
  const [logs, setLogs] = useState<any[]>([])
  const [limit, setLimit] = useState(100)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [kw, setKw] = useState('')

  const load = async (n: number) => {
    setLoading(true); setErr('')
    try { setLogs(await api.auditLogs(n)) } catch (e: any) { setErr(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load(limit) }, [limit])

  const filtered = kw
    ? logs.filter(l =>
        (l.action || '').toLowerCase().includes(kw.toLowerCase()) ||
        (l.username || '').toLowerCase().includes(kw.toLowerCase()) ||
        (l.target || '').toLowerCase().includes(kw.toLowerCase()))
    : logs

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h2>审计日志（{filtered.length} 条）</h2>
            <div className="muted">记录登录、配置变更、账号操作、提示词修改等关键动作，用于追溯与合规检查。</div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="text" placeholder="搜索动作 / 操作人 / 对象" value={kw}
              onChange={e => setKw(e.target.value)} style={{ width: 220, margin: 0 }}
            />
            <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={{ width: 'auto' }}>
              <option value={50}>最近 50 条</option>
              <option value={100}>最近 100 条</option>
              <option value={300}>最近 300 条</option>
              <option value={1000}>最近 1000 条</option>
            </select>
            <button className="btn secondary" onClick={() => load(limit)} disabled={loading}>
              {loading ? '刷新中…' : '刷新'}
            </button>
          </div>
        </div>
        {err && <div className="alert err">{err}</div>}
        {filtered.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无记录。</div> : (
          <table style={{ marginTop: 10 }}>
            <thead><tr><th style={{ width: 170 }}>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
            <tbody>
              {filtered.map(l => (
                <tr key={l.id}>
                  <td className="muted">{l.created_at ? new Date(l.created_at).toLocaleString() : '—'}</td>
                  <td>{l.username || '—'}</td>
                  <td><span className="pill off">{l.action}</span></td>
                  <td>{l.target || '—'}</td>
                  <td className="muted">
                    {l.detail ? <code style={{ fontSize: 11 }}>{JSON.stringify(l.detail)}</code> : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
