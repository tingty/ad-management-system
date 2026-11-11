import { useState } from 'react'

function goTab(t: string) {
  location.hash = '#/' + t
}

const PLATFORMS = ['Facebook / Meta', 'Google Search', 'Unity', 'Adsterra', '移动应用广告位', '激励视频']

const CAPABILITIES = [
  {
    no: 1,
    title: '产品智能分析',
    tag: '需求 1',
    body: '输入落地页 / 应用链接或产品信息，调用已配置的大模型综合分析行业、产品、类型、目标人群、需求痛点与产品优势，并据此推荐适配的推广媒体。',
    to: 'creation', toLabel: '进入创意创作',
  },
  {
    no: 2,
    title: '媒体规格库',
    tag: '需求 2',
    body: '按大媒体广告位逐条列出素材规格与要求（图片尺寸 / 比例、视频规格、文案字数限制），只有匹配规格的素材才能上架对应媒体广告位。',
    to: 'mediaspec', toLabel: '查看媒体规格',
  },
  {
    no: 3,
    title: '创意提示词体系',
    tag: '需求 3',
    body: '分析全球高转化、强吸引力的优质素材，归纳其类型 / 风格 / 场景，沉淀为可复用的提示词，直接应用于图片与视频创作。',
    to: 'matprompts', toLabel: '管理创意提示词',
  },
  {
    no: 4,
    title: '全自动创作流程',
    tag: '需求 4',
    body: '对话式引导：用户仅需输入链接、选择媒体，系统调用大模型自动规划完整创意路线，生成图片 / 视频，并支持放大查阅与下载。',
    to: 'creation', toLabel: '开始自动化创作',
  },
  {
    no: 5,
    title: '历史创意素材库',
    tag: '需求 5',
    body: '归档已创作的素材与视频，支持放大查阅、单张或打包下载，可复用分析结论继续创作，也支持局部修改优化后再下载。',
    to: 'history', toLabel: '打开创意素材库',
  },
]

const STEPS = [
  { t: '输入', d: '落地页 / 应用链接或关键产品信息' },
  { t: '分析', d: '大模型输出结构化产品分析，并推荐推广媒体' },
  { t: '选规格', d: '按所选媒体自动匹配广告位素材规格' },
  { t: '对话规划', d: '系统在对话框展示规划，需人工决策处提供选项' },
  { t: '生成', d: '调用大模型生成图片 / 视频（多风格、多场景）' },
  { t: '确认下载', d: '放大查阅、局部优化、下载到本地' },
]

const PRINCIPLES = [
  '流程自动化：人工仅介入必要信息输入与重要决策',
  '提示词管理：可更新与同步，吸收全球优秀投放师的素材敏感度',
  '布局简洁：突出重点，非重要信息默认不展示',
  '全部调用已配置大模型完成分析 / 创意 / 图片 / 视频生成',
]

export default function CreativeWorkbench() {
  const [url, setUrl] = useState('')
  const [picked, setPicked] = useState<string[]>([])

  const toggle = (p: string) =>
    setPicked((s) => (s.includes(p) ? s.filter((x) => x !== p) : [...s, p]))

  const start = () => { goTab('creation') }

  return (
    <div>
      {/* 模块定位与背景 */}
      <div className="card">
        <h2>模块定位与需求背景</h2>
        <p className="muted" style={{ lineHeight: 1.7, marginTop: -4 }}>
          <b style={{ color: 'var(--text)' }}>创意工作台</b> 是面向效果营销的
          「落地页 / 官网 / 应用」创意素材与创意视频一站式创作系统。
        </p>
        <p className="muted" style={{ lineHeight: 1.7 }}>
          我们是一家效果营销公司，帮助广告主获取用户增长、产生广告效果，主营电商产品推广、应用推广与用户线索获取等在线效果广告。
          针对广告主的产品落地页、应用等，需要创作适配主流大媒体的推广素材与视频，当前覆盖
          Facebook、Google Search、Unity、Adsterra 等，以及移动应用广告位与激励视频。
        </p>
      </div>

      {/* 五大核心能力 */}
      <div className="card">
        <h2>五大核心能力</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
          {CAPABILITIES.map((c) => (
            <div key={c.no} style={{
              border: '1px solid var(--border)', borderRadius: 10, padding: '14px 15px',
              display: 'flex', flexDirection: 'column', gap: 8, background: '#fbfdff',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 24, height: 24, borderRadius: 6, background: 'var(--primary)', color: '#fff',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, fontWeight: 700,
                }}>{c.no}</span>
                <b style={{ fontSize: 14.5 }}>{c.title}</b>
                <span className="pill" style={{ marginLeft: 'auto', background: '#eef2f7', color: 'var(--primary2)' }}>{c.tag}</span>
              </div>
              <p className="muted" style={{ lineHeight: 1.62, margin: 0, fontSize: 12.8 }}>{c.body}</p>
              <button className="btn ghost" style={{ alignSelf: 'flex-start', padding: '6px 12px', fontSize: 12.5 }}
                onClick={() => goTab(c.to)}>{c.toLabel} →</button>
            </div>
          ))}
        </div>
      </div>

      {/* 自动化创作流程 */}
      <div className="card">
        <h2>自动化创作流程</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }}>
          {STEPS.map((s, i) => (
            <div key={s.t} style={{
              border: '1px solid var(--border)', borderRadius: 10, padding: '12px 13px', position: 'relative',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
                <span style={{
                  minWidth: 20, height: 20, padding: '0 6px', borderRadius: 10, background: 'var(--primary2)',
                  color: '#fff', fontSize: 11.5, fontWeight: 700, display: 'inline-flex', alignItems: 'center',
                }}>{i + 1}</span>
                <b style={{ fontSize: 13.5 }}>{s.t}</b>
              </div>
              <p className="muted" style={{ lineHeight: 1.55, margin: 0, fontSize: 12.5 }}>{s.d}</p>
            </div>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 10, fontSize: 12.5 }}>
          优先采用全自动流程：用户输入必要信息 → 系统在对话框中自动规划与确认 → 最终产出可下载素材。
          对无法自动确认或需人工决策的环节，系统在对话框中直接提供选项供用户选择。
        </p>
      </div>

      {/* 媒体覆盖 + 设计要求 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <h2>覆盖媒体</h2>
          <div className="chip-row">
            {PLATFORMS.map((p) => (
              <span key={p} className="chip">{p}</span>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 10, fontSize: 12.5, lineHeight: 1.6 }}>
            素材规格以「媒体规格」页为准；在创意创作中按所选媒体自动校验广告位要求。
          </p>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <h2>设计要求</h2>
          <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--muted)', fontSize: 12.8, lineHeight: 1.9 }}>
            {PRINCIPLES.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      </div>

      {/* 快速开始 */}
      <div className="card" style={{ marginTop: 16, background: 'linear-gradient(180deg,#f5f9ff,#ffffff)' }}>
        <h2>快速开始</h2>
        <p className="muted" style={{ marginTop: -4, fontSize: 12.8 }}>
          输入落地页或产品链接，选择目标媒体，即可进入自动化创作流程。
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
          <label style={{ flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span className="muted" style={{ fontSize: 12 }}>落地页 / 产品链接</span>
            <input
              className="input"
              style={{ padding: '9px 11px', border: '1px solid var(--border)', borderRadius: 8, fontSize: 13 }}
              placeholder="https://example.com/landing-page"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <div style={{ flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span className="muted" style={{ fontSize: 12 }}>目标媒体（可多选）</span>
            <div className="chip-row">
              {PLATFORMS.map((p) => (
                <button key={p} type="button"
                  className={`chip ${picked.includes(p) ? 'on' : ''}`}
                  onClick={() => toggle(p)}>{p}</button>
              ))}
            </div>
          </div>
          <button className="btn" style={{ padding: '10px 22px' }} onClick={start}>
            开始创作 →
          </button>
        </div>
      </div>
    </div>
  )
}
