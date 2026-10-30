import { useEffect, useState } from 'react'
import { api, CompareResult, Material } from '../api'

const TYPE_LABEL: Record<string, string> = { image: '图片', video: '视频', copy: '文案', keyword: '关键词' }

function fmtChars(v: number | number[] | null) {
  if (v == null) return '—'
  return Array.isArray(v) ? v.join(' / ') : String(v)
}

export default function VersionPanel({ materialId, canEdit = true, onClose, onChanged }: {
  materialId: number
  canEdit?: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const [versions, setVersions] = useState<Material[]>([])
  const [slot, setSlot] = useState<any>(null)
  const [leftId, setLeftId] = useState<number | null>(null)
  const [rightId, setRightId] = useState<number | null>(null)
  const [cmp, setCmp] = useState<CompareResult | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const r = await api.versions(materialId)
      setVersions(r.versions)
      setSlot(r.slot)
      if (r.versions.length >= 2) {
        setLeftId(prev => prev ?? r.versions[r.versions.length - 2].id)
        setRightId(prev => prev ?? r.versions[r.versions.length - 1].id)
      }
    } catch (e: any) { setErr(e.message) }
  }
  useEffect(() => { load() }, [materialId])

  useEffect(() => {
    if (!leftId || !rightId || leftId === rightId) { setCmp(null); return }
    api.compare(leftId, rightId).then(setCmp).catch(e => setErr(e.message))
  }, [leftId, rightId])

  const pick = (id: number) => {
    if (leftId === id) { setLeftId(rightId); return }
    if (rightId === id) { setRightId(leftId); return }
    setRightId(id)
  }

  const doSelect = async (id: number) => {
    setBusy(true); setErr('')
    try {
      await api.selectMaterial(id)
      await load()
      onChanged()
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="mat-card" style={{ gridColumn: '1 / -1', background: '#f8fbff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <b>版本链</b>
          <span className="muted"> · {slot ? `${slot.platform} · ${slot.language || '—'} · ${TYPE_LABEL[slot.type] || slot.type}` : ''} · 共 {versions.length} 个版本</span>
        </div>
        <button className="btn small ghost" onClick={onClose}>收起</button>
      </div>

      {err && <div className="alert err">{err}</div>}

      <table style={{ marginTop: 10 }}>
        <thead>
          <tr><th>版本</th><th>变体</th><th>合规</th><th>字数</th><th>描述语</th><th>对比</th><th>定稿</th></tr>
        </thead>
        <tbody>
          {versions.map(v => (
            <tr key={v.id}>
              <td>v{v.version}</td>
              <td><span className="pill ok">{v.variant || `V${v.version}`}</span></td>
              <td>{v.validation
                ? (v.validation.valid ? <span className="pill ok">合规</span> : <span className="pill warn">{v.validation.issues.length} 项</span>)
                : <span className="muted">—</span>}</td>
              <td>{(v.text_content || '').replace(/\n/g, '').length}</td>
              <td className="muted" style={{ maxWidth: 220 }}>{v.prompt_log || '—'}</td>
              <td>
                <button className={`btn small ${leftId === v.id ? '' : 'ghost'}`} onClick={() => setLeftId(v.id)}>A</button>{' '}
                <button className={`btn small ${rightId === v.id ? '' : 'ghost'}`} onClick={() => setRightId(v.id)}>B</button>
              </td>
              <td>
                {v.selected
                  ? <span className="pill ok">已定稿</span>
                  : canEdit
                    ? <button className="btn small ghost" disabled={busy} onClick={() => doSelect(v.id)}>设为定稿</button>
                    : <span className="muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {versions.length === 0 && <div className="muted" style={{ marginTop: 8 }}>暂无版本。</div>}
      {versions.length === 1 && <div className="muted" style={{ marginTop: 8 }}>只有 1 个版本。点素材卡上的「重新生成」并追加描述语，即可产生 A/B 变体。</div>}

      {cmp && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
            <b>并排对比</b>
            <span className="muted">
              {cmp.left.variant}(v{cmp.left.version}) ↔ {cmp.right.variant}(v{cmp.right.version})
              · 变更 {cmp.changed_count} 个字段
              · 字数 {cmp.left.char_total} → {cmp.right.char_total}（{cmp.char_delta >= 0 ? '+' : ''}{cmp.char_delta}）
            </span>
          </div>
          <table style={{ marginTop: 8 }}>
            <thead>
              <tr><th style={{ width: 110 }}>字段</th><th>{cmp.left.variant} · v{cmp.left.version}</th><th>{cmp.right.variant} · v{cmp.right.version}</th></tr>
            </thead>
            <tbody>
              {cmp.fields.map(f => (
                <tr key={f.key} style={{ background: f.changed ? '#fff9db' : undefined }}>
                  <td><b>{f.key}</b>{f.changed && <div className="muted" style={{ fontSize: 11 }}>已变更</div>}</td>
                  <td style={{ fontSize: 12 }}>
                    <pre style={{ margin: 0 }}>{JSON.stringify(f.left, null, 1)}</pre>
                    <div className="muted" style={{ fontSize: 11 }}>字数 {fmtChars(f.left_chars)}</div>
                  </td>
                  <td style={{ fontSize: 12 }}>
                    <pre style={{ margin: 0 }}>{JSON.stringify(f.right, null, 1)}</pre>
                    <div className="muted" style={{ fontSize: 11 }}>字数 {fmtChars(f.right_chars)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
