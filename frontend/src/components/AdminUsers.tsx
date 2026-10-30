import { useEffect, useState } from 'react'
import { api, User } from '../api'

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', manager: '投放经理', editor: '投放执行', viewer: '只读',
}

export default function AdminUsers() {
  const [users, setUsers] = useState<User[]>([])
  const [logs, setLogs] = useState<any[]>([])
  const [form, setForm] = useState({ username: '', password: '', display_name: '', role: 'editor' })
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const load = async () => {
    try {
      setUsers(await api.users())
      setLogs(await api.auditLogs())
    } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    setErr(''); setOk('')
    try {
      await api.createUser(form)
      setOk(`已创建用户 ${form.username}`)
      setForm({ username: '', password: '', display_name: '', role: 'editor' })
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const changeRole = async (u: User, role: string) => {
    setErr(''); setOk('')
    try { await api.updateUser(u.id, { role: role as User['role'] }); await load(); setOk(`${u.username} 角色已改为 ${ROLE_LABEL[role]}`) }
    catch (e: any) { setErr(e.message) }
  }

  const deactivate = async (u: User) => {
    if (!confirm(`确认停用 ${u.username}？该账号将无法登录，历史记录保留。`)) return
    setErr(''); setOk('')
    try { await api.deactivateUser(u.id); await load(); setOk(`${u.username} 已停用`) }
    catch (e: any) { setErr(e.message) }
  }

  return (
    <div>
      <div className="card">
        <h2>用户与角色</h2>
        <div className="muted">角色决定可见页面与可执行动作；停用为软删除，审阅/审计记录保留。</div>
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}
        <table style={{ marginTop: 10 }}>
          <thead><tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>{u.username}</td>
                <td className="muted">{u.display_name || '—'}</td>
                <td>
                  <select value={u.role} style={{ width: 'auto' }}
                          onChange={e => changeRole(u, e.target.value)}>
                    {Object.keys(ROLE_LABEL).map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                  </select>
                </td>
                <td><span className={'pill ' + (u.active ? 'ok' : 'off')}>{u.active ? '启用' : '停用'}</span></td>
                <td>
                  {u.active
                    ? <button className="btn small danger" onClick={() => deactivate(u)}>停用</button>
                    : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>新增用户</h3>
        <div className="row">
          <div>
            <label>用户名</label>
            <input type="text" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
          </div>
          <div>
            <label>初始密码（≥6 位）</label>
            <input type="text" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
          </div>
          <div>
            <label>显示名</label>
            <input type="text" value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} />
          </div>
          <div>
            <label>角色</label>
            <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
              {Object.keys(ROLE_LABEL).map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="btn" onClick={create} disabled={!form.username || !form.password}>创建用户</button>
        </div>
      </div>

      <div className="card">
        <h2>审计日志（最近 50 条）</h2>
        {logs.length === 0 && <div className="muted">暂无记录。</div>}
        {logs.length > 0 && (
          <table>
            <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th></tr></thead>
            <tbody>
              {logs.map(l => (
                <tr key={l.id}>
                  <td className="muted">{l.created_at ? new Date(l.created_at).toLocaleString() : '—'}</td>
                  <td>{l.username || '—'}</td>
                  <td>{l.action}</td>
                  <td className="muted">{l.target || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
