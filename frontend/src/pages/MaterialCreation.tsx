import { useState, useEffect, ChangeEvent } from 'react'
import { api, LandingAnalysis, LandingChannel, ModelInfo } from '../api'

/** 「素材历史 → 复用分析继续创作」的跨页面握手（sessionStorage + 自定义事件） */
export const REUSE_HISTORY_KEY = 'admb:reuseHistory'
export const REUSE_HISTORY_EVENT = 'admb:reuseHistory'
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

export default function MaterialCreation() {
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [showText, setShowText] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  // 单条分析记录（逐步重建：一次只分析一个落地页）
  const [data, setData] = useState<LandingAnalysis | null>(null)
  // V4.36：本次创作会话对应的「素材历史」id，文案 / 图片会增量写回
  const [historyId, setHistoryId] = useState<number | null>(null)
  // 品牌 logo 选择状态：auto=用抓取的；upload=用本地上传的；none=不使用 logo
  const [logoMode, setLogoMode] = useState<'auto' | 'upload' | 'none'>('auto')
  const [uploadedLogo, setUploadedLogo] = useState('')

  // 从「素材历史」复用已保存的分析结论：不重新抓站、不重新调用大模型，直接进入推广设置。
  // 若当前不在本页，组件挂载时读取 sessionStorage；若已在本页，由自定义事件触发。
  useEffect(() => {
    const apply = () => {
      const raw = sessionStorage.getItem(REUSE_HISTORY_KEY)
      if (!raw) return
      sessionStorage.removeItem(REUSE_HISTORY_KEY)
      try {
        const p = JSON.parse(raw)
        if (!p?.analysis) return
        setData(p.analysis)
        setHistoryId(p.historyId ?? null)
        setUrl(p.analysis.url || '')
        setText('')
        setLogoMode('auto'); setUploadedLogo('')
        setErr('')
        setTimeout(() => document.getElementById('media-studio')?.scrollIntoView({ behavior: 'smooth' }), 120)
      } catch { /* 忽略损坏的暂存数据 */ }
    }
    apply()
    window.addEventListener(REUSE_HISTORY_EVENT, apply)
    return () => window.removeEventListener(REUSE_HISTORY_EVENT, apply)
  }, [])

  const run = async () => {
    if (!url.trim() && !text.trim()) { setErr('请填写落地页链接或正文'); return }
    setErr(''); setBusy(true); setData(null); setHistoryId(null)
    setLogoMode('auto'); setUploadedLogo('')
    try {
      const res = await api.landingAnalysis({
        url: url.trim() || undefined,
        text: text.trim() || undefined,
      })
      // 分析完成即建立历史会话（本地 DB 写入，失败不阻断创作主流程）
      let hid: number | null = null
      try {
        const h = await api.createCreationHistory({ analysis: res })
        hid = h.id
      } catch { /* 历史写入失败不影响本次生成 */ }
      setHistoryId(hid)
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
          <ResultView
            data={data}
            historyId={historyId}
            logoMode={logoMode}
            uploadedLogo={uploadedLogo}
            onLogoMode={setLogoMode}
            onUploaded={setUploadedLogo}
            onUpload={(e) => onUploadLogo(e, setUploadedLogo, setErr, setLogoMode)}
            onErr={setErr}
          />
          <div id="media-studio" className="media-studio-section">
            <MediaAdStudio
              initialAnalysis={data}
              onGotoCreation={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              selectedLogo={logoMode === 'upload' ? uploadedLogo : logoMode === 'none' ? '' : (data.logo || '')}
              historyId={historyId}
            />
          </div>
        </>
      )}
    </div>
  )
}

async function onUploadLogo(e: ChangeEvent<HTMLInputElement>, onUploaded: (url: string) => void, onErr: (msg: string) => void, onMode: (m: 'auto' | 'upload' | 'none') => void) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    const r = await api.uploadAsset(file)
    onUploaded(r.url)
    onMode('upload')
  } catch (err: any) {
    onErr(err?.message || '上传失败')
  } finally {
    e.target.value = ''
  }
}

function ResultView({ data, historyId, logoMode, uploadedLogo, onLogoMode, onUploaded, onUpload, onErr }: {
  data: LandingAnalysis
  historyId: number | null
  logoMode: 'auto' | 'upload' | 'none'
  uploadedLogo: string
  onLogoMode: (m: 'auto' | 'upload' | 'none') => void
  onUploaded: (url: string) => void
  onUpload: (e: ChangeEvent<HTMLInputElement>) => void
  onErr: (msg: string) => void
}) {
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
      {historyId && (
        <div className="la-hist-hint muted">
          本次分析已自动存入「素材历史」#{historyId}；后续生成的文案与推广图片会一并归档，
          可在「素材历史」中查阅、放大与再下载，无需重复生成。
        </div>
      )}

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

      {/* (9) 品牌 Logo：抓取展示 + 可选使用 / 上传 */}
      <div className="la-field la-logo">
        <div className="la-label">⑨ 品牌 Logo<span className="la-hint">用于后续推广图合成，可选择使用或上传</span></div>
        <div className="la-value">
          {data.logo ? (
            <div className="logo-preview">
              <img src={data.logo} alt="抓取到的品牌 Logo" className="logo-img" referrerPolicy="no-referrer" />
              <span className="muted">已从落地页抓取</span>
            </div>
          ) : (
            <div className="logo-preview logo-empty">未抓取到 Logo</div>
          )}

          {data.logo && (
            <label className="logo-toggle">
              <input
                type="checkbox"
                checked={logoMode === 'auto'}
                onChange={e => onLogoMode(e.target.checked ? 'auto' : 'none')}
              />
              使用抓取到的 Logo 合成图片
            </label>
          )}

          <div className="logo-upload">
            <label className="logo-upload-btn">
              {logoMode === 'upload' ? '重新上传本地 Logo' : '上传本地 Logo'}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={onUpload}
              />
            </label>
            {logoMode === 'upload' && uploadedLogo && (
              <div className="logo-preview">
                <img src={api.fileUrl(uploadedLogo)} alt="已上传品牌 Logo" className="logo-img" />
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => onLogoMode(data.logo ? 'auto' : 'none')}
                >
                  移除，改用{data.logo ? '抓取到的 Logo' : '不使用 Logo'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// 给基础四字段补上序号（②-⑤），与 ①⑥⑦⑧ 一致
function labelIndex(key: string): string {
  return { language: '②', industry: '③', type: '④', audience: '⑤' }[key] || ''
}
