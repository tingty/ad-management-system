type Spec = {
  platform: string
  kind: string
  placements: string[]
  image: string
  video: string
  copy: string
  note: string
}

const SPECS: Spec[] = [
  {
    platform: 'Facebook / Meta',
    kind: '社交 · 信息流 / 视频',
    placements: ['Feed 信息流', 'Story', 'Reels', 'In-Stream 视频'],
    image: '1080×1080（1:1）、1200×628（1.91:1）；JPG / PNG；≤ 30MB',
    video: '4:5（1080×1350）、1:1、9:16 Reels（1080×1920）；MP4 / MOV；时长 1s–240s（建议 ≤ 15s）；≤ 4GB',
    copy: '标题 ≤ 25 字符、正文 ≤ 125 字符、CTA 按钮固定',
    note: '视频默认静音自动播放，前 3 秒需有强钩子；避免过多文字叠加。',
  },
  {
    platform: 'Google Search',
    kind: '搜索 · 响应式广告',
    placements: ['搜索文字广告', 'Discovery 发现广告', 'YouTube'],
    image: '1200×628（1.91:1）推荐；JPG / PNG / GIF（静态）；≥ 600×314',
    video: '16:9、4:5、1:1；MP4 / MOV；时长 5s–90s；YouTube 建议 12s 以上',
    copy: '标题 ≤ 30 字符（可多条）、描述 ≤ 90 字符、最终网址必填',
    note: '需通过政策审核；素材须与落地页内容一致，禁止夸大与仿冒。',
  },
  {
    platform: 'Unity',
    kind: '游戏内 · 激励 / 插屏',
    placements: ['Rewarded 激励视频', 'Interstitial 插屏', 'Banner'],
    image: '插屏 1024×768 / 768×1024；Banner 320×50、300×250；JPG / PNG',
    video: '16:9（1280×720）或 9:16；MP4；激励视频 15s–30s、插屏 ≤ 30s',
    copy: 'End Card 需含 CTA；文案避免虚假奖励承诺',
    note: '禁止欺骗性「假装关闭」按钮；激励视频须真实可发放奖励，不可强制跳过。',
  },
  {
    platform: 'Adsterra',
    kind: '广告网络 · 展示 / 原生 / Pop',
    placements: ['Native 原生', 'Display Banner', 'Popunder', 'Interstitial'],
    image: 'Banner 300×250、728×90、300×600、320×50；JPG / PNG / GIF；≤ 150KB',
    video: '480×360 / 640×480；MP4；时长 5s–60s；≤ 50MB',
    copy: '原生广告标题 ≤ 60 字符、描述简洁；禁止误导点击',
    note: '严格合规：禁止成人、赌博、仿冒及落地页跳转欺诈；需通过审核。',
  },
  {
    platform: '移动应用广告位（通用）',
    kind: '应用内 · 激励 / 插屏 / 原生',
    placements: ['Rewarded 激励视频', 'Interstitial 插屏', 'Native 原生'],
    image: '原生 1200×627；插屏 1:1 / 3:2；JPG / PNG',
    video: '16:9 或 9:16；MP4；激励 15s–30s、插屏 ≤ 30s；清晰无黑边',
    copy: 'CTA 明确（如「领取奖励」「继续」）；避免诱导误触',
    note: '奖励须真实可发放；插屏需提供关闭按钮且触发频次受限。',
  },
]

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, padding: '7px 0', borderTop: '1px dashed var(--border)' }}>
      <span style={{ flex: '0 0 72px', color: 'var(--primary2)', fontSize: 12.5, fontWeight: 600 }}>{label}</span>
      <span className="muted" style={{ flex: 1, fontSize: 12.6, lineHeight: 1.6 }}>{value}</span>
    </div>
  )
}

export default function MediaSpecs() {
  return (
    <div>
      <div className="card">
        <h2>大媒体素材规格库</h2>
        <p className="muted" style={{ marginTop: -4, lineHeight: 1.65, fontSize: 12.8 }}>
          大媒体平台是素材创作的依据——只有匹配广告位规格的素材才能上架。以下为当前覆盖媒体的图片 / 视频 / 文案规格与合规要求，
          实际以各媒体最新政策为准；在「创意创作」中按所选媒体自动校验。
        </p>
        <div className="chip-row" style={{ marginTop: 6 }}>
          {SPECS.map((s) => <span key={s.platform} className="chip">{s.platform}</span>)}
        </div>
      </div>

      {SPECS.map((s) => (
        <div key={s.platform} className="card">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0 }}>{s.platform}</h2>
            <span className="pill" style={{ background: '#eef2f7', color: 'var(--primary2)' }}>{s.kind}</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0 4px' }}>
            {s.placements.map((p) => <span key={p} className="chip">{p}</span>)}
          </div>
          <Row label="图片" value={s.image} />
          <Row label="视频" value={s.video} />
          <Row label="文案" value={s.copy} />
          <Row label="注意" value={s.note} />
        </div>
      ))}
    </div>
  )
}
