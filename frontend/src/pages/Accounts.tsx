import { useEffect, useState } from 'react'
import { api, User } from '../api'

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', manager: '投放经理', editor: '投放执行', viewer: '只读',
}

type EditorState = {
  id: number | null
  email: string
  username: string
  password: string
  display_name: string
  role: string
}

const emptyForm: EditorState = { id: null, email: '', username: '', password: '', display_name: '', role: 'editor' }

export default function Accounts() {
  const [users, setUsers] = useState<User[]>([])
  const [modal, setModal] = useState<EditorState | null>(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  const load = async () => {
    try { setUsers(await api.users()) } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [])

  const openCreate = () => { setErr(''); setOk(''); setModal({ ...emptyForm }) }
  const openEdit = (u: User) => {
    setErr(''); setOk('')
    setModal({ id: u.id, email: u.email || '', username: u.username, password: '', display_name: u.display_name || '', role: u.role })
  }

  const save = async () => {
    if (!modal) return
    setErr(''); setOk('')
    try {
      if (modal.id) {
        const patch: any = { display_name: modal.display_name, role: modal.role }
        if (modal.password) patch.password = modal.password
        await api.updateUser(modal.id, patch)
        setOk(`已更新账号 ${modal.username}`)
      } else {
        await api.createUser({ email: modal.email.trim(), password: modal.password, display_name: modal.display_name, role: modal.role })
        setOk(`已创建账号 ${modal.email.trim()}`)
      }
      setModal(null)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const toggleActive = async (u: User) => {
    if (u.active && !confirm(`确认停用 ${u.username}？该账号将无法登录，历史记录保留。`)) return
    setErr(''); setOk('')
    try { await api.updateUser(u.id, { active: !u.active }); await load(); setOk(`${u.username} 已${u.active ? '停用' : '启用'}`) }
    catch (e: any) { setErr(e.message) }
  }

  const modalValid = !!modal && (modal.id ? true : (!!modal.email.trim() && modal.password.length >= 6))

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h2>账号与角色（{users.length}）</h2>
            <div className="muted">角色决定可见页面与可执行动作；停用为软删除，审阅/审计记录保留。</div>
          </div>
          <button className="btn" onClick={openCreate}>＋ 新建账号</button>
        </div>
        {err && <div className="alert err">{err}</div>}
        {ok && <div className="alert ok">{ok}</div>}
        <table style={{ marginTop: 10 }}>
          <thead><tr><th>ID</th><th>邮箱</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>{u.email || u.username}</td>
                <td className="muted">{u.display_name || '—'}</td>
                <td>{ROLE_LABEL[u.role] || u.role}</td>
                <td><span className={'pill ' + (u.active ? 'ok' : 'off')}>{u.active ? '启用' : '停用'}</span></td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn small ghost" onClick={() => openEdit(u)}>编辑</button>
                    <button className="btn small danger" onClick={() => toggleActive(u)}>
                      {u.active ? '停用' : '启用'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{modal.id ? `编辑账号：${modal.username}` : '新建账号'}</h3>
            {!modal.id && (
              <>
                <label>邮箱（登录账号，必填）</label>
                <input type="email" value={modal.email} onChange={e => setModal({ ...modal, email: e.target.value })} placeholder="name@company.com" />
              </>
            )}
            {modal.id && (
              <>
                <label>邮箱（登录账号）</label>
                <input type="email" value={modal.email} disabled readOnly />
              </>
            )}
            <label>显示名</label>
            <input type="text" value={modal.display_name} onChange={e => setModal({ ...modal, display_name: e.target.value })} />
            <label>{modal.id ? '重置密码（留空则不修改）' : '初始密码（≥6 位）'}</label>
            <input type="text" value={modal.password} onChange={e => setModal({ ...modal, password: e.target.value })} />
            <label>角色</label>
            <select value={modal.role} onChange={e => setModal({ ...modal, role: e.target.value })}>
              {Object.keys(ROLE_LABEL).map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
            <div className="muted" style={{ marginTop: 8 }}>
              角色权限：管理员全部功能 ｜ 投放经理可审阅 ｜ 投放执行可生成 ｜ 只读仅查看素材库与规格库。
            </div>
            {err && <div className="alert err">{err}</div>}
            <div style={{ display: 'flex', gap: 10, marginTop: 14, justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={() => setModal(null)}>取消</button>
              <button className="btn" onClick={save} disabled={!modalValid}>{modal.id ? '保存修改' : '创建账号'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
