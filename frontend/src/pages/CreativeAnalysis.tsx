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
 * V4.119：新增「分类归并 · 模板沉淀」Tab——12 类主分类 + 目的 + 钩子 + 信息结构相似度
 * 给出候选组；人工确认归并后按框架完整度选 golden 并沉淀图片骨架模板（可覆盖 / 可撤销）。
 *
 * V4.122：移除「投放授权声明」子模块与强制闸门，导入 / 解构 / 归并 / 模板沉淀
 * 不再要求授权声明；模板的按模板创作校验只保留模板自身基础可用性。
 *
 * V4.123：已解构图片在「素材库」与「已沉淀模板」两处均可通过缩略图 / 查看原图
 * 打开原图预览；归并 Tab 主动加载素材列表，确保直接进入该 Tab 也能看到 golden 原图。
 *
 * V4.121：视频素材也可解构——抽帧后按真实视觉通道聚合分镜 / 钩子 / 字幕（真实 OCR）
 * / 节奏，复用同一套 12 类分类与归并键；结果区新增视频维度分区，不可用时如实标注。
 *
 * 保留原「文本快速分析」Tab（V4.50 能力）作为兜底，避免破坏既有用户习惯。
 */

const STATUS_LABEL: Record<string, string> = {
  imported: '已导入', analyzing: '解构中', analyzed: '已解构',
  unavailable: '不可用', low_confidence: '低置信', failed: '失败', merged: '已归并',
}

type Asset = {
  id: number; title: string; source_type: string; file?: string | null; thumb?: string | null;
  source_url?: string | null; platform?: string | null; media_kind: string;
  width?: number | null; height?: number | null; duration_sec?: number | null;
  status: string; merged_template_id?: number | null; created_at?: string;
}

const SOURCE_LABEL: Record<string, string> = {
  upload: '本地上传', url: '图片 URL', screenshot: '网页截图', video: '视频',
}

export default function CreativeAnalysis() {
  const [tab, setTab] = useState<'library' | 'text' | 'merge'>('library')

  // ===== 素材库状态 =====
  const [assets, setAssets] = useState<Asset[]>([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [importMode, setImportMode] = useState<'upload' | 'url' | 'screenshot'>('upload')
  const [importTitle, setImportTitle] = useState('')
  const [importPlatform, setImportPlatform] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const [importErr, setImportErr] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)

  // 解构结果：asset_id -> 分析记录
  const [analyses, setAnalyses] = useState<Record<number, any>>({})
  const [analyzingId, setAnalyzingId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // ===== V4.119 分类归并 / 模板沉淀状态 =====
  const [taxonomy, setTaxonomy] = useState<any>(null)
  const [templates, setTemplates] = useState<any[]>([])
  const [candidates, setCandidates] = useState<any>(null)
  const [candLoading, setCandLoading] = useState(false)
  const [selectedMembers, setSelectedMembers] = useState<Record<string, number[]>>({})
  const [goldenPicks, setGoldenPicks] = useState<Record<string, number>>({})
  const [templateNames, setTemplateNames] = useState<Record<string, string>>({})
  const [mergingKey, setMergingKey] = useState('')
  const [workingTemplateId, setWorkingTemplateId] = useState<number | null>(null)
  const [catEdits, setCatEdits] = useState<Record<number, any>>({})
  const [mergeMsg, setMergeMsg] = useState('')
  const [mergeErr, setMergeErr] = useState('')

  // V4.123：原图预览（素材库卡片 / 已沉淀模板 golden 共用）
  const [previewAsset, setPreviewAsset] = useState<Asset | null>(null)

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
      const list = await api.tlAssets({ limit: 500 })
      setAssets(Array.isArray(list) ? list : [])
    } catch (e: any) {
      setImportErr(e?.message || '加载素材库失败')
    } finally {
      setAssetsLoading(false)
    }
  }

  // V4.119：最新解构 / 模板 / 分类字典（一个素材多次解构只取最新一条）。
  async function loadLibraryMeta() {
    try {
      const [list, tpls, tax] = await Promise.all([
        api.tlAnalyses({ limit: 300 }), api.tlTemplates({ limit: 300 }), api.tlTaxonomy(),
      ])
      const latest: Record<number, any> = {}
      for (const a of (Array.isArray(list) ? list : [])) {
        if (a.asset_id && !latest[a.asset_id]) latest[a.asset_id] = a
      }
      setAnalyses(latest)
      setTemplates(Array.isArray(tpls) ? tpls : [])
      setTaxonomy(tax)
    } catch (e: any) {
      setMergeErr(e?.message || '加载分类字典 / 模板失败')
    }
  }

  async function loadCandidates() {
    setCandLoading(true)
    try {
      const r = await api.tlMergeCandidates()
      setCandidates(r)
      setSelectedMembers({}); setGoldenPicks({}); setTemplateNames({})
    } catch (e: any) {
      setMergeErr(e?.message || '加载归并候选失败')
    } finally { setCandLoading(false) }
  }

  useEffect(() => {
    // V4.123：归并 Tab 也要加载素材列表，否则直接进来时模板卡片找不到 golden 原图。
    if (tab === 'library') { loadAssets(); loadLibraryMeta() }
    if (tab === 'merge') { loadAssets(); loadCandidates(); loadLibraryMeta() }
  }, [tab])

  useEffect(() => {
    if (!previewAsset) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPreviewAsset(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [previewAsset])

  function resetImportMsg() { setImportMsg(''); setImportErr('') }

  // ---- 本地上传（图片 / 视频）----
  async function onUpload(file: File | undefined, kind: 'image' | 'video') {
    if (!file) return
    resetImportMsg()
    setImporting(true)
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
      }
      await api.tlImport(payload)
      setImportMsg(`已导入：${file.name}${kind === 'video' ? '（已归档 + 封面帧，可点击「解构」）' : ''}`)
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
    resetImportMsg()
    setImporting(true)
    try {
      const up = await api.fetchAssetUrl(u)
      await api.tlImport({
        title: importTitle.trim() || u.slice(0, 60), source_type: 'url', media_kind: 'image',
        file: up.url, source_url: u, platform: importPlatform.trim() || null,
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
    resetImportMsg()
    setImporting(true)
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
    setAnalyzingId(asset.id); setExpandedId(asset.id)
    setAnalyses(prev => ({ ...prev, [asset.id]: { status_text: '解构中…' } }))
    try {
      const a = await api.tlAnalyze(asset.id)
      setAnalyses(prev => ({ ...prev, [asset.id]: a }))
      await Promise.all([loadAssets(), loadLibraryMeta()])
    } catch (e: any) {
      setAnalyses(prev => ({ ...prev, [asset.id]: { status_text: '解构失败', reason: e?.message || '' } }))
    } finally { setAnalyzingId(null) }
  }

  async function deleteAsset(asset: Asset) {
    if (!window.confirm(`删除素材「${asset.title}」？原件会一并移除。`)) return
    try {
      await api.tlDeleteAsset(asset.id)
      setAnalyses(prev => { const n = { ...prev }; delete n[asset.id]; return n })
      await Promise.all([loadAssets(), loadLibraryMeta()])
    } catch (e: any) { setImportErr(e?.message || '删除失败') }
  }

  // ---- V4.119 人工确认分类 ----
  async function saveCategory(analysis: any) {
    const edit = catEdits[analysis.id]
    if (!edit?.primary || !edit.purposes?.length || !edit.hooks?.length) {
      setMergeErr('请选择主分类、至少一个推广目的与一个钩子类型')
      return
    }
    setWorkingTemplateId(analysis.id * -1)
    setMergeErr(''); setMergeMsg('')
    try {
      await api.tlConfirmCategory(analysis.id, edit)
      setMergeMsg('分类已确认，归并时以人工值为准（AI 原始建议保留可追溯）')
      await loadLibraryMeta()
    } catch (e: any) { setMergeErr(e?.message || '分类确认失败') }
    finally { setWorkingTemplateId(null) }
  }

  function membersOf(g: any): number[] {
    return selectedMembers[g.key] || g.members.map((m: any) => m.asset_id)
  }
  function toggleMember(g: any, id: number) {
    const current = membersOf(g)
    const next = current.includes(id) ? current.filter(x => x !== id) : [...current, id]
    setSelectedMembers(prev => ({ ...prev, [g.key]: next }))
  }
  async function confirmMerge(g: any) {
    const ids = membersOf(g)
    if (!ids.length) { setMergeErr('请至少勾选一条素材'); return }
    const golden = goldenPicks[g.key] || g.golden_asset_id
    if (!ids.includes(golden)) { setMergeErr('golden 必须在已勾选素材中'); return }
    setMergingKey(g.key); setMergeErr(''); setMergeMsg('')
    try {
      const t = await api.tlMergeConfirm({
        asset_ids: ids, golden_asset_id: golden,
        name: (templateNames[g.key] || '').trim() || g.suggested_name,
      })
      setMergeMsg(`已沉淀模板「${t.name}」：${ids.length} 条素材软归并，golden 素材 #${t.golden_asset_id}（原件保留）`)
      await Promise.all([loadCandidates(), loadLibraryMeta(), loadAssets()])
    } catch (e: any) { setMergeErr(e?.message || '归并失败') }
    finally { setMergingKey('') }
  }
  async function setGolden(t: any, assetId: number) {
    setWorkingTemplateId(t.id); setMergeErr(''); setMergeMsg('')
    try {
      await api.tlSetGolden(t.id, { asset_id: assetId })
      setMergeMsg(`模板「${t.name}」的唯一表达已改为素材 #${assetId}`)
      await Promise.all([loadLibraryMeta(), loadAssets()])
    } catch (e: any) { setMergeErr(e?.message || '改选 golden 失败') }
    finally { setWorkingTemplateId(null) }
  }
  async function unmerge(t: any, assetId: number) {
    if (!window.confirm(`撤销素材 #${assetId} 到「${t.name}」的归并？原件与解构保留。`)) return
    setWorkingTemplateId(t.id); setMergeErr(''); setMergeMsg('')
    try {
      await api.tlUnmerge(t.id, { asset_ids: [assetId] })
      setMergeMsg(`已撤销归并：素材 #${assetId} 回到已解构`)
      await Promise.all([loadCandidates(), loadLibraryMeta(), loadAssets()])
    } catch (e: any) { setMergeErr(e?.message || '撤销归并失败') }
    finally { setWorkingTemplateId(null) }
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

  // V4.123：原图优先用 file，缺失时退回 thumb（两者都由 api.fileUrl 还原成可访问地址）。
  function originalUrl(a: Asset) {
    return api.fileUrl(a.file || a.thumb || '')
  }

  return (
    <div className="page">
      {/* V4.117/4.118：标题与说明由 App.tsx 全局页头渲染，此处不重复。 */}
      <div className="cwb-tabbar" style={{ marginBottom: 16 }}>
        <button className={`cwb-tab ${tab === 'library' ? 'active' : ''}`} onClick={() => setTab('library')}>
          素材库 · 导入与解构
        </button>
        <button className={`cwb-tab ${tab === 'merge' ? 'active' : ''}`} onClick={() => setTab('merge')}>
          分类归并 · 模板沉淀
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
                  上传推广图片（PNG / JPG / WEBP）进入解构；视频请先切到「上传视频」，归档后可解构分镜/钩子/字幕/节奏。
                </div>
                <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp"
                  onChange={e => onUpload(e.target.files?.[0], 'image')} disabled={importing} />
                <div style={{ marginTop: 10 }}>
                  <input ref={videoInputRef} type="file" accept="video/mp4,video/quicktime,video/webm"
                    onChange={e => onUpload(e.target.files?.[0], 'video')} disabled={importing} />
                  <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>↑ 视频（归档后可解构）</span>
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
                    {a.media_kind !== 'video' && (a.thumb || a.file) ? (
                      <button type="button" className="tl-asset-thumb tl-preview-thumb"
                        onClick={() => setPreviewAsset(a)} title="查看原图">
                        <img src={api.fileUrl(a.thumb || a.file || '')} alt={a.title} />
                        <span className="tl-preview-hint">查看原图</span>
                      </button>
                    ) : (
                      <div className="tl-asset-thumb">
                        {(a.thumb || a.file) ? (
                          <img src={api.fileUrl(a.thumb || a.file || '')} alt={a.title} />
                        ) : <span className="muted">无预览</span>}
                      </div>
                    )}
                    <div style={{ fontWeight: 600, marginTop: 8, fontSize: 14 }}>{a.title || '未命名素材'}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {SOURCE_LABEL[a.source_type] || a.source_type} · {a.media_kind === 'video' ? '视频' : '图片'}
                      {a.platform ? ` · ${a.platform}` : ''}
                      {a.width && a.height ? ` · ${a.width}×${a.height}` : ''}
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <span className={`tl-status status-${a.status}`}>{STATUS_LABEL[a.status] || a.status}</span>
                      {a.merged_template_id && (
                        <span className="tl-merged-tag">已归并到 {templates.find(t => t.id === a.merged_template_id)?.name || `模板 #${a.merged_template_id}`}</span>
                      )}
                    </div>
                    {analysis?.category_json && (
                      <div className="tl-cat-line">
                        {analysis.category_json.primary && <span className="chip">{analysis.category_json.primary}</span>}
                        {(analysis.category_json.purposes || []).map((p: string) => <span key={p} className="chip">{p}</span>)}
                        {(analysis.category_json.hooks || []).map((h: string) => <span key={h} className="chip">{h}</span>)}
                        {analysis.category_json.confirmed && <span className="muted" style={{ fontSize: 11 }}>人工已确认</span>}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <button className="btn primary" onClick={() => runAnalyze(a)}
                        disabled={analyzingId === a.id}>
                        {analyzingId === a.id ? '解构中…' : (analysis ? '重新解构' : '解构')}
                      </button>
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
                        <DimBlock title="视频解构（分镜/钩子/字幕/节奏）" data={analysis.dims_json?.video} />
                        <DimBlock title="效果推断（非投放数据）" data={analysis.dims_json?.effect} />
                        {analysis.category_json && (
                          <div className="tl-dim">
                            <div className="tl-dim-title">分类（V4.119 可人工确认 / 修正）</div>
                            <div className="muted" style={{ fontSize: 13 }}>
                              主分类：<b>{analysis.category_json.primary || '—'}</b>
                              {(analysis.category_json.purposes || []).length > 0 && <> · 目的：{analysis.category_json.purposes.join('、')}</>}
                              {(analysis.category_json.hooks || []).length > 0 && <> · 钩子：{analysis.category_json.hooks.join('、')}</>}
                              {analysis.category_json.confirmed && <span className="tl-ok-inline">已人工确认</span>}
                            </div>
                            {(() => {
                              const ce = catEdits[analysis.id] || categoryEditOf(analysis)
                              return (
                                <div className="tl-cat-edit">
                                  <label className="field">
                                    <span className="label">主分类（12 类）</span>
                                    <select value={ce.primary} onChange={e => setCatEdits(prev => ({
                                      ...prev, [analysis.id]: { ...(prev[analysis.id] || categoryEditOf(analysis)), primary: e.target.value },
                                    }))}>
                                      <option value="">— 请选择 —</option>
                                      {(taxonomy?.primary_categories || []).map((c: string) => <option key={c} value={c}>{c}</option>)}
                                    </select>
                                  </label>
                                  <div className="tl-cat-options">
                                    <div><b>推广目的</b>：{(taxonomy?.purposes || []).map((p: string) => (
                                      <label key={p} className="tl-check">
                                        <input type="checkbox" checked={ce.purposes.includes(p)} onChange={e => setCatEdits(prev => {
                                          const cur = prev[analysis.id] || categoryEditOf(analysis)
                                          return { ...prev, [analysis.id]: { ...cur,
                                            purposes: e.target.checked ? [...cur.purposes, p] : cur.purposes.filter((x: string) => x !== p) } }
                                        })} />{p}
                                      </label>
                                    ))}</div>
                                    <div><b>钩子类型</b>：{(taxonomy?.hooks || []).map((h: string) => (
                                      <label key={h} className="tl-check">
                                        <input type="checkbox" checked={ce.hooks.includes(h)} onChange={e => setCatEdits(prev => {
                                          const cur = prev[analysis.id] || categoryEditOf(analysis)
                                          return { ...prev, [analysis.id]: { ...cur,
                                            hooks: e.target.checked ? [...cur.hooks, h] : cur.hooks.filter((x: string) => x !== h) } }
                                        })} />{h}
                                      </label>
                                    ))}</div>
                                  </div>
                                  <button className="btn" onClick={() => saveCategory(analysis)} disabled={workingTemplateId === analysis.id * -1}>
                                    {workingTemplateId === analysis.id * -1 ? '保存中…' : '确认分类'}
                                  </button>
                                </div>
                              )
                            })()}
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
      ) : tab === 'merge' ? (
        /* ===== V4.119 分类归并 + golden 沉淀 ===== */
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="tl-section-title">归并规则（Q4 冻结口径）</div>
            <div className="muted" style={{ fontSize: 13, lineHeight: 1.7 }}>
              主分类相同 + 推广目的相同 + 钩子类型相同 + 信息结构相似度 ≥ {Math.round((taxonomy?.similarity_threshold ?? 0.45) * 100)}%
              → 归并候选组。只有「已解构 + 框架完整度 ≥ {Math.round((taxonomy?.min_completeness ?? 0.5) * 100)}% + 分类已归一」的素材进候选。
              golden 默认选完整度最高（并列时最近导入），人工可覆盖；归并为软标记，原件与解构永久保留、可撤销。
            </div>
            {mergeMsg && <div className="tl-ok">{mergeMsg}</div>}
            {mergeErr && <div className="err">{mergeErr}</div>}
            <div style={{ marginTop: 10 }}>
              <button className="btn" onClick={() => { loadCandidates(); loadLibraryMeta() }} disabled={candLoading}>
                {candLoading ? '刷新中…' : '刷新候选组'}
              </button>
            </div>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="tl-section-title">
              ① 归并候选 <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
                （{(candidates?.groups || []).length} 组；{candidates?.excluded?.length || 0} 条未进候选）
              </span>
            </div>
            {(candidates?.excluded || []).length > 0 && (
              <div className="tl-warn">
                未进候选：{candidates.excluded.slice(0, 8).map((x: any) => `${x.title}（${x.reason}）`).join('；')}
                {candidates.excluded.length > 8 ? ` 等 ${candidates.excluded.length} 条` : ''}。可在「素材库 · 导入与解构」的「看解构」中确认分类或重新解构。
              </div>
            )}
            {(candidates?.groups || []).length === 0 && !candLoading && (
              <div className="muted">暂无候选组。先在素材库解构素材，并确认主分类 / 目的 / 钩子。</div>
            )}
            <div className="tl-merge-list">
              {(candidates?.groups || []).map((g: any) => {
                const ids = membersOf(g)
                const golden = goldenPicks[g.key] || g.golden_asset_id
                return (
                  <div key={g.key} className="tl-merge-group">
                    <div className="tl-merge-head">
                      <b>{g.suggested_name}</b>
                      <span className="muted">{g.size} 条 · 信息结构相似度 {Math.round(g.similarity * 100)}% · {g.category_source === 'manual' ? '人工分类' : 'AI 建议'}</span>
                    </div>
                    <div className="tl-merge-members">
                      {g.members.map((m: any) => (
                        <label key={m.asset_id} className={`tl-merge-member ${m.asset_id === golden ? 'is-golden' : ''}`}>
                          <input type="checkbox" checked={ids.includes(m.asset_id)} onChange={() => toggleMember(g, m.asset_id)} />
                          <input type="radio" name={`golden-${g.key}`} checked={m.asset_id === golden}
                            onChange={() => setGoldenPicks(prev => ({ ...prev, [g.key]: m.asset_id }))} title="选为 golden" />
                          <span className="tl-merge-member-title">{m.title}</span>
                          <span className="chip">{m.media_kind === 'video' ? '视频' : '图片'}</span>
                          <span className="muted">完整度 {Math.round(m.completeness * 100)}%</span>
                          {m.asset_id === g.golden_asset_id && <span className="tl-golden-tag">建议 golden</span>}
                          {m.merged_template_id && <span className="muted">已归并 #{m.merged_template_id}</span>}
                        </label>
                      ))}
                    </div>
                    <div className="tl-merge-actions">
                      <label className="field">
                        <span className="label">模板名称（可留空用建议名）</span>
                        <input value={templateNames[g.key] || ''} onChange={e => setTemplateNames(prev => ({ ...prev, [g.key]: e.target.value }))}
                          placeholder={g.suggested_name} />
                      </label>
                      <button className="btn primary" onClick={() => confirmMerge(g)} disabled={mergingKey === g.key}>
                        {mergingKey === g.key ? '沉淀中…' : '确认归并并沉淀模板'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="card">
            <div className="tl-section-title">② 已沉淀模板 <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>（{templates.length} 条）</span></div>
            {templates.length === 0 && <div className="muted">还没有模板。确认一组候选后即可沉淀。</div>}
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
              {templates.map(t => {
                const goldenAsset = assets.find(a => a.id === t.golden_asset_id)
                return (
                  <div key={t.id} className="card tl-template-card">
                    <div className="tl-template-head">
                      <b>{t.name}</b>
                      <span className="muted">{t.primary_category} · {(t.purpose || []).join('、')} · v{t.version}</span>
                    </div>
                    <div className="tl-template-golden">
                      {goldenAsset && goldenAsset.media_kind !== 'video' && (goldenAsset.thumb || goldenAsset.file) ? (
                        <button type="button" className="tl-preview-thumb tl-template-thumb"
                          onClick={() => setPreviewAsset(goldenAsset)} title="查看 golden 原图">
                          <img src={api.fileUrl(goldenAsset.thumb || goldenAsset.file || '')} alt="golden" />
                        </button>
                      ) : <span className="muted">无 golden 预览</span>}
                      <div>
                        <div className="muted" style={{ fontSize: 12 }}>唯一表达（golden）</div>
                        <div>{goldenAsset?.title || `素材 #${t.golden_asset_id || '—'}`}</div>
                        <div className="muted" style={{ fontSize: 11 }}>骨架字段 {Object.keys(t.image_skeleton_json || {}).length} 项 · 归并 {(t.merged_asset_ids || []).length} 条</div>
                        {goldenAsset && goldenAsset.media_kind !== 'video' && (goldenAsset.thumb || goldenAsset.file) && (
                          <button type="button" className="tl-preview-link"
                            onClick={() => setPreviewAsset(goldenAsset)}>查看原图</button>
                        )}
                      </div>
                    </div>
                    <div className="tl-template-members">
                      {(t.merged_asset_ids || []).map((id: number) => (
                        <div key={id} className="tl-template-member">
                          <span>素材 #{id}{id === t.golden_asset_id ? '（golden）' : ''}</span>
                          {id !== t.golden_asset_id && (
                            <>
                              <button className="btn" disabled={workingTemplateId === t.id}
                                onClick={() => setGolden(t, id)}>设为 golden</button>
                              <button className="btn" disabled={workingTemplateId === t.id}
                                onClick={() => unmerge(t, id)}>撤销归并</button>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
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

      {/* V4.123：已解构图片原图预览（点击缩略图 / 查看原图打开，Esc 或点遮罩关闭） */}
      {previewAsset && (
        <div className="tl-preview-backdrop" onClick={() => setPreviewAsset(null)}>
          <div className="tl-preview-modal" role="dialog" aria-modal="true" aria-label="原图预览"
            onClick={(e) => e.stopPropagation()}>
            <div className="tl-preview-head">
              <div>
                <b>{previewAsset.title || '未命名素材'}</b>
                <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
                  原图预览 · {SOURCE_LABEL[previewAsset.source_type] || previewAsset.source_type}
                  {previewAsset.platform ? ` · ${previewAsset.platform}` : ''}
                  {previewAsset.width && previewAsset.height ? ` · ${previewAsset.width}×${previewAsset.height}` : ''}
                </div>
              </div>
              <button className="btn" onClick={() => setPreviewAsset(null)}>关闭</button>
            </div>
            <div className="tl-preview-body">
              <img src={originalUrl(previewAsset)} alt={previewAsset.title || '原图'} />
            </div>
            <div className="tl-preview-foot">
              <span className="muted" style={{ fontSize: 12 }}>
                {STATUS_LABEL[previewAsset.status] || previewAsset.status} · 长期归档原件
              </span>
              <a className="btn" href={originalUrl(previewAsset)} target="_blank" rel="noreferrer">
                在新窗口打开原图
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** V4.119：分类编辑初值——人工确认值优先，否则取 AI 解构建议。 */
function categoryEditOf(analysis: any) {
  const cat = analysis?.category_json || {}
  return {
    primary: cat.primary || '',
    purposes: Array.isArray(cat.purposes) ? cat.purposes : [],
    hooks: Array.isArray(cat.hooks) ? cat.hooks : [],
  }
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
  shot_sequence: '分镜序列', hook_moment: '钩子时刻', subtitle_strategy: '字幕/画面文字',
  rhythm: '节奏推断', frame_count: '抽帧数', duration_sec: '视频时长',
}
