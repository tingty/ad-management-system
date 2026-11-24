/**
 * V4.124 广告主数据模块 · 一级菜单下「广告主API」独立页面。
 * 界面按新需求独立设计，不复用也不改动现有模块的布局与功能。
 *
 * P0 已实现四区中的前两区：① 可用模板 ② 我的连接（含新建 / 测试 / 启停 / 删除）。
 * ③ 定期任务 ④ 运行记录为占位骨架，P2 落地。
 */
import { useCallback, useEffect, useState } from 'react'
import { advertiserApi, ApiConnection, ApiTemplate, ApiTestResult } from '../api'

type Msg = { kind: 'ok' | 'err'; text: string }

export default function AdvertiserApi() {
  const [templates, setTemplates] = useState<ApiTemplate[]>([])
  const [connections, setConnections] = useState<ApiConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState<Msg | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', template_code: 'cj_publisher_commissions', token: '', cid: '', endpoint: '' })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<number | 'new' | null>(null)
  const [testResult, setTestResult] = useState<ApiTestResult | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [ts, cs] = await Promise.all([advertiserApi.templates(), advertiserApi.connections()])
      setTemplates(ts); setConnections(cs)
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '加载失败' })
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const tpl = templates.find(t => t.code === form.template_code)

  async function create() {
    if (!form.token.trim()) { setMsg({ kind: 'err', text: '请填写 API Token' }); return }
    if (!form.cid.trim()) { setMsg({ kind: 'err', text: '请填写发布者 CID（不是登录邮箱）' }); return }
    setSaving(true); setMsg(null)
    try {
      await advertiserApi.createConnection(form)
      setShowForm(false)
      setForm(f => ({ ...f, name: '', token: '', cid: '', endpoint: '' }))
      setMsg({ kind: 'ok', text: '连接已创建（草稿）。请先测试连接，通过后再启用。' })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '创建失败' }) }
    finally { setSaving(false) }
  }

  async function test(c: ApiConnection | 'new') {
    setTesting(c === 'new' ? 'new' : c.id); setMsg(null); setTestResult(null)
    try {
      const body = c === 'new'
        ? { template_code: form.template_code, token: form.token, cid: form.cid, endpoint: form.endpoint }
        : { connection_id: c.id }
      const r = await advertiserApi.testConnection(body)
      setTestResult(r)
      setMsg(r.ok
        ? { kind: 'ok', text: `连接成功：过去 1 天返回 ${r.count} 条记录` }
        : { kind: 'err', text: r.error || '连接失败' })
      if (c !== 'new') await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '测试失败' }) }
    finally { setTesting(null) }
  }

  async function toggle(c: ApiConnection) {
    setMsg(null)
    try {
      const next = c.status === 'active' ? 'disabled' : 'active'
      await advertiserApi.updateConnection(c.id, { status: next })
      setMsg({ kind: 'ok', text: next === 'active' ? '连接已启用' : '连接已停用' })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '操作失败' }) }
  }

  async function remove(c: ApiConnection) {
    if (!window.confirm(`确认删除连接「${c.name}」？此操作不可恢复。`)) return
    setMsg(null)
    try { await advertiserApi.deleteConnection(c.id); setMsg({ kind: 'ok', text: '已删除' }); await load() }
    catch (e: any) { setMsg({ kind: 'err', text: e?.message || '删除失败' }) }
  }

  return (
    <div className="ad-data-page">
      <div className="ad-sec-head">
        <div>
          <h2 className="ad-sec-title">① 可用模板</h2>
          <p className="ad-sec-desc">模板固化接口怎么调（认证、查询、分页、限流）。新渠道 = 加一份模板，不改业务代码。</p>
        </div>
      </div>
      {loading ? <div className="card muted">加载中…</div> : (
        <div className="ad-tpl-grid">
          {templates.map(t => (
            <div className="card ad-tpl-card" key={t.code}>
              <div className="ad-tpl-top">
                <b>{t.name}</b><span className="chip">{t.vendor}</span>
                <span className="chip">{t.method}</span>
              </div>
              <p className="muted ad-tpl-desc">{t.description}</p>
              <div className="ad-tpl-meta">
                <span>查询：<code>{t.code}</code></span>
                <span>认证：{t.auth_type.toUpperCase()}</span>
                <span>端点：<code>{t.default_endpoint}</code></span>
              </div>
              <div className="ad-tpl-meta"><span className="muted">填写项：</span>
                {t.required_fields.map(f => <span className="chip" key={f.key}>{f.label}{f.required ? ' *' : ''}</span>)}
              </div>
              <div className="ad-tpl-limit">{t.limits}</div>
            </div>
          ))}
        </div>
      )}

      <div className="ad-sec-head ad-sec-gap">
        <div>
          <h2 className="ad-sec-title">② 我的 API 连接</h2>
          <p className="ad-sec-desc">只填 API Token / CID / Endpoint。Token 加密存储、列表脱敏、不回显、不写日志。</p>
        </div>
        <button className="btn primary" onClick={() => { setShowForm(v => !v); setMsg(null) }}>
          {showForm ? '收起' : '新建连接'}
        </button>
      </div>

      {msg && <div className={`ad-msg ${msg.kind}`}>{msg.text}</div>}
      {testResult && !testResult.ok && (
        <div className="ad-msg err">HTTP {testResult.http_code} · {testResult.error}</div>
      )}

      {showForm && (
        <div className="card ad-form">
          <div className="ad-form-grid">
            <label>连接名称
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                     placeholder="例如：CJ 主账号" />
            </label>
            <label>模板
              <select value={form.template_code} onChange={e => setForm(f => ({ ...f, template_code: e.target.value }))}>
                {templates.map(t => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select>
            </label>
            <label>API Token *
              <input type="password" value={form.token} onChange={e => setForm(f => ({ ...f, token: e.target.value }))}
                     placeholder="Bearer 后面的个人访问令牌" autoComplete="off" />
            </label>
            <label>发布者 CID *
              <input value={form.cid} onChange={e => setForm(f => ({ ...f, cid: e.target.value }))}
                     placeholder="发布者公司 ID，不是登录邮箱" />
            </label>
            <label className="span2">Endpoint（留空用模板默认）
              <input value={form.endpoint} onChange={e => setForm(f => ({ ...f, endpoint: e.target.value }))}
                     placeholder={tpl?.default_endpoint || ''} />
            </label>
          </div>
          <div className="ad-form-foot">
            <button className="btn" disabled={testing === 'new'} onClick={() => void test('new')}>
              {testing === 'new' ? '测试中…' : '测试连接（不保存）'}
            </button>
            <button className="btn primary" disabled={saving} onClick={() => void create()}>
              {saving ? '保存为草稿' : '保存为草稿'}
            </button>
          </div>
        </div>
      )}

      {connections.length === 0 ? (
        <div className="card muted ad-empty">还没有连接。点击「新建连接」开始。</div>
      ) : (
        <div className="card ad-table-wrap">
          <table className="ad-table">
            <thead><tr><th>名称</th><th>模板</th><th>CID</th><th>Token</th><th>状态</th><th>最近测试</th><th>操作</th></tr></thead>
            <tbody>
              {connections.map(c => (
                <tr key={c.id}>
                  <td><b>{c.name}</b><div className="muted ad-sub">{new Date(c.created_at || '').toLocaleString()}</div></td>
                  <td><code>{c.template_code}</code></td>
                  <td>{c.cid}</td>
                  <td><code>{c.token_mask}</code></td>
                  <td>
                    <span className={`chip ${c.status === 'active' ? 'ok' : ''}`}>
                      {c.status === 'active' ? '已启用' : c.status === 'disabled' ? '已停用' : '草稿'}
                    </span>
                  </td>
                  <td>
                    {c.last_test_ok === null ? '未测试'
                      : c.last_test_ok ? <span className="ok">通过</span>
                        : <span className="err">失败：{c.last_test_error}</span>}
                  </td>
                  <td>
                    <div className="ad-ops">
                      <button className="btn sm" disabled={testing === c.id} onClick={() => void test(c)}>
                        {testing === c.id ? '测试中…' : '测试'}
                      </button>
                      <button className="btn sm" disabled={c.status !== 'active' && c.last_test_ok !== true}
                              onClick={() => void toggle(c)}>
                        {c.status === 'active' ? '停用' : '启用'}
                      </button>
                      <button className="btn sm danger" onClick={() => void remove(c)}>删除</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="ad-sec-head ad-sec-gap">
        <div>
          <h2 className="ad-sec-title">③ 定期任务</h2>
          <p className="ad-sec-desc">按频率拉取、7 天重叠窗口、失败重试。将在 P2 版本实现。</p>
        </div>
      </div>
      <div className="card muted ad-placeholder">定期任务配置（规划中 · P2）</div>

      <div className="ad-sec-head ad-sec-gap">
        <div>
          <h2 className="ad-sec-title">④ 运行记录</h2>
          <p className="ad-sec-desc">每次拉取的条数、耗时、错误与水位，可手动补拉。将在 P2 版本实现。</p>
        </div>
      </div>
      <div className="card muted ad-placeholder">运行记录（规划中 · P2）</div>
    </div>
  )
}
