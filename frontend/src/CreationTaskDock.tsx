import { useEffect, useState } from 'react'
import {
  useCreationSession, hasActivity, milestones, selectedCount, STAGE_LABEL,
} from './creationSession'

const MILESTONE_LABELS = ['落地页分析', '广告文案', '推广图片']

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function fmtElapsed(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000))
  return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`
}

/**
 * V4.38 · 全局创作任务浮窗
 *
 * 在任意一级菜单都能看到「素材创作」的实时状态：进行中的任务不会因切页中断，
 * 点开面板可查阅阶段、耗时、产物数量与最近进度日志，一键返回工作台继续调整。
 */
export default function CreationTaskDock({ onBack }: { onBack: () => void }) {
  const s = useCreationSession()
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!s.running) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [s.running])

  if (!hasActivity(s)) return null

  const done = milestones(s)
  const activeStep = s.running
    ? (s.stage === 'analyzing' ? 0 : s.stage === 'copy' ? 1 : s.stage === 'images' ? 2 : -1)
    : -1
  const sel = selectedCount(s)
  const label = s.running ? s.taskLabel
    : s.stage === 'idle' ? '创作工作台' : (STAGE_LABEL[s.stage] || '创作工作台')
  const elapsed = s.running && s.taskStartedAt ? fmtElapsed(now - s.taskStartedAt) : ''

  const back = () => { setOpen(false); onBack() }

  return (
    <div className={`ct-dock ${open ? 'open' : ''}`}>
      {!open ? (
        <button className="ct-chip" onClick={() => setOpen(true)} title="查看素材创作任务进度">
          <span className={`ct-dot ${s.running ? 'running' : s.stage === 'error' ? 'err' : ''}`} />
          <span className="ct-chip-label">{label}</span>
          {s.running && <span className="ct-time">{elapsed}</span>}
          {s.images.length > 0 && <span className="ct-badge">{s.images.length} 张</span>}
          <span className="ct-chev">⌃</span>
        </button>
      ) : (
        <div className="ct-panel">
          <div className="ct-head">
            <div>
              <div className="ct-title">素材创作 · 任务进度</div>
              <div className="ct-sub">切换菜单不会中断任务，可随时返回继续调整</div>
            </div>
            <button className="ct-close" onClick={() => setOpen(false)} title="收起">×</button>
          </div>

          <div className="ct-state">
            <span className={`ct-pill ${s.running ? 'running' : s.stage === 'error' ? 'err' : 'ok'}`}>
              {s.running ? '进行中' : s.stage === 'error' ? '失败' : '已完成'}
            </span>
            <b>{label}</b>
            {elapsed && <span className="ct-time">已用 {elapsed}</span>}
          </div>
          {s.taskDetail && <p className="ct-detail">{s.taskDetail}</p>}
          {s.taskUpdatedAt && (
            <div className="ct-updated muted">最近更新：{fmtTime(s.taskUpdatedAt)}</div>
          )}

          <div className="ct-steps">
            {MILESTONE_LABELS.map((m, i) => (
              <div className={`ct-step ${done[i] ? 'done' : ''} ${activeStep === i ? 'active' : ''}`} key={m}>
                <span className="ct-step-no">{done[i] ? '✓' : i + 1}</span>
                <span>{m}</span>
              </div>
            ))}
          </div>

          <div className="ct-stats">
            <div className="ct-stat"><span>媒体平台</span><b>{s.platform || '—'}</b></div>
            <div className="ct-stat"><span>文案语言</span><b>{s.lang.toUpperCase()}</b></div>
            <div className="ct-stat"><span>选用文案</span><b>{s.copy ? `${sel.selected} / ${sel.total}` : '—'}</b></div>
            <div className="ct-stat"><span>推广图片</span><b>{s.images.length} 张</b></div>
            <div className="ct-stat"><span>历史会话</span><b>{s.historyId ? `#${s.historyId}` : '—'}</b></div>
            <div className="ct-stat"><span>当前步骤</span><b>{s.step} / 3</b></div>
          </div>

          {s.taskLogs.length > 0 && (
            <div className="ct-logs">
              <div className="ct-logs-title">最近进度</div>
              {s.taskLogs.slice(-5).reverse().map((l, i) => (
                <div className={`ct-log ${l.kind}`} key={`${l.at}-${i}`}>
                  <span>{fmtTime(l.at)}</span>{l.text}
                </div>
              ))}
            </div>
          )}

          <div className="ct-actions">
            <button className="btn small ghost" onClick={() => { setOpen(false); location.hash = '#/history' }}>
              查看素材历史
            </button>
            <button className="btn small primary" onClick={back}>返回素材创作 →</button>
          </div>
        </div>
      )}
    </div>
  )
}
