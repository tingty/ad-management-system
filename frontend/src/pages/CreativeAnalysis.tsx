import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'

/**
 * 素材工作坊 · 素材创意模板库（V4.117 由「全球创意分析」改造而来，hash 保持 #/creativeanalysis）。
 *
 * V4.118：扩展为「导入 → 解构 → 沉淀」工作台：
 *  - 三态导入：本地上传（图片/视频）、图片 URL、网页链接自动截图；
 *  - 素材库列表：缩略图 / 来源 / 状态 / 解构按钮；
 *  - 解构结果：按维度字典分区展示布局/视觉/信息/效果/分类 + 模板建议 + 完整度；
 *  - 诚实标注：视觉模型不可用 (unavailable) 与截图内容不完整都显式提示，不冒充已解构。
 *
 * 保留原「文本快速分析」Tab（V4.50 能力）作为兜底，避免破坏既有用户习惯。
 * 分类归并（V4.119）/ 工作坊模板模式（V4.120）/ 视频解构（V4.121）后续版本接入。
 */

const STATUS_LABEL: Record<string, string> = {
  imported: '已导入', analyzing: '解构中', analyzed: '已解构',
  unavailable: '不可用', low_confidence: '低置信', failed: '失败', merged: '已归并',
}

type Asset = {
  id: number; title: string; source_type: string; file?: string | null; thumb?: string | null;
  source_url?: string | null; platform?: string | null; media_kind: string;
  width?: number | null; height?: number | null; duration_sec?: number | null;
  rights_note?: string | null; status: string; created_at?: string;
}

const SOURCE_LABEL: Record<string, string> = {
  upload: '本地上传', url: '图片 URL', screenshot: '网页截图', video: '视频',
}

export default function CreativeAnalysis() {
  const [tab, setTab] = useState<'library' | 'text'>('library')

  // ===== 素材库状态 =====
  const [assets, setAssets] = useState<Asset[]>([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [importMode, setImportMode] = useState<'upload' | 'url' | 'screenshot'>('upload')
  const [importTitle, setImportTitle] = useState('')
  const [importPlatform, setImportPlatform] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [rightsNote, setRightsNote] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const [importErr, setImportErr] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)

  // 解构结果：asset_id -> 分析记录
  const [analyses, setAnalyses] = useState<Record<number, any>>({})
  const [analyzingId, setAnalyzingId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // ===== 原文本快速分析状态（保留）=====
  const [urls, setUrls] = useState('')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [copied, setCopied] = useState('')

  async function loadAssets() {
    setAssetsLoading(true)
    try {
      const list = await api.tlAssets({ limit: 100 })
      setAssets(Array.isArray(list) ? list : [])
    } catch (e: any) {
      setImportErr(e?.message || '加载素材库失败')
    } finally {
      setAssetsLoading(false)
    }
  }

  useEffect(() => { if (tab === 'library') loadAssets() }, [tab])

  function resetImportMsg() { setImportMsg(''); setImportErr('') }

  // ---- 本地上传（图片 / 视频）----
  async function onUpload(file: File | undefined, kind: 'image' | 'video') {
    if (!file) return
    resetImportMsg(); setImporting(true)
    try {
      let up: any
      if (kind === 'video') up = await api.uploadVideoAsset(file)
      else up = await api.uploadAsset(file)
      const payload = {
        title: importTitle.trim() || file.name,
        source_type: kind === 'video' ? 'video' : 'upload',
        media_kind: kind,
        file: up.url, thumb: up.thumb || null,
        width: up.width || null, height: up.height || null,
        duration_sec: up.duration_sec || null,
        platform: importPlatform.trim() || null,
        rights_note: rightsNote.trim() || null,
      }
      await api.tlImport(payload)
      setImportMsg(`已导入：${file.name}${kind === 'video' ? '（仅归档 + 封面帧，解构在 V4.121）' : ''}`)
      setImportTitle('')
      await loadAssets()
    } catch (e: any) {
      setImportErr(e?.message || '上传失败')
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (videoInputRef.current) videoInputRef.current.value = ''
    }
  }

  // ---- 图片 URL 导入 ----
  async function importFromUrl() {
    const u = urlInput.trim()
    if (!/^https?:\/\//i.test(u)) { setImportErr('请输入 http(s) 图片链接'); return }
    resetImportMsg(); setImporting(true)
    try {
      const up = await api.fetchAssetUrl(u)
      await api.tlImport({
        title: importTitle.trim() || u.slice(0, 60), source_type: 'url', media_kind: 'image',
        file: up.url, source_url: u, platform: importPlatform.trim() || null,
        rights_note: rightsNote.trim() || null,
      })
      setImportMsg('已导入图片 URL'); setUrlInput(''); setImportTitle('')
      await loadAssets()
    } catch (e: any) {
      setImportErr(e?.message || '导入失败')
    } finally { setImporting(false) }
  }

  // ---- 网页截图导入 ----
  async function importFromScreenshot() {
    const u = urlInput.trim()
    if (!/^https?:\/\//i.test(u)) { setImportErr('请输入 http(s) 网页链接'); return }
    resetImportMsg(); setImporting(true)
    try {
      const shot = await api.screenshotAsset(u, 'viewport')
      if (shot.status !== 'ok' || !shot.url) {
        setImportErr(shot.reason || '截图不可用，未能导入')
        return
      }
      await api.tlImport({
        title: importTitle.trim() || u.slice(0, 60), source_type: 'screenshot', media_kind: 'image',
        file: shot.url, source_url: u, platform: importPlatform.trim() || null,
        width: shot.width || null, height: shot.height || null,
        rights_note: rightsNote.trim() || null,
        note: shot.integrity_note || '网页截图 · 内容完整性未保证',
      })
      setImportMsg('已截图并导入（内容完整性未保证，登录墙 / 动态渲染可能截不全）')
      setUrlInput(''); setImportTitle('')
      await loadAssets()
    } catch (e: any) {
      setImportErr(e?.message || '截图导入失败')
    } finally { setImporting(false) }
  }

  // ---- 触发解构 ----
  async function runAnalyze(asset: Asset) {
    if (asset.media_kind !== 'image') {
      setImportErr('视频解构将在 V4.121 提供，当前仅支持图片')
      return
    }
    setAnalyzingId(asset.id); setExpandedId(asset.id)
    setAnalyses(prev => ({ ...prev, [asset.id]: { status_text: '解构中…' } }))
    try {
      const a = await api.tlAnalyze(asset.id)
      setAnalyses(prev => ({ ...prev, [asset.id]: a }))
      await loadAssets()
    } catch (e: any) {
      setAnalyses(prev => ({ ...prev, [asset.id]: { status_text: '解构失败', reason: e?.message || '' } }))
    } finally { setAnalyzingId(null) }
  }

  async function deleteAsset(asset: Asset) {
    if (!window.confirm(`删除素材「${asset.title}」？原件会一并移除。`)) return
    try {
      await api.tlDeleteAsset(asset.id)
      setAnalyses(prev => { const n = { ...prev }; delete n[asset.id]; return n })
      await loadAssets()
    } catch (e: any) { setImportErr(e?.message || '删除失败') }
  }

  // ---- 原文本快速分析 ----
  async function run() {
    setError(''); setResult(null)
    const urlList = urls.split(/[\n,]/).map(s => s.trim()).filter(Boolean)
    if (!urlList.length && !text.trim()) { setError('请提供参考素材链接或文本'); return }
    setLoading(true)
    try {
      const r = await api.creativeAnalyze({ urls: urlList, text: text.trim(), title: title.trim() || undefined })
      setResult(r)
    } catch (e: any) { setError(e?.message || '分析失败') }
    finally { setLoading(false) }
  }

  function copy(t: string, tag: string) {
    navigator.clipboard?.writeText(t); setCopied(tag); setTimeout(() => setCopied(''), 1500)
  }

  return (
    <div className="page">
      {/* V4.117/4.118：标题与说明由 App.tsx 全局页头渲染，此处不重复。 */}
      <div className="cwb-tabbar" style={{ marginBottom: 16 }}>
        <button className={`cwb-tab ${tab === 'library' ? 'active' : ''}`} onClick={() => setTab('library')}>
          素材库 · 导入与解构
        </button>
        <button className={`cwb-tab ${tab === 'text' ? 'active' : ''}`} onClick={() => setTab('text')}>
          文本快速分析
        </button>
      </div>

      {tab === 'library' ? (
        <>
          {/* ① 导入区：三态 */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="tl-section-title">① 导入素材</div>
            <div className="tl-import-tabs">
              {([['upload', '本地上传'], ['url', '图片 URL'], ['screenshot', '网页截图']] as const).map(([k, label]) => (
                <button key={k} className={`cwb-tab ${importMode === k ? 'active' : ''}`}
                  onClick={() => { setImportMode(k); resetImportMsg() }}>{label}</button>
              ))}
            </div>
            <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
              <label className="field">
                <span className="label">素材标题（可选）</span>
                <input value={importTitle} onChange={e => setImportTitle(e.target.value)} placeholder="如：某家居品牌前后对比图" />
              </label>
              <label className="field">
                <span className="label">来源平台（可选）</span>
                <input value={importPlatform} onChange={e => setImportPlatform(e.target.value)} placeholder="Meta / Google / TikTok…" />
              </label>
            </div>

            {importMode === 'upload' && (
              <div className="tl-dropzone">
                <div className="muted" style={{ marginBottom: 10 }}>
                  上传推广图片（PNG / JPG / WEBP）进入解构；视频仅归档 + 封面帧，解构在 V4.121。
                </div>
                <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp"
                  onChange={e => onUpload(e.target.files?.[0], 'image')} disabled={importing} />
                <div style={{ marginTop: 10 }}>
                  <input ref={videoInputRef} type="file" accept="video/mp4,video/quicktime,video/webm"
                    onChange={e => onUpload(e.target.files?.[0], 'video')} disabled={importing} />
                  <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>↑ 视频（仅归档）</span>
                </div>
              </div>
            )}
            {importMode === 'url' && (
              <div className="tl-dropzone">
                <label className="field">
                  <span className="label">图片直链（http(s)，服务端下载并做 SSRF 安全校验）</span>
                  <input value={urlInput} onChange={e => setUrlInput(e.target.value)}
                    placeholder="https://example.com/ad-creative.jpg" />
                </label>
                <button className="btn primary" style={{ marginTop: 10 }} onClick={importFromUrl} disabled={importing}>
                  {importing ? '导入中…' : '下载并导入'}
                </button>
              </div>
            )}
            {importMode === 'screenshot' && (
              <div className="tl-dropzone">
                <label className="field">
                  <span className="label">网页链接（headless chromium 自动截图 + SSRF 防护）</span>
                  <input value={urlInput} onChange={e => setUrlInput(e.target.value)}
                    placeholder="https://example.com/landing-page" />
                </label>
                <button className="btn primary" style={{ marginTop: 10 }} onClick={importFromScreenshot} disabled={importing}>
                  {importing ? '截图中…' : '截图并导入'}
                </button>
                <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  登录墙 / 验证码 / 动态渲染页可能截不全，结果一律标注「内容完整性未保证」。
                </div>
              </div>
            )}
            <label className="field" style={{ marginTop: 12 }}>
              <span className="label">版权 / 授权标注（可选，仅供分析参考）</span>
              <input value={rightsNote} onChange={e => setRightsNote(e.target.value)} placeholder="如：竞品公开广告截图 / 自有素材" />
            </label>
            {importMsg && <div className="tl-ok">{importMsg}</div>}
            {importErr && <div className="err">{importErr}</div>}
          </div>

          {/* ② 素材库列表 */}
          <div className="card">
            <div className="tl-section-title">
              ② 素材库 <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>（{assets.length} 条，长期归档）</span>
              <button className="btn" style={{ float: 'right' }} onClick={loadAssets} disabled={assetsLoading}>
                {assetsLoading ? '刷新中…' : '刷新'}
              </button>
            </div>
            {assets.length === 0 && !assetsLoading && (
              <div className="muted">素材库为空。先在上方导入图片 / 视频，再点「解构」拆解创意框架。</div>
            )}
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
              {assets.map(a => {
                const analysis = analyses[a.id]
                const expanded = expandedId === a.id
                return (
                  <div key={a.id} className="card tl-asset-card">
                    <div className="tl-asset-thumb">
                      {(a.thumb || a.file) ? (
                        <img src={api.fileUrl(a.thumb || a.file || '')} alt={a.title} />
                      ) : <span className="muted">无预览</span>}
                    </div>
                    <div style={{ fontWeight: 600, marginTop: 8, fontSize: 14 }}>{a.title || '未命名素材'}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {SOURCE_LABEL[a.source_type] || a.source_type} · {a.media_kind === 'video' ? '视频' : '图片'}
                      {a.platform ? ` · ${a.platform}` : ''}
                      {a.width && a.height ? ` · ${a.width}×${a.height}` : ''}
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <span className={`tl-status status-${a.status}`}>{STATUS_LABEL[a.status] || a.status}</span>
                      {a.rights_note && <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>{a.rights_note.slice(0, 30)}</span>}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      {a.media_kind === 'image' && (
                        <button className="btn primary" onClick={() => runAnalyze(a)} disabled={analyzingId === a.id}>
                          {analyzingId === a.id ? '解构中…' : (analysis ? '重新解构' : '解构')}
                        </button>
                      )}
                      <button className="btn" onClick={() => setExpandedId(expanded ? null : a.id)}>
                        {expanded ? '收起' : (analysis ? '看解构' : '详情')}
                      </button>
                      <button className="btn" onClick={() => deleteAsset(a)}>删除</button>
                    </div>

                    {expanded && analysis && (
                      <div className="tl-analysis">
                        {analysis.status_text && <div className="muted">{analysis.status_text}</div>}
                        {analysis.status === 'unavailable' && (
                          <div className="tl-warn">
                            视觉模型不可用或未产出有效维度，未臆造解构结果。原因：{analysis.reason || '—'}
                          </div>
                        )}
                        {analysis.reason && analysis.status !== 'unavailable' && (
                          <div className="muted" style={{ fontSize: 12 }}>{analysis.reason}</div>
                        )}
                        {analysis.completeness != null && (
                          <div className="tl-metrics">
                            框架完整度 <b>{(analysis.completeness * 100).toFixed(0)}%</b>
                            {analysis.confidence != null && <> · 置信度 <b>{(analysis.confidence * 100).toFixed(0)}%</b></>}
                            {analysis.framework_version && <span className="muted"> · {analysis.framework_version}</span>}
                          </div>
                        )}
                        <DimBlock title="布局" data={analysis.dims_json?.layout} />
                        <DimBlock title="视觉" data={analysis.dims_json?.visual} />
                        <DimBlock title="信息与文案" data={analysis.dims_json?.info} />
                        <DimBlock title="效果推断（非投放数据）" data={analysis.dims_json?.effect} />
                        {analysis.category_json && (
                          <div className="tl-dim">
                            <div className="tl-dim-title">分类</div>
                            <div className="muted" style={{ fontSize: 13 }}>
                              主分类：<b>{analysis.category_json.primary || '—'}</b>
                              {(analysis.category_json.purposes || []).length > 0 && <> · 目的：{analysis.category_json.purposes.join('、')}</>}
                              {(analysis.category_json.hooks || []).length > 0 && <> · 钩子：{analysis.category_json.hooks.join('、')}</>}
                            </div>
                          </div>
                        )}
                        {analysis.template_guess?.name && (
                          <div className="tl-dim">
                            <div className="tl-dim-title">模板归属建议</div>
                            <div className="muted" style={{ fontSize: 13 }}>
                              {analysis.template_guess.name} · 置信度 {((analysis.template_guess.confidence || 0) * 100).toFixed(0)}%
                            </div>
                            {(analysis.template_guess.diff || []).length > 0 && (
                              <ul style={{ fontSize: 12, margin: '6px 0 0', paddingLeft: 18 }} className="muted">
                                {analysis.template_guess.diff.map((d: string, i: number) => <li key={i}>{d}</li>)}
                              </ul>
                            )}
                          </div>
                        )}
                        {analysis.model_info?.model && (
                          <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
                            解构模型：{analysis.model_info.provider || '—'} / {analysis.model_info.model}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </>
      ) : (
        /* ===== 原文本快速分析（保留 V4.50 能力）===== */
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="grid" style={{ gridTemplateColumns: '1fr', gap: 12 }}>
              <label className="field">
                <span className="label">分析标题（可选）</span>
                <input value={title} onChange={e => setTitle(e.target.value)} placeholder="如：电商 App 信息流广告" />
              </label>
              <label className="field">
                <span className="label">参考素材链接（多个用换行或逗号分隔）</span>
                <textarea value={urls} onChange={e => setUrls(e.target.value)} rows={3}
                  placeholder="https://...&#10;https://..." />
              </label>
              <label className="field">
                <span className="label">或直接粘贴参考文案 / 素材描述</span>
                <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
                  placeholder="描述你看到的高转化广告创意：构图、色调、文案语气、卖点表达…" />
              </label>
              <div>
                <button className="btn primary" onClick={run} disabled={loading}>
                  {loading ? '分析中…' : '开始分析'}
                </button>
                {result && (
                  <button className="btn" style={{ marginLeft: 8 }} onClick={() => copy(
                    (result.categories || []).map((c: any) => `【${c.name}】\n${c.image_prompt}`).join('\n\n'), 'all')}>
                    {copied === 'all' ? '已复制全部' : '复制全部图片提示词'}
                  </button>
                )}
              </div>
              {error && <div className="err">{error}</div>}
            </div>
          </div>
          {result && (
            <div className="card">
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{result.title}</div>
              {result.summary && <p className="muted" style={{ marginTop: 0 }}>{result.summary}</p>}
              <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
                实际调用模型：{result.model_info?.provider || '—'} / {result.model_info?.model || '—'}
                {result.model_info?.fallback ? '（Mock 兜底，未配置模型）' : ''}
              </div>
              {(result.categories || []).length === 0 && (
                <div className="muted">未归出具体类型（可能参考信息不足或未配置大模型）。配置「分析」模型后重试可获得结构化结果。</div>
              )}
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
                {(result.categories || []).map((c: any, i: number) => (
                  <div key={i} className="card" style={{ border: '1px solid var(--line)', boxShadow: 'none' }}>
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <div className="muted" style={{ fontSize: 13, margin: '6px 0' }}>{c.description}</div>
                    {c.traits?.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        {c.traits.map((t: string, j: number) => <span key={j} className="chip">{t}</span>)}
                      </div>
                    )}
                    <div style={{ fontSize: 13, marginBottom: 4 }}><b>图片提示词</b></div>
                    <pre className="prompt-box">{c.image_prompt || '—'}</pre>
                    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                      <button className="btn" onClick={() => copy(c.image_prompt, `img-${i}`)}>
                        {copied === `img-${i}` ? '已复制' : '复制图片提示词'}
                      </button>
                      {c.video_prompt && (
                        <button className="btn" onClick={() => copy(c.video_prompt, `vid-${i}`)}>
                          {copied === `vid-${i}` ? '已复制' : '复制视频提示词'}
                        </button>
                      )}
                    </div>
                    {c.video_prompt && (
                      <>
                        <div style={{ fontSize: 13, margin: '10px 0 4px' }}><b>视频提示词</b></div>
                        <pre className="prompt-box">{c.video_prompt}</pre>
                      </>
                    )}
                  </div>
                ))}
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                提示：复制提示词后，可在「创意提示词」中保存为可复用模板。
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** 一个维度分区：把 {key:{value,confidence,caveat}} 渲染成可读列表。 */
function DimBlock({ title, data }: { title: string; data?: Record<string, any> }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data).filter(([, v]) => v && typeof v === 'object')
  if (!entries.length) return null
  return (
    <div className="tl-dim">
      <div className="tl-dim-title">{title}</div>
      {entries.map(([k, cell]: [string, any]) => {
        const val = cell.value
        const text = Array.isArray(val) ? val.join('、')
          : (val && typeof val === 'object' ? Object.entries(val).map(([a, b]) => `${a}:${b}`).join('，')
          : String(val ?? ''))
        return (
          <div key={k} className="tl-dim-row">
            <span className="tl-dim-key">{DIM_LABEL[k] || k}</span>
            <span className="tl-dim-val">{text || <span className="muted">—</span>}</span>
            {typeof cell.confidence === 'number' && (
              <span className="tl-dim-conf">{(cell.confidence * 100).toFixed(0)}%</span>
            )}
            {cell.caveat && <span className="tl-dim-caveat">（{cell.caveat}）</span>}
          </div>
        )
      })}
    </div>
  )
}

const DIM_LABEL: Record<string, string> = {
  composition: '构图', focal_path: '动线', subject_position: '主体位置', negative_space: '留白',
  palette: '配色', lighting: '光线', texture: '质感',
  headline_role: '标题角色', benefits: '卖点', cta: 'CTA', evidence_kind: '证据', text_on_image: '画面文字',
  hook_type: '钩子', emotion: '情绪', intent: '意图',
}
