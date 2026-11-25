import { useEffect, useState } from 'react'
import { api, LoginLog, LogStats } from '../api'
import { fmtBeijing } from '../datetime'

type Tab = 'audit' | 'login'
type LoginFilter = 'all' | 'success' | 'fail'
type ActionFilter = 'all' | 'login' | 'logout'

export default function Logs() {
  const [tab, setTab] = useState<Tab>('audit')
  const [limit, setLimit] = useState(100)

  // 审计日志
  const [audit, setAudit] = useState<any[]>([])
  // 登录 / 登出日志
  const [logins, setLogins] = useState<LoginLog[]>([])
  const [loginFilter, setLoginFilter] = useState<LoginFilter>('all')
  const [actionFilter, setActionFilter] = useState<ActionFilter>('all')
  // V4.86：全表真实统计（与列表 limit / 搜索无关）
  const [stats, setStats] = useState<LogStats | null>(null)

  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [kw, setKw] = useState('')

  const load = async () => {
    setLoading(true); setErr('')
    try {
      // 统计独立拉取：失败不影响列表；用于标题显示准确总数
      api.logStats().then(setStats).catch(() => {})
      if (tab === 'audit') {
        setAudit(await api.auditLogs(limit))
      } else {
        const s = loginFilter === 'all' ? undefined : loginFilter === 'success'
        const a = actionFilter === 'all' ? undefined : actionFilter
        setLogins(await api.loginLogs(limit, s, a))
      }
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [tab, limit, loginFilter, actionFilter])

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
        (l.ip || '').toLowerCase().includes(kwLower) ||
        ((l.action === 'logout' ? '登出 logout' : '登录 login')).toLowerCase().includes(kwLower))
    : logins

  // 标题只显示后端全表总数；搜索 / limit 造成的「当前显示」另用小字标注，不再混为一谈
  const total = tab === 'audit' ? stats?.audit_total : stats?.login_total
  const shown = tab === 'audit' ? filteredAudit.length : filteredLogin.length
  const trimmed = stats != null && shown < (total ?? 0)

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h2>系统日志（共 {total == null ? '—' : total} 条）</h2>
            <div className="muted">
              {tab === 'audit'
                ? '审计日志：配置变更、账号操作、提示词修改等关键动作，用于追溯与合规检查。'
                : '登录 / 登出日志：记录账号名称、来源 IP 与时间，含成功与失败尝试，用于安全追溯。'}
              {trimmed && <span>　当前筛选显示 {shown} 条。</span>}
              {tab === 'login' && stats && (
                <span>　登录 {stats.login_count} 次（成功 {stats.login_success} / 失败 {stats.login_fail}），登出 {stats.logout_count} 次。</span>
              )}
            </div>
          </div>
          <div className="seg" style={{ display: 'inline-flex', gap: 4 }}>
            <button className={tab === 'audit' ? 'btn primary' : 'btn secondary'} onClick={() => setTab('audit')}>审计日志</button>
            <button className={tab === 'login' ? 'btn primary' : 'btn secondary'} onClick={() => setTab('login')}>登录日志</button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
          <input
            type="text" placeholder={tab === 'audit' ? '搜索动作 / 操作人 / 对象' : '搜索账号 / IP / 登录 / 登出'} value={kw}
            onChange={e => setKw(e.target.value)} style={{ width: 220, margin: 0 }}
          />
          <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={{ width: 'auto' }}>
            <option value={50}>最近 50 条</option>
            <option value={100}>最近 100 条</option>
            <option value={300}>最近 300 条</option>
            <option value={1000}>最近 1000 条</option>
          </select>
          {tab === 'login' && (
            <>
              <select value={actionFilter} onChange={e => setActionFilter(e.target.value as ActionFilter)} style={{ width: 'auto' }}>
                <option value="all">全部事件</option>
                <option value="login">仅登录</option>
                <option value="logout">仅登出</option>
              </select>
              <select value={loginFilter} onChange={e => setLoginFilter(e.target.value as LoginFilter)} style={{ width: 'auto' }}>
                <option value="all">全部状态</option>
                <option value="success">仅成功</option>
                <option value="fail">仅失败</option>
              </select>
            </>
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
                    <td className="muted">{fmtBeijing(l.created_at)}</td>
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
              <thead><tr><th style={{ width: 170 }}>时间</th><th>账号名称</th><th>IP 地址</th><th>事件 / 状态</th><th>详情</th></tr></thead>
              <tbody>
                {filteredLogin.map(l => (
                  <tr key={l.id}>
                    <td className="muted">{fmtBeijing(l.created_at)}</td>
                    <td>{l.username || '—'}</td>
                    <td><code style={{ fontSize: 12 }}>{l.ip || '—'}</code></td>
                    <td>
                      {(l.action || 'login') === 'logout'
                        ? <span className="pill off">登出</span>
                        : l.success
                          ? <span className="pill ok">登录成功</span>
                          : <span className="pill err">登录失败</span>}
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
