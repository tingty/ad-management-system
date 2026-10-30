import { useEffect, useRef, useState } from 'react'
import { api, BatchItem, Job, Meta } from '../api'

const SAMPLE = `campaign_name,landing_text,platforms,languages,material_types,extra_prompt
SuperSave 首发,SuperSave 自动比价省钱购物 App，覆盖欧美与拉美,Facebook|Google,en|es,image|copy,强调省钱
FitTrack 首发,FitTrack 健身打卡 App，AI 定制训练计划,Unity|AppLovin,en|pt,video|copy|keyword,强调AI定制`

const TYPE_LABEL: Record<string, string> = { image: '图片', video: '视频', copy: '文案', keyword: '关键词' }

function toggle(list: string[], v: string) {
  return list.includes(v) ? list.filter(x => x !== v) : [...list, v]
}

export default function Batch({ meta }: { meta: Meta | null }) {
  const [rows, setRows] = useState(SAMPLE)
  const [platforms, setPlatforms] = useState<string[]>(['Facebook'])
  const [languages, setLanguages] = useState<string[]>(['en'])
  const [types, setTypes] = useState<string[]>(['copy'])
  const [extra, setExtra] = useState('')
  const [preview, setPreview] = useState<BatchItem[]>([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [history, setHistory] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadHistory = async () => {
    try { setHistory(await api.jobs()) } catch { /* 首次启动可能尚无任务 */ }
  }
  useEffect(() => { loadHistory() }, [])

  // 任务进行中轮询进度
  useEffect(() => {
    if (!job || !['pending', 'running'].includes(job.status)) return
    const t = setInterval(async () => {
      try {
        const j = await api.job(job.id)
        setJob(j)
        if (!['pending', 'running'].includes(j.status)) loadHistory()
      } catch { /* 忽略瞬时错误，下个周期重试 */ }
    }, 1200)
    return () => clearInterval(t)
  }, [job?.id, job?.status])

  const parse = async () => {
    setErr(''); setMsg('')
    try {
      const r = await api.batchParse(rows)
      setPreview(r.items)
      setMsg(`解析到 ${r.count} 行${r.count > 50 ? '（预览前 50 行）' : ''}`)
      if (r.errors?.length) setErr(r.errors.join('；'))
    } catch (e: any) { setErr(e.message) }
  }

  const upload = async (f: File) => {
    setErr(''); setMsg('')
    try {
      const r = await api.batchUpload(f)
      const text = await f.text()
      setRows(text.replace(/^\ufeff/, ''))
      setPreview(r.items)
      setMsg(`已导入 ${f.name}：${r.count} 行`)
      if (r.errors?.length) setErr(r.errors.join('；'))
    } catch (e: any) { setErr(e.message) }
  }

  const start = async () => {
    setBusy(true); setErr(''); setMsg('')
    try {
      const j = await api.createJob({
        rows, platforms, languages, material_types: types, extra_prompt: extra || undefined,
      })
      setJob(j)
      setMsg(`任务 #${j.id} 已提交，共 ${j.total} 行`)
      loadHistory()
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  const cancel = async () => {
    if (!job) return
    try { setJob(await api.cancelJob(job.id)) } catch (e: any) { setErr(e.message) }
  }

  const pct = job && job.total ? Math.round((job.done + job.failed) / job.total * 100) : 0
  const okIds = (job?.result || []).filter(r => r.campaign_id).map(r => r.campaign_id as number)

  return (
    <div>
      <div className="card">
        <h2>批量任务 · CSV 导入 → 异步生成</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          列格式：<code>campaign_name, landing_text, platforms, languages, material_types, extra_prompt</code>；
          多值用 <code>|</code> 分隔。CSV 中留空的列将使用下方「默认配置」。
          无表头时按前 6 列顺序解析。
        </div>
        <label>CSV 内容</label>
        <textarea value={rows} onChange={e => setRows(e.target.value)} style={{ minHeight: 150, fontFamily: 'monospace', fontSize: 12.5 }} />

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12, alignItems: 'center' }}>
          <button className="btn secondary" onClick={() => fileRef.current?.click()}>上传 CSV 文件</button>
          <input ref={fileRef} type="file" accept=".csv,text/csv" style={{ display: 'none' }}
                 onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = '' }} />
          <a className="btn ghost" href={api.templateUrl()}>下载 CSV 模板</a>
          <button className="btn ghost" onClick={parse}>解析预览</button>
        </div>

        {preview.length > 0 && (
          <div style={{ marginTop: 14, maxHeight: 220, overflow: 'auto' }}>
            <table>
              <thead>
                <tr><th>#</th><th>Campaign</th><th>落地页文案</th><th>平台</th><th>语言</th><th>类型</th><th>描述语</th></tr>
              </thead>
              <tbody>
                {preview.map((it, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{it.campaign_name}</td>
                    <td style={{ maxWidth: 260 }}>{it.landing_text}</td>
                    <td>{it.platforms.join('、') || <span className="muted">默认</span>}</td>
                    <td>{it.languages.join('、') || <span className="muted">默认</span>}</td>
                    <td>{(it.material_types || []).map(t => TYPE_LABEL[t] || t).join('、') || <span className="muted">默认</span>}</td>
                    <td>{it.extra_prompt || <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>默认配置（CSV 未指定时生效）</h2>
        <label>投放平台</label>
        <div className="chips">
          {(meta?.platforms || []).map(p => (
            <div key={p} className={`chip ${platforms.includes(p) ? 'on' : ''}`} onClick={() => setPlatforms(toggle(platforms, p))}>{p}</div>
          ))}
        </div>
        <label>语言</label>
        <div className="chips">
          {(meta?.languages || []).map(l => (
            <div key={l} className={`chip ${languages.includes(l) ? 'on' : ''}`} onClick={() => setLanguages(toggle(languages, l))}>{l}</div>
          ))}
        </div>
        <label>素材类型</label>
        <div className="chips">
          {(meta?.material_types || []).map(t => (
            <div key={t} className={`chip ${types.includes(t) ? 'on' : ''}`} onClick={() => setTypes(toggle(types, t))}>{TYPE_LABEL[t] || t}</div>
          ))}
        </div>
        <label>统一补充描述语（可选）</label>
        <input type="text" value={extra} onChange={e => setExtra(e.target.value)} placeholder="如：强调限时优惠，面向拉美西语用户" />

        <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
          <button className="btn" onClick={start} disabled={busy || !rows.trim()}>创建批量任务</button>
          {job && ['pending', 'running'].includes(job.status) &&
            <button className="btn danger" onClick={cancel}>取消任务</button>}
        </div>
        {err && <div className="alert err">{err}</div>}
        {msg && <div className="alert ok">{msg}</div>}
      </div>

      {job && (
        <div className="card">
          <h2>任务 #{job.id} · 进度</h2>
          <div className="progress"><div className="progress-inner" style={{ width: `${pct}%` }} /></div>
          <div className="muted" style={{ marginTop: 8 }}>
            状态 <b>{job.status}</b> · 完成 {job.done} / 失败 {job.failed} / 共 {job.total} · {pct}%
            {job.payload?.skipped ? ` · 已跳过非法行 ${job.payload.skipped}` : ''}
          </div>
          {job.error && <div className="alert err">{job.error}</div>}

          {okIds.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <a className="btn small" href={api.batchExportUrl(okIds)}>批量下载已完成（{okIds.length} 个 Campaign）</a>
            </div>
          )}

          {!!(job.result || []).length && (
            <div style={{ marginTop: 14, maxHeight: 300, overflow: 'auto' }}>
              <table>
                <thead><tr><th>#</th><th>名称</th><th>结果</th><th>素材数</th><th>Campaign</th></tr></thead>
                <tbody>
                  {(job.result || []).map(r => (
                    <tr key={r.index}>
                      <td>{r.index + 1}</td>
                      <td>{r.name}</td>
                      <td>{r.ok ? <span className="pill ok">成功</span> : <span className="pill off">失败</span>}</td>
                      <td>{r.materials}</td>
                      <td>{r.campaign_id ? `#${r.campaign_id}` : <span className="muted">{r.error}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h2>历史任务</h2>
        {history.length === 0 && <div className="muted">暂无任务记录。</div>}
        {history.length > 0 && (
          <table>
            <thead><tr><th>ID</th><th>状态</th><th>进度</th><th>创建时间</th><th></th></tr></thead>
            <tbody>
              {history.map(h => (
                <tr key={h.id}>
                  <td>#{h.id}</td>
                  <td><span className={`pill ${h.status === 'success' ? 'ok' : h.status === 'failed' ? 'off' : 'warn'}`}>{h.status}</span></td>
                  <td>{h.done}/{h.total}{h.failed ? ` · 失败 ${h.failed}` : ''}</td>
                  <td className="muted">{h.created_at ? new Date(h.created_at).toLocaleString() : '—'}</td>
                  <td><button className="btn small ghost" onClick={() => setJob(h)}>查看</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
