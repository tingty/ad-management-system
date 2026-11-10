import { useEffect, useMemo, useState } from 'react'
import { api, MediaPlatform, CreativePresets, ModelInfo } from '../api'
import {
  useCreationSession, updateSession, beginTask, endTask, failTask,
  allSelectedCopy, selectedCount, buildCopyVariants,
} from '../creationSession'
import type { StudioStep } from '../creationSession'

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

/**
 * V4.38：所有工作台状态来自跨页面会话中枢；组件本身由 App 常驻挂载。
 * 切换到其它一级菜单时，正在执行的文案 / 图片请求继续运行，回来后可直接调整。
 */
export default function MediaAdStudio() {
  const s = useCreationSession()
  const [platforms, setPlatforms] = useState<MediaPlatform[]>([])
  const [presets, setPresets] = useState<CreativePresets | null>(null)

  // 放大预览的键盘操作：ESC 关闭 / ← → 切换
  useEffect(() => {
    if (s.viewer === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { updateSession({ viewer: null }); return }
      if (!s.images.length) return
      if (e.key === 'ArrowRight')
        updateSession(st => ({ viewer: st.viewer === null ? null : (st.viewer + 1) % st.images.length }))
      else if (e.key === 'ArrowLeft')
        updateSession(st => ({ viewer: st.viewer === null ? null : (st.viewer - 1 + st.images.length) % st.images.length }))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [s.viewer, s.images.length])

  useEffect(() => {
    Promise.all([api.mediaPlatforms().catch(() => []), api.creativePresets().catch(() => null)])
      .then(([ps, pr]) => {
        setPlatforms(ps as MediaPlatform[])
        setPresets(pr as CreativePresets)
      })
  }, [])

  const spec = useMemo(() => platforms.find(p => p.platform === s.platform) || null, [platforms, s.platform])
  const variants = useMemo(() => buildCopyVariants(s), [s])
  const selCount = selectedCount(s)
  const selectedLogo = s.logoMode === 'upload' ? s.uploadedLogo
    : s.logoMode === 'none' ? '' : (s.analysis?.logo || '')

  function choosePlatform(p: string) {
    if (s.running) return   // 任务进行中不重置工作台，避免结果写回错乱
    const sp = platforms.find(x => x.platform === p)
    updateSession({
      platform: p,
      selectedPlacements: sp ? sp.placements.filter(pl => pl.default).map(pl => pl.id) : [],
      count: sp ? sp.recommended_count : 3,
      copy: null, copyEdit: {}, selectedCopy: {}, images: [], imageModel: null,
      viewer: null, checked: [], savedNote: '', studioError: '',
    })
  }

  function togglePlacement(id: string) {
    if (s.running) return
    updateSession(st => ({
      selectedPlacements: st.selectedPlacements.includes(id)
        ? st.selectedPlacements.filter(x => x !== id)
        : [...st.selectedPlacements, id],
    }))
  }

  function buildSlots(): { size: string; placement: string }[] {
    if (!spec) return []
    const pairs: { size: string; placement: string }[] = []
    for (const id of s.selectedPlacements) {
      const pl = spec.placements.find(p => p.id === id)
      if (!pl) continue
      for (const size of pl.sizes) pairs.push({ size, placement: pl.name })
    }
    return pairs.slice(0, Math.max(1, s.count))
  }

  async function genCopy() {
    if (!s.analysis) { updateSession({ studioError: '请先在「素材创作」完成落地页分析' }); return }
    if (!s.platform) { updateSession({ studioError: '请选择一个媒体推广平台' }); return }
    if (s.running) return
    updateSession({ studioError: '' })
    beginTask('copy', '正在生成广告文案', `平台 ${s.platform} · 语言 ${s.lang.toUpperCase()}，调用文案大模型…`)
    try {
      const res = await api.mediaCopy({ analysis: s.analysis, platform: s.platform, lang: s.lang })
      const sel = allSelectedCopy(res, { ...res.fields })
      updateSession({
        copy: res, copyEdit: { ...res.fields }, brandEdit: res.brand || '',
        selectedCopy: sel, step: 2, savedNote: '',
      })
      endTask('copy_ready', '广告文案已生成',
        `共 ${res.schema.reduce((n, f) => n + f.count, 0)} 条可编辑文案；生成图片前可逐条勾选作为创意素材。` +
        (res.needs_revision?.length
          ? ` 其中 ${res.needs_revision.length} 条超长文案语义压缩未通过（needs_revision），需人工修改后才能作为合格素材。`
          : ''))
      // V4.36：文案一生成即写入历史，即使后续没有出图也能在「素材历史」查阅 / 再下载
      if (s.historyId) {
        api.updateCreationHistory(s.historyId, {
          platform: s.platform, lang: s.lang, copy: { ...res, selected_copy: sel },
        }).then(() => updateSession({ savedNote: '文案已存入「素材历史」' })).catch(() => {})
      }
    } catch (e: any) {
      failTask(e?.message || '文案生成失败')
    }
  }

  function setField(key: string, value: any) {
    updateSession(st => ({ copyEdit: { ...st.copyEdit, [key]: value } }))
  }

  function isCopySelected(key: string, index: number): boolean {
    return s.selectedCopy[key]?.[index] ?? true
  }

  function toggleCopyItem(key: string, index: number) {
    updateSession(st => {
      const cur = st.selectedCopy[key] || []
      const next = [...cur]
      while (next.length <= index) next.push(true)
      next[index] = !(next[index] ?? true)
      return { selectedCopy: { ...st.selectedCopy, [key]: next } }
    })
  }

  function setAllCopy(value: boolean) {
    updateSession(st => {
      const out: Record<string, boolean[]> = {}
      for (const f of st.copy?.schema || []) {
        const v = st.copyEdit[f.key]
        const n = Array.isArray(v) ? v.length : 1
        out[f.key] = Array.from({ length: Math.max(1, n) }, () => value)
      }
      return { selectedCopy: out }
    })
  }

  function onlyFirstCopy() {
    updateSession(st => {
      const out: Record<string, boolean[]> = {}
      for (const f of st.copy?.schema || []) {
        const v = st.copyEdit[f.key]
        const n = Array.isArray(v) ? v.length : 1
        out[f.key] = Array.from({ length: Math.max(1, n) }, (_, i) => i === 0)
      }
      return { selectedCopy: out }
    })
  }

  async function genImages() {
    if (!s.analysis || !s.platform || !s.copy) return
    if (s.running) return
    const slots = buildSlots()
    if (!slots.length) { updateSession({ studioError: '请至少选择一个广告版位' }); return }
    if (!variants.length) {
      updateSession({ studioError: '请至少勾选一条创意文案作为图片素材（标题 / 描述 / 正文 / CTA 均可）' })
      return
    }
    updateSession({ studioError: '' })
    beginTask('images', '正在生成推广图片',
      `共 ${slots.length} 个版位，按 ${variants.length} 组选用文案轮换出图…`)
    try {
      const payloadCopy = { ...s.copyEdit, brand: s.brandEdit }
      const res = await api.mediaImages({
        analysis: s.analysis, platform: s.platform, lang: s.lang,
        copy_fields: payloadCopy,
        copy_variants: variants,
        style_opts: { creative_direction: s.direction, content_style: s.styleName, color_scheme: s.colorName },
        slots,
        logo: selectedLogo || '',
      })
      updateSession({
        images: res.images, imageModel: res.image_model, imgNote: res.note || '',
        imageIssues: res.issues || [],
        step: 3, viewer: null, checked: [], savedNote: '',
      })
      endTask('images_ready', '本批推广图片已生成',
        `成功 ${res.images.length} 张；每张图片已标注所用创意文案，可放大查阅、单张或打包下载。` +
        (res.issues?.length ? ` 另有 ${res.issues.length} 个版位因图内文案超预算被阻止生成（needs_revision）。` : ''))
      // V4.36：把「编辑后的最终文案 + 本批图片 + 风格 / 模型」写回历史会话（追加）
      if (s.historyId) {
        const finalCopy = {
          ...s.copy, fields: { ...s.copyEdit }, brand: s.brandEdit,
          selected_copy: s.selectedCopy, copy_variants: variants,
        }
        api.updateCreationHistory(s.historyId, {
          platform: s.platform, lang: s.lang, copy: finalCopy,
          images: res.images.map(im => ({ ...im, url: im.file })),
          images_mode: 'append',
          style_opts: { creative_direction: s.direction, content_style: s.styleName, color_scheme: s.colorName },
          image_model: res.image_model,
          note: res.note || '',
        }).then(() => updateSession({ savedNote: '本批图片与选用文案已存入「素材历史」，可随时再下载' }))
          .catch(() => updateSession({ savedNote: '图片已生成，但写入「素材历史」失败' }))
      }
    } catch (e: any) {
      failTask(e?.message || '图片生成失败')
    }
  }

  // ----------------------------- 渲染辅助 -----------------------------
  const analysisSummary = s.analysis ? [
    s.analysis.industry && `行业：${s.analysis.industry}`,
    s.analysis.type && `类型：${s.analysis.type}`,
    s.analysis.audience && `对象：${s.analysis.audience}`,
    s.analysis.advantages?.length && `优势：${s.analysis.advantages.join('、')}`,
    s.analysis.competitors?.length && `竞品：${s.analysis.competitors.join('、')}`,
  ].filter(Boolean).join('　|　') : ''

  const STEPS: { id: StudioStep; label: string }[] = [
    { id: 1, label: '设置媒体平台' },
    { id: 2, label: '展示文案' },
    { id: 3, label: '生成推广图片' },
  ]

  // 多选用纯文件名作 key（后端已保证每次生成的文件名唯一）
  const allChecked = s.images.length > 0 && s.images.every(im => s.checked.includes(im.file))
  const toggleAll = () => updateSession({ checked: allChecked ? [] : s.images.map(im => im.file) })
  const toggleOne = (f: string) => updateSession(st => ({
    checked: st.checked.includes(f) ? st.checked.filter(x => x !== f) : [...st.checked, f],
  }))
  const gotoStep = (n: StudioStep) => updateSession({ step: n })

  if (!s.analysis) {
    return (
      <div className="card media-empty">
        <h3>营销推广的媒体平台设置</h3>
        <p className="muted">本模块需要先对落地页做分析，再据此生成推广素材。</p>
        <button className="btn" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>前往「素材创作」分析落地页</button>
      </div>
    )
  }

  return (
    <div className="media-studio">
      <div className="card media-analysis">
        <div className="ma-head">
          <b>落地页分析结论（生成依据）</b>
          <ModelBadge info={s.analysis.model_info} fallbackText="分析未走大模型" />
        </div>
        <div className="ma-url">{s.analysis.url || '（直接输入正文）'}</div>
        <div className="ma-summary">{analysisSummary || '（分析结论为空，请回到「素材创作」重新分析）'}</div>
      </div>

      {/* 步骤条 */}
      <div className="stepper">
        {STEPS.map(st => (
          <button
            key={st.id}
            className={`mstep ${s.step === st.id ? 'active' : ''} ${s.step > st.id ? 'done' : ''}`}
            onClick={() => st.id < s.step && gotoStep(st.id)}
            disabled={st.id > s.step}
          >
            <span className="mstep-no">{st.id}</span>
            <span className="mstep-label">{st.label}</span>
          </button>
        ))}
      </div>

      {s.studioError && <div className="alert err">{s.studioError}</div>}
      {s.stage === 'error' && s.taskDetail && <div className="alert err">任务失败：{s.taskDetail}</div>}

      {/* Step 1：设置媒体平台 */}
      {s.step === 1 && (
        <div className="card">
          <h3>① 选择媒体推广平台（默认单平台）</h3>
          <p className="muted">只能选择一个平台；选中后展示该平台支持的图片素材数量、规格与尺寸，并可按常规方案调整。</p>
          <div className="platform-grid">
            {platforms.map(p => (
              <button
                key={p.platform}
                className={`platform-card ${s.platform === p.platform ? 'active' : ''}`}
                onClick={() => choosePlatform(p.platform)}
                disabled={s.running}
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
                  <label key={pl.id} className={`placement-card ${s.selectedPlacements.includes(pl.id) ? 'on' : ''}`}>
                    <input type="checkbox" checked={s.selectedPlacements.includes(pl.id)}
                           onChange={() => togglePlacement(pl.id)} disabled={s.running} />
                    <span className="pl-name">{pl.name}{pl.default && <em>常规</em>}</span>
                    <span className="pl-desc">{pl.desc}</span>
                    <span className="pl-sizes">{pl.sizes.join(' · ')}</span>
                  </label>
                ))}
              </div>
              <div className="sp-count">
                <label>生成图片数量：</label>
                <input
                  type="number" min={1} max={20} value={s.count}
                  onChange={e => updateSession({ count: Math.max(1, parseInt(e.target.value || '1', 10)) })}
                />
                <span className="muted">（按所选版位顺序取前 {Math.max(1, s.count)} 张）</span>
              </div>
              <div className="sp-lang">
                <label>文案语言：</label>
                <select value={s.lang} onChange={e => updateSession({ lang: e.target.value })}>
                  {['en', 'es', 'pt', 'id', 'zh', 'ja', 'ko', 'ar', 'fr', 'de'].map(l => (
                    <option key={l} value={l}>{l.toUpperCase()}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div className="form-actions">
            <button className="btn primary" disabled={!s.platform || s.running} onClick={genCopy}>
              {s.running ? '任务进行中…' : '生成广告文案 →'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2：展示文案 + V4.38 创意文案选用 + 风格设置 */}
      {s.step === 2 && s.copy && (
        <div className="card">
          <h3>② 广告文案（已结合落地页分析结论生成，可编辑并勾选用于出图）</h3>
          <ModelBadge info={s.copy.model_info} fallbackText="文案未走大模型" />

          {/* V4.39 / F01：残句不再被判合格，压缩失败必须显式阻断 */}
          {(s.copy.needs_revision?.length || 0) > 0 && (
            <div className="alert warn rev-alert">
              <b>{s.copy.needs_revision!.length} 条超长文案未通过语义压缩（needs_revision）</b>
              <div className="muted">
                已保留完整原文，不会输出残句或省略号；这些字段不得作为合格素材导出。
                请手动缩短后重新生成，或改用其它文案。系统优先保留否定、价格条件、订阅 / 退款限制。
              </div>
              <ul className="rev-list">
                {s.copy.needs_revision!.map((x, i) => (
                  <li key={i}>
                    <b>{x.label}{x.index > 1 ? ` #${x.index}` : ''}</b>：
                    {x.original.length} 字 / 预算 {x.limit} 字
                    {x.protected?.length ? ` · 必须保留：${x.protected.slice(0, 4).join('、')}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="cp-toolbar">
            <div className="cp-tb-left">
              <b>创意文案选用</b>
              <span className="muted">已选 {selCount.selected} / {selCount.total} 条 · 只有勾选的文案会作为图片创意素材</span>
            </div>
            <div className="cp-tb-right">
              <button className="btn small ghost" onClick={() => setAllCopy(true)}>全选</button>
              <button className="btn small ghost" onClick={() => setAllCopy(false)}>清空</button>
              <button className="btn small ghost" onClick={onlyFirstCopy}>仅选每组首条</button>
            </div>
          </div>

          <div className="copy-grid">
            {s.copy.schema.map(f => {
              const raw = s.copyEdit[f.key]
              const arr: string[] = Array.isArray(raw) ? raw : [String(raw ?? '')]
              return (
                <div className="copy-field" key={f.key}>
                  <div className="cf-head">
                    <label className="cf-title">{f.label}</label>
                    <span className="cf-limit">≤ {f.max}{f.count > 1 ? ` ×${f.count}` : ''}</span>
                  </div>
                  <div className="cf-multi">
                    {arr.map((v, i) => {
                      const on = isCopySelected(f.key, i)
                      return (
                        <div className={`cf-line ${on ? 'on' : ''}`} key={i}>
                          <label className="cf-check" title="勾选后用作创意素材文案">
                            <input type="checkbox" checked={on} onChange={() => toggleCopyItem(f.key, i)} />
                            <span>{f.count > 1 ? `#${i + 1}` : '选用'}</span>
                          </label>
                          <input
                            value={v || ''}
                            maxLength={f.max + 4}
                            onChange={e => {
                              if (f.count > 1) {
                                const next = [...arr]
                                next[i] = e.target.value
                                setField(f.key, next)
                              } else {
                                setField(f.key, e.target.value)
                              }
                            }}
                            placeholder={`${f.label} ${i + 1}`}
                          />
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
            <div className="copy-field">
              <div className="cf-head"><label className="cf-title">品牌名（显示在图片）</label></div>
              <div className="cf-line plain">
                <input value={s.brandEdit} maxLength={40}
                       onChange={e => updateSession({ brandEdit: e.target.value })}
                       placeholder="留空则自动从域名推断" />
              </div>
            </div>
          </div>

          {/* V4.38：生成图片前预览将实际使用的文案组合 */}
          <div className="cv-panel">
            <div className="cv-head">
              <h4>将用于图片的创意文案组合（{variants.length} 组）</h4>
              <span className="muted">按版位顺序轮换叠加到 {Math.max(1, s.count)} 张图片</span>
            </div>
            {variants.length ? (
              <div className="cv-list">
                {variants.map((v, i) => (
                  <div className="cv-card" key={i}>
                    <span className="pill img">{v.label}</span>
                    <b>{v.headline || '（无标题）'}</b>
                    <span>{v.sub || '（无副标 / 正文）'}</span>
                    <em>{v.cta || '（无 CTA）'}</em>
                  </div>
                ))}
              </div>
            ) : (
              <div className="alert err">尚未勾选任何文案，请至少选择一条标题 / 描述 / 正文 / CTA 后再生成图片。</div>
            )}
            <p className="muted">
              第 n 张图片使用第 (n-1) % {Math.max(1, variants.length)} + 1 组文案；未勾选的文案仍保留在文案库与「素材历史」中，但不会出现在图片上。
            </p>
          </div>

          {/* 图片风格 / 样式 / 颜色 */}
          <div className="style-panel">
            <h4>图片生成风格设置（生成前可选，越丰富越能吸引用户）</h4>
            <div className="style-row">
              <label>创意方向
                <select value={s.direction} onChange={e => updateSession({ direction: e.target.value })}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.directions.map(d => <option key={d.id} value={d.id}>{d.id} · {d.name}</option>)}
                </select>
              </label>
              <label>内容风格
                <select value={s.styleName} onChange={e => updateSession({ styleName: e.target.value })}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.styles.map(x => <option key={x.id} value={x.id}>{x.id} · {x.name}</option>)}
                </select>
              </label>
              <label>配色方案
                <select value={s.colorName} onChange={e => updateSession({ colorName: e.target.value })}>
                  <option value="">（跟随平台默认）</option>
                  {presets?.colors.map(c => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
                </select>
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button className="btn" onClick={() => gotoStep(1)}>← 上一步</button>
            <button className="btn primary" disabled={s.running || !variants.length} onClick={genImages}>
              {s.running ? '任务进行中…' : '生成推广图片 →'}
            </button>
          </div>
        </div>
      )}

      {/* Step 3：生成推广图片（放大查阅 / 单张下载 / 勾选打包 / 一键打包） */}
      {s.step === 3 && (
        <div className="card">
          <h3>③ 推广图片素材</h3>
          {s.imageModel && <ModelBadge info={s.imageModel} fallbackText="使用 Pillow 模板兜底" />}
          {s.imgNote && <p className="muted">{s.imgNote}</p>}
          {(s.imageIssues || []).length > 0 && (
            <div className="alert warn rev-alert">
              <b>{s.imageIssues.length} 个版位未生成（needs_revision）</b>
              <ul className="rev-list">
                {s.imageIssues.map((x, i) => (
                  <li key={i}><b>{x.size}{x.placement ? ` · ${x.placement}` : ''}</b>：{x.message}</li>
                ))}
              </ul>
            </div>
          )}
          {s.savedNote && <div className="alert ok">{s.savedNote}</div>}

          {s.images.length > 0 && (
            <div className="img-toolbar">
              <div className="it-left">
                <label className="it-check">
                  <input type="checkbox" checked={allChecked} onChange={toggleAll} />
                  全选
                </label>
                <span className="muted">共 {s.images.length} 张 · 已勾选 {s.checked.length} 张</span>
              </div>
              <div className="it-right">
                <a className="btn small" href={api.mediaZipUrl(s.images.map(im => im.file), '推广图片_全部')}>
                  ⬇ 一键打包全部
                </a>
                {s.checked.length > 0 ? (
                  <a className="btn small primary" href={api.mediaZipUrl(s.checked, '推广图片_所选')}>
                    ⬇ 打包所选（{s.checked.length}）
                  </a>
                ) : (
                  <button className="btn small primary" disabled>⬇ 打包所选（0）</button>
                )}
              </div>
            </div>
          )}

          <div className="img-grid">
            {s.images.map((img, i) => (
              <div className={`img-card ${s.checked.includes(img.file) ? 'checked' : ''}`} key={img.file || i}>
                <label className="ic-check" title="勾选以打包下载">
                  <input type="checkbox" checked={s.checked.includes(img.file)} onChange={() => toggleOne(img.file)} />
                </label>
                <div className="ic-preview" onClick={() => updateSession({ viewer: i })} title="点击放大查看">
                  <img src={api.fileUrl(img.url)} alt={`${img.placement} ${img.size}`} loading="lazy" />
                  <span className="ic-zoom">放大查看</span>
                </div>
                <div className="ic-meta">
                  <span className="pill img">{img.size}</span>
                  <span className="muted">{img.placement || '—'}</span>
                </div>
                {img.copy && (
                  <div className="ic-copy" title="本张图片选用的创意文案">
                    {img.variant && <span className="pill off">{img.variant}</span>}
                    <b>{img.copy.headline || '（无标题）'}</b>
                    <span>{img.copy.sub || '（无副标）'}</span>
                  </div>
                )}
                <div className="ic-actions">
                  <button className="btn small ghost" onClick={() => updateSession({ viewer: i })}>放大</button>
                  <a className="btn small" href={api.mediaFileDownloadUrl(img.file)}>下载</a>
                </div>
              </div>
            ))}
          </div>
          {!s.images.length && <p className="muted">未生成图片，请返回上一步检查版位与数量设置。</p>}
          <div className="form-actions">
            <button className="btn" onClick={() => gotoStep(2)}>← 上一步</button>
            <button className="btn primary" onClick={genImages} disabled={s.running}>
              {s.running ? '重新生成中…' : '重新生成'}
            </button>
          </div>

          {/* 放大预览：点遮罩 / ESC 关闭，← → 切换，可直接下载当前图 */}
          {s.viewer !== null && s.images[s.viewer] && (
            <div className="lightbox" onClick={() => updateSession({ viewer: null })}>
              <div className="lb-inner" onClick={e => e.stopPropagation()}>
                <button className="lb-close" onClick={() => updateSession({ viewer: null })} title="关闭（ESC）">×</button>
                {s.images.length > 1 && (
                  <>
                    <button className="lb-nav prev" title="上一张"
                      onClick={() => updateSession(st => ({ viewer: ((st.viewer ?? 0) - 1 + st.images.length) % st.images.length }))}>‹</button>
                    <button className="lb-nav next" title="下一张"
                      onClick={() => updateSession(st => ({ viewer: ((st.viewer ?? 0) + 1) % st.images.length }))}>›</button>
                  </>
                )}
                <img className="lb-img" src={api.fileUrl(s.images[s.viewer].url)}
                     alt={`${s.images[s.viewer].placement} ${s.images[s.viewer].size}`} />
                <div className="lb-foot">
                  <span>{s.viewer + 1} / {s.images.length} · {s.images[s.viewer].size} · {s.images[s.viewer].placement || '—'}</span>
                  <div className="lb-btns">
                    <a className="btn small" href={api.mediaFileDownloadUrl(s.images[s.viewer].file)}>下载此图</a>
                    <button className="btn small ghost" onClick={() => updateSession({ viewer: null })}>关闭</button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
