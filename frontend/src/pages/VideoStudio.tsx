import React, { useRef, useEffect, useState } from 'react'
import { api } from '../api'

/* V4.70 创意工作台 · 视频素材模块（受控组件，状态由父级 CreativeWorkbench 托管，便于 Step2 规划 → Step3 工作区共享分镜方案）
 * mode="plan"：第二步「规划创意」中的视频策划对话框（逐镜规划 / 多轮微调），不触发生成；
 * mode="work"：第三步「批量生成」中的视频工作区（生成进度 + 成片结果 + 生成后微调对话框）。
 */

interface VideoMsg { role: 'user' | 'assistant'; content: string }

// 父级托管的视频状态切片
export interface VideoState {
  messages: VideoMsg[]
  plan: any
  videos: any[]
  options: any
  note: string
  modelInfo: any       // V4.78：分镜策划（文本模型）的调用快照，role=analysis
  videoModel: any      // V4.78：实际出片（视频模型）的快照，role=video；未配置时 provider=storyboard
  outputAspect: string
  planning: boolean
  generating: boolean
  error: string
  refineInput: string
  // V4.79：出片失败的结构化信息（error_code / 唯一动作 / 脱敏证据）；为空表示没失败
  videoFail?: { code: string; message: string; action: string; stage?: string; taskId?: string; evidence?: any } | null
}

interface VideoStudioProps {
  analysis?: any
  platform?: string
  referenceImage?: string
  brandLogo?: string
  injectLogo?: boolean
  mode: 'plan' | 'work'
  state: VideoState
  setState: (updater: (prev: VideoState) => VideoState) => void
  // 工作区模式下，由父级注入「生成中」的聚合进度文本（可选）
  progressText?: string
  // V4.83 / C02：出片统一由父级提交（持久任务 + 幂等 + 批次订阅）。
  // VideoStudio 不再自己长轮询 /cw-video/generate，避免出现「抽屉一条、页面另一条」两套状态。
  // 返回 false 表示父级拒绝提交（未选草稿 / 未规划等），组件保持当前状态即可。
  onSubmitJob?: (payload: {
    plan: any; options: any; refinement?: string
  }) => Promise<boolean> | boolean
}

const MODE_OPTS = [
  { v: 'text_to_video', label: '文生视频' },
  { v: 'image_to_video', label: '图生视频（参考图驱动）' },
]
const VOICEOVER_OPTS = [
  { v: 'none', label: '无配音（纯画面）' },
  { v: 'narration', label: '旁白脚本（字幕 / VO 文案）' },
  { v: 'tts', label: 'AI 配音（TTS）' },
]
const ASPECT_OPTS = [
  { v: '9:16', label: '竖版 9:16（信息流 / Reels）' },
  { v: '1:1', label: '方版 1:1' },
  { v: '16:9', label: '横版 16:9' },
]
const DURATION_OPTS = [5, 10, 15]

function fileUrl(u?: string) {
  if (!u) return ''
  if (/^https?:\/\//i.test(u)) return u
  return api.fileUrl(u)
}

// V4.78：两个模型徽标必须分开——
// · 分镜策划用的是「文本模型」（analysis/copy 用途，可能是 DeepSeek / 千问文本）；
// · 出片用的是「视频模型」（video 用途，如阿里云百炼 wan3.0-video）。
// 此前两者共用一个 modelInfo，视频面板把文本模型当成视频模型展示，用户看到的就是「视频模型是 deepseek」。
function planModelLabel(mi: any) {
  if (!mi) return ''
  if (mi.fallback) return '分镜模型（文本）· 兜底'
  const name = mi.model || mi.provider || ''
  if (!name) return ''
  return `分镜模型（文本）· ${name}`
}

function videoModelLabel(mi: any) {
  if (!mi) return ''
  if (mi.provider === 'storyboard') return '出片模型 · 未配置（回退分镜）'
  if (mi.provider === 'kling') return `出片模型 · 可灵 ${mi.model || ''}`.trim()
  if (mi.provider === 'model') return `出片模型 · ${mi.model || '视频模型'}`
  return `出片模型 · ${mi.model || mi.provider}`
}

// V4.79：出片失败结构化信息。error_code 为空即成功；非空时界面只展示「一个动作」，
// 而不是让用户自己猜该重试、该改配置还是该重新下载。
function failOf(r: any) {
  if (!r?.error_code) return null
  return {
    code: String(r.error_code),
    message: r.error_message || r.note || '',
    action: r.error_action || '',
    stage: r.stage || '',
    taskId: r.error_task_id || '',
    evidence: r.evidence || null,
  }
}

const STAGE_LABEL: Record<string, string> = {
  config: '配置', submit: '提交任务', poll: '查询任务', download: '下载成片',
  storage: '写入文件', generate: '生成',
}

// 输出比例标签：显式标注实际出片比例（如 9:16 竖屏）
function aspectKind(a?: string): string {
  if (a === '9:16') return '竖屏'
  if (a === '1:1') return '方版'
  if (a === '16:9') return '横版'
  return ''
}
function AspectChip({ aspect }: { aspect?: string }) {
  if (!aspect) return null
  const kind = aspectKind(aspect)
  return (
    <span className={`vs-aspect-chip ${aspect === '9:16' ? 'portrait' : aspect === '16:9' ? 'landscape' : 'square'}`}>
      输出比例 {aspect}{kind ? `（${kind}）` : ''}
    </span>
  )
}

export default function VideoStudio({ analysis, platform, referenceImage, brandLogo, injectLogo, mode, state, setState, onSubmitJob }: VideoStudioProps) {
  const { messages, plan, videos, options, note, modelInfo, videoModel, planning, generating, error, refineInput } = state
  const chatRef = useRef<HTMLDivElement>(null)
  // V4.75：视频链路自检结果（只读配置，不触发出片）
  const [diag, setDiag] = useState<any>(null)
  const [diagBusy, setDiagBusy] = useState(false)
  // V4.78：进面板即静默读取「实际出片模型」，让用户随时能看到真正会被调用的视频模型
  // （此前只有文本分镜模型可见，且被误标成「视频模型」，是「视频模型显示 deepseek」的直接来源）
  const [route, setRoute] = useState<{ checked: boolean; ready: boolean; model: string; provider: string; id: number | null }>(
    { checked: false, ready: false, model: '', provider: '', id: null })
  useEffect(() => {
    api.cwVideoDiagnose()
      .then((r: any) => setRoute({ checked: true, ready: !!r?.configured, model: r?.model || '', provider: r?.provider || '', id: r?.config_id ?? null }))
      // 请求失败（未授权 / 网络）时不置 checked：宁可不显示徽标，也不要误报「未配置」误导用户
      .catch(() => { /* 保持未检测状态 */ })
  }, [])
  // V4.76：出片为后台任务，这里只展示已等待时长与阶段（避免用户以为卡死）
  const [genSec, setGenSec] = useState(0)
  const [genStage, setGenStage] = useState('')

  async function runDiagnose() {
    setDiagBusy(true)
    try {
      const r = await api.cwVideoDiagnose()
      setDiag(r)
    } catch (e: any) {
      setDiag({ configured: false, hints: ['诊断请求失败：' + (e?.message || '未知错误')] })
    } finally {
      setDiagBusy(false)
    }
  }

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages, planning])

  function setOpt(key: string, val: any) {
    setState(s => ({ ...s, options: { ...s.options, [key]: val } }))
  }

  async function planStoryboard(seed?: string) {
    setState(s => ({ ...s, error: '' }))
    const msgs = seed ? [...s_messages(), { role: 'user', content: seed } as VideoMsg] : s_messages()
    if (!msgs.length) {
      setState(s => ({ ...s, error: '请先输入创作构想，或点击「生成分镜草案」' }))
      return
    }
    setState(s => ({ ...s, planning: true }))
    try {
      const r: any = await api.cwVideoPlan({
        analysis: analysis || {},
        platform: platform || '',
        reference_image: referenceImage || '',
        brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
        messages: msgs,
        current_plan: plan || undefined,
        options,
      })
      const next = [...msgs]
      if (r?.reply) next.push({ role: 'assistant', content: r.reply })
      setState(s => ({ ...s, messages: next, plan: r?.plan || s.plan, modelInfo: r?.model_info || s.modelInfo, videoModel: r?.video_model_info || s.videoModel, outputAspect: r?.output_aspect || s.outputAspect, planning: false, error: '' }))
    } catch (e: any) {
      setState(s => ({ ...s, error: '分镜规划失败：' + (e?.message || ''), planning: false }))
    }
  }
  function s_messages(): VideoMsg[] { return state.messages }

  async function generate() {
    if (!plan || !plan.shots?.length) {
      setState(s => ({ ...s, error: '请先在第二步生成分镜方案（点击「生成分镜草案」或输入构想）' }))
      return
    }
    if (!onSubmitJob) {
      setState(s => ({ ...s, error: '出片入口尚未就绪，请从创意工作台第三步提交' }))
      return
    }
    // V4.83 / C01+C02：新执行先清旧失败与旧成片，旧红色失败框不再跟到新任务；
    // 提交统一交给父级（持久任务 / 幂等键 / batch_id），本组件不再独立长轮询。
    setState(s => ({ ...s, error: '', generating: true, videos: [], note: '', videoFail: null }))
    setGenSec(0); setGenStage('提交中')
    try {
      const ok = await onSubmitJob({
        plan, options: { ...options, prompt_hint: options.prompt_hint },
      })
      if (ok === false) setState(s => ({ ...s, generating: false }))
      // 返回 true 时父级负责把 generating 归位并按 batch 回填，避免两处写同一份状态。
    } catch (e: any) {
      const fail = { code: 'CLIENT_ERROR', message: e?.message || '', action: '稍后重试；连续失败请展开「诊断视频配置」核对链路。' }
      setState(s => ({ ...s, error: '视频提交失败：' + (e?.message || ''), generating: false, videoFail: fail }))
    }
  }

  // 生成后微调：基于当前分镜 + 新调整提示词，先精修分镜再重生成
  async function refine() {
    const seed = (refineInput || '').trim()
    if (!seed) return
    setState(s => ({ ...s, error: '' }))
    const msgs = [...s_messages(), { role: 'user', content: seed } as VideoMsg]
    setState(s => ({ ...s, planning: true, refineInput: '' }))
    try {
      const r: any = await api.cwVideoPlan({
        analysis: analysis || {},
        platform: platform || '',
        reference_image: referenceImage || '',
        brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
        messages: msgs,
        current_plan: plan || undefined,
        options,
      })
      const next = [...msgs]
      if (r?.reply) next.push({ role: 'assistant', content: r.reply })
      const newPlan = r?.plan || plan
      setState(s => ({ ...s, messages: next, plan: newPlan, modelInfo: r?.model_info || s.modelInfo, videoModel: r?.video_model_info || s.videoModel, outputAspect: r?.output_aspect || s.outputAspect, planning: false, error: '' }))
      if (newPlan && newPlan.shots?.length) {
        if (!onSubmitJob) {
          setState(s => ({ ...s, planning: false, error: '出片入口尚未就绪，请从创意工作台第三步提交' }))
          return
        }
        // V4.83 / C02：微调与批量生成共用同一提交链路；带 refinement 便于日志区分，
        // 但批次、草稿、幂等键仍由父级统一生成，结果只从服务端任务快照回填。
        setState(s => ({ ...s, generating: true, videos: [], note: '', videoFail: null }))
        setGenSec(0); setGenStage('提交中')
        const ok = await onSubmitJob({
          plan: newPlan, options: { ...options, prompt_hint: options.prompt_hint }, refinement: seed,
        })
        if (ok === false) setState(s => ({ ...s, generating: false }))
      }
    } catch (e: any) {
      const fail = { code: 'CLIENT_ERROR', message: e?.message || '', action: '稍后重试；连续失败请展开「诊断视频配置」核对链路。' }
      setState(s => ({ ...s, error: '视频微调提交失败：' + (e?.message || ''), planning: false, generating: false, videoFail: fail }))
    }
  }

  function downloadJson() {
    if (!plan) return
    const blob = new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'video_storyboard.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  function reset() {
    setState(s => ({ ...s, messages: [], plan: null, videos: [], note: '', error: '', modelInfo: null, videoModel: null, refineInput: '', videoFail: null }))
  }

  const showRef = options.mode === 'image_to_video' && referenceImage

  // 出片模型徽标：优先用规划/出片接口回传的视频模型，其次用进面板时静默拉取的诊断结果。
  // 两者都没有（或未配置）时明确显示「未配置（回退分镜）」，不再拿文本模型顶替。
  const vm = (videoModel && videoModel.provider && videoModel.provider !== 'storyboard')
    ? { label: videoModelLabel(videoModel), ok: true }
    : route.checked
      ? (route.ready
        ? { label: `出片模型 · ${route.model || route.provider}`, ok: true }
        : { label: '出片模型 · 未配置（回退分镜）', ok: false })
      : null

  // ===== 规划模式（Step 2）=====
  if (mode === 'plan') {
    return (
      <section className="vs-panel vs-plan">
        <div className="vs-head">
          <h4 className="vs-title">🎬 视频创意规划</h4>
          <div className="vs-chips">
            {vm && <span className={`vs-model-chip ${vm.ok ? 'model' : 'storyboard'}`}>{vm.label}</span>}
            {modelInfo && planModelLabel(modelInfo) && (
              <span className="vs-model-chip analysis">{planModelLabel(modelInfo)}</span>
            )}
            <AspectChip aspect={state.outputAspect} />
          </div>
          <span className="vs-sub">基于网站分析 + 媒体平台规则，逐镜规划视频分镜</span>
        </div>

        <div className="vs-options">
          <label className="vs-opt">
            <span>表现形式</span>
            <select value={options.mode} onChange={(e) => setOpt('mode', e.target.value)}>
              {MODE_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </label>
          <label className="vs-opt">
            <span>配音</span>
            <select value={options.voiceover} onChange={(e) => setOpt('voiceover', e.target.value)}>
              {VOICEOVER_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </label>
          <label className="vs-opt">
            <span>时长</span>
            <select value={options.duration} onChange={(e) => setOpt('duration', Number(e.target.value))}>
              {DURATION_OPTS.map((d) => <option key={d} value={d}>{d} 秒</option>)}
            </select>
          </label>
          <label className="vs-opt">
            <span>比例</span>
            <select value={options.aspect} onChange={(e) => setOpt('aspect', e.target.value)}>
              {ASPECT_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </label>
          {showRef && (
            <div className="vs-ref">
              <img src={fileUrl(referenceImage)} alt="参考图" />
              <span>参考图（图生视频驱动）</span>
            </div>
          )}
        </div>

        <div className="vs-chat">
          <div className="vs-chat-head">对话式策划 · 针对提示词 / 创作构想 / 方案微调</div>
          <div className="vs-chat-log" ref={chatRef}>
            {messages.length === 0 && (
              <div className="vs-chat-empty">
                输入创作构想，模型据此微调分镜。例如：「前 3 秒用强对比抓注意力」「强调续航卖点，节奏更快」「换成生活方式叙事角度」。
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`vs-msg vs-msg-${m.role}`}>
                <div className="vs-msg-role">{m.role === 'user' ? '我' : '导演'}</div>
                <div className="vs-msg-text">{m.content}</div>
              </div>
            ))}
            {planning && <div className="vs-msg vs-msg-assistant"><div className="vs-msg-text">规划中…</div></div>}
          </div>
          <div className="vs-chat-input">
            <textarea
              value={state.refineInput}
              onChange={(e) => setState(s => ({ ...s, refineInput: e.target.value }))}
              placeholder="输入提示词微调 / 创作构想 / 方案修改…"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  const s = e.currentTarget.value.trim()
                  if (s) planStoryboard(s)
                }
              }}
            />
            <div className="vs-chat-actions">
              <button onClick={() => { const s = state.refineInput.trim(); if (s) planStoryboard(s) }} disabled={planning}>
                {plan ? '发送并微调分镜' : '发送'}
              </button>
              <button className="vs-ghost" onClick={() => planStoryboard(`根据产品分析，帮我规划一个 ${options.duration} 秒、${options.aspect} 的推广视频分镜，重点突出核心卖点与转化路径`)} disabled={planning}>
                生成分镜草案
              </button>
            </div>
          </div>
        </div>

        <div className="vs-preview">
          <div className="vs-preview-head">
            <span className="vs-preview-title">
              分镜方案{plan ? `（${plan.shots?.length || 0} 镜 · ${plan.duration_sec || options.duration}s · ${plan.aspect || options.aspect}）` : ''}
            </span>
            <div className="vs-preview-actions">
              {plan && <button className="vs-ghost" onClick={downloadJson}>下载分镜 JSON</button>}
              <button className="vs-ghost" onClick={reset}>重置</button>
            </div>
          </div>
          {plan ? (
            <div className="vs-shots">
              {(plan.shots || []).map((s: any) => (
                <div className="vs-shot" key={s.idx}>
                  <div className="vs-shot-meta">
                    <span className="vs-shot-t">{s.t}</span>
                    <span className="vs-shot-kind">{s.shot}</span>
                  </div>
                  <div className="vs-shot-visual">{s.visual}</div>
                  {s.text && <div className="vs-shot-line"><b>字幕</b> {s.text}</div>}
                  {s.vo && <div className="vs-shot-line"><b>VO</b> {s.vo}</div>}
                  {s.camera && <div className="vs-shot-line"><b>运镜</b> {s.camera}</div>}
                  {s.motion && <div className="vs-shot-line"><b>运动</b> {s.motion}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div className="vs-preview-empty">尚无分镜方案。在左侧输入构想或点击「生成分镜草案」。</div>
          )}
        </div>

        {error && <div className="vs-error">{error}</div>}
      </section>
    )
  }

  // ===== 工作区模式（Step 3）=====
  return (
    <section className="vs-panel vs-work">
      <div className="vs-head">
        <h4 className="vs-title">🎬 视频生成工作区</h4>
        <div className="vs-chips">
          {vm && <span className={`vs-model-chip ${vm.ok ? 'model' : 'storyboard'}`}>{vm.label}</span>}
          {modelInfo && planModelLabel(modelInfo) && (
            <span className="vs-model-chip analysis">{planModelLabel(modelInfo)}</span>
          )}
          <AspectChip aspect={state.outputAspect} />
        </div>
        <button className="vs-ghost vs-diag-btn" onClick={runDiagnose} disabled={diagBusy}>
          {diagBusy ? '诊断中…' : '诊断视频配置'}
        </button>
      </div>

      {diag && (
        <div className={`vs-diag ${diag.configured ? 'ok' : 'warn'}`}>
          <div className="vs-diag-head">
            <b>{diag.state === 'ready'
              ? `✅ ${diag.state_label || '视频模型已就绪，可直接出片'}`
              : `⚠️ ${diag.state_label || '视频模型未就绪'}（当前会回退分镜脚本）`}</b>
            <button className="vs-ghost" onClick={() => setDiag(null)}>关闭</button>
          </div>
          {/* V4.79：四态收敛成一个动作，不用在一堆提示里自己找结论 */}
          {diag.action && <div className="vs-diag-act">👉 {diag.action}</div>}
          {diag.configured && (
            <div className="vs-diag-meta">
              <span>配置 #{diag.config_id}</span>
              <span>{diag.provider || '—'}</span>
              <span>{diag.model || '—'}</span>
              <span>{diag.host || '—'}</span>
              <span>{diag.is_active ? '已启用' : '已停用'}</span>
              <span>
                连通测试：{diag.last_test_ok === true ? '通过' : diag.last_test_ok === false ? '失败' : '未测试'}
              </span>
            </div>
          )}
          {(diag.hints || []).length > 0 && (
            <ul className="vs-diag-hints">
              {(diag.hints as string[]).map((h, i) => <li key={i}>{h}</li>)}
            </ul>
          )}
          {/* V4.78：把「候选」与「被跳过」都摊开，避免用户误以为系统在用文本模型出片 */}
          {((diag.candidates || []).length + (diag.skipped || []).length) > 0 && (
            <div className="vs-diag-rows">
              {(diag.candidates || []).map((c: any) => (
                <div className="vs-diag-row ok" key={'c' + c.id}>
                  <b>#{c.id} {c.name || c.model}</b>
                  <span>{c.provider || '—'} · {c.model || '—'}</span>
                  <span>用途 {((c.usages || []).join(' / ') || '—')}</span>
                  <span>{c.is_active ? '已启用' : '已停用'}</span>
                  <span>{c.id === diag.config_id ? '← 本次出片将使用' : '可用候选（未选中）'}</span>
                </div>
              ))}
              {(diag.skipped || []).map((c: any) => (
                <div className="vs-diag-row skip" key={'s' + c.id}>
                  <b>#{c.id} {c.name || c.model}</b>
                  <span>{c.provider || '—'} · {c.model || '—'}</span>
                  <span>已跳过：{c.reason}</span>
                </div>
              ))}
            </div>
          )}
          {diag.last_test_error && <pre className="vs-diag-err">{diag.last_test_error}</pre>}
        </div>
      )}

      {(generating || state.generating) && (
        <div className="vs-gen-status">
          视频生成中{genSec > 0 ? `（已等待 ${genSec} 秒` : '（'}…
          {genStage ? ` · ${genStage}` : ''}）
          <span className="vs-gen-tip">任务已在服务端后台运行，等待期间请保持本页打开（最长约 12 分钟）；出片后会自动展示并可下载。</span>
        </div>
      )}
      {note && <div className="vs-note">{note}</div>}

      {/* V4.79：失败要说清楚「卡在哪一步、下一步做什么」，并保留脱敏证据供核对 */}
      {state.videoFail && (
        <div className="vs-fail">
          <div className="vs-fail-head">
            <b>❌ 出片失败（{state.videoFail.code}）</b>
            {state.videoFail.stage && <span>阶段：{STAGE_LABEL[state.videoFail.stage] || state.videoFail.stage}</span>}
          </div>
          {state.videoFail.message && <div className="vs-fail-msg">{state.videoFail.message}</div>}
          {state.videoFail.action && <div className="vs-fail-act">👉 {state.videoFail.action}</div>}
          {state.videoFail.taskId && (
            <div className="vs-fail-task">厂商任务号：<code>{state.videoFail.taskId}</code>（可到厂商控制台按此号取片）</div>
          )}
          {state.videoFail.evidence && (
            <details className="vs-fail-ev">
              <summary>查看证据（提交 / 轮询 / 下载原文，已脱敏）</summary>
              <pre>{JSON.stringify(state.videoFail.evidence, null, 2)}</pre>
            </details>
          )}
        </div>
      )}

      {videos.length > 0 && (
        <div className="vs-videos">
          <div className="vs-videos-head">
            生成结果
            {state.outputAspect && <AspectChip aspect={state.outputAspect} />}
          </div>
          <div className="vs-video-grid">
            {videos.map((v, i) => (
              <div className="vs-video" key={i}>
                <video src={fileUrl(v.url)} controls preload="metadata" />
                <div className="vs-video-cap">
                  {v.caption || `片段 ${i + 1}`}
                  {v.duration_sec ? (
                    <span className="vs-video-dur" title={v.duration_source === 'measured' ? '实测成片时长' : '计划时长'}>
                      {v.duration_sec}{v.duration_source === 'measured' ? 's · 实测' : 's'}
                    </span>
                  ) : null}
                  {/* V4.83：原片保留但不冒充达标成品 */}
                  {v.delivery_status && v.delivery_status !== 'compliant'
                    ? <span className="vs-video-bad">{v.delivery_status === 'noncompliant' ? '未达要求' : '时长未验证'}</span>
                    : null}
                </div>
                <a className="vs-video-dl" href={fileUrl(v.url)} download target="_blank" rel="noreferrer">下载视频</a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 生成后微调对话框：针对已生成视频输入新调整提示词，重生成合规视频素材 */}
      {videos.length > 0 && (
        <div className="vs-refine">
          <div className="vs-refine-head">微调已生成视频</div>
          <p className="vs-refine-hint">输入新的调整提示词（如「节奏更紧凑」「突出价格优势」「换成竖版构图」），将基于当前分镜精修并重生成。</p>
          <textarea
            value={refineInput}
            onChange={(e) => setState(s => ({ ...s, refineInput: e.target.value }))}
            placeholder="输入微调提示词…"
          />
          <div className="vs-refine-actions">
            <button className="vs-primary" onClick={refine} disabled={planning || generating || !refineInput.trim()}>
              {planning || generating ? '重生成中…' : '微调并重生成'}
            </button>
          </div>
        </div>
      )}

      {error && <div className="vs-error">{error}</div>}
      {!plan && <div className="vs-preview-empty">尚未生成分镜方案。请返回第二步「视频创意规划」。</div>}
    </section>
  )
}
