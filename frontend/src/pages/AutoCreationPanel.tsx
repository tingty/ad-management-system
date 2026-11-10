/**
 * V4.45 / D1–D3 · 默认自动创作面板
 *
 * 设计原则（依据《素材创作平台新版验收与自动化创作改造实施方案》）：
 * - 不另造生成系统：本面板只做「策划 + 确认」，执行仍走 MediaAdStudio 既有
 *   mediaCopy → generation-jobs → 素材历史 链路。
 * - 产品界面展示结果而不是实现细节：推荐画面描述、推荐理由、覆盖摘要在前，
 *   原始 JSON 折叠在「完整策划数据」里。
 * - 不夸大能力：规则目录未官方核验、多平台全覆盖（D4）与 PromptBundle 明确标注未完成。
 * - 关键资料缺失时按需提示，不要求用户填写整份问卷；不隐式发起收费任务。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { MediaPlatform, WorkspaceDefaults } from '../api'
import {
  useCreationSession, updateSession, setCreationMode, updateWorkspaceDefaults,
} from '../creationSession'
import { buildAdaptations } from '../taskMatrix'

const STATUS_META: Record<string, { label: string; cls: string; hint: string }> = {
  ready: { label: '可生成', cls: 'ok', hint: '产品事实与证据已齐备，可确认媒体并生成。' },
  draft_only: {
    label: '仅草案', cls: 'warn',
    hint: '缺少官方商品图 / 真实 UI 等资产，只能产出草案，不能计作可投放商品广告（A08）。',
  },
  needs_input: {
    label: '需补充资料', cls: 'err',
    hint: '存在会改变产品身份或事实承诺的阻断项，请先明确推广对象或重新分析落地页。',
  },
}

const COUNTRIES = [
  ['US', '美国'], ['GB', '英国'], ['DE', '德国'], ['FR', '法国'],
  ['BR', '巴西'], ['MX', '墨西哥'], ['JP', '日本'], ['ID', '印尼'],
]
const LANGS = [['en', '英语'], ['es', '西语'], ['pt', '葡语'], ['de', '德语'],
               ['fr', '法语'], ['ja', '日语'], ['id', '印尼语'], ['zh', '中文']]

export default function AutoCreationPanel() {
  const s = useCreationSession()
  const [platforms, setPlatforms] = useState<MediaPlatform[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [showDefaults, setShowDefaults] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [picked, setPicked] = useState<string>(s.platform || '')
  const lastKey = useRef('')

  useEffect(() => {
    let alive = true
    api.mediaPlatforms().then(d => {
      if (!alive) return
      setPlatforms(d || [])
      setPicked(prev => prev || (d?.[0]?.platform || ''))
    }).catch(() => {})
    return () => { alive = false }
  }, [])

  // 只包含会影响策划的输入；刻意不含 recommendation 本身，避免写入结果后再次触发请求。
  const planKey = useMemo(() => [
    s.analysis?.url || '', s.analysis?.final_url || '',
    s.analysis?.evidence_snapshot_id || '',
    s.platform || '', picked,
    s.workspaceDefaults.country, s.workspaceDefaults.language,
    s.workspaceDefaults.os, s.workspaceDefaults.goal,
    s.workspaceDefaults.budget_cap, s.workspaceDefaults.concept_count,
  ].join('~'), [s.analysis?.url, s.analysis?.final_url, s.analysis?.evidence_snapshot_id,
                s.platform, picked, s.workspaceDefaults])

  /** 分析完成后自动给出推荐；确定性规则接口，不触发新的大模型推理与收费。 */
  useEffect(() => {
    if (s.mode !== 'auto' || !s.analysis) return
    if (lastKey.current === planKey && s.recommendation) return
    lastKey.current = planKey
    let alive = true
    setLoading(true)
    setErr('')
    api.creationRecommendation({
      analysis: s.analysis,
      platforms: picked ? [picked] : [],
      workspace_defaults: s.workspaceDefaults,
      mode: 'auto',
    }).then(r => {
      if (!alive) return
      updateSession({ recommendation: r })
    }).catch((e: any) => {
      if (alive) setErr(e?.message || '推荐生成失败，可切换到定制创作继续')
    }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey, s.mode, !!s.analysis])

  const rec = s.recommendation
  const meta = STATUS_META[rec?.status || 'draft_only'] || STATUS_META.draft_only
  const wd = s.workspaceDefaults

  function patch(patchValue: Partial<WorkspaceDefaults>) {
    lastKey.current = ''       // 允许按新默认值重算推荐
    updateWorkspaceDefaults(patchValue)
  }

  /** 用户显式点击后，才把自动链路交给工作台执行（不隐式收费）。 */
  function confirmAndGenerate() {
    const p = picked || platforms[0]?.platform || ''
    if (!p) { setErr('请选择一个媒体平台'); return }
    if (!s.analysis) { setErr('请先完成落地页分析'); return }
    if (rec?.status === 'needs_input') {
      setErr('存在阻断项，请先明确推广对象或重新分析落地页')
      return
    }
    const sp = platforms.find(x => x.platform === p) || null
    const defaultIds = sp ? sp.placements.filter(pl => pl.default).map(pl => pl.id) : []
    const { adaptations } = buildAdaptations(sp, defaultIds, false)
    updateSession({
      platform: p,
      selectedPlacements: defaultIds,
      count: Math.max(1, adaptations.length),
      conceptCount: Math.max(1, Math.min(3, wd.concept_count || 1)),
      lang: wd.language || 'en',
      step: 1,
      studioError: '',
      autoContinue: true,
      autoStage: 'idle',
      taskLogs: [...s.taskLogs, {
        at: Date.now(), kind: 'info' as const,
        text: `自动创作已确认：平台 ${p}，主要图片任务约 ${Math.max(1, adaptations.length)} 项，计划版本 ${rec?.plan_hash || '-'}`,
      }].slice(-40),
    })
    setTimeout(() => document.getElementById('media-studio')?.scrollIntoView({ behavior: 'smooth' }), 80)
  }

  return (
    <div className="card ac-panel">
      <div className="ac-head">
        <div>
          <div className="ac-kicker">自动创作 · 推荐方案</div>
          <h3 className="ac-title">推荐怎么拍 / 怎么画</h3>
        </div>
        <div className="ac-head-actions">
          {rec && <span className={`ac-status ${meta.cls}`}>{meta.label}</span>}
          <button className="linkbtn" onClick={() => setCreationMode('custom')}>
            调整创作方案 →
          </button>
        </div>
      </div>

      <p className="muted ac-hint">
        系统已自动识别产品、组织证据并给出推荐画面；确认媒体后一次点击即可生成。
        定制创作保留在上方模式切换中，不会清空已输入内容或既有素材。
      </p>

      {loading && <div className="alert ok">正在整理产品证据与推荐画面…</div>}
      {err && <div className="alert err">{err}</div>}

      {rec && (
        <>
          <div className="ac-summary">{rec.recommended_visual_summary}</div>
          <div className={`alert ${meta.cls} ac-status-hint`}>{meta.hint}</div>

          <div className="ac-grid">
            <div className="ac-block">
              <div className="ac-label">为什么适合该产品</div>
              <ul className="ac-list">
                {rec.rationale.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
              <div className="ac-label">产品概要</div>
              <div className="ac-kv">
                <span>品牌</span><b>{rec.product_profile.brand || '未在页面确认'}</b>
                <span>类型</span><b>{rec.industry_profile_label} / {rec.product_profile.entity_type}</b>
                <span>来源</span><b className="ac-ellipsis">{rec.product_profile.source || '—'}</b>
                <span>证据状态</span><b>{rec.evidence.review_status === 'locatable_not_reviewed'
                  ? `可定位原文 ${rec.evidence.count} 段（商业真实性未审核）`
                  : '旧资料，未自动升级为已审核'}</b>
              </div>
              {rec.product_profile.uncertainty && (
                <div className="ac-note">不确定原因：{rec.product_profile.uncertainty}</div>
              )}
            </div>

            <div className="ac-block">
              <div className="ac-label">将覆盖哪些版位</div>
              <div className="ac-kv">
                <span>平台</span><b>{rec.coverage_summary.platforms.join('、') || '未选择'}</b>
                <span>主要图片角色</span><b>{rec.coverage_summary.asset_roles.length} 类</b>
                <span>预计任务</span><b>{rec.coverage_summary.required_tasks} 项</b>
                <span>规则核验</span><b>{rec.coverage_summary.spec_verified ? '已核验' : '内部目录，投放前须官方核验'}</b>
              </div>
              <div className="ac-roles">
                {(rec.coverage_summary.asset_roles.length
                  ? rec.coverage_summary.asset_roles
                  : ['（尚未选择平台，确认媒体后计算）']).slice(0, 6).map((r, i) => (
                  <span className="ac-role" key={i}>{r}</span>
                ))}
              </div>
              <div className="ac-note">{rec.coverage_summary.estimate_note}</div>
            </div>
          </div>

          {/* V4.45 / D2：结构化概念 —— 展示购买理由，不暴露提示词与内部动作池 */}
          {rec.structured_concepts.length > 0 && (
            <div className="ac-concepts">
              <div className="ac-label">推荐概念（购买理由各不相同）</div>
              {rec.structured_concepts.map(c => (
                <div className="ac-concept" key={c.concept_id}>
                  <div className="ac-concept-head">
                    <b>{c.concept_id} · {c.distinct_reason}</b>
                    <span className={c.claim_status === 'unsupported' ? 'ac-chip err' : 'ac-chip'}>
                      {c.claim_status === 'unsupported' ? '事实未定位原文，已移除量化承诺'
                        : c.claim_ids.length ? `证据 ${c.claim_ids.join(' / ')}（可定位，未审核真实性）`
                          : '不含量化承诺'}
                    </span>
                  </div>
                  <div className="ac-concept-body">{c.promise}</div>
                  {c.must_preserve_qualifiers.length > 0 && (
                    <div className="ac-note">源文限定必须保留：{c.must_preserve_qualifiers.join('、')}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* V4.45 / N03：交付门 —— 草案与可投放严格分开，不按 PNG 保存成功转正 */}
          <div className={`ac-grade ${rec.delivery_grade === 'draft' ? 'draft' : 'standard'}`}>
            <div className="ac-label">
              交付等级：{rec.delivery_grade === 'draft' ? '草案（不可用于投放）' : '可交付'}
            </div>
            <div className="muted">{rec.quality_gate.note}</div>
            <ul className="ac-list">
              {rec.quality_gate.checks.map(ch => (
                <li key={ch.key} className={ch.passed ? 'ok' : 'warn'}>
                  {ch.passed ? '✓' : '○'} {ch.note}
                </li>
              ))}
            </ul>
            <div className="ac-note">
              计划 {rec.plan_id} · 版本 {rec.plan_version} · 行业策略 v{rec.industry_profile_version}
              · 媒体规则 {rec.coverage_summary.spec_version}
            </div>
            {rec.pricing_gate.has_price_terms && (
              <div className="ac-note">{rec.pricing_gate.note}</div>
            )}
          </div>

          {(rec.missing_inputs.length > 0 || rec.blocking_reasons.length > 0) && (
            <div className="ac-missing">
              <div className="ac-label">需要补充 / 已阻断</div>
              <ul className="ac-list">
                {rec.missing_inputs.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            </div>
          )}

          <div className="ac-confirm">
            <div className="ac-label">确认媒体</div>
            <div className="ac-platforms">
              {platforms.map(p => (
                <button
                  key={p.platform}
                  className={`ac-platform ${picked === p.platform ? 'on' : ''}`}
                  onClick={() => { setPicked(p.platform); lastKey.current = '' }}
                >{p.platform}</button>
              ))}
            </div>
            <div className="ac-note">
              本期按单个平台执行主要图片角色；多平台全覆盖计划、版本化官方规则与 PromptBundle 属于后续 D4–D5，尚未上线。
            </div>

            <button className="linkbtn ac-defaults-toggle" onClick={() => setShowDefaults(v => !v)}>
              {showDefaults ? '收起工作区默认值' : '展开查看 / 修改工作区默认值'}
            </button>
            {showDefaults && (
              <div className="ac-defaults">
                <label>投放国家
                  <select value={wd.country} onChange={e => patch({ country: e.target.value })}>
                    {COUNTRIES.map(([v, n]) => <option key={v} value={v}>{n} · {v}</option>)}
                  </select>
                </label>
                <label>语言
                  <select value={wd.language} onChange={e => patch({ language: e.target.value })}>
                    {LANGS.map(([v, n]) => <option key={v} value={v}>{n} · {v}</option>)}
                  </select>
                </label>
                <label>目标
                  <select value={wd.goal} onChange={e => patch({ goal: e.target.value })}>
                    <option value="conversion">转化</option>
                    <option value="traffic">流量</option>
                    <option value="awareness">认知</option>
                    <option value="install">安装</option>
                  </select>
                </label>
                <label>概念数
                  <input type="number" min={1} max={3} value={wd.concept_count}
                    onChange={e => patch({ concept_count: Math.max(1, Math.min(3, Number(e.target.value) || 1)) })} />
                </label>
                <label>费用上限（0 = 未设置）
                  <input type="number" min={0} value={wd.budget_cap}
                    onChange={e => patch({ budget_cap: Math.max(0, Number(e.target.value) || 0) })} />
                </label>
                <div className="ac-note">国家 / 语言来自工作区默认值，不从页面语言或域名推断；修改后原推荐与覆盖摘要会失效并重新计算。</div>
              </div>
            )}

            <div className="ac-actions">
              <button className="btn primary" onClick={confirmAndGenerate}
                disabled={loading || rec.status === 'needs_input' || s.running || !picked}>
                {s.running ? '任务进行中…'
                  : rec.delivery_grade === 'draft' ? '生成草案（不计可投放）' : '确认媒体并生成'}
              </button>
              <button className="btn" onClick={() => setCreationMode('custom')}>改用定制创作</button>
            </div>
          </div>

          <details className="ac-raw" open={showRaw} onToggle={e => setShowRaw((e.currentTarget as HTMLDetailsElement).open)}>
            <summary>完整策划数据（产品对象 / VisualBrief / 证据快照 / 规则版本）</summary>
            <pre>{JSON.stringify(rec, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  )
}
