import { useState } from 'react'
import { api, setToken, User } from '../api'

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setErr('')
    if (!email.trim() || !password) {
      setErr('请输入邮箱和密码')
      return
    }
    setBusy(true)
    try {
      const r = await api.login(email.trim(), password)
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
          <label>邮箱</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="请输入登录邮箱" autoFocus />
          <label>密码</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="请输入密码" />
          <div style={{ marginTop: 16 }}>
            <button className="btn" type="submit" disabled={busy} style={{ width: '100%' }}>
              {busy ? '登录中…' : '登录'}
            </button>
          </div>
        </form>
        {err && <div className="alert err">{err}</div>}
      </div>
    </div>
  )
}
