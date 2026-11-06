import { useEffect, useMemo, useState } from 'react'
import { api, LandingAnalysis, MediaPlatform, MediaCopyResult, MediaImageResult, MediaImageItem, CreativePresets, ModelInfo } from '../api'

type Step = 1 | 2 | 3

interface Props {
  initialAnalysis: LandingAnalysis | null
  onGotoCreation: () => void
  selectedLogo?: string
}

function ModelBadge({ info, fallbackText }: { info: ModelInfo; fallbackText?: string }) {
  if (!info) return null
  const name = info.model ? `${info.provider} / ${info.model}` : (info.provider || '内置兜底')
  return (
    <span className={`model-badge ${info.fallback ? 'warn' : 'ok'}`} title={`用途：${info.role || '-'}`}>
      <span className="mb-dot" />
      调用模型：{name}
      {info.fallback && <em>（未配置模型，{fallbackText || '使用内置兜底'}）</em>}
    </span>
  )
}

export default function MediaAdStudio({ initialAnalysis, onGotoCreation, selectedLogo }: Props) {
  const [analysis, setAnalysis] = useState<LandingAnalysis | null>(initialAnalysis)
  const [platforms, setPlatforms] = useState<MediaPlatform[]>([])
  const [presets, setPresets] = useState<CreativePresets | null>(null)

  const [step, setStep] = useState<Step>(1)
  const [platform, setPlatform] = useState('')
  const [selectedPlacements, setSelectedPlacements] = useState<string[]>([])
  const [count, setCount] = useState(3)
  const [lang, setLang] = useState('en')

  const [copy, setCopy] = useState<MediaCopyResult | null>(null)
  const [copyEdit, setCopyEdit] = useState<Record<string, any>>({})
  const [brandEdit, setBrandEdit] = useState('')

  const [direction, setDirection] = useState('')
  const [styleName, setStyleName] = useState('')
  const [colorName, setColorName] = useState('')

  const [images, setImages] = useState<MediaImageItem[]>([])
  const [imageModel, setImageModel] = useState<ModelInfo | null>(null)
  const [imgNote, setImgNote] = useState('')

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.mediaPlatforms().catch(() => []), api.creativePresets().catch(() => null)])
      .then(([ps, pr]) => {
        setPlatforms(ps as MediaPlatform[])
        setPresets(pr as CreativePresets)
      })
  }, [])

  // 落地页分析结果变化时，重置流程（确保"先分析、再推广"的顺序）
  useEffect(() => {
    setAnalysis(initialAnalysis)
    if (initialAnalysis) {
      const l = (initialAnalysis.language || '').toLowerCase()
      setLang(['en', 'es', 'pt', 'id'].includes(l) ? l : 'en')
      setStep(1)
      setPlatform('')
      setCopy(null)
      setImages([])
      setImageModel(null)
      setDirection(''); setStyleName(''); setColorName('')
    }
  }, [initialAnalysis])

  const spec = useMemo(() => platforms.find(p => p.platform === platform) || null, [platforms, platform])

  function choosePlatform(p: string) {
    const sp = platforms.find(x => x.platform === p)
    setPlatform(p)
    setSelectedPlacements(sp ? sp.placements.filter(pl => pl.default).map(pl => pl.id) : [])
    setCount(sp ? sp.recommended_count : 3)
    setCopy(null); setImages([]); setImageModel(null); setError('')
  }

  function togglePlacement(id: string) {
    setSelectedPlacements(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  function buildSlots(): { size: string; placement: string }[] {
    if (!spec) return []
    const pairs: { size: string; placement: string }[] = []
    for (const id of selectedPlacements) {
      const pl = spec.placements.find(p => p.id === id)
      if (!pl) continue
      for (const size of pl.sizes) pairs.push({ size, placement: pl.name })
    }
    return pairs.slice(0, Math.max(1, count))
  }

  async function genCopy() {
    if (!analysis) { setError('请先在「素材创作」完成落地页分析'); return }
    if (!platform) { setError('请选择一个媒体推广平台'); return }
    setBusy(true); setError('')
    try {
      const res = await api.mediaCopy({ analysis, platform, lang })
      setCopy(res)
      setCopyEdit({ ...res.fields })
      setBrandEdit(res.brand || '')
      setStep(2)
    } catch (e: any) {
      setError(e?.message || '文案生成失败')
    } finally {
      setBusy(false)
    }
  }

  function setField(key: string, value: any) {
    setCopyEdit(prev => ({ ...prev, [key]: value }))
  }

  async function genImages() {
    if (!analysis || !platform || !copy) return
    setBusy(true); setError('')
    try {
      const slots = buildSlots()
      if (!slots.length) { setError('请至少选择一个广告版位'); setBusy(false); return }
      const payloadCopy = { ...copyEdit, brand: brandEdit }
      const res = await api.mediaImages({
        analysis, platform, lang,
        copy_fields: payloadCopy,
        style_opts: { creative_direction: direction, content_style: styleName, color_scheme: colorName },
        slots,
        logo: selectedLogo || "",
      })
      setImages(res.images)
      setImageModel(res.image_model)
      setImgNote(res.note || '')
      setStep(3)
    } catch (e: any) {
      setError(e?.message || '图片生成失败')
    } finally {
      setBusy(false)
    }
  }

  // ----------------------------- 渲染辅助 -----------------------------
  const analysisSummary = analysis ? [
    analysis.industry && `行业：${analysis.industry}`,
    analysis.type && `类型：${analysis.type}`,
    analysis.audience && `对象：${analysis.audience}`,
    analysis.advantages?.length && `优势：${analysis.advantages.join('、')}`,
    analysis.competitors?.length && `竞品：${analysis.competitors.join('、')}`,
  ].filter(Boolean).join('　|　') : ''

  const STEPS: { id: Step; label: string }[] = [
    { id: 1, label: '设置媒体平台' },
    { id: 2, label: '展示文案' },
    { id: 3, label: '生成推广图片' },
  ]

  if (!analysis) {
    return (
      <div className="card media-empty">
        <h3>营销推广的媒体平台设置</h3>
        <p className="muted">本模块需要先对落地页做分析，再据此生成推广素材。</p>
        <button className="btn" onClick={onGotoCreation}>前往「素材创作」分析落地页</button>
      </div>
    )
  }

  return (
    <div className="media-studio">
      <div className="card media-analysis">
        <div className="ma-head">
          <b>落地页分析结论（生成依据）</b>
          <ModelBadge info={analysis.model_info} fallbackText="分析未走大模型" />
        </div>
        <div className="ma-url">{analysis.url || '（直接输入正文）'}</div>
        <div className="ma-summary">{analysisSummary || '（分析结论为空，请回到「素材创作」重新分析）'}</div>
      </div>

      {/* 步骤条 */}
      <div className="stepper">
        {STEPS.map(s => (
          <button
            key={s.id}
            className={`mstep ${step === s.id ? 'active' : ''} ${step > s.id ? 'done' : ''}`}
            onClick={() => s.id < step && setStep(s.id)}
            disabled={s.id > step}
          >
            <span className="mstep-no">{s.id}</span>
            <span className="mstep-label">{s.label}</span>
          </button>
        ))}
      </div>

      {error && <div className="alert err">{error}</div>}

      {/* Step 1：设置媒体平台 */}
      {step === 1 && (
        <div className="card">
          <h3>① 选择媒体推广平台（默认单平台）</h3>
          <p className="muted">只能选择一个平台；选中后展示该平台支持的图片素材数量、规格与尺寸，并可按常规方案调整。</p>
          <div className="platform-grid">
            {platforms.map(p => (
              <button
                key={p.platform}
                className={`platform-card ${platform === p.platform ? 'active' : ''}`}
                onClick={() => choosePlatform(p.platform)}
              >
                <span className="pc-name">{p.platform}</span>
                <span className="pc-count">常规 {p.recommended_count} 张</span>
                <span className="pc-sizes">{p.image_sizes.join(' · ')}</span>
              </button>
            ))}
          </div>

          {spec && (
            <div className="spec-panel">
              <div className="sp-head">
                <b>{spec.platform} · 规格与尺寸</b>
                <span className="pill img">图片素材 {spec.recommended_count} 张</span>
              </div>
              <ul className="sp-meta">
                <li><span>支持尺寸</span>{spec.image_sizes.join('、')}</li>
                <li><span>常规用法</span>{spec.usage}</li>
              </ul>
              <div className="sp-placements">
                {spec.placements.map(pl => (
                  <label key={pl.id} className={`placement-card ${selectedPlacements.includes(pl.id) ? 'on' : ''}`}>
                    <input type="checkbox" checked={selectedPlacements.includes(pl.id)} onChange={() => togglePlacement(pl.id)} />
                    <span className="pl-name">{pl.name}{pl.default && <em>常规</em>}</span>
                    <span className="pl-desc">{pl.desc}</span>
                    <span className="pl-sizes">{pl.sizes.join(' · ')}</span>
                  </label>
                ))}
              </div>
              <div className="sp-count">
                <label>生成图片数量：</label>
                <input
                  type="number" min={1} max={20} value={count}
                  onChange={e => setCount(Math.max(1, parseInt(e.target.value || '1', 10)))}
                />
                <span className="muted">（按所选版位顺序取前 {Math.max(1, count)} 张）</span>
              </div>
              <div className="sp-lang">
                <label>文案语言：</label>
                <select value={lang} onChange={e => setLang(e.target.value)}>
                  {['en', 'es', 'pt', 'id', 'zh', 'ja', 'ko', 'ar', 'fr', 'de'].map(l => (
                    <option key={l} value={l}>{l.toUpperCase()}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div className="form-actions">
            <button className="btn primary" disabled={!platform || busy} onClick={genCopy}>
              {busy ? '生成中…' : '生成广告文案 →'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2：展示文案 + 风格设置 */}
      {step === 2 && copy && (
        <div className="card">
          <h3>② 广告文案（已结合落地页分析结论生成，可编辑）</h3>
          <ModelBadge info={copy.model_info} fallbackText="文案未走大模型" />
          <div className="copy-grid">
            {copy.schema.map(f => (
              <div className="copy-field" key={f.key}>
                <label>
                  {f.label}
                  <span className="cf-limit">≤ {f.max}{f.count > 1 ? ` ×${f.count}` : ''}</span>
                </label>
                {f.count > 1 ? (
                  <div className="cf-multi">
                    {(copyEdit[f.key] && Array.isArray(copyEdit[f.key]) ? copyEdit[f.key] : ['']).map((v: string, i: number) => (
                      <input
                        key={i}
                        value={v || ''}
                        maxLength={f.max + 4}
                        onChange={e => {
                          const arr = Array.isArray(copyEdit[f.key]) ? [...copyEdit[f.key]] : []
                          arr[i] = e.target.value
                          setField(f.key, arr)
                        }}
                        placeholder={`${f.label} ${i + 1}`}
                      />
                    ))}
                  </div>
                ) : (
                  <input
                    value={copyEdit[f.key] ?? ''}
                    maxLength={f.max + 4}
                    onChange={e => setField(f.key, e.target.value)}
                  />
                )}
              </div>
            ))}
            <div className="copy-field">
              <label>品牌名（显示在图片）</label>
              <input value={brandEdit} maxLength={40} onChange={e => setBrandEdit(e.target.value)} placeholder="留空则自动从域名推断" />
            </div>
          </div>

          {/* 图片风格 / 样式 / 颜色 */}
          <div className="style-panel">
            <h4>图片生成风格设置（生成前可选，越丰富越能吸引用户）</h4>
            <div className="style-row">
              <label>创意方向
                <select value={direction} onChange={e => setDirection(e.target.value)}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.directions.map(d => <option key={d.id} value={d.id}>{d.id} · {d.name}</option>)}
                </select>
              </label>
              <label>内容风格
                <select value={styleName} onChange={e => setStyleName(e.target.value)}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.styles.map(s => <option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}
                </select>
              </label>
              <label>配色方案
                <select value={colorName} onChange={e => setColorName(e.target.value)}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.colors.map(c => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
                </select>
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button className="btn" onClick={() => setStep(1)}>← 上一步</button>
            <button className="btn primary" disabled={busy} onClick={genImages}>
              {busy ? '生成中…' : '生成推广图片 →'}
            </button>
          </div>
        </div>
      )}

      {/* Step 3：生成推广图片 */}
      {step === 3 && (
        <div className="card">
          <h3>③ 推广图片素材</h3>
          {imageModel && <ModelBadge info={imageModel} fallbackText="使用 Pillow 模板兜底" />}
          {imgNote && <p className="muted">{imgNote}</p>}
          <div className="img-grid">
            {images.map((img, i) => (
              <div className="img-card" key={i}>
                <img src={api.fileUrl(img.url)} alt={`${img.placement} ${img.size}`} loading="lazy" />
                <div className="ic-meta">
                  <span className="pill img">{img.size}</span>
                  <span className="muted">{img.placement}</span>
                </div>
              </div>
            ))}
          </div>
          {!images.length && <p className="muted">未生成图片，请返回上一步检查版位与数量设置。</p>}
          <div className="form-actions">
            <button className="btn" onClick={() => setStep(2)}>← 上一步</button>
            <button className="btn primary" onClick={genImages} disabled={busy}>
              {busy ? '重新生成中…' : '重新生成'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
