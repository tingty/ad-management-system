import { useEffect, useState } from 'react'
import { api, PlatformSpec } from '../api'

export default function Specs({ canEdit = false }: { canEdit?: boolean }) {
  const [list, setList] = useState<PlatformSpec[]>([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<{ title_max: string; description_max: string; sizes: string }>(
    { title_max: '', description_max: '', sizes: '' })

  const load = () => api.specs().then(setList).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const startEdit = (s: PlatformSpec) => {
    setEditId(s.id)
    setForm({
      title_max: String(s.copy_limits?.title_max ?? ''),
      description_max: String(s.copy_limits?.description_max ?? ''),
      sizes: (s.image_sizes || []).join(','),
    })
    setMsg('')
  }

  const save = async (s: PlatformSpec) => {
    setErr(''); setMsg('')
    const limits: any = { ...(s.copy_limits || {}) }
    if (form.title_max) limits.title_max = Number(form.title_max)
    if (form.description_max) limits.description_max = Number(form.description_max)
    const sizes = form.sizes.split(',').map(x => x.trim()).filter(Boolean)
    try {
      await api.updateSpec(s.id, {
        copy_limits: Object.keys(limits).length ? limits : s.copy_limits,
        image_sizes: sizes.length ? sizes : s.image_sizes,
      })
      setEditId(null)
      setMsg(`${s.platform} 规格已更新，后续生成与校验立即生效。`)
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  return (
    <div>
      <div className="card">
        <h2>平台素材规格库</h2>
        <div className="muted">
          内置 7 个投放平台的图片尺寸、视频规格、文案字数红线与关键词逻辑。规格库存于数据库，
          {canEdit ? '可在此直接维护（管理员/投放经理），修改会写入审计日志并立即影响生成与校验。' : '由管理员/投放经理维护。'}
        </div>
        {err && <div className="alert err">{err}</div>}
        {msg && <div className="alert ok">{msg}</div>}
      </div>

      {list.map(s => (
        <div className="card" key={s.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ marginBottom: 8 }}>
              {s.platform} <span className="muted" style={{ fontSize: 13 }}>· {s.ad_placement}</span>
            </h2>
            {canEdit && editId !== s.id && (
              <button className="btn small ghost" onClick={() => startEdit(s)}>编辑规格</button>
            )}
          </div>

          {editId === s.id ? (
            <div>
              <div className="row">
                <div>
                  <label>标题字数上限</label>
                  <input type="text" value={form.title_max}
                         onChange={e => setForm({ ...form, title_max: e.target.value })} />
                </div>
                <div>
                  <label>描述字数上限</label>
                  <input type="text" value={form.description_max}
                         onChange={e => setForm({ ...form, description_max: e.target.value })} />
                </div>
              </div>
              <label>图片尺寸（逗号分隔，主尺寸放第一位）</label>
              <input type="text" value={form.sizes} onChange={e => setForm({ ...form, sizes: e.target.value })} />
              <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                <button className="btn small" onClick={() => save(s)}>保存</button>
                <button className="btn small ghost" onClick={() => setEditId(null)}>取消</button>
              </div>
            </div>
          ) : (
            <div className="kv">
              <div className="k">图片尺寸</div><div>{(s.image_sizes || []).join('、')}</div>
              <div className="k">视频规格</div><div>{s.video_spec || '—'}</div>
              <div className="k">文案规则</div><div>{s.copy_rules || '—'}</div>
              <div className="k">字数红线</div>
              <div>
                {s.copy_limits ? (
                  <>
                    标题 ≤ {s.copy_limits.title_max ?? '—'} 字
                    ｜ 描述 ≤ {s.copy_limits.description_max ?? '—'} 字
                    {s.copy_limits.primary_text_max ? ` ｜ 主文案 ≤ ${s.copy_limits.primary_text_max} 字` : ''}
                  </>
                ) : '—'}
              </div>
              <div className="k">关键词逻辑</div><div>{s.keyword_logic || '—'}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
