const TYPE_HINT: Record<string, string> = {
  storyboard: '分镜脚本（未配置视频模型）',
  model: '视频模型输出',
}

export default function Storyboard({ content }: { content: any }) {
  if (!content || typeof content !== 'object') return null

  if (content.provider === 'model') {
    return (
      <div>
        <div className="muted">来源：{TYPE_HINT.model} · {content.model || ''}</div>
        {content.url
          ? <a className="btn small" href={content.url} target="_blank" rel="noreferrer">打开视频</a>
          : <div className="muted">已生成文件：{content.file_path}</div>}
      </div>
    )
  }

  const shots = content.shots || []
  return (
    <div>
      <div className="muted" style={{ marginBottom: 6 }}>
        {TYPE_HINT.storyboard} · {content.duration_sec}s · {content.aspect} · {content.resolution} · {content.format}
      </div>
      <table>
        <thead><tr><th style={{ width: 58 }}>时间</th><th style={{ width: 82 }}>镜头</th><th>画面</th><th>字幕</th><th>口播</th></tr></thead>
        <tbody>
          {shots.map((s: any, i: number) => (
            <tr key={i}>
              <td>{s.t}</td>
              <td>{s.shot}</td>
              <td style={{ fontSize: 12 }}>{s.visual}</td>
              <td style={{ fontSize: 12 }}>{s.text}</td>
              <td style={{ fontSize: 12 }} className="muted">{s.vo}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {content.deliverables && (
        <div className="muted" style={{ marginTop: 6 }}>交付物：{content.deliverables.join('、')}</div>
      )}
      {content.note && <div className="muted" style={{ marginTop: 4 }}>{content.note}</div>}
    </div>
  )
}
