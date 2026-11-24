/**
 * V4.128 / V4.129 · 广告主数据 / API对接。
 * V4.129：测试请求改为真正拉取 publisherCommissions.records（Object: PublisherCommission），
 * 滑窗明确标注请求对象并展示逐条订单佣金明细样例，而不是只显示 count 统计。
 * 在 V4.125「一张列表 + 两个弹窗」基础上，列表最后新增「测试」列：
 *   - 点击测试立即发起一次真实请求，右侧滑出测试详情抽屉；
 *   - 抽屉顶部展示完整请求链接 / 方法 / GraphQL 请求体；
 *   - 请求下方完整展示 HTTP 状态摘要与上游响应原文（Token 脱敏，不回显）；
 *   - 支持关闭按钮、遮罩点击、Esc 关闭；列表状态浮层与双弹窗保持不变。
 * 只改动本页面与 API 封装，不影响任何现有模块布局与功能。
 */
import { useCallback, useEffect, useState } from 'react'
import { advertiserApi, ApiConnection, ApiSchedule, ApiTemplate, ApiTestResult } from '../api'

type Msg = { kind: 'ok' | 'err'; text: string }
type TestDrawer = {
  id: number
  name: string
  result: ApiTestResult | null
  loading: boolean
  error?: string
}
const DEFAULT_SCHEDULE: ApiSchedule = {
  enabled: false, frequency: 'daily', hour: 2, lookback_days: 7, backfill_days: 90,
}
const CJ_TEMPLATE = 'CJ联盟'
const PUBLISHER_COMMISSION_DESC =
  'A record of a publisher commission event, potentially including items purchased and advertiser-supplied custom attributes.'

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
    return ['尚未进行接口测试', '点击列表最后一列「测试」发起一次真实请求']
  }
  const when = c.last_test_at ? new Date(c.last_test_at).toLocaleString() : '—'
  if (c.last_test_ok) {
    return [
      `HTTP ${c.last_test_http_code || 200} · 请求成功`,
      `拉取 ${c.last_test_count ?? 0} 条 PublisherCommission 订单佣金明细`,
      `测试时间：${when}`,
    ]
  }
  return [
    `HTTP ${c.last_test_http_code ?? '—'} · 请求失败`,
    c.last_test_error || '接口返回内容异常',
    `测试时间：${when}`,
  ]
}

function pretty(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') {
    try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
  }
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
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
  const [testDrawer, setTestDrawer] = useState<TestDrawer | null>(null)

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
      setShowCreate(false); setSettingsId(null); setHover(null); setTestDrawer(null)
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
        ? { kind: 'ok', text: `测试成功：HTTP ${r.http_code}，拉取 ${r.record_count || r.count} 条 PublisherCommission 明细` }
        : { kind: 'err', text: `测试失败：HTTP ${r.http_code || '—'} · ${r.error || '接口返回异常'}` })
      await load()
    } catch (e: any) { setMsg({ kind: 'err', text: e?.message || '测试失败' }) }
    finally { setTestingId(null) }
  }

  async function startTest(id: number, name: string) {
    setHover(null); setMsg(null)
    setTestDrawer({ id, name, result: null, loading: true })
    try {
      const r = await advertiserApi.testConnection({ connection_id: id })
      setTestDrawer(d => d && d.id === id ? { ...d, result: r, loading: false } : d)
      await load()
    } catch (e: any) {
      setTestDrawer(d => d && d.id === id
        ? { ...d, loading: false, error: e?.message || '测试请求失败' } : d)
    }
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
  const drawerResult = testDrawer?.result || null
  const drawerStatus = testDrawer?.loading ? 'idle' : drawerResult?.ok ? 'ok' : 'fail'
  const sampleRecords = (drawerResult?.sample_records || []) as Record<string, any>[]

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
            <thead><tr><th>NO.</th><th>广告主</th><th>模板</th><th>状态</th><th>设置</th><th>测试</th></tr></thead>
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
                  <td>
                    <button
                      className="btn sm"
                      disabled={!!testDrawer && testDrawer.id === c.id && testDrawer.loading}
                      onClick={() => void startTest(c.id, c.name)}
                    >{testDrawer?.id === c.id && testDrawer.loading ? '测试中…' : '测试'}</button>
                  </td>
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

      {testDrawer && (
        <div className="ad-drawer-mask" onMouseDown={() => setTestDrawer(null)}>
          <aside className="ad-drawer" role="dialog" aria-label="接口测试详情"
                 onMouseDown={e => e.stopPropagation()}>
            <header className="ad-drawer-head">
              <div className="ad-drawer-title">
                <span className="ad-drawer-kicker">接口测试详情</span>
                <h3>{testDrawer.name}</h3>
              </div>
              <button className="ad-drawer-x" aria-label="关闭测试详情"
                      onClick={() => setTestDrawer(null)}>×</button>
            </header>

            <div className="ad-drawer-body">
              <div className="ad-object-banner">
                <span className="ad-object-tag">请求对象</span>
                <div>
                  <b>PublisherCommission</b>
                  <span>{PUBLISHER_COMMISSION_DESC}</span>
                  <span>查询字段 publisherCommissions → records[] 逐条订单佣金明细（含 items 与广告主自定义属性），不是 count 统计报表。</span>
                </div>
              </div>

              <div className="ad-drawer-summary">
                <div className="ad-drawer-metric">
                  <span>请求状态</span>
                  <b className={`ad-status ${drawerStatus}`}>
                    {testDrawer.loading ? '测试中…' : drawerResult?.ok ? '成功' : '失败'}
                  </b>
                </div>
                <div className="ad-drawer-metric">
                  <span>HTTP Code</span>
                  <b>{drawerResult?.http_code || '—'}</b>
                </div>
                <div className="ad-drawer-metric">
                  <span>明细记录</span>
                  <b>{drawerResult?.ok ? (drawerResult.record_count || drawerResult.count) : '—'}</b>
                </div>
                <div className="ad-drawer-metric">
                  <span>测试时间</span>
                  <b className="ad-metric-time">
                    {drawerResult?.tested_at ? new Date(drawerResult.tested_at).toLocaleString() : '—'}
                  </b>
                </div>
              </div>

              {testDrawer.error && <div className="ad-msg err">{testDrawer.error}</div>}
              {!testDrawer.loading && drawerResult?.error && (
                <div className="ad-msg err">{drawerResult.error}</div>
              )}

              <section className="ad-drawer-sec">
                <div className="ad-drawer-sec-head">
                  <span className="ad-step">01</span>
                  <h4>请求链接</h4>
                  <span className="ad-drawer-sec-note">完整 Endpoint</span>
                </div>
                <div className="ad-url-bar">
                  <span className="ad-method">{drawerResult?.request_method || 'POST'}</span>
                  <code>{drawerResult?.request_url || '—'}</code>
                </div>
                <p className="ad-drawer-hint">Authorization: Bearer **** · Token 不回显；查询窗口为最近 1 天的事件日期，请求 publisherCommissions.records。</p>
                <details className="ad-drawer-details" open>
                  <summary>请求内容 · GraphQL</summary>
                  <pre>{pretty(drawerResult?.request_body)}</pre>
                </details>
              </section>

              <section className="ad-drawer-sec">
                <div className="ad-drawer-sec-head">
                  <span className="ad-step">02</span>
                  <h4>订单佣金明细</h4>
                  <span className="ad-drawer-sec-note">PublisherCommission · 最多 3 条</span>
                </div>
                {testDrawer.loading ? (
                  <div className="ad-drawer-loading">正在拉取 PublisherCommission 明细…</div>
                ) : !drawerResult?.ok ? (
                  <p className="ad-drawer-hint">请求成功后，这里展示逐条 PublisherCommission 订单佣金明细。</p>
                ) : sampleRecords.length === 0 ? (
                  <p className="ad-drawer-hint">该 1 天事件日期窗口内没有 PublisherCommission 明细记录。</p>
                ) : (
                  <div className="ad-sample-wrap">
                    <table className="ad-sample-table">
                      <thead><tr>
                        <th>commissionId</th><th>orderId</th><th>advertiserName</th>
                        <th>eventDate</th><th>original</th><th>items</th>
                      </tr></thead>
                      <tbody>
                        {sampleRecords.map((r, i) => (
                          <tr key={i}>
                            <td><code>{String(r.commissionId ?? '—')}</code></td>
                            <td><code>{String(r.orderId ?? '—')}</code></td>
                            <td>{String(r.advertiserName ?? '—')}</td>
                            <td>{String(r.eventDate ?? '—')}</td>
                            <td>{r.original === true ? '原始单' : r.original === false ? '修正单' : '—'}</td>
                            <td>{Array.isArray(r.items) ? r.items.length : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="ad-drawer-hint">每条明细对应一个订单的一笔佣金（含原始单与修正单）；完整字段请查看下方响应原文。</p>
              </section>

              <section className="ad-drawer-sec">
                <div className="ad-drawer-sec-head">
                  <span className="ad-step">03</span>
                  <h4>响应结果</h4>
                  <span className="ad-drawer-sec-note">上游原文 · 可完整滚动查看</span>
                </div>
                {testDrawer.loading ? (
                  <div className="ad-drawer-loading">正在请求 CJ 接口，请稍候…</div>
                ) : (
                  <pre className="ad-response">{pretty(drawerResult?.response_text)}</pre>
                )}
              </section>
            </div>

            <footer className="ad-drawer-foot">
              <button
                className="btn"
                disabled={testDrawer.loading}
                onClick={() => void startTest(testDrawer.id, testDrawer.name)}
              >{testDrawer.loading ? '测试中…' : '重新测试'}</button>
              <button className="btn primary" onClick={() => setTestDrawer(null)}>关闭</button>
            </footer>
          </aside>
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
