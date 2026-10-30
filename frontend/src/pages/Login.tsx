import { useState } from 'react'
import { api, setToken, User } from '../api'

const DEMO = [
  { u: 'admin', p: 'Admin@123', r: '管理员 · 全部权限' },
  { u: 'manager', p: 'Manager@123', r: '投放经理 · 审阅/规格' },
  { u: 'editor', p: 'Editor@123', r: '投放执行 · 生成/导出' },
  { u: 'viewer', p: 'Viewer@123', r: '只读账号' },
]

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('Admin@123')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await api.login(username.trim(), password)
      setToken(r.token)
      onLogin(r.user)
    } catch (e: any) {
      setErr(e.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>广告管理系统</h1>
        <div className="muted" style={{ marginBottom: 16 }}>
          落地页分析 → 多平台素材生成 → 素材库 → 批量 → 审阅协作
        </div>
        <form onSubmit={submit}>
          <label>用户名</label>
          <input type="text" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
          <label>密码</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} />
          <div style={{ marginTop: 16 }}>
            <button className="btn" type="submit" disabled={busy} style={{ width: '100%' }}>
              {busy ? '登录中…' : '登录'}
            </button>
          </div>
        </form>
        {err && <div className="alert err">{err}</div>}
        <div style={{ marginTop: 18 }}>
          <div className="muted" style={{ marginBottom: 6 }}>演示账号（点击填入）</div>
          <table>
            <tbody>
              {DEMO.map(d => (
                <tr key={d.u} style={{ cursor: 'pointer' }} onClick={() => { setUsername(d.u); setPassword(d.p) }}>
                  <td><code>{d.u}</code></td>
                  <td className="muted">{d.p}</td>
                  <td className="muted">{d.r}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
