import { useEffect, useMemo, useState } from 'react'
import { api, MediaPlatform, MediaRules, CreativePresets, ModelInfo } from '../api'
import {
  useCreationSession, updateSession, beginTask, endTask, failTask,
  allSelectedCopy, selectedCount,
} from '../creationSession'
import type { StudioStep } from '../creationSession'
import {
  buildConcepts, buildAdaptations, buildTaskMatrix, toCopyVariants, toSlots,
} from '../taskMatrix'

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
  const [rules, setRules] = useState<MediaRules | null>(null)

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
    Promise.all([
      api.mediaPlatforms().catch(() => []),
      api.creativePresets().catch(() => null),
      api.mediaRules().catch(() => null),
    ]).then(([ps, pr, mr]) => {
      setPlatforms(ps as MediaPlatform[])
      setPresets(pr as CreativePresets)
      setRules(mr as MediaRules | null)
    })
  }, [])

  const spec = useMemo(() => platforms.find(p => p.platform === s.platform) || null, [platforms, s.platform])
  const selCount = selectedCount(s)
  const selectedLogo = s.logoMode === 'upload' ? s.uploadedLogo
    : s.logoMode === 'none' ? '' : (s.analysis?.logo || '')

  // V4.40 / F07：概念与任务矩阵都是纯函数派生，预览与实际请求使用同一份数据。
  const concepts = useMemo(() => buildConcepts({
    copy: s.copy, copyEdit: s.copyEdit, selectedCopy: s.selectedCopy,
    brand: (s.brandEdit || s.copy?.brand || '').trim(),
    variantsPerConcept: s.variantsPerConcept,
  }), [s.copy, s.copyEdit, s.selectedCopy, s.brandEdit, s.variantsPerConcept])

  const matrix = useMemo(() => buildTaskMatrix({
    spec, selectedPlacementIds: s.selectedPlacements,
    keepDistinctRoles: s.keepDistinctRoles,
    concepts, conceptCount: s.conceptCount,
    assignment: s.assignment, budget: s.count,
  }), [spec, s.selectedPlacements, s.keepDistinctRoles, concepts,
       s.conceptCount, s.assignment, s.count])

  const effectiveVariants = useMemo(() => toCopyVariants(matrix.concepts), [matrix.concepts])
  const preferredIds: string[] = useMemo(() => {
    const key = s.analysis?.industry_profile || 'general'
    return rules?.industry_placement_preferences?.[key] || []
  }, [rules, s.analysis?.industry_profile])

  function choosePlatform(p: string) {
    if (s.running) return   // 任务进行中不重置工作台，避免结果写回错乱
    const sp = platforms.find(x => x.platform === p) || null
    const defaults = sp ? sp.placements.filter(pl => pl.default).map(pl => pl.id) : []
    // 默认预算 = 选中版位的完整任务数，不再用 recommended_count 静默截断 Stories / UAC
    const { adaptations } = buildAdaptations(sp, defaults, false)
    updateSession({
      platform: p,
      selectedPlacements: defaults,
      count: Math.max(1, adaptations.length),
      conceptCount: 3, variantsPerConcept: 1,
      assignment: 'round_robin', keepDistinctRoles: false,
      copy: null, copyEdit: {}, selectedCopy: {}, images: [], imageModel: null,
      imageIssues: [], viewer: null, checked: [], savedNote: '', studioError: '',
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
    const slots = toSlots(matrix.tasks)
    if (!slots.length) { updateSession({ studioError: '请至少选择一个广告版位' }); return }
    if (!effectiveVariants.length) {
      updateSession({ studioError: '请至少勾选一条创意文案作为图片素材（标题 / 描述 / 正文 / CTA 均可）' })
      return
    }
    if (!matrix.budgetOk) {
      updateSession({ studioError: matrix.warnings.find(w => w.startsWith('预算不足')) || '生成预算不足，请调整后再出图' })
      return
    }
    updateSession({ studioError: '' })
    beginTask('images', '正在生成推广图片',
      `任务矩阵 ${slots.length} 个版位 · ${matrix.concepts.length} 个概念 · 规则 ${matrix.specVersion || '服务端解析中'}…`)
    try {
      const payloadCopy = { ...s.copyEdit, brand: s.brandEdit }
      const res = await api.mediaImages({
        analysis: s.analysis, platform: s.platform, lang: s.lang,
        copy_fields: payloadCopy,
        copy_variants: effectiveVariants,
        style_opts: { creative_direction: s.direction, content_style: s.styleName, color_scheme: s.colorName },
        slots,
        logo: selectedLogo || '',
        spec_version: matrix.specVersion || '',
        total_pixels: matrix.tasks.reduce((n, t) => {
          const [w, h] = t.size.toLowerCase().split('x').map(Number)
          return n + (w || 0) * (h || 0)
        }, 0),
      })
      updateSession({
        images: res.images, imageModel: res.image_model, imgNote: res.note || '',
        imageIssues: res.issues || [],
        step: 3, viewer: null, checked: [], savedNote: '',
      })
      const aiCount = res.images.filter(im => im.ai_background).length
      const fallbackCount = res.images.length - aiCount
      const failed = (res.issues || []).filter(x => x.status === 'failed').length
      endTask(res.status === 'failed' ? 'error' : 'images_ready',
        res.status === 'failed' ? '本批无可用素材' : '本批推广图片已生成',
        `成功 ${res.images.length} 张（AI 底图 ${aiCount} / 模板兜底 ${fallbackCount}）` +
        (res.status === 'partial_success' ? `，批次为部分成功；另有 ${(res.issues || []).length} 项未生成` : '') +
        (failed ? `，其中 ${failed} 项失败（未计入合格素材，可仅重试失败项）` : '') +
        `；规则版本 ${res.spec_version || '-'}，每张图已标注适用广告产品与所用概念。`)
      // V4.36：把「编辑后的最终文案 + 本批图片 + 风格 / 模型」写回历史会话（追加）
      if (s.historyId) {
        const finalCopy = {
          ...s.copy, fields: { ...s.copyEdit }, brand: s.brandEdit,
          selected_copy: s.selectedCopy, copy_variants: effectiveVariants,
          task_matrix: { tasks: matrix.tasks, concepts: matrix.concepts.map(c => ({
            key: c.key, label: c.label, headline: c.headline, sub: c.sub, cta: c.cta,
            sourceIndices: c.sourceIndices, subKey: c.subKey,
          })), spec_version: matrix.specVersion },
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
                    <span className="pl-name">
                      {pl.name}{pl.default && <em>常规</em>}
                      {preferredIds.includes(pl.id) && <em className="pl-pref">行业建议</em>}
                    </span>
                    <span className="pl-desc">{pl.desc}</span>
                    <span className="pl-sizes">{pl.sizes.join(' · ')}</span>
                    {(pl.ad_product || pl.asset_role) && (
                      <span className="pl-role">{pl.ad_product || '未标注广告产品'} · {pl.asset_role}</span>
                    )}
                  </label>
                ))}
              </div>
              <div className="sp-count">
                <label>生成预算（任务数上限）：</label>
                <input
                  type="number" min={1} max={24} value={s.count}
                  onChange={e => updateSession({ count: Math.max(1, Math.min(24, parseInt(e.target.value || '1', 10))) })}
                  disabled={s.running}
                />
                <span className="muted">
                  当前版位清单共需 <b>{matrix.required}</b> 个任务（{matrix.adaptationCount} 个适配
                  {matrix.droppedDuplicates.length ? ` · 已合并 ${matrix.droppedDuplicates.length} 个重复` : ''}）；
                  预算不足时不会静默截断，会明确提示并禁止出图。
                </span>
              </div>
              <div className="sp-count">
                <label className="tm-check">
                  <input type="checkbox" checked={s.keepDistinctRoles}
                         onChange={e => updateSession({ keepDistinctRoles: e.target.checked })}
                         disabled={s.running} />
                  保留同尺寸但不同广告产品的任务
                </label>
                {matrix.budgetOk ? (
                  <span className="pill ok">预算充足</span>
                ) : (
                  <button className="btn small" disabled={s.running}
                          onClick={() => updateSession({ count: matrix.required })}>
                    按清单补足预算（{matrix.required}）
                  </button>
                )}
              </div>
              {spec.spec_version && (
                <div className="sp-rules">
                  <b>媒体规则 {spec.spec_version}</b>
                  <span className="muted">
                    来源：{spec.spec_source}；
                    官方核验日期：{spec.spec_verified_on || '未核验'}。
                    {spec.spec_disclaimer}
                  </span>
                  <span className="muted">单批最多 {spec.rules?.limits.max_slots ?? 24} 个任务、
                    累计像素 {((spec.rules?.limits.max_total_pixels ?? 40000000) / 1e6).toFixed(0)} MP；
                    未知平台、异常尺寸与超量请求会在调用模型前被拒绝。</span>
                </div>
              )}
              {matrix.warnings.filter(w => w.startsWith('预算不足')).map((w, i) => (
                <div className="alert warn" key={`bw-${i}`}>{w}</div>
              ))}
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

          {/* V4.40 / F07：概念 → 任务矩阵，预览数量与实际请求完全一致 */}
          <div className="cv-panel">
            <div className="cv-head">
              <h4>创意概念（{concepts.length} 个 · 本批使用 {matrix.concepts.length} 个）</h4>
              <span className="muted">同一概念的主标题、证据与 CTA 来自同一来源位置，不做取模错配</span>
            </div>
            {concepts.length ? (
              <div className="cv-list">
                {concepts.map((c, i) => (
                  <div className={`cv-card ${i < matrix.concepts.length ? '' : 'off'}`} key={c.key}>
                    <span className="pill img">{c.label}</span>
                    <b>{c.headline || '（无标题）'}</b>
                    <span>{c.sub || '（无副标 / 证据）'}</span>
                    <em>{c.cta || '（无 CTA）'}</em>
                    <small>来源：标题 #{c.sourceIndices.headline + 1} ·
                      {c.subKey || '证据'} #{c.sourceIndices.sub + 1} · CTA #{c.sourceIndices.cta + 1}
                      {c.headlineVariants.length > 1 ? ` · ${c.headlineVariants.length} 个标题变体` : ''}</small>
                  </div>
                ))}
              </div>
            ) : (
              <div className="alert err">尚未勾选任何文案，请至少选择一条标题 / 描述 / 正文 / CTA 后再生成图片。</div>
            )}
            <div className="tm-controls">
              <label>使用概念数
                <input type="number" min={1} max={Math.max(1, concepts.length)}
                       value={Math.min(s.conceptCount, Math.max(1, concepts.length))}
                       onChange={e => updateSession({ conceptCount: Math.max(1, parseInt(e.target.value || '1', 10)) })}
                       disabled={s.running} />
              </label>
              <label>每概念标题变体数
                <input type="number" min={1} max={4} value={s.variantsPerConcept}
                       onChange={e => updateSession({ variantsPerConcept: Math.max(1, Math.min(4, parseInt(e.target.value || '1', 10))) })}
                       disabled={s.running} />
              </label>
              <label>概念分配方式
                <select value={s.assignment} disabled={s.running}
                        onChange={e => updateSession({ assignment: e.target.value as 'round_robin' | 'full_cover' })}>
                  <option value="round_robin">先覆盖版位（顺序分配）</option>
                  <option value="full_cover">每个概念覆盖全部版位</option>
                </select>
              </label>
              <span className="tm-count">
                适配数 <b>{matrix.adaptationCount}</b> × 概念数 <b>{matrix.conceptCount}</b>
                → 任务 <b>{matrix.required}</b> / 预算 {matrix.budget}
              </span>
            </div>
            {matrix.warnings.map((w, i) => (
              <div className="alert warn" key={`mw-${i}`}>{w}</div>
            ))}
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr><th>#</th><th>版位</th><th>尺寸</th><th>广告产品</th><th>资产角色</th><th>概念</th></tr>
                </thead>
                <tbody>
                  {matrix.tasks.map((t, i) => (
                    <tr key={`${t.placement_id}-${t.size}-${t.concept_index}-${i}`}>
                      <td>{i + 1}</td>
                      <td>{t.placement || '—'}</td>
                      <td><span className="pill img">{t.size}</span></td>
                      <td>{t.ad_product || '—'}</td>
                      <td>{t.asset_role || '—'}</td>
                      <td><b>{t.concept_id || '—'}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!matrix.tasks.length && <p className="muted">任务清单为空，请回到第 ① 步选择广告版位。</p>}
            </div>
            <p className="muted">
              平台正文（primary_text）不进入图内文字；未勾选的文案仍保留在文案库与「素材历史」中，但不会出现在图片上。
              规则版本 {matrix.specVersion || '由服务端解析'}；每张导出的图片都会标注适用广告产品。
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
            <button className="btn primary"
                    disabled={s.running || !effectiveVariants.length || !matrix.budgetOk || !matrix.tasks.length}
                    onClick={genImages}>
              {s.running ? '任务进行中…' : `生成推广图片（${matrix.required} 个任务）→`}
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
            <div className={`alert ${s.imageIssues.some(x => x.status === 'failed') ? 'err' : 'warn'} rev-alert`}>
              <b>{s.imageIssues.length} 个任务未生成（逐项状态见下）</b>
              <ul className="rev-list">
                {s.imageIssues.map((x, i) => (
                  <li key={i}>
                    <span className={`pill ${x.status === 'failed' ? 'err' : 'off'}`}>
                      {x.status === 'failed' ? '失败' : 'needs_revision'}
                    </span>
                    <b>{x.size}{x.placement ? ` · ${x.placement}` : ''}</b>
                    {x.concept_id ? ` · ${x.concept_id}` : ''}
                    {x.ad_product ? ` · ${x.ad_product}` : ''}：{x.message}
                  </li>
                ))}
              </ul>
              <div className="muted">失败任务未计入合格素材；可返回上一步仅重试失败项，不会对已成功图片重复计费或重复归档。</div>
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
                  <span className={`pill ${img.ai_background ? 'ok' : 'off'}`}
                        title={img.fallback_reason || (img.ai_background ? '文生图模型生成背景' : 'Pillow 模板兜底')}>
                    {img.ai_background ? 'AI 底图' : '模板兜底'}
                  </span>
                </div>
                {img.copy && (
                  <div className="ic-copy" title="本张图片选用的创意文案">
                    {img.variant && <span className="pill off">{img.variant}</span>}
                    {img.concept_id && <span className="pill off">{img.concept_id}</span>}
                    <b>{img.copy.headline || '（无标题）'}</b>
                    <span>{img.copy.sub || '（无副标）'}</span>
                  </div>
                )}
                {(img.ad_product || img.spec_version) && (
                  <div className="ic-spec">
                    {img.ad_product || '未标注广告产品'} · 规则 {img.spec_version || '—'}
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
