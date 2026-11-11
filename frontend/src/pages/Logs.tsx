import { useEffect, useState } from 'react'
import { api, LoginLog } from '../api'

type Tab = 'audit' | 'login'

export default function Logs() {
  const [tab, setTab] = useState<Tab>('audit')
  const [limit, setLimit] = useState(100)

  // 审计日志
  const [audit, setAudit] = useState<any[]>([])
  // 登录日志
  const [logins, setLogins] = useState<LoginLog[]>([])
  const [loginFilter, setLoginFilter] = useState<'all' | 'success' | 'fail'>('all')

  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [kw, setKw] = useState('')

  const load = async () => {
    setLoading(true); setErr('')
    try {
      if (tab === 'audit') {
        setAudit(await api.auditLogs(limit))
      } else {
        const s = loginFilter === 'all' ? undefined : loginFilter === 'success'
        setLogins(await api.loginLogs(limit, s))
      }
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [tab, limit, loginFilter])

  const kwLower = kw.toLowerCase()
  const filteredAudit = kw
    ? audit.filter(l =>
        (l.action || '').toLowerCase().includes(kwLower) ||
        (l.username || '').toLowerCase().includes(kwLower) ||
        (l.target || '').toLowerCase().includes(kwLower))
    : audit
  const filteredLogin = kw
    ? logins.filter(l =>
        (l.username || '').toLowerCase().includes(kwLower) ||
        (l.ip || '').toLowerCase().includes(kwLower))
    : logins

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h2>系统日志（{tab === 'audit' ? filteredAudit.length : filteredLogin.length} 条）</h2>
            <div className="muted">
              {tab === 'audit'
                ? '审计日志：配置变更、账号操作、提示词修改等关键动作，用于追溯与合规检查。'
                : '登录日志：全部账号的登录记录（登陆账号名称 / 登陆 IP 地址 / 登陆时间），含成功与失败尝试，用于安全追溯。'}
            </div>
          </div>
          <div className="seg" style={{ display: 'inline-flex', gap: 4 }}>
            <button className={tab === 'audit' ? 'btn primary' : 'btn secondary'} onClick={() => setTab('audit')}>审计日志</button>
            <button className={tab === 'login' ? 'btn primary' : 'btn secondary'} onClick={() => setTab('login')}>登录日志</button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
          <input
            type="text" placeholder={tab === 'audit' ? '搜索动作 / 操作人 / 对象' : '搜索账号 / IP'} value={kw}
            onChange={e => setKw(e.target.value)} style={{ width: 220, margin: 0 }}
          />
          <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={{ width: 'auto' }}>
            <option value={50}>最近 50 条</option>
            <option value={100}>最近 100 条</option>
            <option value={300}>最近 300 条</option>
            <option value={1000}>最近 1000 条</option>
          </select>
          {tab === 'login' && (
            <select value={loginFilter} onChange={e => setLoginFilter(e.target.value as any)} style={{ width: 'auto' }}>
              <option value="all">全部</option>
              <option value="success">仅成功</option>
              <option value="fail">仅失败</option>
            </select>
          )}
          <button className="btn secondary" onClick={() => load()} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>

        {err && <div className="alert err">{err}</div>}

        {tab === 'audit' ? (
          filteredAudit.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无记录。</div> : (
            <table style={{ marginTop: 10 }}>
              <thead><tr><th style={{ width: 170 }}>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
              <tbody>
                {filteredAudit.map(l => (
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
          )
        ) : (
          filteredLogin.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>暂无记录。</div> : (
            <table style={{ marginTop: 10 }}>
              <thead><tr><th style={{ width: 170 }}>登陆时间</th><th>登陆账号名称</th><th>登陆 IP 地址</th><th>状态</th><th>详情</th></tr></thead>
              <tbody>
                {filteredLogin.map(l => (
                  <tr key={l.id}>
                    <td className="muted">{l.created_at ? new Date(l.created_at).toLocaleString() : '—'}</td>
                    <td>{l.username || '—'}</td>
                    <td><code style={{ fontSize: 12 }}>{l.ip || '—'}</code></td>
                    <td>
                      {l.success
                        ? <span className="pill ok">成功</span>
                        : <span className="pill err">失败</span>}
                    </td>
                    <td className="muted">
                      {l.detail ? <code style={{ fontSize: 11 }}>{JSON.stringify(l.detail)}</code> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  )
}
