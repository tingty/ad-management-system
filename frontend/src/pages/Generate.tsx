import { useState } from 'react'
import { api, Framework, Meta, Material } from '../api'
import ValidationBadge from '../components/ValidationBadge'
import Storyboard from '../components/Storyboard'

function Chips({ options, value, onChange }: { options: string[]; value: string[]; onChange: (v: string[]) => void }) {
  const toggle = (o: string) =>
    onChange(value.includes(o) ? value.filter(x => x !== o) : [...value, o])
  return (
    <div className="chips">
      {options.map(o => (
        <div key={o} className={'chip' + (value.includes(o) ? ' on' : '')} onClick={() => toggle(o)}>{o}</div>
      ))}
    </div>
  )
}

export default function Generate({ meta, framework, onDone }: {
  meta: Meta | null; framework: Framework | null; onDone: () => void
}) {
  const [name, setName] = useState(() => framework ? `${framework.product} Campaign` : 'New Campaign')
  const [platforms, setPlatforms] = useState<string[]>(['Facebook', 'Google'])
  const [types, setTypes] = useState<string[]>(['image', 'video', 'copy', 'keyword'])
  const [langs, setLangs] = useState<string[]>(['en'])
  const [extra, setExtra] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [campaignId, setCampaignId] = useState<number | null>(null)
  const [mats, setMats] = useState<Material[]>([])

  const TYPE_LABEL: Record<string, string> = { image: '图片', video: '视频', copy: '文案', keyword: '关键词' }

  const run = async () => {
    if (!framework) return
    setLoading(true); setErr('')
    try {
      const res = await api.generate({
        framework_id: framework.id, campaign_name: name,
        platforms, material_types: types, languages: langs, extra_prompt: extra || undefined,
      })
      setCampaignId(res.id); setMats(res.materials || [])
    } catch (e: any) { setErr(e.message) } finally { setLoading(false) }
  }

  const regen = async (m: Material) => {
    const p = prompt('追加描述语后重新生成（例如：更口语化、强调省钱、面向拉美西语用户）', extra || '')
    if (p === null) return
    try {
      const nm = await api.regenerate(m.id, p)
      setMats(prev => [...prev, nm])
    } catch (e: any) { setErr(e.message) }
  }

  return (
    <div>
      {!framework && (
        <div className="card"><div className="alert err">请先在「① 落地页分析」生成推广框架，再回到此处生成素材。</div></div>
      )}
      <div className="card">
        <h2>按平台规格生成广告素材</h2>
        <div className="row">
          <div>
            <label>Campaign 名称</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <label>追加描述语（可选，不满意可后续重生成）</label>
            <input type="text" value={extra} onChange={e => setExtra(e.target.value)} placeholder="例如：更强调省钱 / 面向拉美西语用户" />
          </div>
        </div>
        <label>投放平台（多选）</label>
        <Chips options={meta?.platforms || []} value={platforms} onChange={setPlatforms} />
        <label>素材类型（多选）</label>
        <Chips options={meta?.material_types || []} value={types} onChange={setTypes} />
        <label>语言（多选）</label>
        <Chips options={meta?.languages || []} value={langs} onChange={setLangs} />
        <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
          <button className="btn" onClick={run} disabled={loading || !framework || platforms.length === 0 || types.length === 0}>
            {loading ? '生成中…' : '生成素材'}
          </button>
          {campaignId && <button className="btn secondary" onClick={onDone}>去素材库查看 →</button>}
        </div>
        {err && <div className="alert err">{err}</div>}
      </div>

      {mats.length > 0 && (
        <div className="card">
          <h2>已生成素材（{mats.length}）</h2>
          <div className="grid">
            {mats.map(m => (
              <div className="mat-card" key={m.id}>
                <div>
                  <span className="type">{TYPE_LABEL[m.type] || m.type}</span>
                  <span className="plat">{m.platform} · {m.language} · v{m.version}</span>
                </div>
                <ValidationBadge m={m} />
                {m.type === 'image' && m.file_path && (
                  <div>
                    <img src={api.fileUrl(m.file_path)} alt="image" />
                    <div className="muted" style={{ fontSize: 11 }}>
                      {m.spec_json?.size || ''} · PNG{m.spec_json?.primary ? ' · 主尺寸' : ''}
                    </div>
                  </div>
                )}
                {m.text_content && <pre>{m.text_content}</pre>}
                {m.type === 'video' && m.content && <Storyboard content={m.content} />}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <a className="btn small" href={api.downloadUrl(m.id)}>下载</a>
                  <button className="btn small ghost" onClick={() => regen(m)}>重新生成</button>
                </div>
                {m.prompt_log && <div className="muted" style={{ marginTop: 6 }}>描述语：{m.prompt_log}</div>}
              </div>
            ))}
          </div>
          {campaignId && (
            <div style={{ marginTop: 14 }}>
              <a className="btn" href={api.exportUrl(campaignId)}>批量导出 ZIP</a>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
