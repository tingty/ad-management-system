import { useState } from 'react'
import { api, setToken, User } from '../api'

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPwd, setShowPwd] = useState(false)
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
        <div className="muted" style={{ marginBottom: 18 }}>
          落地页分析 → 多平台素材生成 → 素材库 → 批量 → 审阅协作
        </div>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="login-email">邮箱</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="请输入登录邮箱"
              autoFocus
              autoComplete="username"
            />
          </div>

          <div className="field">
            <label htmlFor="login-pwd">密码</label>
            <div className="pwd-wrap">
              <input
                id="login-pwd"
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="请输入密码"
                autoComplete="current-password"
              />
              <button
                type="button"
                className="pwd-toggle"
                onClick={() => setShowPwd(v => !v)}
                aria-label={showPwd ? '隐藏密码' : '显示密码'}
                title={showPwd ? '隐藏密码' : '显示密码'}
              >
                {showPwd ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>

          <div style={{ marginTop: 20 }}>
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

function Eye() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeOff() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}
