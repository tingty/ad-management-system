/**
 * V4.145 / V4.146 · 模仿创作视频 —— 独立一级功能模块。
 *
 * V4.145：页面壳 + 后端任务列表只读展示。
 * V4.146：新建任务双入口（直链代下载 / 本地上传复用）+ 原片 <video> 预览 +
 *         元数据展示 + 权利声明确认 + 建任务。本版不调用大模型、不产生费用；
 *         分析脚本 / 创作脚本 / 出片由 V4.147–V4.149 交付。
 *
 * 只新增本页与 API 封装，不改动现有 4 个一级模块的布局与功能。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, imitateVideoApi, ImitateTask, ImitateSource } from '../api'

type Msg = { kind: 'ok' | 'err'; text: string }
type Tab = 'url' | 'upload'

const STAGE_LABEL: Record<string, string> = {
  source_acquiring: '获取源视频', analyzing: '结构分析', planning: '创作策划',
  awaiting_confirm: '待确认', submitting: '提交中', provider_pending: '模型生成中',
  downloading: '下载校验中', validating: '复核中', completed: '已完成',
}

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '进行中', succeeded: '已完成',
  needs_attention: '需关注', failed: '失败', cancelled: '已取消',
}

function sourceLabel(s?: string): string {
  if (!s) return '—'
  if (s === 'url') return '链接'
  if (s === 'upload') return '上传'
  return s
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
  const [targetPlatform, setTargetPlatform] = useState('')
  const [structureFidelity, setStructureFidelity] = useState('medium')
  const [language, setLanguage] = useState('')
  const [creating, setCreating] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

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
          target_platform: targetPlatform.trim(),
          structure_fidelity: structureFidelity,
          language: language.trim(),
        },
      })
      setMsg({ kind: 'ok', text: `任务已创建：${r.job_id}（阶段：获取源视频，本版不产生费用）` })
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
    <div className="card">
      <div className="ad-panel-head">
        <div>
          <h2 style={{ margin: 0 }}>模仿创作视频</h2>
          <div className="muted" style={{ marginTop: 6 }}>
            以专业投放视频为学习对象，解构其创作方案后重新演绎出符合投放规格的新视频。
          </div>
        </div>
      </div>

      <p className="note" style={{ borderLeft: '3px solid var(--accent, #2b6cb0)', paddingLeft: 10 }}>
        V4.146：可提交参考视频（直链或上传）并查看原片与元数据，任务在后台持久执行、切页不中断。
        分析脚本、创作脚本与出片将在后续版本交付；本版不产生任何模型费用。
      </p>

      {msg && <div className={msg.kind === 'err' ? 'err' : 'ok'} style={{ margin: '10px 0' }}>{msg.text}</div>}

      {/* ---- 新建任务：双入口 ---- */}
      <div className="ad-panel-head" style={{ marginTop: 16 }}>
        <h3 style={{ margin: 0 }}>新建任务 · 源视频</h3>
        <div>
          <button className="btn" style={{ marginRight: 6, background: tab === 'url' ? 'var(--accent, #2b6cb0)' : undefined, color: tab === 'url' ? '#fff' : undefined }} onClick={() => switchTab('url')}>视频链接</button>
          <button className="btn" style={{ background: tab === 'upload' ? 'var(--accent, #2b6cb0)' : undefined, color: tab === 'upload' ? '#fff' : undefined }} onClick={() => switchTab('upload')}>本地上传</button>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
        {tab === 'url' ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input style={{ flex: 1, minWidth: 260 }} placeholder="粘贴视频直链（http/https，≤200MB）"
              value={url} onChange={e => setUrl(e.target.value)} />
            <button className="btn primary" onClick={() => void acquireUrl()} disabled={acquiring}>
              {acquiring ? '获取中…' : '获取源视频'}
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
              ref={fileRef} onChange={e => { const f = e.target.files?.[0]; if (f) void uploadFile(f) }} />
            <span className="muted">支持 MP4 / MOV / WEBM，≤200MB</span>
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <label style={{ flex: 1, minWidth: 180 }}>任务名称
            <input style={{ display: 'block', width: '100%', marginTop: 4 }} value={taskName}
              onChange={e => setTaskName(e.target.value)} placeholder="可选，默认取源视频名" />
          </label>
          <label style={{ flex: 1, minWidth: 160 }}>目标投放平台
            <input style={{ display: 'block', width: '100%', marginTop: 4 }} value={targetPlatform}
              onChange={e => setTargetPlatform(e.target.value)} placeholder="如 TikTok / Meta（可选）" />
          </label>
          <label style={{ minWidth: 140 }}>结构保持度
            <select style={{ display: 'block', width: '100%', marginTop: 4 }} value={structureFidelity}
              onChange={e => setStructureFidelity(e.target.value)}>
              <option value="high">高（逐镜保留）</option>
              <option value="medium">中（保留钩子/CTA）</option>
              <option value="low">低（仅叙事骨架）</option>
            </select>
          </label>
          <label style={{ minWidth: 130 }}>目标语言
            <select style={{ display: 'block', width: '100%', marginTop: 4 }} value={language}
              onChange={e => setLanguage(e.target.value)}>
              <option value="">跟随原片</option>
              <option value="en">英文</option>
              <option value="zh">中文</option>
            </select>
          </label>
        </div>

        {/* ---- 原片预览 + 元数据 ---- */}
        {source && (
          <div style={{ border: '1px solid var(--border, #ddd)', borderRadius: 6, padding: 12 }}>
            <div className="muted" style={{ marginBottom: 8 }}>
              源视频：{source.name || '—'} · {source.source === 'url' ? '链接获取' : '本地上传'}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <video
                src={source.source === 'url'
                  ? api.fileUrl(source.file || '')
                  : api.fileUrl(source.file || '')}
                controls playsInline style={{ width: 320, maxWidth: '100%', background: '#000' }} />
              <div style={{ minWidth: 200 }}>
                <table className="ad-table">
                  <tbody>
                    <tr><td>分辨率</td><td>{source.width && source.height ? `${source.width}×${source.height}` : (source.source === 'upload' ? '建任务时补全' : '未知')}</td></tr>
                    <tr><td>画幅比</td><td>{source.aspect_ratio || '未知'}</td></tr>
                    <tr><td>时长</td><td>{source.duration_sec ? `${source.duration_sec.toFixed(1)} 秒` : '未知'}</td></tr>
                    <tr><td>帧率</td><td>{source.fps || '未知'}</td></tr>
                    <tr><td>音轨</td><td>{source.has_audio ? '有' : '无'}</td></tr>
                    <tr><td>大小</td><td>{source.bytes ? `${(source.bytes / 1024 / 1024).toFixed(1)} MB` : '—'}</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
            <label style={{ display: 'block', marginTop: 12 }}>
              <input type="checkbox" checked={rightsAck} onChange={e => setRightsAck(e.target.checked)} />
              {' '}我已获得该视频的使用授权，仅用于学习其创作结构并重新创作（权利声明将留痕）
            </label>
            <button className="btn primary" style={{ marginTop: 10 }} onClick={() => void createJob()} disabled={creating}>
              {creating ? '创建中…' : '确认源视频并创建任务'}
            </button>
          </div>
        )}
      </div>

      {/* ---- 任务列表 ---- */}
      <div className="ad-panel-head" style={{ marginTop: 20 }}>
        <h3 style={{ margin: 0 }}>任务列表</h3>
        <button className="btn" onClick={() => void load()} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {loading && <div className="muted">加载中…</div>}
      {!loading && items.length === 0 && (
        <div className="muted" style={{ padding: '24px 0' }}>暂无任务，请先在上方提交参考视频。</div>
      )}
      {!loading && items.length > 0 && (
        <table className="ad-table">
          <thead>
            <tr>
              <th>任务</th><th>状态</th><th>阶段</th><th>来源</th>
              <th>画幅/时长</th><th>原片</th><th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {items.map(t => (
              <tr key={t.job_id}>
                <td>{t.name || t.job_id}</td>
                <td>{STATUS_LABEL[t.status] || t.status}</td>
                <td>{t.stage ? (STAGE_LABEL[t.stage] || t.stage) : '—'}</td>
                <td>{sourceLabel(t.source)}</td>
                <td>{[t.aspect_ratio, t.duration_sec ? `${t.duration_sec.toFixed(1)}s` : ''].filter(Boolean).join(' / ') || '—'}</td>
                <td>
                  {t.source_file && (
                    <a href={imitateVideoApi.sourceUrl(t.job_id)} target="_blank" rel="noreferrer">预览</a>
                  )}
                </td>
                <td>{t.created_at || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
