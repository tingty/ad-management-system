import React, { useState } from 'react'
import { api } from '../api'

/**
 * 创意工作台 · 全球创意分析
 * 输入参考素材（链接 / 文本）→ 调用已配置大模型归类的创意风格/类型 → 产出可复用提示词模板。
 * 提示词可「复制」沉淀到「素材提示词」库复用（需求 2：提示词更新与同步）。
 */
export default function CreativeAnalysis() {
  const [urls, setUrls] = useState('')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [copied, setCopied] = useState('')

  async function run() {
    setError(''); setResult(null)
    const urlList = urls.split(/[\n,]/).map(s => s.trim()).filter(Boolean)
    if (!urlList.length && !text.trim()) {
      setError('请提供参考素材链接或文本')
      return
    }
    setLoading(true)
    try {
      const r = await api.creativeAnalyze({ urls: urlList, text: text.trim(), title: title.trim() || undefined })
      setResult(r)
    } catch (e: any) {
      setError(e?.message || '分析失败')
    } finally {
      setLoading(false)
    }
  }

  function copy(text: string, tag: string) {
    navigator.clipboard?.writeText(text)
    setCopied(tag)
    setTimeout(() => setCopied(''), 1500)
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>全球创意分析</h2>
        <p className="muted">分析 Facebook / Google / Unity / Adsterra 等大媒体上最具创意与转化效果的素材，
          归类创意风格与类型，并产出可直接调用的图片 / 视频提示词模板。</p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="grid" style={{ gridTemplateColumns: '1fr', gap: 12 }}>
          <label className="field">
            <span className="label">分析标题（可选）</span>
            <input value={title} onChange={e => setTitle(e.target.value)} placeholder="如：电商 App 信息流广告" />
          </label>
          <label className="field">
            <span className="label">参考素材链接（多个用换行或逗号分隔）</span>
            <textarea value={urls} onChange={e => setUrls(e.target.value)} rows={3}
              placeholder="https://...&#10;https://..." />
          </label>
          <label className="field">
            <span className="label">或直接粘贴参考文案 / 素材描述</span>
            <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
              placeholder="描述你看到的高转化广告创意：构图、色调、文案语气、卖点表达…" />
          </label>
          <div>
            <button className="btn primary" onClick={run} disabled={loading}>
              {loading ? '分析中…' : '开始分析'}
            </button>
            {result && (
              <button className="btn" style={{ marginLeft: 8 }} onClick={() => copy(
                (result.categories || []).map((c: any) => `【${c.name}】\n${c.image_prompt}`).join('\n\n'), 'all')}>
                {copied === 'all' ? '已复制全部' : '复制全部图片提示词'}
              </button>
            )}
          </div>
          {error && <div className="err">{error}</div>}
        </div>
      </div>

      {result && (
        <div className="card">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{result.title}</div>
          {result.summary && <p className="muted" style={{ marginTop: 0 }}>{result.summary}</p>}
          <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
            实际调用模型：{result.model_info?.provider || '—'} / {result.model_info?.model || '—'}
            {result.model_info?.fallback ? '（Mock 兜底，未配置模型）' : ''}
          </div>

          {(result.categories || []).length === 0 && (
            <div className="muted">未归出具体类型（可能参考信息不足或未配置大模型）。配置「分析」模型后重试可获得结构化结果。</div>
          )}

          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
            {(result.categories || []).map((c: any, i: number) => (
              <div key={i} className="card" style={{ border: '1px solid var(--line)', boxShadow: 'none' }}>
                <div style={{ fontWeight: 600 }}>{c.name}</div>
                <div className="muted" style={{ fontSize: 13, margin: '6px 0' }}>{c.description}</div>
                {c.traits?.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    {c.traits.map((t: string, j: number) => <span key={j} className="chip">{t}</span>)}
                  </div>
                )}
                {c.examples?.length > 0 && (
                  <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                    适用：{c.examples.join('、')}
                  </div>
                )}
                <div style={{ fontSize: 13, marginBottom: 4 }}><b>图片提示词</b></div>
                <pre className="prompt-box">{c.image_prompt || '—'}</pre>
                <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                  <button className="btn" onClick={() => copy(c.image_prompt, `img-${i}`)}>
                    {copied === `img-${i}` ? '已复制' : '复制图片提示词'}
                  </button>
                  {c.video_prompt && (
                    <button className="btn" onClick={() => copy(c.video_prompt, `vid-${i}`)}>
                      {copied === `vid-${i}` ? '已复制' : '复制视频提示词'}
                    </button>
                  )}
                </div>
                {c.video_prompt && (
                  <>
                    <div style={{ fontSize: 13, margin: '10px 0 4px' }}><b>视频提示词</b></div>
                    <pre className="prompt-box">{c.video_prompt}</pre>
                  </>
                )}
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            提示：复制提示词后，可在「创意提示词」中保存为可复用模板，实现「吸收全球优秀投放师敏感度」的同步沉淀。
          </div>
        </div>
      )}
    </div>
  )
}
