/**
 * V4.145 · 模仿创作视频 —— 独立一级功能模块（页面骨架）。
 *
 * 本版只交付骨架：一级菜单入口 + 页面壳 + 后端任务列表只读展示 + 新建任务入口占位。
 * 不产生费用、不调用大模型、不提交视频生成。源视频获取/分析脚本/创作脚本/出片
 * 依次由 V4.146–V4.149 交付。
 *
 * 只新增本页面与 API 封装，不改动现有 4 个一级模块的布局与功能。
 */
import { useCallback, useEffect, useState } from 'react'
import { imitateVideoApi, ImitateTask } from '../api'

type Msg = { kind: 'ok' | 'err'; text: string }

const STAGE_LABEL: Record<string, string> = {
  source_acquiring: '获取源视频', analyzing: '结构分析', planning: '创作策划',
  awaiting_confirm: '待确认', submitting: '提交中', provider_pending: '模型生成中',
  downloading: '下载校验中', validating: '复核中', completed: '已完成',
}

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中', running: '进行中', succeeded: '已完成',
  needs_attention: '需关注', failed: '失败', cancelled: '已取消',
}

export default function ImitateVideo() {
  const [items, setItems] = useState<ImitateTask[]>([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<Msg | null>(null)

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
        当前为 V4.145 骨架版本：任务事实与状态机已就绪，源视频获取、分析脚本、创作脚本与出片能力将按 V4.146–V4.149 陆续交付，本版不产生任何模型费用。
      </p>

      {msg && <div className={msg.kind === 'err' ? 'err' : 'ok'} style={{ margin: '10px 0' }}>{msg.text}</div>}

      <div className="ad-panel-head" style={{ marginTop: 16 }}>
        <h3 style={{ margin: 0 }}>任务列表</h3>
        <button className="btn" onClick={() => void load()} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {loading && <div className="muted">加载中…</div>}
      {!loading && items.length === 0 && (
        <div className="muted" style={{ padding: '24px 0' }}>
          暂无任务。新建任务入口将在 V4.146（源视频获取）交付后开放。
        </div>
      )}
      {!loading && items.length > 0 && (
        <table className="ad-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>状态</th>
              <th>阶段</th>
              <th>来源</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            {items.map(t => (
              <tr key={t.job_id}>
                <td>{t.name || t.job_id}</td>
                <td>{STATUS_LABEL[t.status] || t.status}</td>
                <td>{t.stage ? (STAGE_LABEL[t.stage] || t.stage) : '—'}</td>
                <td>{t.source || '—'}</td>
                <td>{t.created_at || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
