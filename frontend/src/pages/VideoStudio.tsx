import React, { useRef, useEffect } from 'react'
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
  modelInfo: any
  planning: boolean
  generating: boolean
  error: string
  refineInput: string
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

function providerLabel(mi: any) {
  if (!mi) return ''
  if (mi.provider === 'storyboard') return '分镜脚本（未配置视频模型）'
  if (mi.provider === 'kling') return `可灵 · ${mi.model || ''}`
  if (mi.provider === 'model') return `视频模型 · ${mi.model || ''}`
  return mi.provider || ''
}

export default function VideoStudio({ analysis, platform, referenceImage, brandLogo, injectLogo, mode, state, setState }: VideoStudioProps) {
  const { messages, plan, videos, options, note, modelInfo, planning, generating, error, refineInput } = state
  const chatRef = useRef<HTMLDivElement>(null)

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
      setState(s => ({ ...s, messages: next, plan: r?.plan || s.plan, modelInfo: r?.model_info || s.modelInfo, planning: false, error: '' }))
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
    setState(s => ({ ...s, error: '', generating: true, videos: [], note: '' }))
    try {
      const r: any = await api.cwVideoGenerate({
        analysis: analysis || {},
        platform: platform || '',
        reference_image: referenceImage || '',
        brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
        plan,
        options: { ...options, prompt_hint: options.prompt_hint },
      })
      setState(s => ({ ...s, videos: r?.videos || [], note: r?.note || '', modelInfo: r?.model_info || s.modelInfo, generating: false, plan: r?.storyboard || s.plan, error: '' }))
    } catch (e: any) {
      setState(s => ({ ...s, error: '视频生成失败：' + (e?.message || ''), generating: false }))
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
      setState(s => ({ ...s, messages: next, plan: newPlan, modelInfo: r?.model_info || s.modelInfo, planning: false, error: '' }))
      if (newPlan && newPlan.shots?.length) {
        setState(s => ({ ...s, generating: true, videos: [], note: '' }))
        const g: any = await api.cwVideoGenerate({
          analysis: analysis || {},
          platform: platform || '',
          reference_image: referenceImage || '',
          brand_logo: (injectLogo && brandLogo) ? brandLogo : '',
          plan: newPlan,
          options: { ...options, prompt_hint: options.prompt_hint },
        })
        setState(s => ({ ...s, videos: g?.videos || [], note: g?.note || '', modelInfo: g?.model_info || s.modelInfo, generating: false, plan: g?.storyboard || s.plan, error: '' }))
      }
    } catch (e: any) {
      setState(s => ({ ...s, error: '视频微调失败：' + (e?.message || ''), planning: false, generating: false }))
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
    setState(s => ({ ...s, messages: [], plan: null, videos: [], note: '', error: '', modelInfo: null, refineInput: '' }))
  }

  const showRef = options.mode === 'image_to_video' && referenceImage

  // ===== 规划模式（Step 2）=====
  if (mode === 'plan') {
    return (
      <section className="vs-panel vs-plan">
        <div className="vs-head">
          <h4 className="vs-title">🎬 视频创意规划</h4>
          {modelInfo && providerLabel(modelInfo) && (
            <span className={`vs-model-chip ${modelInfo.provider}`}>{providerLabel(modelInfo)}</span>
          )}
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
        {modelInfo && providerLabel(modelInfo) && (
          <span className={`vs-model-chip ${modelInfo.provider}`}>{providerLabel(modelInfo)}</span>
        )}
      </div>

      {(generating || state.generating) && (
        <div className="vs-gen-status">视频生成中（直连已配置的视频模型，通常需要 1–3 分钟，仅展示进度）…</div>
      )}
      {note && <div className="vs-note">{note}</div>}

      {videos.length > 0 && (
        <div className="vs-videos">
          <div className="vs-videos-head">生成结果</div>
          <div className="vs-video-grid">
            {videos.map((v, i) => (
              <div className="vs-video" key={i}>
                <video src={fileUrl(v.url)} controls preload="metadata" />
                <div className="vs-video-cap">{v.caption || `片段 ${i + 1}`}</div>
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
