import { useState } from 'react'
import { api, LandingAnalysis, LandingChannel, ModelInfo } from '../api'
import MediaAdStudio from './MediaAdStudio'

// 8 个必要字段的展示元信息（顺序即展示顺序）
const FIELD_META = [
  { key: 'language', label: '语言', hint: '网站主要语言' },
  { key: 'industry', label: '行业', hint: '从网站主营信息推断出的行业' },
  { key: 'type', label: '类型', hint: '网站属性：电商 / 技术服务 / 公益 / 政府 / 旅游 / 家政…' },
  { key: 'audience', label: '对象', hint: '目标人群 / 企业 / 渠道 / 地区' },
] as const

function modelLabel(m: ModelInfo): string {
  if (!m.provider) return '—'
  const role = m.role === 'copy' ? '（复用「文案」模型）' : ''
  const fb = m.fallback ? '（调用失败，已回退）' : ''
  return `${m.provider} / ${m.model}${role}${fb}`
}

export default function MaterialCreation({ meta }: { meta: any }) {
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [showText, setShowText] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  // 单条分析记录（逐步重建：一次只分析一个落地页）
  const [data, setData] = useState<LandingAnalysis | null>(null)

  const run = async () => {
    if (!url.trim() && !text.trim()) { setErr('请填写落地页链接或正文'); return }
    setErr(''); setBusy(true); setData(null)
    try {
      const res = await api.landingAnalysis({
        url: url.trim() || undefined,
        text: text.trim() || undefined,
      })
      setData(res)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card step">
        <div className="step-head">
          <div className="step-title-wrap">
            <h3 className="step-title">落地页分析与评价</h3>
            <div className="step-desc">
              输入要分析的落地页链接或正文，调用已配置的「大模型配置」中的模型进行推理，
              提取 8 项关键信息；分析完成后会标注本次实际调用了哪个大模型，便于持续跟踪其优劣势。
            </div>
          </div>
        </div>

        <div className="analyze-box">
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (url || text)) run() }}
            placeholder="https://你的产品落地页"
          />
          <button
            className="btn"
            onClick={run}
            disabled={busy || (!url.trim() && !text.trim())}
          >
            {busy ? '分析中…' : data ? '重新分析' : '抓取并分析'}
          </button>
        </div>

        <div className="analyze-sub">
          <button className="linkbtn" onClick={() => setShowText(v => !v)}>
            {showText ? '收起正文输入' : '链接打不开？粘贴落地页正文 / 产品说明'}
          </button>
          <span className="muted">支持 JS 渲染失败的站点、内部测试页，或只有一份产品文档的情况</span>
        </div>

        {showText && (
          <textarea
            rows={5}
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="把落地页正文、产品介绍或投放 brief 粘进来。"
          />
        )}

        {busy && <div className="alert ok">正在抓取落地页并调用大模型推理分析…</div>}
        {err && <div className="alert err">{err}</div>}
      </div>

      {data && (
        <>
          <ResultView data={data} />
          <div id="media-studio" className="media-studio-section">
            <MediaAdStudio
              initialAnalysis={data}
              onGotoCreation={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            />
          </div>
        </>
      )}
    </div>
  )
}

function ResultView({ data }: { data: LandingAnalysis }) {
  const m = data.model_info
  const llmUsed = data.source === 'llm'

  return (
    <div className="card step">
      {/* 模型信息 banner：明确"这次分析用了哪个模型" */}
      <div className={'la-model ' + (llmUsed ? 'ok' : 'warn')}>
        {llmUsed ? (
          <>本次分析由大模型 <b>{modelLabel(m)}</b> 推理产出。</>
        ) : (
          <><b>未使用大模型推理</b>：{m.provider
            ? `模型「${modelLabel(m)}」调用失败`
            : '系统尚未在「大模型配置」中配置可用的「分析 / 文案」模型'}，
            以下结果为本地兜底，请在「大模型配置」中配置后重试。</>
        )}
      </div>

      <div className="la-next">
        <span className="muted">分析完成。以下将基于上述结论进行营销推广设置与推广图片生成：</span>
        <button className="btn primary" onClick={() => document.getElementById('media-studio')?.scrollIntoView({ behavior: 'smooth' })}>开始营销推广设置 ↓</button>
      </div>

      {/* (1) 网站地址：仅展示 */}
      <div className="la-field">
        <div className="la-label">① 网站地址<span className="la-hint">仅展示，不参与推理</span></div>
        <div className="la-value">
          {data.url ? (
            <a href={data.url} target="_blank" rel="noreferrer">{data.url}</a>
          ) : '—'}
        </div>
      </div>

      {/* (2)-(5) 基础四字段 */}
      <div className="la-grid">
        {FIELD_META.map(f => (
          <div className="la-field" key={f.key}>
            <div className="la-label">{labelIndex(f.key)} {f.label}<span className="la-hint">{f.hint}</span></div>
            <div className="la-value">{(data as any)[f.key] || '—'}</div>
          </div>
        ))}
      </div>

      {/* (6) 竞品 */}
      <div className="la-field">
        <div className="la-label">⑥ 竞品<span className="la-hint">全球排名 Top 3</span></div>
        <div className="la-value">
          {data.competitors.length ? (
            <div className="la-tags">
              {data.competitors.map((c, i) => <span key={i} className="pill off">{c}</span>)}
            </div>
          ) : '—'}
        </div>
      </div>

      {/* (7) 优势 */}
      <div className="la-field">
        <div className="la-label">⑦ 优势<span className="la-hint">提炼核心卖点，非功能罗列（≤5）</span></div>
        <div className="la-value">
          {data.advantages.length ? (
            <ul className="la-list">
              {data.advantages.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          ) : '—'}
        </div>
      </div>

      {/* (8) 推广途径 */}
      <div className="la-field">
        <div className="la-label">⑧ 推广途径<span className="la-hint">推荐媒体平台 + 理由（≤5）</span></div>
        <div className="la-value">
          {data.channels.length ? (
            <div className="la-channels">
              {data.channels.map((c: LandingChannel, i) => (
                <div key={i} className="la-channel">
                  <span className="pill ok">{c.platform}</span>
                  <span className="la-reason">{c.reason || '—'}</span>
                </div>
              ))}
            </div>
          ) : '—'}
        </div>
      </div>
    </div>
  )
}

// 给基础四字段补上序号（②-⑤），与 ①⑥⑦⑧ 一致
function labelIndex(key: string): string {
  return { language: '②', industry: '③', type: '④', audience: '⑤' }[key] || ''
}
