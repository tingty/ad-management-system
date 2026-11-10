import { useEffect, useState, ChangeEvent } from 'react'
import { api, LandingAnalysis, LandingChannel, ModelInfo, IndustryProfile } from '../api'
import {
  useCreationSession, updateSession, studioDefaults, clearSession, getSession,
  beginTask, endTask, failTask, logTask,
} from '../creationSession'
import MediaAdStudio from './MediaAdStudio'

/** 「素材历史 → 复用分析继续创作」的跨页面握手（sessionStorage + 自定义事件） */
export const REUSE_HISTORY_KEY = 'admb:reuseHistory'
export const REUSE_HISTORY_EVENT = 'admb:reuseHistory'

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
  /* V4.38：状态全部放在跨页面会话中枢里。组件由 App 常驻挂载，
     切换到其它菜单时不会被卸载，正在进行的请求与结果都不会丢失。 */
  const s = useCreationSession()

  // 从「素材历史」复用已保存的分析结论：不重新抓站、不重新调用大模型，直接进入推广设置。
  // V4.38：由于本组件常驻挂载，即使当前停留在「素材历史」页也能立即接收握手并还原现场。
  useEffect(() => {
    const apply = () => {
      const raw = sessionStorage.getItem(REUSE_HISTORY_KEY)
      if (!raw) return
      // 有任务在跑时不覆盖会话，避免进行中的请求把结果写进刚复用的新现场
      if (getSession().running) {
        sessionStorage.removeItem(REUSE_HISTORY_KEY)
        updateSession({ error: '当前有创作任务正在执行，请等待完成后再复用「素材历史」分析。' })
        return
      }
      sessionStorage.removeItem(REUSE_HISTORY_KEY)
      try {
        const p = JSON.parse(raw)
        if (!p?.analysis) return
        updateSession({
          ...studioDefaults(),
          analysis: p.analysis,
          historyId: p.historyId ?? null,
          urlInput: p.analysis.url || '',
          textInput: '',
          logoMode: 'auto', uploadedLogo: '', error: '',
          stage: 'analyzed', running: false,
          taskLabel: '已复用「素材历史」分析结论',
          taskDetail: '跳过重复抓站与大模型推理，可直接进行营销推广设置。',
          taskLogs: [{ at: Date.now(), text: '复用历史分析结论，新建创作会话', kind: 'ok' }],
          taskStartedAt: null, taskUpdatedAt: Date.now(),
        })
        setTimeout(() => document.getElementById('media-studio')?.scrollIntoView({ behavior: 'smooth' }), 120)
      } catch { /* 忽略损坏的暂存数据 */ }
    }
    apply()
    window.addEventListener(REUSE_HISTORY_EVENT, apply)
    return () => window.removeEventListener(REUSE_HISTORY_EVENT, apply)
  }, [])

  const run = async () => {
    const url = s.urlInput.trim(), text = s.textInput.trim()
    if (!url && !text) { updateSession({ error: '请填写落地页链接或正文' }); return }
    if (s.running) return
    updateSession({ error: '', analysis: null, historyId: null, ...studioDefaults(), logoMode: 'auto', uploadedLogo: '' })
    beginTask('analyzing', '正在分析落地页', '抓取页面并调用已配置的大模型推理 8 项关键结论…')
    try {
      const res = await api.landingAnalysis({ url: url || undefined, text: text || undefined })
      const l = (res.language || '').toLowerCase()
      updateSession({ lang: ['en', 'es', 'pt', 'id'].includes(l) ? l : 'en' })
      // 分析完成即建立历史会话（本地 DB 写入，失败不阻断创作主流程）
      let hid: number | null = null
      try {
        const h = await api.createCreationHistory({ analysis: res })
        hid = h.id
        logTask(`已建立「素材历史」会话 #${h.id}`, 'info')
      } catch { /* 历史写入失败不影响本次生成 */ }
      updateSession({ historyId: hid, analysis: res })
      endTask('analyzed', '落地页分析完成',
        `实际模型：${modelLabel(res.model_info)}；已得到 8 项结论，可继续进行营销推广设置。`)
    } catch (e: any) {
      failTask(e?.message || '落地页分析失败')
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
            value={s.urlInput}
            onChange={e => updateSession({ urlInput: e.target.value })}
            onKeyDown={e => { if (e.key === 'Enter' && (s.urlInput || s.textInput)) run() }}
            placeholder="https://你的产品落地页"
          />
          <button
            className="btn"
            onClick={run}
            disabled={s.running || (!s.urlInput.trim() && !s.textInput.trim())}
          >
            {s.running ? '任务进行中…' : s.analysis ? '重新分析' : '抓取并分析'}
          </button>
        </div>

        <div className="analyze-sub">
          <button className="linkbtn" onClick={() => updateSession({ showText: !s.showText })}>
            {s.showText ? '收起正文输入' : '链接打不开？粘贴落地页正文 / 产品说明'}
          </button>
          <span className="muted">支持 JS 渲染失败的站点、内部测试页，或只有一份产品文档的情况</span>
          <button
            className="linkbtn"
            disabled={s.running}
            onClick={() => {
              if (s.running) return
              if (window.confirm('清空当前创作工作台（含分析结论、文案与图片）并重新开始？\n已存入「素材历史」的记录不会被删除。')) clearSession()
            }}
          >
            新建创作会话
          </button>
        </div>

        {s.showText && (
          <textarea
            rows={5}
            value={s.textInput}
            onChange={e => updateSession({ textInput: e.target.value })}
            placeholder="把落地页正文、产品介绍或投放 brief 粘进来。"
          />
        )}

        <div className="ct-inline-hint muted">
          任务进行中可切换到其它菜单，分析与生成不会中断；右下角「创作任务」可查看实时进度并一键返回继续调整。
        </div>

        {s.running && s.stage === 'analyzing' && (
          <div className="alert ok">正在抓取落地页并调用大模型推理分析…</div>
        )}
        {s.error && <div className="alert err">{s.error}</div>}
      </div>

      {s.analysis && (
        <>
          <ResultView
            data={s.analysis}
            historyId={s.historyId}
            logoMode={s.logoMode}
            uploadedLogo={s.uploadedLogo}
            onLogoMode={m => updateSession({ logoMode: m })}
            onUpload={(e) => onUploadLogo(e)}
          />
          <div id="media-studio" className="media-studio-section">
            <MediaAdStudio />
          </div>
        </>
      )}
    </div>
  )
}

async function onUploadLogo(e: ChangeEvent<HTMLInputElement>) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    const r = await api.uploadAsset(file)
    updateSession({ uploadedLogo: r.url, logoMode: 'upload' })
  } catch (err: any) {
    updateSession({ error: err?.message || '上传失败' })
  } finally {
    e.target.value = ''
  }
}

function ResultView({ data, historyId, logoMode, uploadedLogo, onLogoMode, onUpload }: {
  data: LandingAnalysis
  historyId: number | null
  logoMode: 'auto' | 'upload' | 'none'
  uploadedLogo: string
  onLogoMode: (m: 'auto' | 'upload' | 'none') => void
  onUpload: (e: ChangeEvent<HTMLInputElement>) => void
}) {
  const m = data.model_info
  const llmUsed = data.source === 'llm'
  const mockUsed = data.source === 'mock'
  const [profiles, setProfiles] = useState<IndustryProfile[]>([])
  useEffect(() => {
    let alive = true
    api.industryProfiles().then(d => alive && setProfiles(d.profiles)).catch(() => {})
    return () => { alive = false }
  }, [])
  const currentProfile = profiles.find(p => p.key === data.industry_profile)

  /** V4.39：用户明确确认品牌 / 调整行业画像，直接写回会话里的分析结论。 */
  function patchAnalysis(patch: Partial<LandingAnalysis>) {
    const cur = getSession().analysis
    if (cur) updateSession({ analysis: { ...cur, ...patch } })
  }

  return (
    <div className="card step">
      {/* 模型信息 banner：如实区分 llm / mock / local，不把回退误标成真实模型 */}
      <div className={'la-model ' + (llmUsed ? 'ok' : 'warn')}>
        {llmUsed ? (
          <>本次分析由大模型 <b>{modelLabel(m)}</b> 推理产出。</>
        ) : mockUsed ? (
          <><b>实际使用了 Mock 兜底</b>：配置的模型「{modelLabel(m)}」调用失败
          {m.error_type ? `（${m.error_type}）` : ''}，结果不可作为可投放事实；
          请检查「大模型配置」的连通性后重试。</>
        ) : (
          <><b>未使用大模型推理</b>：{m.provider
            ? `模型「${modelLabel(m)}」调用失败`
            : '系统尚未在「大模型配置」中配置可用的「分析 / 文案」模型'}，
            以下结果为本地兜底，请在「大模型配置」中配置后重试。</>
        )}
        {m.request_id && <span className="la-req muted">调用快照 #{m.request_id}
          {m.config_id ? ` · 配置 ${m.config_id}` : ''} · 来源 {m.source || data.source}</span>}
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

      {/* V4.39：F02 / F10 的可核验信息 + 行业画像局部调整 */}
      <div className="la-trust">
        <div className="la-trust-head">
          <b>输入可信度与行业适配</b>
          <span className="muted">V4.39 · 通用主干 + 局部调整</span>
        </div>
        <div className="la-trust-grid">
          <div className="la-trust-item"><span>输入链接（仅追踪）</span><b>{data.input_url || data.url || '—'}</b></div>
          <div className="la-trust-item"><span>最终落地页（相对链接基准）</span><b>{data.final_url || '—'}</b></div>
          <div className="la-trust-item">
            <span>跳转 / 抓取质量</span>
            <b>{(data.redirect_chain || []).length} 次跳转 · {{
              ok: '正常', thin_content: '正文过少', fetch_failed: '抓取失败',
              manual_text: '手工正文', not_fetched: '未抓取',
            }[data.fetch_quality || 'not_fetched'] || data.fetch_quality}</b>
          </div>
          <div className="la-trust-item">
            <span>模型调用来源</span>
            <b>{data.source === 'llm' ? '真实大模型' : data.source === 'mock' ? 'Mock 兜底（不可作投放事实）' : '本地兜底'}
              {m.error_type ? ` · ${m.error_type}` : ''}</b>
          </div>
        </div>
        <div className="la-trust-row">
          <span className="la-trust-key">品牌</span>
          <input
            className="la-trust-input"
            value={data.brand || ''}
            placeholder="未确认时留空，不从追踪域名猜测"
            onChange={e => patchAnalysis({
              brand: e.target.value,
              brand_status: e.target.value.trim() ? 'confirmed' : 'needs_input',
            })}
          />
          <span className={`la-badge la-badge-${data.brand_status || 'needs_input'}`}>
            {{ confirmed: '已确认', unverified: '待核实', needs_input: '待补充' }[data.brand_status || 'needs_input']}
          </span>
          <span className="muted">{data.brand_reason || '—'}</span>
        </div>
        <div className="la-trust-row">
          <span className="la-trust-key">Logo</span>
          <span>{data.logo_source || '未抓取'} · {data.logo_verified ? '已核验' : '待核验'}</span>
          <span className="muted">{data.logo_reason || '—'}</span>
        </div>
        <div className="la-trust-row">
          <span className="la-trust-key">行业 / 品类</span>
          <select
            className="la-trust-select"
            value={data.industry_profile || '__auto__'}
            onChange={e => {
              const v = e.target.value
              const p = profiles.find(x => x.key === v)
              patchAnalysis({ industry_profile: v === '__auto__' ? '' : v,
                industry_profile_label: p ? p.label : '自动识别' })
            }}
          >
            <option value="__auto__">自动识别（当前：{data.industry_profile_label || '通用 / 未分类'}）</option>
            {profiles.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
          <span className="muted">切换画像只调整价值维度、语义保护、证据类型与视觉主体，通用链路不变。</span>
        </div>
        {currentProfile && (
          <div className="la-profile-detail">
            <span>价值维度：{currentProfile.value_axes.join(' / ')}</span>
            <span>需核验事实：{currentProfile.evidence_types.join(' / ')}</span>
            <span>视觉主体：{currentProfile.visual_subject}</span>
          </div>
        )}
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
