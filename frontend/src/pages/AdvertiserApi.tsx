/**
 * V4.125 · 广告主数据 / API对接。
 * 界面按用户确认意见收敛为「一张列表 + 两个弹窗」：
 *   - 页面标题 API对接，删除顶部解释文案与模板样例/运行记录占位区；
 *   - 列表列：NO. / 广告主 / 模板 / 状态 / 设置；状态悬浮显示 HTTP 明细；
 *   - 新建弹窗只有一个「保存」按钮，保存即创建 + 真实测试 + 回写状态；
 *   - 设置弹窗承载定期任务配置，可保存 / 重新测试 / 删除。
 * 只改动本页面与 API 封装，不影响任何现有模块布局与功能。
 */
import { useCallback, useEffect, useState } from 'react'
import { advertiserApi, ApiConnection, ApiSchedule, ApiTemplate } from '../api'

type Msg = { kind: 'ok' | 'err'; text: string }
const DEFAULT_SCHEDULE: ApiSchedule = {
  enabled: false, frequency: 'daily', hour: 2, lookback_days: 7, backfill_days: 90,
}
const CJ_TEMPLATE = 'CJ联盟'

function statusLabel(c: ApiConnection): string {
  if (c.last_test_ok === null || c.last_test_ok === undefined) return '未测试'
  return c.last_test_ok ? '成功' : '失败'
}

function statusClass(c: ApiConnection): string {
  if (c.last_test_ok === null || c.last_test_ok === undefined) return 'idle'
  return c.last_test_ok ? 'ok' : 'fail'
}

function statusDetail(c: ApiConnection): string[] {
  if (c.last_test_ok === null || c.last_test_ok === undefined) {
    return ['尚未进行接口测试', '点击「设置 → 重新测试」发起一次真实请求']
  }
  const when = c.last_test_at ? new Date(c.last_test_at).toLocaleString() : '—'
  if (c.last_test_ok) {
    return [
      `HTTP ${c.last_test_http_code || 200} · 请求成功`,
      `接口返回 ${c.last_test_count ?? 0} 条佣金记录`,
      `测试时间：${when}`,
    ]
  }
  return [
    `HTTP ${c.last_test_http_code ?? '—'} · 请求失败`,
    c.last_test_error || '接口返回内容异常',
    `测试时间：${when}`,
  ]
}

export default function AdvertiserApi() {
  const [templates, setTemplates] = useState<ApiTemplate[]>([])
  const [connections, setConnections] = useState<ApiConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState<Msg | null>(null)

  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', template_code: 'cj_publisher_commissions', token: '', cid: '', endpoint: '' })
  const [saving, setSaving] = useState(false)

  const [settingsId, setSettingsId] = useState<number | null>(null)
  const [settings, setSettings] = useState<ApiSchedule>(DEFAULT_SCHEDULE)
  const [savingSettings, setSavingSettings] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [hover, setHover] = useState<{ id: number; x: number; y: number } | null>(null)

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setShowCreate(false); setSettingsId(null); setHover(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const templateName = (code: string) => {
    const t = templates.find(x => x.code === code)
    if (t && code === 'cj_publisher_commissions') return CJ_TEMPLATE
    return t?.name || (code === 'cj_publisher_commissions' ? CJ_TEMPLATE : code)
  }

  async function saveNew() {
    if (!form.name.trim()) { setMsg({ kind: 'err', text: '请填写广告主名称' }); return }
    if (!form.token.trim()) { setMsg({ kind: 'err', text: '请填写 API Token' }); return }
    if (!form.cid.trim()) { setMsg({ kind: 'err', text: '请填写发布者 CID（不是登录邮箱）' }); return }
    setSaving(true); setMsg(null)
    try {
      const r = await advertiserApi.createAndTestConnection(form)
      setShowCreate(false)
      setForm({ name: '', template_code: 'cj_publisher_commissions', token: '', cid: '', endpoint: '' })
      setMsg(r.last_test_ok
        ? { kind: 'ok', text: `「${r.name}」已保存，接口测试成功` }
        : { kind: 'err', text: `「${r.name}」已保存，但接口测试失败：${r.last_test_error || '请检查填写信息'}` })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '保存失败' }) }
    finally { setSaving(false) }
  }

  function openSettings(c: ApiConnection) {
    setMsg(null); setHover(null)
    setSettingsId(c.id)
    setSettings({ ...DEFAULT_SCHEDULE, ...(c.schedule || {}) })
  }

  async function saveSettings() {
    if (settingsId === null) return
    setSavingSettings(true); setMsg(null)
    try {
      await advertiserApi.updateConnection(settingsId, { schedule: settings })
      setSettingsId(null)
      setMsg({ kind: 'ok', text: '定期任务设置已保存' })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '保存设置失败' }) }
    finally { setSavingSettings(false) }
  }

  async function retest() {
    if (settingsId === null) return
    setTestingId(settingsId); setMsg(null)
    try {
      const r = await advertiserApi.testConnection({ connection_id: settingsId })
      setMsg(r.ok
        ? { kind: 'ok', text: `测试成功：HTTP ${r.http_code}，返回 ${r.count} 条记录` }
        : { kind: 'err', text: `测试失败：HTTP ${r.http_code || '—'} · ${r.error || '接口返回异常'}` })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '测试失败' }) }
    finally { setTestingId(null) }
  }

  async function remove() {
    if (settingsId === null) return
    const c = connections.find(x => x.id === settingsId)
    if (!window.confirm(`确认删除广告主「${c?.name || ''}」的 API 对接？此操作不可恢复。`)) return
    setMsg(null)
    try {
      await advertiserApi.deleteConnection(settingsId)
      setSettingsId(null)
      setMsg({ kind: 'ok', text: '已删除' })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '删除失败' }) }
  }

  const hovered = hover ? connections.find(c => c.id === hover.id) : null

  return (
    <div className="ad-data-page">
      <div className="ad-page-head">
        <button className="btn primary" onClick={() => { setShowCreate(true); setMsg(null) }}>新建 API</button>
      </div>

      {msg && <div className={`ad-msg ${msg.kind}`}>{msg.text}</div>}

      {loading ? <div className="card muted">加载中…</div> : connections.length === 0 ? (
        <div className="card muted ad-empty">还没有已对接的 API。点击「新建 API」添加。</div>
      ) : (
        <div className="card ad-table-wrap">
          <table className="ad-table">
            <thead><tr><th>NO.</th><th>广告主</th><th>模板</th><th>状态</th><th>设置</th></tr></thead>
            <tbody>
              {connections.map(c => (
                <tr key={c.id}>
                  <td className="ad-no">{c.id}</td>
                  <td><b>{c.name}</b><div className="muted ad-sub">CID {c.cid}</div></td>
                  <td><code>{templateName(c.template_code)}</code></td>
                  <td>
                    <span
                      className={`ad-status ${statusClass(c)}`}
                      tabIndex={0}
                      onMouseEnter={e => {
                        const r = e.currentTarget.getBoundingClientRect()
                        setHover({ id: c.id, x: r.left, y: r.bottom })
                      }}
                      onMouseLeave={() => setHover(null)}
                      onFocus={e => {
                        const r = e.currentTarget.getBoundingClientRect()
                        setHover({ id: c.id, x: r.left, y: r.bottom })
                      }}
                      onBlur={() => setHover(null)}
                    >{statusLabel(c)}</span>
                  </td>
                  <td><button className="btn sm" onClick={() => openSettings(c)}>设置</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hover && hovered && (
        <div className="ad-status-pop" style={{ left: hover.x, top: hover.y + 6 }}>
          {statusDetail(hovered).map((line, i) => <span key={i}>{line}</span>)}
        </div>
      )}

      {showCreate && (
        <div className="ad-modal-mask" onMouseDown={() => setShowCreate(false)}>
          <div className="ad-modal" onMouseDown={e => e.stopPropagation()}>
            <div className="ad-modal-head">
              <h3>新建 API 对接</h3>
              <button className="ad-modal-x" aria-label="关闭" onClick={() => setShowCreate(false)}>×</button>
            </div>
            <div className="ad-form-grid">
              <label>广告主 *
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                       placeholder="例如：CJ 主账号" />
              </label>
              <label>模板
                <select value={form.template_code} onChange={e => setForm(f => ({ ...f, template_code: e.target.value }))}>
                  {templates.map(t => (
                    <option key={t.code} value={t.code}>{t.code === 'cj_publisher_commissions' ? CJ_TEMPLATE : t.name}</option>
                  ))}
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
                       placeholder="https://commissions.api.cj.com/query" />
              </label>
            </div>
            <div className="ad-modal-foot">
              <button className="btn primary" disabled={saving} onClick={() => void saveNew()}>
                {saving ? '保存并测试中…' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {settingsId !== null && (
        <div className="ad-modal-mask" onMouseDown={() => setSettingsId(null)}>
          <div className="ad-modal" onMouseDown={e => e.stopPropagation()}>
            <div className="ad-modal-head">
              <h3>设置 · 定期任务</h3>
              <button className="ad-modal-x" aria-label="关闭" onClick={() => setSettingsId(null)}>×</button>
            </div>
            <div className="ad-form-grid">
              <label className="span2 ad-check-line">
                <input type="checkbox" checked={settings.enabled}
                       onChange={e => setSettings(s => ({ ...s, enabled: e.target.checked }))} />
                启用定期拉取
              </label>
              <label>频率
                <select value={settings.frequency}
                        onChange={e => setSettings(s => ({ ...s, frequency: e.target.value as ApiSchedule['frequency'] }))}>
                  <option value="daily">每日一次</option>
                  <option value="6h">每 6 小时</option>
                </select>
              </label>
              <label>执行小时（每日）
                <input type="number" min={0} max={23} value={settings.hour}
                       onChange={e => setSettings(s => ({ ...s, hour: Number(e.target.value) }))} />
              </label>
              <label>回溯窗口（天）
                <input type="number" min={1} max={90} value={settings.lookback_days}
                       onChange={e => setSettings(s => ({ ...s, lookback_days: Number(e.target.value) }))} />
              </label>
              <label>首次回填（天）
                <input type="number" min={1} max={365} value={settings.backfill_days}
                       onChange={e => setSettings(s => ({ ...s, backfill_days: Number(e.target.value) }))} />
              </label>
            </div>
            <p className="ad-modal-hint muted">当前保存任务配置；自动调度执行按版本规划在后续阶段接入。</p>
            <div className="ad-modal-foot">
              <button className="btn" disabled={testingId !== null} onClick={() => void retest()}>
                {testingId !== null ? '测试中…' : '重新测试'}
              </button>
              <button className="btn" disabled={savingSettings} onClick={() => void saveSettings()}>
                {savingSettings ? '保存中…' : '保存设置'}
              </button>
              <button className="btn danger" onClick={() => void remove()}>删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
