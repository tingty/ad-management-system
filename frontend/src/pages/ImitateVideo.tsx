/**
 * V4.145–V4.149 · 模仿创作视频 —— 独立一级功能模块。
 *
 * V4.145：页面壳 + 后端任务列表只读展示。
 * V4.146：新建任务双入口（直链代下载 / 本地上传复用）+ 原片 <video> 预览 +
 *         元数据展示 + 权利声明确认 + 建任务。
 * V4.147：分析脚本 A1–A10 查看 / 编辑 / 导出（真实视觉模型，后台任务）。
 * V4.148：创作脚本 C1–C8（统一文本模型）+ 确认闸门 + 成本预估 + 幂等键；
 *         逐镜快捷编辑与全量 JSON 编辑；本版确认后只停在 creation_confirmed。
 * V4.149：按系统级 UI 规范重构——输入 / 下拉 / 文本域 / 按钮统一复用创意工作台样式；
 *         页面全部改为自上而下布局，任务列表由宽表改为纵向卡片，统一高度与间距。
 *
 * 业务逻辑保持不变；本版只改 UI 结构与样式。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  api, imitateVideoApi, ImitateTask, ImitateSource,
  ImitateAnalysisScript, ImitateCreationScript, ImitateVideoSpec,
} from '../api'
import {
  UiActionRow, UiButton, UiCard, UiCheckRow, UiFormRow, UiInput,
  UiLinkButton, UiPanel, UiSelect, UiStack, UiTextarea,
} from '../ui'

type Msg = { kind: 'ok' | 'err'; text: string }
type Tab = 'url' | 'upload'

const A_LABELS: Record<string, string> = {
  A1: '全局规格', A2: '叙事骨架', A3: '内容布局', A4: '逐镜镜头表', A5: '运动轨迹',
  A6: '色彩光影', A7: '商业信息', A8: '音频', A9: '合规标记', A10: '可模仿结论',
}

const C_LABELS: Record<string, string> = {
  C1: '目标规格', C2: '结构方案', C3: '逐镜生成指令', C4: '风格方案',
  C5: '商业信息方案', C6: '字幕/话术方案', C7: '合规标注', C8: '生成参数',
}

const STAGE_LABEL: Record<string, string> = {
  source_acquiring: '获取源视频', analysis_pending: '分析脚本生成中',
  analysis_ready: '分析脚本就绪', analysis_unavailable: '分析不可用',
  creation_pending: '创作脚本生成中', creation_unavailable: '创作脚本不可用',
  awaiting_confirm: '待确认', creation_confirmed: '已确认待生成',
  planning: '创作策划', submitting: '提交中', provider_pending: '模型生成中',
  downloading: '下载校验中', validating: '复核中', completed: '已完成',
}

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '进行中', succeeded: '已完成',
  needs_attention: '需关注', failed: '失败', cancelled: '已取消',
}

const COMMERCIAL_LABELS: Record<string, string> = {
  brand: '品牌', copy: '文案', sales: '销售信息', promotion: '促销信息',
}

function sourceLabel(s?: string): string {
  if (!s) return '—'
  if (s === 'url') return '链接'
  if (s === 'upload') return '上传'
  return s
}

function specLabel(spec?: ImitateVideoSpec): string {
  if (!spec) return '未选择'
  const ratio = (spec.aspect_ratios || [])[0] || '比例未登记'
  return `${spec.platform} · ${spec.ad_product || '默认版位'} · ${ratio}`
}

function MetaRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="ui-kv-row">
      <span>{label}</span>
      <b>{value || '未知'}</b>
    </div>
  )
}

function ScriptDetails({ code, label, value }: { code: string; label: string; value: any }) {
  return (
    <details className="ui-script-details">
      <summary>{code} · {label}</summary>
      <pre>{JSON.stringify(value ?? {}, null, 2)}</pre>
    </details>
  )
}

export default function ImitateVideo() {
  const [items, setItems] = useState<ImitateTask[]>([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<Msg | null>(null)

  // 新建区状态
  const [tab, setTab] = useState<Tab>('url')
  const [url, setUrl] = useState('')
  const [taskName, setTaskName] = useState('')
  const [source, setSource] = useState<ImitateSource | null>(null)
  const [acquiring, setAcquiring] = useState(false)
  const [rightsAck, setRightsAck] = useState(false)
  const [specs, setSpecs] = useState<ImitateVideoSpec[]>([])
  const [targetSpecId, setTargetSpecId] = useState('')
  const [structureFidelity, setStructureFidelity] = useState('medium')
  const [language, setLanguage] = useState('')
  const [creating, setCreating] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // 分析脚本区状态（V4.147）
  const [scriptTask, setScriptTask] = useState<ImitateTask | null>(null)
  const [script, setScript] = useState<ImitateAnalysisScript | null>(null)
  const [scriptDraft, setScriptDraft] = useState('')
  const [scriptLoading, setScriptLoading] = useState(false)
  const [scriptEditing, setScriptEditing] = useState(false)
  const [analyzingId, setAnalyzingId] = useState('')

  // 创作脚本区状态（V4.148）
  const [creationTask, setCreationTask] = useState<ImitateTask | null>(null)
  const [creation, setCreation] = useState<ImitateCreationScript | null>(null)
  const [creationDraft, setCreationDraft] = useState('')
  const [creationLoading, setCreationLoading] = useState(false)
  const [creationEditing, setCreationEditing] = useState(false)
  const [creatingScriptId, setCreatingScriptId] = useState('')
  const [confirmingId, setConfirmingId] = useState('')
  const [feeAck, setFeeAck] = useState(false)
  const [commercialOptions, setCommercialOptions] = useState<Record<string, boolean>>({
    brand: false, copy: false, sales: false, promotion: false,
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await imitateVideoApi.tasks())
      setMsg(null)
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '任务列表加载失败' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    void imitateVideoApi.videoSpecs()
      .then(r => setSpecs(r?.items || []))
      .catch(() => setSpecs([]))
  }, [])

  // 自动轮询：分析/创作生成中的任务每 4 秒刷新，切页不中断、回到页面即可续看
  useEffect(() => {
    if (!items.some(t => t.stage === 'analysis_pending' || t.stage === 'creation_pending')) return
    const id = window.setInterval(() => { void load() }, 4000)
    return () => window.clearInterval(id)
  }, [items, load])

  // ---------------- 分析脚本 ----------------
  const triggerAnalyze = async (t: ImitateTask) => {
    setAnalyzingId(t.job_id)
    setMsg(null)
    try {
      const r: any = await imitateVideoApi.analyze(t.job_id)
      setMsg({ kind: 'ok', text: r.cached ? '命中缓存，分析脚本已就绪' : '分析任务已提交，正在用真实视觉模型生成 A1–A10 脚本' })
      await load()
      if (r.cached || r.script_id) await openScript(t)
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '触发分析失败' })
    } finally {
      setAnalyzingId('')
    }
  }

  const openScript = async (t: ImitateTask) => {
    setScriptTask(t)
    setScript(null)
    setScriptEditing(false)
    setScriptLoading(true)
    try {
      const s = await imitateVideoApi.analysisScript(t.job_id)
      setScript(s)
      setScriptDraft(JSON.stringify(s.script_json || {}, null, 2))
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '分析脚本尚未生成' })
    } finally {
      setScriptLoading(false)
    }
  }

  const saveScriptLocal = () => {
    try {
      const parsed = JSON.parse(scriptDraft)
      setScript(s => s ? { ...s, script_json: parsed } : s)
      setScriptEditing(false)
      setMsg({ kind: 'ok', text: '脚本草稿已在本页更新；创作脚本使用服务端持久化编辑。' })
    } catch {
      setMsg({ kind: 'err', text: 'JSON 格式不正确，请检查后重试' })
    }
  }

  const downloadScript = () => {
    if (!script) return
    const blob = new Blob([JSON.stringify(script.script_json || {}, null, 2)],
      { type: 'application/json;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `imitate-analysis-${script.script_id}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  // ---------------- 创作脚本 ----------------
  const openCreation = async (t: ImitateTask) => {
    setCreationTask(t)
    setCreation(null)
    setCreationEditing(false)
    setFeeAck(false)
    setCreationLoading(true)
    try {
      const s = await imitateVideoApi.creationScript(t.job_id)
      setCreation(s)
      setCreationDraft(JSON.stringify(s.script_json || {}, null, 2))
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '创作脚本尚未生成' })
    } finally {
      setCreationLoading(false)
    }
  }

  const triggerCreation = async (t: ImitateTask) => {
    setCreatingScriptId(t.job_id)
    setMsg(null)
    try {
      const specId = t.target_spec_id || targetSpecId || ''
      if (!specId) {
        setMsg({ kind: 'err', text: '请先为该任务选择目标投放规格' })
        setCreationTask(t)
        return
      }
      const r: any = await imitateVideoApi.createCreationScript(t.job_id, {
        target_spec_id: specId,
        creation_options: commercialOptions,
      })
      setMsg({ kind: 'ok', text: r.cached ? '命中创作脚本缓存' : '创作脚本任务已提交，后台用统一文本模型生成 C1–C8' })
      await load()
      setCreationTask(t)
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '触发创作脚本失败' })
    } finally {
      setCreatingScriptId('')
    }
  }

  const patchCreation = async (nextScript: Record<string, any>, note: string, okText: string) => {
    if (!creationTask) return
    try {
      const out = await imitateVideoApi.updateCreationScript(creationTask.job_id, nextScript, note)
      setCreation(out)
      setCreationDraft(JSON.stringify(out.script_json || {}, null, 2))
      setCreationEditing(false)
      setFeeAck(false)
      setMsg({ kind: 'ok', text: okText })
      await load()
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '创作脚本编辑失败' })
    }
  }

  const saveCreation = () => {
    if (!creation) return
    try {
      void patchCreation(JSON.parse(creationDraft), '全量 JSON 编辑', '创作脚本已保存并重新计价，请重新确认')
    } catch {
      setMsg({ kind: 'err', text: 'JSON 格式不正确，请检查后重试' })
    }
  }

  const updateSection = (key: string, value: any, note: string) => {
    if (!creation) return
    void patchCreation({ ...(creation.script_json || {}), [key]: value }, note, '已保存并重新计价，请重新确认')
  }

  const updateFidelity = (fidelity: string) => {
    if (!creation) return
    const c2 = { ...(creation.script_json?.C2 || {}), fidelity }
    updateSection('C2', c2, `结构保持度调整为 ${fidelity}`)
  }

  const updateCommercialToggle = (key: string, retain: boolean) => {
    if (!creation) return
    const c5 = creation.script_json?.C5 || {}
    const toggles = { ...(c5.toggles || {}), [key]: retain }
    const items = (c5.items || []).map((it: any) => it?.type === key
      ? { ...it, retain, burn_in: retain, rewritten: retain ? it.rewritten : '' }
      : it)
    updateSection('C5', { ...c5, toggles, items }, `商业信息 ${COMMERCIAL_LABELS[key] || key} 保留项调整`)
  }

  const updateVoiceover = (text: string) => {
    if (!creation) return
    const c6 = { ...(creation.script_json?.C6 || {}), voiceover_text: text }
    updateSection('C6', c6, '口播改写稿更新')
  }

  const shots: any[] = (creation?.script_json?.C3?.shots || []) as any[]
  const moveShot = (index: number, delta: number) => {
    if (!creation) return
    const next = [...shots]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    const tmp = next[index]
    next[index] = next[target]
    next[target] = tmp
    next.forEach((s, i) => { s.index = i + 1 })
    updateSection('C3', { ...(creation.script_json?.C3 || {}), shots: next }, '逐镜顺序调整')
  }
  const deleteShot = (index: number) => {
    if (!creation) return
    const next = shots.filter((_, i) => i !== index)
    next.forEach((s, i) => { s.index = i + 1 })
    updateSection('C3', { ...(creation.script_json?.C3 || {}), shots: next }, '删除镜头')
  }

  const confirmCreation = async (t: ImitateTask) => {
    setConfirmingId(t.job_id)
    setMsg(null)
    try {
      const r: any = await imitateVideoApi.confirmCreation(t.job_id, feeAck)
      setMsg({ kind: 'ok', text: `创作脚本已确认；幂等键 ${r.idempotency_key || '—'}（本版不提交付费生成）` })
      await load()
      if (!creationTask || creationTask.job_id !== t.job_id) await openCreation(t)
      else setCreation(c => c ? { ...c, status: 'confirmed', meta_json: { ...(c.meta_json || {}), idempotency_key: r.idempotency_key } } : c)
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '确认失败' })
    } finally {
      setConfirmingId('')
    }
  }

  const downloadCreation = () => {
    if (!creation) return
    const blob = new Blob([JSON.stringify(creation.script_json || {}, null, 2)],
      { type: 'application/json;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `imitate-creation-${creation.script_id}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  // ---------------- 源视频 / 建任务 ----------------
  const acquireUrl = async () => {
    if (!url.trim()) { setMsg({ kind: 'err', text: '请填写视频直链' }); return }
    setAcquiring(true)
    setMsg(null)
    try {
      const s = await imitateVideoApi.fetchSource(url.trim(), taskName.trim())
      setSource(s)
      setMsg({ kind: 'ok', text: `源视频获取成功：${s.width || '?'}×${s.height || '?'} · ${s.duration_sec?.toFixed(1) || '?'}s · ${s.aspect_ratio || '画幅未知'} · ${s.has_audio ? '有音轨' : '无音轨'}` })
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '源视频获取失败' })
    } finally {
      setAcquiring(false)
    }
  }

  const uploadFile = async (file: File) => {
    setAcquiring(true)
    setMsg(null)
    try {
      const r = await api.uploadVideoAsset(file)
      const s: ImitateSource = {
        status: r.status, name: r.name, source: 'upload',
        file: r.path || r.url || '', file_path: r.path,
        duration_sec: r.duration_sec ?? null,
      }
      setSource(s)
      if (!taskName.trim()) setTaskName(file.name.replace(/\.[^.]+$/, ''))
      setMsg({ kind: 'ok', text: `已上传：${file.name}（${r.duration_sec?.toFixed(1) || '?'}s）。元数据将在建任务时补全。` })
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '上传失败' })
    } finally {
      setAcquiring(false)
    }
  }

  const createJob = async () => {
    if (!source) { setMsg({ kind: 'err', text: '请先获取或上传源视频' }); return }
    if (!rightsAck) { setMsg({ kind: 'err', text: '请勾选权利声明' }); return }
    if (!targetSpecId) { setMsg({ kind: 'err', text: '请选择目标投放规格' }); return }
    const spec = specs.find(s => s.spec_id === targetSpecId)
    setCreating(true)
    setMsg(null)
    try {
      const r = await imitateVideoApi.createJob({
        file: source.file_path || source.file || '',
        source: source.source || 'upload',
        source_url: source.source_url || '',
        name: taskName.trim() || source.name || '',
        rights_ack: rightsAck,
        options: {
          target_spec_id: targetSpecId,
          target_platform: spec?.platform || '',
          target_ad_product: spec?.ad_product || '',
          target_aspect_ratio: (spec?.aspect_ratios || [])[0] || '',
          structure_fidelity: structureFidelity,
          language: language.trim(),
        },
      })
      setMsg({ kind: 'ok', text: `任务已创建：${r.job_id}（本步不产生费用）` })
      setSource(null)
      setTaskName(''); setUrl(''); setRightsAck(false)
      if (fileRef.current) fileRef.current.value = ''
      await load()
    } catch (e: any) {
      setMsg({ kind: 'err', text: e?.message || '创建任务失败' })
    } finally {
      setCreating(false)
    }
  }

  const switchTab = (t: Tab) => {
    setTab(t)
    setSource(null)
    setMsg(null)
  }

  return (
    <div className="ui-page">
      {msg && <div className={`ui-message ${msg.kind === 'err' ? 'err' : 'ok'}`}>{msg.text}</div>}

      {/* ---- 新建任务：从上到下的单列表单 ---- */}
      <UiCard title="新建任务 · 源视频" subtitle="链接或上传专业投放视频，系统学习其创作结构后重新演绎。">
        <div className="ui-form">
          <UiFormRow label="参考来源">
            <UiActionRow inline>
              <UiButton block active={tab === 'url'} onClick={() => switchTab('url')}>视频链接</UiButton>
              <UiButton block active={tab === 'upload'} onClick={() => switchTab('upload')}>本地上传</UiButton>
            </UiActionRow>
          </UiFormRow>

          {tab === 'url' ? (
            <UiFormRow label="视频直链" hint="仅支持 http/https 直链，文件不超过 200MB。">
              <UiInput placeholder="粘贴视频直链" value={url} onChange={e => setUrl(e.target.value)} />
              <UiButton variant="primary" block onClick={() => void acquireUrl()} disabled={acquiring}>
                {acquiring ? '获取中…' : '获取源视频'}
              </UiButton>
            </UiFormRow>
          ) : (
            <UiFormRow label="本地视频" hint="支持 MP4 / MOV / WEBM / M4V，文件不超过 200MB。">
              <UiInput ref={fileRef} type="file" className="ui-file"
                accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                onChange={e => { const f = e.target.files?.[0]; if (f) void uploadFile(f) }} />
            </UiFormRow>
          )}

          <UiFormRow label="任务名称" htmlFor="iv-task-name">
            <UiInput id="iv-task-name" value={taskName} onChange={e => setTaskName(e.target.value)}
              placeholder="可选，默认取源视频名" />
          </UiFormRow>

          <UiFormRow label="目标投放规格" htmlFor="iv-target-spec">
            <UiSelect id="iv-target-spec" value={targetSpecId} onChange={e => setTargetSpecId(e.target.value)}>
              <option value="">请选择平台 + 版位</option>
              {specs.map(s => (
                <option key={s.spec_id} value={s.spec_id}>{specLabel(s)}（{s.verification_label || s.verification}）</option>
              ))}
            </UiSelect>
          </UiFormRow>

          <UiFormRow label="结构保持度" htmlFor="iv-fidelity">
            <UiSelect id="iv-fidelity" value={structureFidelity} onChange={e => setStructureFidelity(e.target.value)}>
              <option value="high">高（逐镜保留）</option>
              <option value="medium">中（保留钩子/CTA）</option>
              <option value="low">低（仅叙事骨架）</option>
            </UiSelect>
          </UiFormRow>

          <UiFormRow label="目标语言" htmlFor="iv-language">
            <UiSelect id="iv-language" value={language} onChange={e => setLanguage(e.target.value)}>
              <option value="">跟随原片</option>
              <option value="en">英文</option>
              <option value="zh">中文</option>
            </UiSelect>
          </UiFormRow>
        </div>

        {/* ---- 原片预览 + 元数据：单列纵向 ---- */}
        {source && (
          <UiPanel title="源视频预览与元数据" subtitle={`${source.name || '—'} · ${sourceLabel(source.source)}`}>
            <UiStack>
              <video className="ui-video" src={api.fileUrl(source.file || '')} controls playsInline />
              <div className="ui-kv">
                <MetaRow label="分辨率" value={source.width && source.height ? `${source.width}×${source.height}` : (source.source === 'upload' ? '建任务时补全' : '未知')} />
                <MetaRow label="画幅比" value={source.aspect_ratio} />
                <MetaRow label="时长" value={source.duration_sec ? `${source.duration_sec.toFixed(1)} 秒` : '未知'} />
                <MetaRow label="帧率" value={source.fps} />
                <MetaRow label="音轨" value={source.has_audio ? '有' : '无'} />
                <MetaRow label="大小" value={source.bytes ? `${(source.bytes / 1024 / 1024).toFixed(1)} MB` : '—'} />
              </div>
              <UiCheckRow checked={rightsAck} onChange={setRightsAck}>
                我已获得该视频的使用授权，仅用于学习其创作结构并重新创作（权利声明将留痕）
              </UiCheckRow>
              <UiButton variant="primary" block onClick={() => void createJob()} disabled={creating}>
                {creating ? '创建中…' : '确认源视频并创建任务'}
              </UiButton>
            </UiStack>
          </UiPanel>
        )}
      </UiCard>

      {/* ---- 任务列表：宽表改为纵向卡片 ---- */}
      <UiCard title="任务列表" actions={<UiButton block onClick={() => void load()} disabled={loading}>{loading ? '刷新中…' : '刷新'}</UiButton>}>
        {loading && <div className="ui-empty">加载中…</div>}
        {!loading && items.length === 0 && <div className="ui-empty">暂无任务，请先在上方提交参考视频。</div>}
        {!loading && items.length > 0 && (
          <div className="ui-task-list">
            {items.map(t => (
              <div className="ui-task-card" key={t.job_id}>
                <div className="ui-task-title">{t.name || t.job_id}</div>
                <div className="ui-task-id">任务号：{t.job_id}</div>
                <div className="ui-badge-row">
                  <span className="ui-badge on">{STATUS_LABEL[t.status] || t.status}</span>
                  <span className="ui-badge">{t.stage ? (STAGE_LABEL[t.stage] || t.stage) : '—'}</span>
                  <span className="ui-badge">来源：{sourceLabel(t.source)}</span>
                </div>
                <div className="ui-task-meta">
                  <MetaRow label="画幅 / 时长" value={[t.aspect_ratio, t.duration_sec ? `${t.duration_sec.toFixed(1)}s` : ''].filter(Boolean).join(' / ') || '—'} />
                  <MetaRow label="创建时间" value={t.created_at} />
                </div>
                <UiStack gap="tight">
                  {t.source_file && (
                    <UiLinkButton block href={imitateVideoApi.sourceUrl(t.job_id)} target="_blank" rel="noreferrer">预览原片</UiLinkButton>
                  )}
                  {t.analysis_script_id ? (
                    <UiButton block onClick={() => void openScript(t)}>查看分析脚本{t.analysis_cached ? '（缓存）' : ''}</UiButton>
                  ) : t.stage === 'analysis_pending' ? (
                    <div className="ui-badge">分析脚本生成中…</div>
                  ) : t.stage === 'analysis_unavailable' ? (
                    <UiButton block disabled={!!analyzingId} onClick={() => void triggerAnalyze(t)}>重试分析</UiButton>
                  ) : t.stage === 'source_acquiring' ? (
                    <UiButton block disabled={!!analyzingId} onClick={() => void triggerAnalyze(t)}>
                      {analyzingId === t.job_id ? '提交中…' : '生成分析脚本'}
                    </UiButton>
                  ) : null}

                  {t.creation_script_id ? (
                    <UiButton block onClick={() => void openCreation(t)}>查看/确认创作脚本{t.creation_status === 'confirmed' ? '（已确认）' : ''}</UiButton>
                  ) : t.stage === 'creation_pending' ? (
                    <div className="ui-badge">创作脚本生成中…</div>
                  ) : t.stage === 'creation_unavailable' ? (
                    <UiButton block disabled={!!creatingScriptId} onClick={() => void triggerCreation(t)}>重试创作脚本</UiButton>
                  ) : t.stage === 'analysis_ready' ? (
                    <UiButton block disabled={!!creatingScriptId} onClick={() => void triggerCreation(t)}>
                      {creatingScriptId === t.job_id ? '提交中…' : '生成创作脚本'}
                    </UiButton>
                  ) : t.stage === 'awaiting_confirm' ? (
                    <UiButton block onClick={() => void openCreation(t)}>去确认创作脚本</UiButton>
                  ) : null}
                </UiStack>
              </div>
            ))}
          </div>
        )}
      </UiCard>

      {/* ---- 分析脚本查看 / 编辑（A1–A10）---- */}
      {scriptTask && (
        <UiCard
          title={`分析脚本 A1–A10 · ${scriptTask.name || scriptTask.job_id}`}
          subtitle={script?.meta_json?.model
            ? `模型：${String(script.meta_json.provider || '')} / ${String(script.meta_json.model)}${script?.meta_json?.frames ? ` · 抽帧 ${String(script.meta_json.frames)} 张` : ''}`
            : '真实视觉模型分析'}
          actions={(
            <>
              {script && !scriptEditing && (
                <>
                  <UiButton block onClick={() => setScriptEditing(true)}>编辑</UiButton>
                  <UiButton block onClick={downloadScript}>导出 JSON</UiButton>
                </>
              )}
              <UiButton block onClick={() => { setScriptTask(null); setScript(null) }}>关闭</UiButton>
            </>
          )}
        >
          {scriptLoading && <div className="ui-empty">加载分析脚本…</div>}
          {!scriptLoading && !script && (
            <div className="ui-empty">尚无分析脚本。可在任务卡片点击「生成分析脚本」（使用系统已配置的真实视觉模型）。</div>
          )}
          {!scriptLoading && scriptEditing && (
            <UiStack>
              <UiTextarea value={scriptDraft} onChange={e => setScriptDraft(e.target.value)} className="ui-json-textarea" />
              <UiActionRow>
                <UiButton variant="primary" block onClick={saveScriptLocal}>保存草稿</UiButton>
                <UiButton block onClick={() => { setScriptEditing(false); setScriptDraft(JSON.stringify(script?.script_json || {}, null, 2)) }}>取消</UiButton>
              </UiActionRow>
            </UiStack>
          )}
          {!scriptLoading && !scriptEditing && script?.script_json && (
            <div className="ui-script-list">
              {Object.keys(A_LABELS).map(k => (
                <ScriptDetails key={k} code={k} label={A_LABELS[k]} value={script.script_json?.[k] ?? {}} />
              ))}
            </div>
          )}
        </UiCard>
      )}

      {/* ---- 创作脚本查看 / 编辑 / 确认（C1–C8）---- */}
      {creationTask && (
        <UiCard
          title={`创作脚本 C1–C8 · ${creationTask.name || creationTask.job_id}`}
          subtitle={`${creation?.meta_json?.model ? `模型：${String(creation.meta_json.provider || '')} / ${String(creation.meta_json.model)}` : '统一文本模型'}${creation?.script_json?.C1?.spec_id ? ` · 规格：${String(creation.script_json.C1.spec_id)}` : ''}${creation?.meta_json?.idempotency_key ? ` · 幂等键：${String(creation.meta_json.idempotency_key)}` : ''}`}
          actions={(
            <>
              {creation && !creationEditing && (
                <>
                  <UiButton block onClick={() => setCreationEditing(true)}>JSON 编辑</UiButton>
                  <UiButton block onClick={downloadCreation}>导出 JSON</UiButton>
                </>
              )}
              <UiButton block onClick={() => { setCreationTask(null); setCreation(null) }}>关闭</UiButton>
            </>
          )}
        >
          {creationLoading && <div className="ui-empty">加载创作脚本…</div>}
          {!creationLoading && !creation && (
            <div className="ui-empty">
              {creationTask.stage === 'creation_pending'
                ? '创作脚本正在后台生成，可切页等待，回到本页点击刷新即可。'
                : '尚无创作脚本。请先在任务卡片点击「生成创作脚本」。'}
            </div>
          )}

          {creation && (
            <UiStack>
              <UiFormRow label="结构保持度" htmlFor="iv-creation-fidelity">
                <UiSelect id="iv-creation-fidelity" value={String(creation.script_json?.C2?.fidelity || 'medium')}
                  onChange={e => updateFidelity(e.target.value)}>
                  <option value="high">高（逐镜保留）</option>
                  <option value="medium">中（保留钩子/CTA）</option>
                  <option value="low">低（仅叙事骨架）</option>
                </UiSelect>
              </UiFormRow>

              <UiPanel title="成本预估" subtitle={`${creation.script_json?.C8?.estimated_cost?.amount ?? '—'} ${String(creation.script_json?.C8?.estimated_cost?.currency || 'USD')} · ${String(creation.script_json?.C8?.estimated_cost?.note || '工程预估，非供应商报价')}`} />

              <UiPanel title="商业信息保留" subtitle="勾选后必须改写，不逐字复制原文。">
                <UiStack gap="tight">
                  {Object.keys(COMMERCIAL_LABELS).map(k => (
                    <UiCheckRow key={k} checked={!!creation.script_json?.C5?.toggles?.[k]}
                      onChange={v => updateCommercialToggle(k, v)}>
                      {COMMERCIAL_LABELS[k]}
                    </UiCheckRow>
                  ))}
                </UiStack>
              </UiPanel>

              <UiFormRow label="口播改写稿" hint="仅交付文案，人工配音。">
                <UiTextarea value={String(creation.script_json?.C6?.voiceover_text || '')}
                  onChange={e => setCreation(s => s ? {
                    ...s,
                    script_json: { ...(s.script_json || {}), C6: { ...(s.script_json?.C6 || {}), voiceover_text: e.target.value } },
                  } : s)}
                  onBlur={() => updateVoiceover(String(creation.script_json?.C6?.voiceover_text || ''))} />
              </UiFormRow>

              <UiPanel title="逐镜指令" subtitle="可调整顺序或删除镜头；每次修改都会自动重新计价并作废旧幂等键。">
                {shots.length === 0 ? <div className="ui-empty">暂无镜头指令。</div> : (
                  <div className="ui-shot-list">
                    {shots.map((s, i) => (
                      <div className="ui-shot-card" key={`${s.index || i}-${i}`}>
                        <div className="ui-shot-head">
                          <span className="ui-badge on">#{s.index || i + 1}</span>
                          <span className="ui-badge">{[s.tc_start, s.tc_end].filter(Boolean).join('→') || '时码未定'}</span>
                          <span className="ui-badge">时长 {s.duration || '—'}</span>
                        </div>
                        <div className="ui-shot-line"><span>画面指令：</span>{s.visual_prompt || '—'}</div>
                        <div className="ui-shot-line"><span>运镜：</span>{s.camera || s.movement_path || '—'}</div>
                        <UiActionRow inline>
                          <UiButton disabled={i === 0} onClick={() => moveShot(i, -1)}>上移</UiButton>
                          <UiButton disabled={i === shots.length - 1} onClick={() => moveShot(i, 1)}>下移</UiButton>
                          <UiButton onClick={() => deleteShot(i)}>删除</UiButton>
                        </UiActionRow>
                      </div>
                    ))}
                  </div>
                )}
              </UiPanel>

              {creationEditing && (
                <UiStack>
                  <UiTextarea value={creationDraft} onChange={e => setCreationDraft(e.target.value)} className="ui-json-textarea" />
                  <UiActionRow>
                    <UiButton variant="primary" block onClick={saveCreation}>保存创作脚本</UiButton>
                    <UiButton block onClick={() => { setCreationEditing(false); setCreationDraft(JSON.stringify(creation.script_json || {}, null, 2)) }}>取消</UiButton>
                  </UiActionRow>
                </UiStack>
              )}

              <div className="ui-script-list">
                {Object.keys(C_LABELS).map(k => (
                  <ScriptDetails key={k} code={k} label={C_LABELS[k]} value={creation.script_json?.[k] ?? {}} />
                ))}
              </div>

              {creationTask.stage === 'awaiting_confirm' && (
                <UiPanel title="确认闸门" subtitle="确认后冻结脚本与幂等键；本版不会提交供应商，也不会设置任何视频付费字段。">
                  <UiStack>
                    <UiCheckRow checked={feeAck} onChange={setFeeAck}>
                      我已知晓上述预计消耗与合规标注，确认按此脚本进入后续生成
                    </UiCheckRow>
                    <UiButton variant="primary" block disabled={!feeAck || !!confirmingId}
                      onClick={() => void confirmCreation(creationTask)}>
                      {confirmingId ? '确认中…' : '确认并冻结脚本'}
                    </UiButton>
                  </UiStack>
                </UiPanel>
              )}
            </UiStack>
          )}
        </UiCard>
      )}
    </div>
  )
}
