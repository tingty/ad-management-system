import React, { useState, useRef, useEffect } from 'react'
import { api } from '../api'

/* V4.66 创意工作台 · 视频素材创作区
 * 与「图片素材创作区」上下分区、互不干扰：本组件只负责视频，不改动既有图片流程。
 * ① 视频专属选项（表现形式 / 配音 / 时长 / 比例）
 * ② 对话式策划框：针对提示词、创作构想、分镜方案进行多轮微调
 * ③ 分镜预览 + 一键生成（直连视频模型 / 未配置则回退可执行分镜脚本）+ 视频结果网格
 */

interface VideoMsg { role: 'user' | 'assistant'; content: string }
interface VideoStudioProps {
  analysis?: any
  platform?: string
  referenceImage?: string
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

export default function VideoStudio({ analysis, platform, referenceImage }: VideoStudioProps) {
  const [options, setOptions] = useState({
    mode: referenceImage ? 'image_to_video' : 'text_to_video',
    voiceover: 'narration',
    duration: 15,
    aspect: '9:16',
    lang: 'zh',
    prompt_hint: '',
  })
  const [messages, setMessages] = useState<VideoMsg[]>([])
  const [plan, setPlan] = useState<any>(null)
  const [videos, setVideos] = useState<any[]>([])
  const [planning, setPlanning] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [modelInfo, setModelInfo] = useState<any>(null)
  const [input, setInput] = useState('')
  const chatRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages, planning])

  async function planStoryboard(seed?: string) {
    setError('')
    const msgs = seed ? [...messages, { role: 'user', content: seed } as VideoMsg] : messages
    if (!msgs.length) {
      setError('请先输入创作构想，或点击「生成分镜草案」')
      return
    }
    setPlanning(true)
    try {
      const r: any = await api.cwVideoPlan({
        analysis: analysis || {},
        platform: platform || '',
        reference_image: referenceImage || '',
        messages: msgs,
        current_plan: plan || undefined,
        options,
      })
      const next = [...msgs]
      if (r?.reply) next.push({ role: 'assistant', content: r.reply })
      setMessages(next)
      if (r?.plan) setPlan(r.plan)
      setModelInfo(r?.model_info || null)
    } catch (e: any) {
      setError('分镜规划失败：' + (e?.message || ''))
    } finally {
      setPlanning(false)
    }
  }

  async function generate() {
    if (!plan || !plan.shots?.length) {
      setError('请先生成分镜方案（点击「生成分镜草案」或输入构想）')
      return
    }
    setError('')
    setGenerating(true)
    setVideos([])
    setNote('')
    try {
      const r: any = await api.cwVideoGenerate({
        analysis: analysis || {},
        platform: platform || '',
        reference_image: referenceImage || '',
        plan,
        options: { ...options, prompt_hint: options.prompt_hint },
      })
      setVideos(r?.videos || [])
      setNote(r?.note || '')
      setModelInfo(r?.model_info || null)
      if (r?.storyboard) setPlan(r.storyboard)
    } catch (e: any) {
      setError('视频生成失败：' + (e?.message || ''))
    } finally {
      setGenerating(false)
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
    setMessages([])
    setPlan(null)
    setVideos([])
    setNote('')
    setError('')
    setModelInfo(null)
  }

  const showRef = options.mode === 'image_to_video' && referenceImage

  return (
    <section className="vs-panel">
      <div className="vs-head">
        <h3 className="vs-title">🎬 视频素材创作区</h3>
        {modelInfo && providerLabel(modelInfo) && (
          <span className={`vs-model-chip ${modelInfo.provider}`}>{providerLabel(modelInfo)}</span>
        )}
        <span className="vs-sub">媒体推广 · 引流转化 · 独立于图片创作流程</span>
      </div>

      {/* ① 视频专属选项 */}
      <div className="vs-options">
        <label className="vs-opt">
          <span>表现形式</span>
          <select value={options.mode} onChange={(e) => setOptions({ ...options, mode: e.target.value })}>
            {MODE_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
        </label>
        <label className="vs-opt">
          <span>配音</span>
          <select value={options.voiceover} onChange={(e) => setOptions({ ...options, voiceover: e.target.value })}>
            {VOICEOVER_OPTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
        </label>
        <label className="vs-opt">
          <span>时长</span>
          <select value={options.duration} onChange={(e) => setOptions({ ...options, duration: Number(e.target.value) })}>
            {DURATION_OPTS.map((d) => <option key={d} value={d}>{d} 秒</option>)}
          </select>
        </label>
        <label className="vs-opt">
          <span>比例</span>
          <select value={options.aspect} onChange={(e) => setOptions({ ...options, aspect: e.target.value })}>
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

      <div className="vs-body">
        {/* ② 对话式策划框 */}
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
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入提示词微调 / 创作构想 / 方案修改…"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  const s = input.trim()
                  if (s) { setInput(''); planStoryboard(s) }
                }
              }}
            />
            <div className="vs-chat-actions">
              <button onClick={() => { const s = input.trim(); if (!s) return; setInput(''); planStoryboard(s) }} disabled={planning}>
                {plan ? '发送并微调分镜' : '发送'}
              </button>
              <button className="vs-ghost" onClick={() => planStoryboard(`根据产品分析，帮我规划一个 ${options.duration} 秒、${options.aspect} 的推广视频分镜，重点突出核心卖点与转化路径`)} disabled={planning}>
                生成分镜草案
              </button>
            </div>
          </div>
        </div>

        {/* ③ 分镜预览 + 生成 + 结果 */}
        <div className="vs-preview">
          <div className="vs-preview-head">
            <span className="vs-preview-title">
              分镜方案{plan ? `（${plan.shots?.length || 0} 镜 · ${plan.duration_sec || options.duration}s · ${plan.aspect || options.aspect}）` : ''}
            </span>
            <div className="vs-preview-actions">
              {plan && <button className="vs-ghost" onClick={downloadJson}>下载分镜 JSON</button>}
              <button className="vs-primary" onClick={generate} disabled={generating || !plan}>
                {generating ? '生成中…' : '生成视频'}
              </button>
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

          {generating && <div className="vs-gen-status">视频生成中（直连已配置的视频模型，通常需要 1–3 分钟）…</div>}
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

          {error && <div className="vs-error">{error}</div>}
        </div>
      </div>
    </section>
  )
}
