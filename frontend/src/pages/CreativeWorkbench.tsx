import React, { useEffect, useState } from 'react'
import { api } from '../api'

type ChatMsg = { role: 'system' | 'user'; text: string; meta?: any }

const DEFAULT_PLATFORMS = ['Facebook', 'Google Search', 'Unity', 'Adsterra', '移动应用广告位', '激励视频']

/**
 * 创意工作台 · 对话式自动创作
 * 用户输入落地页 / 应用链接或产品信息 → 选择推广媒体（图片/视频）→ 大模型分析产品并总结框架
 * → 在对话框中确认媒体与重要决策 → 自动调用大模型生成推广图片 → 放大查阅与下载。
 * 视频节点本期预留（下期待生成），不阻断主流程。
 */
export default function CreativeWorkbench() {
  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS)
  const [selected, setSelected] = useState<string[]>(['Facebook'])
  const [genImage, setGenImage] = useState(true)
  const [genVideo, setGenVideo] = useState(false)

  const [input, setInput] = useState('')
  const [chat, setChat] = useState<ChatMsg[]>([])
  const [step, setStep] = useState<'input' | 'confirm' | 'generating' | 'done'>('input')
  const [analysis, setAnalysis] = useState<any>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const [progress, setProgress] = useState('')
  const [assets, setAssets] = useState<any[]>([])
  const [historyId, setHistoryId] = useState<number | null>(null)

  useEffect(() => {
    api.mediaPlatforms().then((d: any) => {
      const names = (d?.platforms || []).map((p: any) => p.platform).filter(Boolean)
      if (names.length) {
        setPlatforms(names)
        setSelected(names.slice(0, 1))
      }
    }).catch(() => {})
  }, [])

  function togglePlatform(p: string) {
    setSelected(s => s.includes(p) ? s.filter(x => x !== p) : [...s, p])
  }

  async function analyze() {
    setError('')
    const url = input.trim()
    if (!url && !input.trim()) { setError('请输入落地页 / 应用链接或产品信息'); return }
    setRunning(true)
    setChat([{ role: 'user', text: input.trim() || '(已粘贴产品信息)' }])
    try {
      const res: any = await api.landingAnalysis({ url: url.startsWith('http') ? url : undefined,
        text: url.startsWith('http') ? undefined : input })
      setAnalysis(res)
      setStep('confirm')
      const ch = (res.channels || []).map((c: any) => `${c.platform}（${c.reason}）`).join('；') || '未给出明确推荐'
      setChat(c => [...c, {
        role: 'system',
        text: `已完成产品分析。行业：${res.industry || '—'}；类型：${res.type || '—'}；对象：${res.audience || '—'}；` +
              `优势：${(res.advantages || []).join('、') || '—'}。\n推荐媒体：${ch}。`,
        meta: res,
      }, {
        role: 'system',
        text: '请在右侧确认要投发的媒体平台，并选择是否生成图片 / 视频，然后点击「确认并开始创作」。',
      }])
    } catch (e: any) {
      setError(e?.message || '分析失败')
    } finally {
      setRunning(false)
    }
  }

  async function generate() {
    if (!analysis) return
    setError(''); setStep('generating'); setAssets([]); setProgress('正在创建历史会话…')
    let hid: number | null = null
    try {
      const h: any = await api.createCreationHistory({ analysis, platform: selected[0], lang: 'en' }).catch(() => null)
      hid = h?.id ?? null
      setHistoryId(hid)
    } catch { /* 历史可选，失败不阻断 */ }

    const targets = selected.filter(Boolean)
    if (genImage && targets.length) {
      try {
        const rules: any = await api.mediaRules().catch(() => ({}))
        const allowed: Record<string, string[]> = rules?.platforms || {}
        for (const plat of targets) {
          setProgress(`正在为 ${plat} 生成推广图片…`)
          const sizes = (allowed[plat] || ['1080x1080']).slice(0, 2)
          const slots = sizes.map(size => ({ size, placement: plat }))
          const payload = {
            images_request: {
              analysis, platform: plat, lang: 'en',
              copy_fields: {}, copy_variants: [], style_opts: {},
              slots, spec_version: rules?.spec_version || '',
              total_pixels: sizes.reduce((n: number, s: string) => {
                const [w, h] = s.split('x').map(Number); return n + (w * h || 0)
              }, 0),
            },
            archive: hid ? { history_id: hid, platform: plat, lang: 'en' } : undefined,
            idempotency_key: `cw_${plat}_${Date.now()}`,
          }
          const job: any = await api.createGenerationJob(payload)
          const jobId = job?.job_id
          // 轮询任务
          let st = job
          for (let i = 0; i < 40; i++) {
            await new Promise(r => setTimeout(r, 1500))
            st = await api.generationJob(jobId)
            if (['succeeded', 'partial_success', 'failed', 'canceled'].includes(st?.status)) break
            setProgress(`正在为 ${plat} 生成图片…（${st?.status || ''} ${st?.progress ?? 0}%）`)
          }
          const got: any = await api.creativeAssets({ job_id: jobId }).catch(() => ({ items: [] }))
          setAssets(a => [...a, ...(got?.items || [])])
        }
      } catch (e: any) {
        setError((e?.message || '图片生成失败') + '（可重试或调整媒体后继续）')
      }
    }
    setProgress(genVideo ? '视频生成将在下期待生成，本期已生成图片。' : '创作完成。')
    setStep('done')
    setChat(c => [...c, { role: 'system', text: '创作完成，可在右侧放大查阅并下载素材。视频节点为下期待生成。' }])
  }

  function download(file: string) {
    window.open(api.mediaFileDownloadUrl(file), '_blank')
  }
  function downloadZip() {
    if (historyId) window.open(api.historyItemZipUrl(historyId), '_blank')
    else if (assets.length) window.open(api.mediaZipUrl(assets.map(a => a.file)), '_blank')
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>创意工作台</h2>
        <p className="muted">面向落地页 / 官网 / 应用的自动化创意素材创作。输入产品链接或信息，选择媒体平台，
          剩余由大模型自动分析与创作。</p>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(320px, 1fr) minmax(360px, 1.3fr)', gap: 16, alignItems: 'start' }}>
        {/* 左：对话 / 输入区 */}
        <div className="card">
          {step === 'input' && (
            <>
              <label className="field">
                <span className="label">产品链接 / 应用链接 / 产品信息</span>
                <textarea value={input} onChange={e => setInput(e.target.value)} rows={4}
                  placeholder="粘贴落地页网址（https://…）或直接描述产品信息" />
              </label>
              <div className="field">
                <span className="label">推广媒体平台（可多选）</span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
                  {platforms.map(p => (
                    <button key={p} className={`chip ${selected.includes(p) ? 'on' : ''}`}
                      onClick={() => togglePlatform(p)}>{p}</button>
                  ))}
                </div>
              </div>
              <div className="field" style={{ display: 'flex', gap: 16 }}>
                <label><input type="checkbox" checked={genImage} onChange={e => setGenImage(e.target.checked)} /> 生成图片</label>
                <label><input type="checkbox" checked={genVideo} onChange={e => setGenVideo(e.target.checked)} /> 生成视频</label>
              </div>
              <button className="btn primary" onClick={analyze} disabled={running}>
                {running ? '分析中…' : '开始创作'}
              </button>
            </>
          )}

          {step !== 'input' && (
            <div className="chat">
              {chat.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  <div className="who">{m.role === 'user' ? '你' : '创意助手'}</div>
                  <div className="txt" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
                </div>
              ))}
              {step === 'confirm' && (
                <div className="bubble system">
                  <div className="who">创意助手</div>
                  <div className="txt">
                    <div style={{ marginBottom: 8 }}>确认投发媒体：</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {platforms.map(p => (
                        <button key={p} className={`chip ${selected.includes(p) ? 'on' : ''}`}
                          onClick={() => togglePlatform(p)}>{p}</button>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 16, margin: '10px 0' }}>
                      <label><input type="checkbox" checked={genImage} onChange={e => setGenImage(e.target.checked)} /> 生成图片</label>
                      <label><input type="checkbox" checked={genVideo} onChange={e => setGenVideo(e.target.checked)} /> 生成视频</label>
                    </div>
                    <button className="btn primary" onClick={generate}>确认并开始创作</button>
                  </div>
                </div>
              )}
              {step === 'generating' && <div className="bubble system"><div className="who">创意助手</div><div className="txt">{progress}</div></div>}
              {step === 'done' && (
                <div className="bubble system">
                  <div className="who">创意助手</div>
                  <div className="txt">{progress}
                    <div style={{ marginTop: 8 }}>
                      <button className="btn" onClick={() => { setStep('input'); setChat([]); setAnalysis(null); setAssets([]); setProgress('') }}>新的创作</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
          {error && <div className="err" style={{ marginTop: 10 }}>{error}</div>}
        </div>

        {/* 右：创作路线 / 成果 */}
        <div className="card">
          <div style={{ fontWeight: 600, marginBottom: 8 }}>产品框架</div>
          {analysis ? (
            <div className="kv">
              <div><span>行业</span><b>{analysis.industry || '—'}</b></div>
              <div><span>类型</span><b>{analysis.type || '—'}</b></div>
              <div><span>对象</span><b>{analysis.audience || '—'}</b></div>
              <div><span>优势</span><b>{(analysis.advantages || []).join('、') || '—'}</b></div>
            </div>
          ) : <div className="muted">输入产品信息并分析后展示产品框架。</div>}

          <div style={{ fontWeight: 600, margin: '16px 0 8px' }}>创作成果</div>
          {assets.length === 0 && step !== 'generating' && (
            <div className="muted">尚未生成素材。</div>
          )}
          {step === 'generating' && <div className="muted">{progress}</div>}
          {assets.length > 0 && (
            <>
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
                {assets.map((a, i) => (
                  <div key={i} className="asset">
                    <img src={api.fileUrl(a.file)} alt={a.placement || 'creative'} />
                    <div className="asset-bar">
                      <button className="btn tiny" onClick={() => download(a.file)}>下载</button>
                    </div>
                  </div>
                ))}
              </div>
              <button className="btn" style={{ marginTop: 10 }} onClick={downloadZip}>打包下载全部</button>
            </>
          )}

          {genVideo && (
            <div className="reserved" style={{ marginTop: 14 }}>
              🎬 视频生成（下期待生成）：本期聚焦图片，视频节点已预留，将在下期接入文生视频模型后打通。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
