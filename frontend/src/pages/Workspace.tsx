import { useEffect, useMemo, useState } from 'react'
import {
  api, AnalysisReport, Angle, Campaign, Framework, Material, Meta, OptimizeResult,
  PlanEstimate, PlatformSpec,
} from '../api'

const TEMPLATE_LABEL: Record<string, string> = {
  bigtype: '纯字体版式', stat: '数字主体', rating: '评分卡', promo: '折扣角标',
  ugc: 'UGC 手机框', compare: '前后对比',
}

const TYPE_LABEL: Record<string, string> = { metric: '量化', proof: '背书', benefit: '价值' }
const LEVEL_CLASS: Record<string, string> = { error: 'err', warn: 'warn', info: 'info' }

const OPT_TIPS = ['标题更短', '去掉数字', '更口语', '换成纯文字版式', '主色改蓝', '按钮改成立即下载']

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function Chips({ options, value, onChange, hint }: {
  options: string[]; value: string[]; onChange: (v: string[]) => void
  hint?: (o: string) => string
}) {
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter(x => x !== o) : [...value, o])
  return (
    <div className="chips">
      {options.map(o => (
        <div key={o} className={'chip' + (value.includes(o) ? ' on' : '')} onClick={() => toggle(o)}>
          {o}{hint && <span className="chip-hint">{hint(o)}</span>}
        </div>
      ))}
    </div>
  )
}

function CharBar({ len, max }: { len: number; max: number }) {
  const pct = Math.min(100, Math.round((len / Math.max(1, max)) * 100))
  const over = len > max
  return (
    <div className="charbar">
      <div className={'charbar-in' + (over ? ' over' : pct > 90 ? ' near' : '')} style={{ width: pct + '%' }} />
      <span className={over ? 'over' : ''}>{len}/{max}</span>
    </div>
  )
}

function CopyBlock({ m }: { m: Material }) {
  const rows = (m.content?.char_table || []) as { field: string; text: string; len: number; max: number; over: boolean }[]
  const problems = (m.validation?.problems || []) as { level: string; field: string; msg: string }[]
  const ok = m.validation?.valid !== false
  return (
    <div className="copy-block">
      <div className="copy-head">
        <span className="copy-ver">文案 v{m.version}{m.variant ? ` · ${m.variant}` : ''}</span>
        <span className={'pill ' + (ok ? 'ok' : 'err')}>{ok ? '校验通过' : '需修正'}</span>
        <button className="linkbtn" onClick={() => navigator.clipboard?.writeText(m.text_content || '')}>复制</button>
      </div>
      <table className="copy-table">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="cf">{r.field}</td>
              <td className="cv">{r.text || '—'}</td>
              <td className="cc"><CharBar len={r.len} max={r.max} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {problems.length > 0 && (
        <div className="copy-issues">
          {problems.map((p, i) => (
            <span key={i} className={'pill ' + (p.level === 'error' ? 'off' : 'warn')}>{p.field}：{p.msg}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function StepHead({ no, title, desc, extra }: {
  no: string; title: string; desc?: string; extra?: React.ReactNode
}) {
  return (
    <div className="step-head">
      <span className="step-no">{no}</span>
      <div className="step-title-wrap">
        <h2 className="step-title">{title}</h2>
        {desc && <div className="step-desc">{desc}</div>}
      </div>
      {extra && <div className="step-extra">{extra}</div>}
    </div>
  )
}

function ReportItem({ it }: { it: any }) {
  if (typeof it.point === 'string') {
    return (
      <div className="vprop">
        <span className="vp-rank">{it.rank}</span>
        <div className="vp-body">
          <div className="vp-text">{it.point}</div>
          <div className="vp-tags">
            <span className="pill off">{TYPE_LABEL[it.type] || it.type}</span>
            <span className={'pill ' + (it.strength === '强' ? 'ok' : it.strength === '弱' ? 'off' : 'warn')}>
              强度 {it.strength}
            </span>
            <span className="vp-evi">{it.evidence}</span>
          </div>
        </div>
      </div>
    )
  }
  if (typeof it.platform === 'string') {
    return (
      <div className="plat-row">
        <div className="plat-name">{it.platform}<span className="plat-role">{it.role}</span></div>
        <div className="plat-note">{it.note}</div>
      </div>
    )
  }
  if (typeof it.hook === 'string') {
    return (
      <div className="hook-row">
        <div className="hook-head">
          <b>{it.name}</b>
          {it.recommended && <span className="pill ok">推荐</span>}
          <span className="pill off">{it.kpi}</span>
          <span className="ac-tpl">{TEMPLATE_LABEL[it.template] || it.template}</span>
        </div>
        <div className="hook-text">“{it.hook}”</div>
        <div className="hook-ins">{it.insight}</div>
      </div>
    )
  }
  return null
}

function ReportView({ report, fw, onDownload }: {
  report: AnalysisReport; fw: Framework; onDownload: () => void
}) {
  const r = report
  const metricPills = r.proof.metrics
  return (
    <div className="report">
      <div className="rep-head">
        <div className="rep-main">
          <div className="rep-title">
            {fw.product}
            <span className="pill off">{fw.category || '未分类'}</span>
            <span className={'pill ' + (r.source.fetched ? 'ok' : 'warn')}>
              {r.source.fetched ? '整页抓取成功' : '未抓到正文'}
            </span>
          </div>
          <div className="rep-claim">{r.verdict.claim ? `“${r.verdict.claim}”` : '页面未给出明确主张'}</div>
          <div className="rep-meta">
            {r.source.url || '—'} · {r.source.chars.toLocaleString()} 字
            {r.source.images > 0 && ` · ${r.source.images} 张图`}
            {r.source.has_video && ' · 含视频'}
            {r.source.lang && ` · 页面语言 ${r.source.lang}`}
            {' · '}{r.source.analyzer === 'local' ? '本地抽取' : '大模型 + 本地事实'}
            {' · '}{r.source.extracted_at}
          </div>
        </div>
        <div className="rep-score">
          <div className="rs-num">{r.verdict.confidence}<span>/100</span></div>
          <div className="rs-bar"><i style={{ width: `${r.verdict.confidence}%` }} /></div>
          <div className="rs-label">结论可信度 · {r.verdict.confidence_label}</div>
        </div>
      </div>

      <div className="rep-reasons">
        {r.verdict.reasons.map((x, i) => <span key={i} className="rr">{x}</span>)}
      </div>

      {metricPills.length > 0 && (
        <div className="rep-metrics">
          {metricPills.map((m, i) => (
            <span key={i} className="pill met">
              {m.value}<i>{m.label}</i>
            </span>
          ))}
        </div>
      )}

      <div className="rep-grid">
        {r.sections.map(sec => (
          <section key={sec.key} className="rsec">
            <h4>{sec.title}</h4>
            {sec.summary && <p className="rsec-sum">{sec.summary}</p>}
            {sec.rows?.map((row, i) => (
              <div key={i} className="rrow">
                <span className="rk">{row.label}</span>
                <span className="rv">{row.value || '—'}</span>
                {row.note && <span className="rn">{row.note}</span>}
              </div>
            ))}
            {sec.items?.map((it, i) => <ReportItem key={i} it={it} />)}
          </section>
        ))}
      </div>

      <div className="rep-bottom">
        {r.risks.length > 0 && (
          <section className="rsec">
            <h4>风险与合规</h4>
            {r.risks.map((x, i) => (
              <div key={i} className={'line-item ' + (LEVEL_CLASS[x.level] || 'info')}>
                <b>{x.item}</b><span>{x.detail}</span>
              </div>
            ))}
          </section>
        )}
        {r.gaps.length > 0 && (
          <section className="rsec">
            <h4>信息缺口</h4>
            {r.gaps.map((g, i) => (
              <div key={i} className={'line-item ' + (LEVEL_CLASS[g.level] || 'info')}>
                <b>{g.item}</b><span>{g.impact}</span>
              </div>
            ))}
          </section>
        )}
        <section className="rsec">
          <h4>下一步</h4>
          <ol className="next-list">{r.actions.map((a, i) => <li key={i}>{a}</li>)}</ol>
          <button className="btn small ghost" onClick={onDownload}>下载分析报告（Markdown）</button>
        </section>
      </div>
    </div>
  )
}

export default function Workspace({ meta, onOpenLibrary }: { meta: Meta | null; onOpenLibrary: () => void }) {
  // 1. 分析
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [showText, setShowText] = useState(false)
  const [fw, setFw] = useState<Framework | null>(null)
  const [report, setReport] = useState<AnalysisReport | null>(null)
  const [angles, setAngles] = useState<Angle[]>([])
  const [picked, setPicked] = useState<string[]>([])

  // 2. 投放设置
  const [platforms, setPlatforms] = useState<string[]>(['Facebook'])
  const [langs, setLangs] = useState<string[]>(['en'])
  const [types, setTypes] = useState<string[]>(['image', 'copy'])
  const [sizes, setSizes] = useState(2)
  const [videoMode, setVideoMode] = useState<'off' | 'first' | 'all'>('off')
  const [brand, setBrand] = useState('#FFB020')
  const [productImg, setProductImg] = useState('')
  const [specs, setSpecs] = useState<PlatformSpec[]>([])

  // 3. 生成
  const [est, setEst] = useState<PlanEstimate | null>(null)
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')

  // 4. 优化
  const [instruction, setInstruction] = useState('')
  const [scope, setScope] = useState<'all' | 'copy' | 'image'>('all')
  const [optBusy, setOptBusy] = useState(false)
  const [optRes, setOptRes] = useState<OptimizeResult | null>(null)

  // 5. 素材墙
  const [plat, setPlat] = useState('')
  const [lang, setLang] = useState('')
  const [ver, setVer] = useState<number | 'latest'>('latest')
  const [validOnly, setValidOnly] = useState(false)
  const [zoom, setZoom] = useState('')

  useEffect(() => { api.specs().then(setSpecs).catch(() => { }) }, [])

  useEffect(() => {
    if (!campaign) return
    setPlat(campaign.platforms?.[0] || '')
    setLang(campaign.options?.languages?.[0] || langs[0] || 'en')
    setVer('latest')
    setOptRes(null)
  }, [campaign?.id])

  const sizeHint = (p: string) => {
    const s = specs.find(x => x.platform === p)
    return s?.image_sizes?.length ? ` ${s.image_sizes.length} 版位` : ''
  }

  // ----------------------------- 分析 -----------------------------
  const runAnalyze = async () => {
    setErr(''); setBusy('正在抓取落地页并分析…'); setCampaign(null); setReport(null); setAngles([])
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
      setTimeout(() => scrollTo('step2'), 120)
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

  const materialTypes = useMemo(
    () => (videoMode === 'off' ? types.filter(t => t !== 'video') : [...types.filter(t => t !== 'video'), 'video']),
    [types, videoMode],
  )

  useEffect(() => {
    if (!picked.length || !platforms.length) { setEst(null); return }
    let alive = true
    api.estimate({
      angle_keys: picked, platforms, material_types: materialTypes,
      languages: langs, sizes_per_angle: sizes, video_mode: videoMode,
    }).then(e => { if (alive) setEst(e) }).catch(() => { if (alive) setEst(null) })
    return () => { alive = false }
  }, [picked, platforms, langs, materialTypes, sizes, videoMode])

  const produce = async () => {
    if (!fw) return
    setErr(''); setBusy('正在按方向生产素材…')
    try {
      const c = await api.produce({
        framework_id: fw.id,
        campaign_name: `${fw.product} · ${picked.length} 方向`,
        angle_keys: picked,
        platforms, material_types: materialTypes, languages: langs,
        sizes_per_angle: sizes, video_mode: videoMode,
      })
      setCampaign(c)
      setBusy('')
      setTimeout(() => scrollTo('step4'), 120)
    } catch (e: any) { setErr(e.message); setBusy('') }
  }

  // ----------------------------- 优化 -----------------------------
  const runOptimize = async () => {
    if (!campaign || !instruction.trim()) return
    setErr(''); setOptBusy(true); setOptRes(null)
    try {
      const res = await api.optimize(campaign.id, {
        instruction: instruction.trim(), scope, angle_keys: picked,
      })
      setCampaign(res.campaign)
      setOptRes(res)
      setVer('latest')
      setTimeout(() => scrollTo('opt-result'), 80)
    } catch (e: any) { setErr(e.message) } finally { setOptBusy(false) }
  }

  // ----------------------------- 素材墙 -----------------------------
  const versions = useMemo(() => {
    if (!campaign) return []
    const s = new Set(campaign.materials
      .filter(m => m.platform === plat && (m.language || 'en') === lang)
      .map(m => m.version))
    return Array.from(s).sort((a, b) => a - b)
  }, [campaign, plat, lang])

  const curVer = useMemo(() => {
    if (ver !== 'latest') return ver
    return versions.length ? versions[versions.length - 1] : 1
  }, [ver, versions])

  const wall = useMemo(() => {
    if (!campaign) return []
    const mats = campaign.materials.filter(m => m.platform === plat && (m.language || 'en') === lang)
    return picked.map(key => {
      const info = angles.find(a => a.key === key)
      const group = mats.filter(m => (m.angle_key || 'base') === key && m.version <= curVer)
      const bySize = new Map<string, Material>()
      group.filter(m => m.type === 'image').forEach(m => {
        const size = m.spec_json?.size || ''
        const prev = bySize.get(size)
        if (!prev || (m.version || 1) > (prev.version || 1)) bySize.set(size, m)
      })
      const imgs = Array.from(bySize.values()).sort(
        (a, b) => (b.spec_json?.w || 0) * (b.spec_json?.h || 0) - (a.spec_json?.w || 0) * (a.spec_json?.h || 0),
      )
      const latest = (t: string) => group.filter(m => m.type === t)
        .sort((a, b) => (b.version || 1) - (a.version || 1))[0]
      return { key, info, imgs, copy: latest('copy'), video: latest('video'), kw: latest('keyword') }
    }).filter(g => g.info)
  }, [campaign, plat, lang, curVer, picked, angles])

  const visibleWall = useMemo(() => (validOnly
    ? wall.map(g => ({
      ...g,
      imgs: g.imgs.filter(m => m.validation?.valid !== false),
      copy: g.copy && g.copy.validation?.valid !== false ? g.copy : undefined,
    })).filter(g => g.imgs.length || g.copy)
    : wall), [wall, validOnly])

  // 交付统计按「每组最新版本」算：历史版本不会进压缩包，算进去会让人以为要上传十几张
  const stats = useMemo(() => {
    if (!campaign) return { imgs: 0, valid: 0, copy: 0, versions: 0, history: 0 }
    const mats = campaign.materials
    const latest = new Map<string, Material>()
    mats.forEach(m => {
      const k = [m.angle_key, m.platform, m.language, m.type,
        m.type === 'image' ? (m.spec_json?.size || '') : ''].join('|')
      const prev = latest.get(k)
      if (!prev || (m.version || 1) > (prev.version || 1)) latest.set(k, m)
    })
    const cur = Array.from(latest.values())
    const imgs = cur.filter(m => m.type === 'image')
    return {
      imgs: imgs.length,
      valid: imgs.filter(m => m.validation?.valid !== false).length,
      copy: cur.filter(m => m.type === 'copy').length,
      versions: new Set(mats.map(m => m.version)).size,
      history: mats.length,
    }
  }, [campaign])

  return (
    <div>
      <nav className="flow-nav">
        {[['step1', '① 产品分析'], ['step2', '② 投放设置'], ['step3', '③ 创意方向'],
          ['step4', '④ 素材与优化'], ['step5', '⑤ 交付下载']].map(([id, label]) => (
          <a key={id} href={`#${id}`} onClick={e => { e.preventDefault(); scrollTo(id) }}>{label}</a>
        ))}
      </nav>

      {/* ---------------- ① 产品分析 ---------------- */}
      <section className="card step" id="step1">
        <StepHead
          no="1"
          title="推广产品分析"
          desc="输入要推广的产品落地页链接，抓取整页内容并给出结构化分析报告：定位、卖点、背书、人群、平台打法与风险。"
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
            placeholder="把落地页正文、产品介绍或投放 brief 粘进来。工具会先做本地事实抽取，再据此生成报告。"
          />
        )}
        {busy && !fw && <div className="alert ok">{busy}</div>}
        {err && <div className="alert err">{err}</div>}
        {report && fw && (
          <ReportView report={report} fw={fw} onDownload={() => window.open(api.reportMdUrl(fw.id), '_blank')} />
        )}
      </section>

      {/* ---------------- ② 投放设置 ---------------- */}
      <section className={'card step' + (fw ? '' : ' disabled')} id="step2">
        <StepHead
          no="2"
          title="投放设置"
          desc="选平台即决定素材版位与文案字段规则：FB 三段式、Google RSA 多标题、激励视频竖版等。"
          extra={fw ? <button className="btn small ghost" onClick={() => scrollTo('step3')}>选方向</button> : undefined}
        />
        <div className="setting-grid">
          <div>
            <label>投放平台（决定版位与字数上限）</label>
            <Chips options={meta?.platforms || []} value={platforms} onChange={setPlatforms} hint={sizeHint} />
          </div>
          <div>
            <label>投放语言</label>
            <Chips options={meta?.languages || []} value={langs} onChange={setLangs} />
          </div>
        </div>
        <div className="setting-grid">
          <div>
            <label>产出类型</label>
            <Chips options={['image', 'copy', 'keyword']} value={types} onChange={setTypes} />
          </div>
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
            <label>视频</label>
            <select value={videoMode} onChange={e => setVideoMode(e.target.value as 'off' | 'first' | 'all')}>
              <option value="off">不出视频（最快）</option>
              <option value="first">仅首个方向出分镜</option>
              <option value="all">每个方向都出分镜</option>
            </select>
          </div>
        </div>
        <div className="setting-grid">
          <div>
            <label>品牌色（决定所有素材配色）</label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="color" value={brand} onChange={e => saveBrand(e.target.value)}
                style={{ width: 52, height: 38, padding: 2, border: '1px solid var(--border)', borderRadius: 8, background: '#fff' }} />
              <input type="text" value={brand} onChange={e => setBrand(e.target.value)} onBlur={e => saveBrand(e.target.value)} />
            </div>
          </div>
          <div>
            <label>产品图 / Logo（合成进素材，PNG 透明底最佳）</label>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => upload(e.target.files?.[0])} />
            {productImg && <div className="muted" style={{ marginTop: 4 }}>已上传：{productImg.split('/').pop()}</div>}
          </div>
        </div>
        {est && (
          <div className={'est-bar' + (est.over_limit ? ' over' : '')}>
            预计生成 <b>{est.total}</b> 个素材：{est.images} 张图 · {est.copy} 套文案
            {est.keyword > 0 && ` · ${est.keyword} 组关键词`}
            {est.video > 0 && ` · ${est.video} 条视频分镜`}
            {est.over_limit && `（超过单次上限 ${est.limit}，请减少方向或版位）`}
          </div>
        )}
        {campaign && <div className="alert ok">已生成 {campaign.materials.length} 个素材，往下可以直接优化或下载。</div>}
      </section>

      {/* ---------------- ③ 创意方向 ---------------- */}
      {angles.length > 0 && (
        <section className="card step" id="step3">
          <StepHead
            no="3"
            title="创意方向"
            desc="每个方向是一套独立创意：洞察、钩子、版式都不同。已按分析结果预选，可自行增减。"
            extra={<span className="muted">已选 {picked.length} / {angles.length}</span>}
          />
          <div className="angle-grid">
            {angles.map(a => {
              const on = picked.includes(a.key)
              const rec = report?.creative.angles.find(x => x.key === a.key)?.recommended
              return (
                <div key={a.key} className={'angle-card' + (on ? ' on' : '')}
                  onClick={() => setPicked(on ? picked.filter(x => x !== a.key) : [...picked, a.key])}>
                  <div className="ac-head">
                    <span className="ac-check">{on ? '✓' : ''}</span>
                    <b>{a.name}</b>
                    {rec && <span className="pill ok">推荐</span>}
                    <span className="ac-tpl">{TEMPLATE_LABEL[a.template || ''] || a.template}</span>
                  </div>
                  <div className="ac-hook">{a.hook}</div>
                  <div className="ac-insight">{a.insight}</div>
                  <div className="ac-meta">
                    <span className="pill off">{a.kpi}</span>
                    {(a.platform_fit || []).slice(0, 3).map(p => <span key={p} className="pill off">{p}</span>)}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="step-actions">
            <button className="btn" onClick={produce} disabled={!!busy || picked.length === 0 || !!est?.over_limit}>
              {busy.startsWith('正在按方向') ? busy : `生成 ${picked.length} 方向 × ${platforms.length} 平台素材`}
            </button>
            {busy && <span className="muted">{busy}</span>}
          </div>
        </section>
      )}

      {/* ---------------- ④ 素材与优化 ---------------- */}
      {campaign && (
        <section className="card step" id="step4">
          <StepHead
            no="4"
            title="素材与优化"
            desc="先看效果，再告诉我要改什么。每轮优化都会生成新版本，随时可以切回旧版对比。"
            extra={<span className="muted">最新版本 {stats.imgs} 张图 · {stats.copy} 套文案 · 共 {stats.versions} 版</span>}
          />

          <div className="opt-bar">
            <div className="opt-row">
              <input
                type="text"
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && instruction.trim()) runOptimize() }}
                placeholder="希望怎么改？例如：标题更短、去掉数字、突出免费试用、换成纯文字版式、主色改蓝"
              />
              <select value={scope} onChange={e => setScope(e.target.value as any)}>
                <option value="all">文案 + 图片</option>
                <option value="copy">仅文案</option>
                <option value="image">仅图片（同步文字）</option>
              </select>
              <button className="btn" onClick={runOptimize} disabled={optBusy || !instruction.trim()}>
                {optBusy ? '优化中…' : '应用优化'}
              </button>
            </div>
            <div className="opt-chips">
              <span className="muted">常用：</span>
              {OPT_TIPS.map(t => (
                <button key={t} className="opt-chip" onClick={() => setInstruction(t)}>{t}</button>
              ))}
            </div>
            {scope === 'copy' && <div className="muted">仅文案：图片保持原样，适合只调整投放文案。</div>}
            <div className="muted" style={{ marginTop: 6 }}>
              规则模式：只做能保证语义完整的调整（更短 / 去数字 / 换版式 / 换色等）；
              要整句重写请在「设置」里配置文案模型。
            </div>
            {err && <div className="alert err">{err}</div>}
          </div>

          {optRes && (
            <div className="opt-res" id="opt-result">
              <div className="or-head">
                {optRes.created > 0
                  ? <>本轮产出 <b>{optRes.created}</b> 个新素材（最新版本 v{optRes.version}）</>
                  : <>本轮没有可安全执行的改动，现有素材保持 v{optRes.version}</>}
                {optRes.rules.length > 0 && <span className="muted"> · 识别到 {optRes.rules.map(r => r.label).join('、')}</span>}
              </div>
              {optRes.warnings.length > 0 && (
                <div className={'or-warns' + (optRes.created ? '' : ' soft')}>
                  {optRes.warnings.map((w, i) => (
                    <div key={i}>{optRes.created ? '⚠ ' : '· '}{w}</div>
                  ))}
                </div>
              )}
              {optRes.applied.map(a => (
                <div key={a.rule} className="or-rule">
                  <div className="or-rule-head">
                    <b>{a.label}</b>
                    <span className="muted">{a.note}</span>
                  </div>
                  {a.changes.length === 0 && (
                    <div className="or-none">
                      {a.rule === 'template' || a.rule === 'color'
                        ? '已应用到本轮重渲染的图片'
                        : '没有可替换的完整表述，见下方说明'}
                    </div>
                  )}
                  {a.changes.map((c, i) => (
                    <div key={i} className="or-change">
                      <span className="or-field">{c.field}</span>
                      <span className="or-before">{c.before || '—'}</span>
                      <span className="or-arrow">→</span>
                      <span className="or-after">{c.after || '—'}</span>
                    </div>
                  ))}
                </div>
              ))}
              {optRes.notes.map((n, i) => <div key={i} className="muted">· {n}</div>)}
            </div>
          )}

          <div className="wall-tabs">
            <div className="wt-group">
              {(campaign.platforms || []).map(p => (
                <button key={p} className={'wt' + (plat === p ? ' on' : '')} onClick={() => setPlat(p)}>{p}</button>
              ))}
            </div>
            <div className="wt-group">
              {(campaign.options?.languages || langs).map(l => (
                <button key={l} className={'wt' + (lang === l ? ' on' : '')} onClick={() => setLang(l)}>{l}</button>
              ))}
            </div>
            {versions.length > 1 && (
              <div className="wt-group">
                {versions.map(v => (
                  <button key={v} className={'wt' + (curVer === v ? ' on' : '')} onClick={() => setVer(v)}>v{v}</button>
                ))}
              </div>
            )}
            <label className="checkline">
              <input type="checkbox" checked={validOnly} onChange={e => setValidOnly(e.target.checked)} />
              只看校验通过
            </label>
          </div>

          {visibleWall.length === 0 && (
            <div className="muted">当前筛选下没有素材，换个版本或取消「只看校验通过」。</div>
          )}

          {visibleWall.map(g => (
            <div key={g.key} className="wall-group">
              <div className="wg-head">
                <b>{g.info!.name}</b>
                <span className="ac-tpl">{TEMPLATE_LABEL[g.info!.template || '']}</span>
                <span className="muted">{g.info!.insight}</span>
              </div>
              <div className="wg-body">
                <div className="shot-row">
                  {g.imgs.map(m => (
                    <div key={m.id} className="shot">
                      <img src={api.fileUrl(m.file_path)} alt={m.spec_json?.size} onClick={() => setZoom(api.fileUrl(m.file_path))} />
                      <div className="shot-cap">
                        <span>{m.spec_json?.size}</span>
                        <span className="shot-actions">
                          <span className={'dot ' + (m.validation?.valid === false ? 'bad' : 'good')} />
                          <a href={api.downloadUrl(m.id)}>下载</a>
                        </span>
                      </div>
                    </div>
                  ))}
                  {g.imgs.length === 0 && <div className="muted">该方向在当前版本下没有图片</div>}
                </div>
                <div className="wg-side">
                  {g.copy ? <CopyBlock m={g.copy} /> : <div className="muted">没有文案素材</div>}
                  {g.kw && (
                    <div className="kw-block">
                      <div className="kf-title">搜索关键词 · {plat}</div>
                      <pre className="kw-pre">{g.kw.text_content}</pre>
                    </div>
                  )}
                  {g.video && (
                    <div className="kf-block">
                      <div className="kf-title">视频分镜（15s）· 关键帧可单独下载</div>
                      <div className="kf-row">
                        {(g.video.content?.keyframes || []).map((k: any) => (
                          <a key={k.index} href={api.fileUrl(k.file)} target="_blank" rel="noreferrer" className="kf">
                            <img src={api.fileUrl(k.file)} alt={k.scene} />
                            <span>{k.timecode}</span>
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* ---------------- ⑤ 交付下载 ---------------- */}
      {campaign && (
        <section className="card step" id="step5">
          <StepHead no="5" title="交付下载" desc="单张图直接下载；打包按「平台/方向」分目录，每组只打最新版本。" />
          <div className="deliver-stats">
            <div><b>{stats.imgs}</b><span>张图片（最新）</span></div>
            <div><b className="ok">{stats.valid}</b><span>校验通过</span></div>
            <div><b>{stats.copy}</b><span>套文案（最新）</span></div>
            <div><b>{stats.versions}</b><span>个版本</span></div>
            <div><b className="sm">{stats.history}</b><span>个素材含历史</span></div>
          </div>
          <div className="deliver-actions">
            <a className="btn" href={api.exportUrl(campaign.id)}>下载全部素材 ZIP</a>
            <a className="btn ghost" href={api.exportValidUrl(campaign.id)}>仅下载校验通过的</a>
            {fw && <a className="btn ghost" href={api.reportMdUrl(fw.id)}>下载分析报告</a>}
            <button className="btn ghost" onClick={onOpenLibrary}>进素材库</button>
          </div>
          <div className="muted" style={{ marginTop: 8 }}>
            压缩包含 manifest.json、copy.csv（逐字段文案与字数）与投放说明；历史版本不打包，需要对比请在素材墙切版本。
          </div>
        </section>
      )}

      {zoom && <div className="zoom-mask" onClick={() => setZoom('')}><img src={zoom} alt="preview" /></div>}
    </div>
  )
}
