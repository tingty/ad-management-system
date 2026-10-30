import { Material } from '../api'

export default function ValidationBadge({ m }: { m: Material }) {
  const v = m.validation
  if (!v) return null
  const errors = v.issues.filter(i => i.level === 'error')
  const warns = v.issues.filter(i => i.level === 'warn')
  const cls = errors.length ? 'off' : warns.length ? 'warn' : 'ok'
  const text = errors.length ? `✗ ${errors.length} 项不合规` : warns.length ? `⚠ ${warns.length} 项提醒` : '✓ 规格合规'
  return (
    <div style={{ margin: '6px 0' }}>
      <span className={'pill ' + cls}>{text}</span>
      {v.issues.length > 0 && (
        <ul className="vissues">
          {v.issues.map((i, idx) => (
            <li key={idx} className={i.level === 'warn' ? 'warn' : ''}>{i.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
