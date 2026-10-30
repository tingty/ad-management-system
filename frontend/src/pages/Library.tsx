import { useEffect, useState } from 'react'
import { api, Campaign, Material, ReviewRecord, User } from '../api'
import ValidationBadge from '../components/ValidationBadge'
import Storyboard from '../components/Storyboard'
import VersionPanel from '../components/VersionPanel'

const STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'pill off' },
  in_review: { label: '审阅中', cls: 'pill warn' },
  approved: { label: '已通过', cls: 'pill ok' },
  rejected: { label: '已驳回', cls: 'pill off' },
  active: { label: '可用', cls: 'pill ok' },
}

export default function Library({ user, canReview, isEditor }: {
  user: User; canReview: boolean; isEditor: boolean
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [product, setProduct] = useState('')
  const [platform, setPlatform] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [versionFor, setVersionFor] = useState<number | null>(null)
  const [reviewFor, setReviewFor] = useState<number | null>(null)
  const [records, setRecords] = useState<ReviewRecord[]>([])
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const TYPE_LABEL: Record<string, string> = { image: '图片', video: '视频', copy: '文案', keyword: '关键词' }

  const toggleSel = (id: number) =>
    setSelected(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]))
  const allSelected = campaigns.length > 0 && campaigns.every(c => selected.includes(c.id))

  const load = async (p = product, plat = platform) => {
    setErr('')
    try {
      let list = await api.campaigns()
      if (p) list = list.filter(c => (c.name || '').includes(p))
      if (plat) list = list.filter(c => (c.platforms || []).includes(plat))
      setCampaigns(list)
    } catch (e: any) { setErr(e.message) }
  }

  useEffect(() => { load() }, [])

  const regen = async (m: Material) => {
    const p = prompt('追加描述语后重新生成', m.prompt_log || '')
    if (p === null) return
    try {
      await api.regenerate(m.id, p)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const act = async (fn: () => Promise<any>) => {
    setErr('')
    try { await fn(); await load(); if (reviewFor) await loadRecords(reviewFor) }
    catch (e: any) { setErr(e.message) }
  }

  const loadRecords = async (cid: number) => {
    try {
      if (reviewFor === cid) { setReviewFor(null); return }
      setRecords(await api.reviews(cid))
      setReviewFor(cid)
    } catch (e: any) { setErr(e.message) }
  }

  const doReject = (c: Campaign) => {
    const reason = prompt('驳回原因（必填）', '')
    if (reason === null) return
    if (!reason.trim()) { setErr('驳回必须填写原因'); return }
    act(() => api.rejectReview(c.id, reason.trim()))
  }

  return (
    <div>
      <div className="card">
        <h2>素材库 · 历史方案检索</h2>
        <div className="row">
          <div>
            <label>按 Campaign / 产品名过滤</label>
            <input type="text" value={product} onChange={e => setProduct(e.target.value)} placeholder="关键词" />
          </div>
          <div>
            <label>按平台过滤</label>
            <input type="text" value={platform} onChange={e => setPlatform(e.target.value)} placeholder="如 Facebook / Google / Unity" />
          </div>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 10 }}>
          <button className="btn" onClick={() => load(product, platform)}>检索</button>
          <button className="btn ghost" onClick={() => { setProduct(''); setPlatform(''); load('', '') }}>重置</button>
        </div>
        {err && <div className="alert err">{err}</div>}
        {campaigns.length > 0 && (
          <div className="selectbar">
            <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
              <input type="checkbox" checked={allSelected} style={{ width: 'auto' }}
                     onChange={() => setSelected(allSelected ? [] : campaigns.map(c => c.id))} />
              全选（{campaigns.length} 个方案）
            </label>
            <span className="muted">已选 {selected.length} 个</span>
            {selected.length > 0 && (
              <a className="btn small" href={api.batchExportUrl(selected)}>批量导出所选 ZIP</a>
            )}
            {selected.length > 0 && (
              <button className="btn small ghost" onClick={() => setSelected([])}>清空选择</button>
            )}
          </div>
        )}
      </div>

      {campaigns.length === 0 && <div className="card"><div className="muted">暂无方案。先在「素材生成」创建 Campaign。</div></div>}

      {campaigns.map(c => (
        <div className="card" key={c.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2 style={{ marginBottom: 4 }}>{c.name}</h2>
              <div className="muted" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span>#{c.id} · 平台：{(c.platforms || []).join('、')} · 素材 {c.materials?.length || 0} 条</span>
                <span className={STATUS[c.status]?.cls || 'pill off'}>{STATUS[c.status]?.label || c.status}</span>
                {c.review_note && <span>审阅意见：{c.review_note}</span>}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="checkbox" checked={selected.includes(c.id)} style={{ width: 'auto' }}
                     onChange={() => toggleSel(c.id)} title="选择以批量导出" />
              <button className="btn small secondary" onClick={() => setOpen(open === c.id ? null : c.id)}>
                {open === c.id ? '收起' : '展开素材'}
              </button>
              <a className="btn small" href={api.exportUrl(c.id)}>批量导出 ZIP</a>
              <a className="btn small secondary" href={api.abExportUrl(c.id)}>A/B 分组导出</a>
              <a className="btn small ghost" href={api.abExportUrl(c.id, true)}>定稿导出</a>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
            {isEditor && ['draft', 'rejected'].includes(c.status) && (
              <button className="btn small" onClick={() => act(() => api.submitReview(c.id))}>提交审阅</button>
            )}
            {canReview && c.status === 'in_review' && (
              <>
                <button className="btn small" onClick={() => act(() => api.approveReview(c.id))}>通过</button>
                <button className="btn small danger" onClick={() => doReject(c)}>驳回</button>
              </>
            )}
            <button className="btn small ghost" onClick={() => loadRecords(c.id)}>
              {reviewFor === c.id ? '收起审阅记录' : '审阅记录'}
            </button>
            {c.status === 'approved' && <span className="muted">已通过审阅，可「定稿导出」交付投放。</span>}
          </div>

          {reviewFor === c.id && (
            <div style={{ marginTop: 10, maxHeight: 200, overflow: 'auto' }}>
              {records.length === 0
                ? <div className="muted">暂无审阅记录。</div>
                : (
                  <table>
                    <thead><tr><th>时间</th><th>动作</th><th>操作人</th><th>状态变化</th><th>意见</th></tr></thead>
                    <tbody>
                      {records.map(r => (
                        <tr key={r.id}>
                          <td className="muted">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                          <td>{r.action}</td>
                          <td>{r.username}</td>
                          <td className="muted">{r.from_status || '—'} → {r.to_status || '—'}</td>
                          <td>{r.comment || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </div>
          )}

          {open === c.id && (
            <div className="grid" style={{ marginTop: 14 }}>
              {(c.materials || []).map(m => (
                <div className="mat-card" key={m.id}>
                  <div>
                    <span className="type">{TYPE_LABEL[m.type] || m.type}</span>
                    <span className="plat">{m.platform} · {m.language} · v{m.version}</span>
                  </div>
                  <ValidationBadge m={m} />
                  {m.type === 'image' && m.file_path && (
                    <div>
                      <img src={api.fileUrl(m.file_path)} alt="" />
                      <div className="muted" style={{ fontSize: 11 }}>
                        {m.spec_json?.size || ''} · PNG{m.spec_json?.primary ? ' · 主尺寸' : ''}
                      </div>
                    </div>
                  )}
                  {m.text_content && <pre>{m.text_content}</pre>}
                  {m.type === 'video' && m.content && <Storyboard content={m.content} />}
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <a className="btn small" href={api.downloadUrl(m.id)}>下载</a>
                    {isEditor && <button className="btn small ghost" onClick={() => regen(m)}>重新生成</button>}
                    <button className="btn small secondary"
                            onClick={() => setVersionFor(versionFor === m.id ? null : m.id)}>版本链 / A-B</button>
                  </div>
                  {m.prompt_log && <div className="muted" style={{ marginTop: 6 }}>描述语：{m.prompt_log}</div>}
                </div>
              ))}
              {versionFor && (c.materials || []).some(m => m.id === versionFor) && (
                <VersionPanel
                  materialId={versionFor}
                  canEdit={isEditor}
                  onClose={() => setVersionFor(null)}
                  onChanged={() => load()}
                />
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
