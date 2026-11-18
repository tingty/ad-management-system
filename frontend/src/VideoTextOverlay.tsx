import React, { useState } from 'react'

/**
 * V4.94 阶段二 · 播放层文字叠加。
 *
 * 视频模型只负责无字画面；品牌名 / CTA 由这里的 DOM 逐字渲染，从根上避开
 * 模型画字必然出现的错拼、缺字与乱码。文案只来自后端黄金词典下发的
 * text_overlay，前端不自行拼装、也不改写；下载的原片保持零文字。
 */
export default function VideoTextOverlay({ spec }: { spec?: any }) {
  const [visible, setVisible] = useState(true)
  const items: any[] = spec?.enabled ? (spec.items || []) : []
  if (!items.length) return null

  return (
    <>
      <div className="vs-overlay-layer" style={{ display: visible ? 'block' : 'none' }}>
        {items.map((it, i) => (
          <span
            key={i}
            className={`vs-overlay-text vs-overlay-${it.role || 'brand'} vs-overlay-pos-${it.position || 'top-left'}`}
          >
            {String(it.text || '')}
          </span>
        ))}
      </div>
      <button
        type="button"
        className="vs-overlay-toggle"
        onClick={(e) => { e.preventDefault(); setVisible(v => !v) }}
        title="品牌字样由播放器叠加，下载的原片无字"
      >
        {visible ? '隐藏叠加字' : '显示叠加字'}
      </button>
    </>
  )
}
