import { useEffect, useState } from 'react'
import {
  cwTaskDismiss, cwTaskElapsedSec, formatElapsed, getCwTask,
  subscribeCwTask, type CwTaskSnapshot,
} from './cwTask'

const STATUS_TEXT: Record<string, string> = {
  running: '进行中', done: '已完成', failed: '失败', interrupted: '已中断',
}

const STAGE_ICON: Record<string, string> = {
  pending: '○', running: '◐', done: '✓', failed: '!', stopped: '–',
}

/**
 * V4.77 素材创作任务浮窗（常驻）
 *
 * 用户点「开始生成」后，无论切到哪个菜单都能在右下角看到任务进度；
 * 点击「查看任务」回到创意工作台，原来的生成流程与结果仍在（工作台改为常驻挂载）。
 * 只负责展示与跳转，任务本身的执行与状态由 CreativeWorkbench 写入 cwTask 存储。
 */
export default function CwTaskDock({ hidden, onOpen }: { hidden: boolean; onOpen: () => void }) {
  const [t, setT] = useState<CwTaskSnapshot>(getCwTask())
  const [now, setNow] = useState(Date.now())
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => subscribeCwTask(() => setT(getCwTask())), [])

  // 运行中每秒刷新已用时
  useEffect(() => {
    if (t.status !== 'running') return
    const h = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(h)
  }, [t.status, t.seq])

  if (hidden || t.status === 'idle') return null

  const elapsed = cwTaskElapsedSec(t, now)
  const pct = Math.max(0, Math.min(100, Math.round(t.progress || 0)))
  const meta = [t.product, (t.platforms || []).join(' / ')].filter(Boolean).join(' · ')
  // 中断 / 失败时没有"结果"可看，按钮语义应为「回工作台」
  const actionLabel = t.status === 'running' ? '查看任务' : (t.status === 'done' ? '查看结果' : '返回工作台')

  return (
    <div className={`cwtd cwtd-${t.status} ${collapsed ? 'is-collapsed' : ''}`}>
      <div className="cwtd-head">
        <span className="cwtd-dot" />
        <b className="cwtd-title">素材创作任务</b>
        <span className="cwtd-chip">{STATUS_TEXT[t.status] || ''}</span>
        <span className="cwtd-elapsed">
          {t.status === 'running' ? `已用 ${formatElapsed(elapsed)}` : `耗时 ${formatElapsed(elapsed)}`}
        </span>
        <button className="cwtd-mini" title={collapsed ? '展开' : '收起'}
          onClick={() => setCollapsed(v => !v)}>{collapsed ? '▴' : '▾'}</button>
        <button className="cwtd-close" title="关闭任务栏（任务不受影响）" onClick={cwTaskDismiss}>×</button>
      </div>

      {collapsed ? (
        <div className="cwtd-collapsed-bar">
          <div className="cwtd-bar"><div className="cwtd-bar-fill" style={{ width: `${pct}%` }} /></div>
          <span>{pct}%</span>
        </div>
      ) : (
        <>
          {meta && <div className="cwtd-meta" title={meta}>{meta}</div>}
          <div className="cwtd-bar"><div className="cwtd-bar-fill" style={{ width: `${pct}%` }} /></div>
          <div className="cwtd-txt">
            <span className="cwtd-pct">{pct}%</span>
            {t.statusText || (t.status === 'running' ? '处理中…' : '')}
          </div>

          {t.stages?.length > 0 && (
            <ul className="cwtd-stages">
              {t.stages.map(s => (
                <li key={s.key} className={`cwtd-stage ${s.status}`}>
                  <i>{STAGE_ICON[s.status] || '○'}</i>
                  <span>{s.label}</span>
                  {s.note && <em>{s.note}</em>}
                </li>
              ))}
            </ul>
          )}

          {t.error && <div className="cwtd-err">{t.error}</div>}

          <div className="cwtd-actions">
            <button className="btn small primary" onClick={onOpen}>{actionLabel}</button>
            {t.status !== 'running' && (
              <button className="btn small ghost" onClick={cwTaskDismiss}>知道了</button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
