import { useEffect, useMemo, useState } from 'react'
import {
  api, AnalysisReport, Angle, Campaign, Framework, Material, Meta, PlatformSpec,
} from '../api'
// 复用创作工作台的同一套分析视图与基础组件，保证“落地页综合分析”与创作工作台完全一致
import { Chips, StepHead, CopyBlock, ReportView } from './Workspace'

const TEMPLATE_LABEL: Record<string, string> = {
  bigtype: '纯字体版式', stat: '数字主体', rating: '评分卡', promo: '折扣角标',
  ugc: 'UGC 手机框', compare: '前后对比', scenario: '场景叙事',
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* 把一次 Produced 的素材按创意方向分组，供两个子模块复用同一套素材墙样式 */
function angleGroups(campaign: Campaign, angles: Angle[]) {
  const map = new Map<string, {
    key: string; name: string; insight?: string; hook?: string
    imgs: Material[]; copy?: Material; video?: Material; kw?: Material
  }>()
  const ensure = (key: string) => {
    if (!map.has(key)) {
      const a = angles.find(x => x.key === key)
      map.set(key, { key, name: a?.name || key, insight: a?.insight, hook: a?.hook, imgs: [], copy: undefined, video: undefined, kw: undefined })
    }
    return map.get(key)!
  }
  for (const m of campaign.materials) {
    const g = ensure(m.angle_key || 'default')
    if (m.type === 'image') g.imgs.push(m)
    else if (m.type === 'copy') g.copy = m
    else if (m.type === 'video') g.video = m
    else if (m.type === 'keyword') g.kw = m
  }
  return Array.from(map.values()).filter(g => g.imgs.length || g.copy || g.video || g.kw)
}

export default function MaterialCreation({ meta }: { meta: Meta | null }) {
  // ---------------- 共享：落地页综合分析 ----------------
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [showText, setShowText] = useState(false)
  const [fw, setFw] = useState<Framework | null>(null)
  const [report, setReport] = useState<AnalysisReport | null>(null)
  const [angles, setAngles] = useState<Angle[]>([])
  const [picked, setPicked] = useState<string[]>([])

  // ---------------- 共享：媒体设置与品牌风格 ----------------
  const [platforms, setPlatforms] = useState<string[]>(['Facebook'])
  const [langs, setLangs] = useState<string[]>(['en'])
  const [sizes, setSizes] = useState(2)
  const [brand, setBrand] = useState('#FFB020')
  const [productImg, setProductImg] = useState('')
  const [specs, setSpecs] = useState<PlatformSpec[]>([])

  // ---------------- 状态 ----------------
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [sub, setSub] = useState<'image' | 'video'>('image')

  // 两个独立子模块各自的一次性产出（共享同一框架 / 品牌 / 方向，保证风格一致）
  const [imageCampaign, setImageCampaign] = useState<Campaign | null>(null)
  const [videoCampaign, setVideoCampaign] = useState<Campaign | null>(null)
  const [imgBusy, setImgBusy] = useState('')
  const [vidBusy, setVidBusy] = useState('')

  useEffect(() => { api.specs().then(setSpecs).catch(() => {}) }, [])

  // 支持视频广告位的媒介（用于决定是否生成完整视频）
  const videoCapable = useMemo(
    () => platforms.filter(p => (specs.find(s => s.platform === p)?.video_spec || '').trim().length > 0),
    [platforms, specs],
  )

  // ----------------------------- 分析（与创作工作台一致） -----------------------------
  const runAnalyze = async () => {
    setErr(''); setBusy('正在抓取落地页并分析…'); setFw(null); setReport(null); setAngles([])
    setImageCampaign(null); setVideoCampaign(null); setPicked([])
    try {
      const res = await api.report({
        url: url.trim() || undefined,
        text: text.trim() || undefined,
        platforms,
        lang: langs[0],
      })
      setFw(res.framework)
      setReport(res.report)
      setAngles(res.angles)
      const rec = res.report.creative.angles.filter(a => a.recommended).map(a => a.key)
      const fallback = res.angles.slice(0, 3).map(a => a.key)
      setPicked((rec.length ? rec : fallback).slice(0, 4))
      if (res.framework.languages?.length) setLangs([res.framework.languages[0]])
      if (res.framework.brand_color) setBrand(res.framework.brand_color)
      setBusy('')
      setTimeout(() => scrollTo('mc-step2'), 120)
    } catch (e: any) {
      setErr(e.message)
      setBusy('')
    }
  }

  const upload = async (file?: File) => {
    if (!file) return
    try {
      const r = await api.uploadAsset(file)
      setProductImg(r.path)
      if (fw) await api.updateBrand(fw.id, { brand_color: brand, assets: { product: r.path } })
    } catch (e: any) { setErr(e.message) }
  }

  const saveBrand = async (color: string) => {
    setBrand(color)
    if (fw) {
      try { await api.updateBrand(fw.id, { brand_color: color, assets: productImg ? { product: productImg } : {} }) } catch { /* 颜色保存失败不影响出图 */ }
    }
  }

  // ----------------------------- 生成（图片 / 视频 独立任务） -----------------------------
  const produce = async (kind: 'image' | 'video') => {
    if (!fw || picked.length === 0) { setErr('请先完成落地页分析并至少选择一个创意方向'); return }
    const isImg = kind === 'image'
    setErr('')
    if (isImg) setImgBusy('正在生成图片素材…'); else setVidBusy('正在生成视频素材…')
    try {
      const c = await api.produce({
        framework_id: fw.id,
        campaign_name: `${fw.product} · ${isImg ? '图片创作' : '视频创作'}`,
        angle_keys: picked,
        platforms,
        material_types: isImg ? ['image', 'copy', 'keyword'] : ['video', 'copy'],
        languages: langs,
        sizes_per_angle: sizes,
        video_mode: isImg ? 'off' : 'all',
        full_video: !isImg && videoCapable.length > 0,
      })
      if (isImg) setImageCampaign(c); else setVideoCampaign(c)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      if (isImg) setImgBusy(''); else setVidBusy('')
    }
  }

  const canProduce = !!fw && picked.length > 0

  return (
    <div>
      {/* 一致性说明：两个子模块共享同一分析/品牌/方向 */}
      <div className="mc-banner">
        <b>风格一致性</b>：图片创作与视频创作共用同一份落地页分析、品牌色、产品图与创意方向，
        保证同一落地页在两个模块下产出的素材在配色、产品识别、主张与语气上保持可识别的一致。
      </div>

      <nav className="flow-nav">
        {[['mc-step1', '① 产品分析'], ['mc-step2', '② 媒体与品牌'], ['mc-step3', '③ 创意方向'], ['mc-step4', '④ 创作']].map(([id, label]) => (
          <a key={id} href={`#${id}`} onClick={e => { e.preventDefault(); scrollTo(id) }}>{label}</a>
        ))}
      </nav>

      {/* ---------------- ① 产品分析（与创作工作台一致） ---------------- */}
      <section className="card step" id="mc-step1">
        <StepHead
          no="1"
          title="推广产品分析（落地页综合分析）"
          desc="输入要推广的产品落地页链接，抓取整页内容并给出结构化分析报告：定位、卖点、背书、人群、平台打法与风险。与「创作工作台」使用同一分析引擎与报告视图。"
        />
        <div className="analyze-box">
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (url || text)) runAnalyze() }}
            placeholder="https://你的产品落地页"
          />
          <button className="btn" onClick={runAnalyze} disabled={!!busy || (!url.trim() && !text.trim())}>
            {busy ? '分析中…' : fw ? '重新分析' : '抓取并分析'}
          </button>
        </div>
        <div className="analyze-sub">
          <button className="linkbtn" onClick={() => setShowText(v => !v)}>
            {showText ? '收起正文输入' : '链接打不开？粘贴落地页正文 / 产品说明'}
          </button>
          <span className="muted">支持 JS 渲染失败的站点、内部测试页，或只有一份产品文档的情况</span>
        </div>
        {showText && (
          <textarea
            rows={5}
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="把落地页正文、产品介绍或投放 brief 粘进来。"
          />
        )}
        {busy && !fw && <div className="alert ok">{busy}</div>}
        {err && <div className="alert err">{err}</div>}
        {report && fw && (
          <ReportView report={report} fw={fw} onDownload={() => window.open(api.reportMdUrl(fw.id), '_blank')} />
        )}
      </section>

      {/* ---------------- ② 媒体与品牌（与创作工作台一致） ---------------- */}
      <section className={'card step' + (fw ? '' : ' disabled')} id="mc-step2">
        <StepHead
          no="2"
          title="投放设置与品牌风格"
          desc="选平台即决定素材版位与文案字段规则；品牌色与产品图会被图片与视频两个子模块同时采用，是风格一致性的来源。"
          extra={fw ? <button className="btn small ghost" onClick={() => scrollTo('mc-step3')}>选方向</button> : undefined}
        />
        <div className="setting-grid">
          <div>
            <label>投放平台（决定版位与字数上限）</label>
            <Chips options={meta?.platforms || []} value={platforms} onChange={setPlatforms} />
          </div>
          <div>
            <label>投放语言</label>
            <Chips options={meta?.languages || []} value={langs} onChange={setLangs} />
          </div>
        </div>
        <div className="setting-grid">
          <div>
            <label>每个方向出几个版位</label>
            <select value={sizes} onChange={e => setSizes(Number(e.target.value))}>
              <option value={1}>1 个（只要主尺寸）</option>
              <option value={2}>2 个（先看方向对不对）</option>
              <option value={3}>3 个</option>
              <option value={4}>4 个（覆盖 Feed / 竖版 / 横版）</option>
              <option value={6}>6 个（全版位铺开）</option>
            </select>
          </div>
          <div>
            <label>品牌色（图片与视频共用，决定所有素材配色）</label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="color" value={brand} onChange={e => saveBrand(e.target.value)}
                style={{ width: 52, height: 38, padding: 2, border: '1px solid var(--border)', borderRadius: 8, background: '#fff' }} />
              <input type="text" value={brand} onChange={e => setBrand(e.target.value)} onBlur={e => saveBrand(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="setting-grid">
          <div>
            <label>产品图 / Logo（合成进素材，PNG 透明底最佳）</label>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => upload(e.target.files?.[0])} />
            {productImg && <div className="muted" style={{ marginTop: 4 }}>已上传：{productImg.split('/').pop()}</div>}
          </div>
          <div>
            <label>视频广告位</label>
            <div className="muted">
              {videoCapable.length
                ? `支持视频素材的媒介：${videoCapable.join('、')}（视频创作将合成完整成片）`
                : '当前所选媒介均无视频广告位，视频创作将只产出关键帧与分镜。'}
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- ③ 创意方向（与创作工作台一致） ---------------- */}
      {angles.length > 0 && (
        <section className="card step" id="mc-step3">
          <StepHead
            no="3"
            title="创意方向"
            desc="每个方向是一套独立创意：洞察、钩子、版式都不同。图片与视频两个子模块都基于这里选定的方向生成。"
            extra={<span className="muted">已选 {picked.length} / {angles.length}</span>}
          />
          <div className="angle-grid">
            {angles.map(a => {
              const on = picked.includes(a.key)
              const meta = report?.creative.angles.find(x => x.key === a.key)
              const rec = meta?.recommended
              return (
                <div key={a.key} className={'angle-card' + (on ? ' on' : '')}
                  onClick={() => setPicked(on ? picked.filter(x => x !== a.key) : [...picked, a.key])}>
                  <div className="ac-head">
                    <span className="ac-check">{on ? '✓' : ''}</span>
                    <b>{a.name}</b>
                    {rec && <span className="pill ok">推荐</span>}
                    {a.hook_type && <span className="ac-tpl">{a.hook_type}</span>}
                    <span className="ac-tpl">{TEMPLATE_LABEL[a.template || ''] || a.template}</span>
                  </div>
                  <div className="ac-hook">{a.hook}</div>
                  <div className="ac-insight">{a.insight}</div>
                  {a.storyboard && a.storyboard.length > 0 && (
                    <div className="ac-sb">
                      <div className="muted sb-title">分镜脚本</div>
                      <ol className="sb-list">
                        {a.storyboard.map((s, i) => (
                          <li key={i}>
                            <span className="sb-t">{s.t}</span>
                            <span className="sb-c">{s.copy}</span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                  <div className="ac-meta">
                    <span className="pill off">{a.kpi}</span>
                    {(a.platform_fit || []).slice(0, 3).map(p => <span key={p} className="pill off">{p}</span>)}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ---------------- ④ 创作（图片 / 视频 两个独立子模块） ---------------- */}
      <section className={'card step' + (fw ? '' : ' disabled')} id="mc-step4">
        <StepHead
          no="4"
          title="素材创作"
          desc="两个独立子模块共享同一份分析、品牌与方向。先完成上方分析与方向选择，再分别进入图片或视频创作。"
        />

        <div className="mc-tabs">
          <button className={'mc-tab' + (sub === 'image' ? ' on' : '')} onClick={() => setSub('image')}>
            🖼 图片创作
          </button>
          <button className={'mc-tab' + (sub === 'video' ? ' on' : '')} onClick={() => setSub('video')}>
            🎬 视频创作
          </button>
        </div>

        {!fw && <div className="muted">请先在「① 产品分析」完成落地页综合分析。</div>}
        {fw && picked.length === 0 && <div className="muted">请在「③ 创意方向」至少选择一个方向。</div>}

        {/* ===== 图片创作子模块 ===== */}
        {sub === 'image' && fw && (
          <div className="mc-pane">
            <div className="step-actions">
              <button className="btn" onClick={() => produce('image')} disabled={!!imgBusy || !canProduce}>
                {imgBusy || (imageCampaign ? '重新生成图片素材' : `生成 ${picked.length} 方向 × ${platforms.length} 平台图片`)}
              </button>
              {imgBusy && <span className="muted">{imgBusy}</span>}
              {imageCampaign && (
                <a className="btn ghost" href={api.exportUrl(imageCampaign.id)}>下载图片素材 ZIP</a>
              )}
            </div>
            {imageCampaign && <ImageWall campaign={imageCampaign} angles={angles} />}
          </div>
        )}

        {/* ===== 视频创作子模块 ===== */}
        {sub === 'video' && fw && (
          <div className="mc-pane">
            <div className="step-actions">
              <button className="btn" onClick={() => produce('video')} disabled={!!vidBusy || !canProduce}>
                {vidBusy || (videoCampaign ? '重新生成视频素材' : `生成 ${picked.length} 方向 × ${platforms.length} 平台视频`)}
              </button>
              {vidBusy && <span className="muted">{vidBusy}</span>}
              {videoCampaign && (
                <a className="btn ghost" href={api.exportUrl(videoCampaign.id)}>下载视频素材 ZIP</a>
              )}
            </div>
            {videoCampaign && <VideoWall campaign={videoCampaign} angles={angles} />}
          </div>
        )}
      </section>
    </div>
  )
}

/* ---------------- 图片素材墙（复用创作工作台样式类） ---------------- */
function ImageWall({ campaign, angles }: { campaign: Campaign; angles: Angle[] }) {
  const groups = angleGroups(campaign, angles)
  if (groups.length === 0) return <div className="muted">暂无图片素材。</div>
  return (
    <div className="wall">
      {groups.map(g => (
        <div key={g.key} className="wall-group">
          <div className="wg-head">
            <b>{g.name}</b>
            {g.insight && <span className="muted">{g.insight}</span>}
          </div>
          <section className="wg-sec wg-sec-img">
            <div className="wg-sec-head">
              <span className="wg-sec-tag">图片</span>
              <b>图片素材</b>
              <span className="muted">{g.imgs.length} 张 · 点击可放大</span>
            </div>
            <div className="shot-row">
              {g.imgs.map(m => (
                <div key={m.id} className="shot">
                  <img src={api.fileUrl(m.file_path)} alt={m.spec_json?.size} onClick={() => window.open(api.fileUrl(m.file_path))} />
                  <div className="shot-cap">
                    <span>{m.spec_json?.size}</span>
                    <span className="shot-actions">
                      <span className={'dot ' + (m.validation?.valid === false ? 'bad' : 'good')} />
                      <a href={api.downloadUrl(m.id)}>下载</a>
                    </span>
                  </div>
                </div>
              ))}
              {g.imgs.length === 0 && <div className="muted">该方向没有图片</div>}
            </div>
          </section>
          {g.copy && (
            <section className="wg-sec wg-sec-text">
              <div className="wg-sec-head">
                <span className="wg-sec-tag">文案</span>
                <b>文案与关键词</b>
              </div>
              <CopyBlock m={g.copy} />
              {g.kw && <pre className="kw-pre">{g.kw.text_content}</pre>}
            </section>
          )}
        </div>
      ))}
    </div>
  )
}

/* ---------------- 视频素材墙（复用创作工作台样式类） ---------------- */
function VideoWall({ campaign, angles }: { campaign: Campaign; angles: Angle[] }) {
  const groups = angleGroups(campaign, angles)
  const videos = groups.filter(g => g.video)
  if (videos.length === 0) return <div className="muted">暂无视频素材。点击上方「生成」开始。</div>
  return (
    <div className="wall">
      {videos.map(g => {
        const v = g.video!
        return (
          <div key={g.key} className="wall-group">
            <div className="wg-head">
              <b>{g.name}</b>
              {g.hook && <span className="muted">钩子：{g.hook}</span>}
            </div>
            <section className="wg-sec wg-sec-video">
              <div className="wg-sec-head">
                <span className="wg-sec-tag">视频</span>
                <b>视频素材</b>
                <span className="muted">
                  {v.content?.provider === 'llm_storyboard' ? 'AI 分镜脚本' : '内置分镜脚本'}
                  {v.content?.video_file ? ' · 含完整视频' : ' · 仅关键帧与脚本'}
                </span>
              </div>
              {v.content?.video_file && (
                <div className="fv-player">
                  <video
                    controls playsInline
                    poster={api.fileUrl(v.content?.cover || v.file_path)}
                    src={api.fileUrl(v.content.video_file)}
                    style={{ width: '100%', maxWidth: 420, maxHeight: 560, borderRadius: 10, background: '#000', display: 'block' }}
                  />
                  <div className="fv-actions">
                    <a className="btn" href={api.downloadUrl(v.id)}>下载完整视频 MP4</a>
                    {v.content?.cover && <a className="btn ghost" href={api.fileUrl(v.content.cover)} download>下载封面图</a>}
                    <span className="muted">{v.content?.video_note || '完整视频由关键帧逐镜合成（无声）'}</span>
                  </div>
                  {v.content?.video_error && (
                    <div className="alert" style={{ marginTop: 6 }}>完整视频合成失败：{v.content.video_error}，已保留关键帧与分镜。</div>
                  )}
                </div>
              )}
              <div className="kf-note">
                关键帧就是投放画面：镜号、时间码、画面说明与旁白只在这里标注，不写入图片，也不进成片。
              </div>
              <div className="kf-list">
                {(v.content?.keyframes || []).map((k: any) => (
                  <article key={k.index} className="kf-item">
                    <a className="kf-shot" href={api.fileUrl(k.file)} target="_blank" rel="noreferrer">
                      <img src={api.fileUrl(k.file)} alt={k.scene} />
                    </a>
                    <div className="kf-meta">
                      <div className="kf-meta-head">
                        <span className="kf-no">{String(k.index ?? 0).padStart(2, '0')}</span>
                        <b>{k.scene}</b>
                        <span className="kf-tc">{k.timecode}{k.duration ? ` · ${k.duration}s` : ''}</span>
                      </div>
                      {k.note && <p className="kf-line"><em>画面</em><span>{k.note}</span></p>}
                      {k.text && <p className="kf-line"><em>建议字幕</em><span>{k.text}</span></p>}
                      {k.vo && <p className="kf-line"><em>旁白</em><span>{k.vo}</span></p>}
                      <div className="kf-acts">
                        <a className="btn ghost small" href={api.fileUrl(k.file)} target="_blank" rel="noreferrer">查看原图</a>
                        <a className="btn ghost small" href={api.fileUrl(k.file)} download={`kf${k.index}.png`}>下载该帧</a>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              {(v.content?.hook || v.content?.cta) && (
                <div className="kf-extra">
                  {v.content?.hook && <span><em>开场钩子</em>{v.content.hook}</span>}
                  {v.content?.cta && <span><em>收口行动</em>{v.content.cta}</span>}
                </div>
              )}
            </section>
          </div>
        )
      })}
    </div>
  )
}
