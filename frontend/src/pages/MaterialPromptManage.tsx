import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { PromptConfig, MaterialPromptMeta, LayerMatchResult } from '../api'

/**
 * V4.98 / V4.100 · 提示词管理（创意工作台二级菜单）
 *
 * 三类通用提示词模板：文案 / 图片 / 视频。每类展示：
 *   1. 一句话意图（intent）——这条提示词想表达什么；
 *   2. 六层心理链条可勾选（痛点识别 / 渴望激发 / 可信证据 / 能力归因 / 决策降本 / 行动收口），
 *      支持「按产品分析自动匹配」与「全选六层」；
 *   3. 中文带变量模板，变量严格对应系统真实生成逻辑（后端给变量来源说明，不臆造）。
 *
 * 数据来自后端 /api/settings/prompts?module=提示词管理 + /material-prompts/meta，
 * 与生成链路共用同一注册表；管理员编辑保存即生效（下一次进入页面读到新内容）。
 */
const keyOfType: Record<string, string> = {
  copy: 'material_prompt_copy',
  image: 'material_prompt_image',
  video: 'material_prompt_video',
}

export default function MaterialPromptManage({ canEdit }: { canEdit: boolean }) {
  const [meta, setMeta] = useState<MaterialPromptMeta | null>(null)
  const [rows, setRows] = useState<PromptConfig[]>([])
  const [active, setActive] = useState('copy')
  const [draft, setDraft] = useState<{ content: string; intent: string; layers: string[] } | null>(null)
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [matchInfo, setMatchInfo] = useState<LayerMatchResult | null>(null)

  const load = async () => {
    try {
      // V4.100：模块名从后端元数据读取，页面改名后不再依赖写死的字符串；
      // 旧模块名仍由后端兼容查询，不影响已保存模板。
      const m = await api.materialPromptMeta()
      const list = await api.prompts(m.module)
      setMeta(m)
      setRows(list)
    } catch (e: any) {
      setMsg('加载失败：' + (e?.message || '未知错误'))
    }
  }
  useEffect(() => { load() }, [])

  const current = useMemo(() => rows.find(r => r.key === keyOfType[active]), [rows, active])
  useEffect(() => {
    if (!current) { setDraft(null); return }
    setDraft({
      content: current.content || '',
      intent: current.intent || '',
      layers: (current.psychological_layers || '').split(',').map(s => s.trim()).filter(Boolean),
    })
    setMatchInfo(null)
    setMsg('')
  }, [current])

  const typeMeta = meta?.types.find(t => t.key === active)
  const variables = meta?.variables?.[active] || []
  const layers = meta?.layers || []

  const toggleLayer = (k: string) => {
    if (!draft) return
    setDraft({ ...draft, layers: draft.layers.includes(k)
      ? draft.layers.filter(x => x !== k)
      : [...draft.layers, k] })
    setMsg('')
  }

  const autoMatch = async () => {
    try {
      // 用当前工作区已保存的产品分析做匹配；无分析时用空对象，后端会给出基础层（行动收口）。
      let analysis: any = {}
      try {
        const raw = sessionStorage.getItem('cw_session_v1')
        if (raw) {
          const s = JSON.parse(raw)
          analysis = s?.analysis || s?.cwRes?.analysis || {}
        }
      } catch { /* 无会话则按空分析 */ }
      const r = await api.matchLayers(analysis)
      setMatchInfo(r)
      if (draft) setDraft({ ...draft, layers: r.layers })
      setMsg('已按产品分析匹配心理链条，可继续手动调整')
    } catch (e: any) {
      setMsg('自动匹配失败：' + (e?.message || '未知错误'))
    }
  }

  const selectAll = () => {
    if (draft) { setDraft({ ...draft, layers: layers.map(l => l.key) }); setMsg('') }
  }

  const save = async () => {
    if (!current || !draft) return
    setSaving(true)
    try {
      const updated = await api.updatePrompt(current.key, {
        content: draft.content,
        intent: draft.intent,
        psychological_layers: draft.layers.join(','),
      })
      setRows(prev => prev.map(r => r.key === updated.key ? updated : r))
      setMsg('已保存，下一次生成相关提示词时生效')
    } catch (e: any) {
      setMsg('保存失败：' + (e?.message || '未知错误'))
    } finally { setSaving(false) }
  }

  const reset = async () => {
    if (!current) return
    setSaving(true)
    try {
      const updated = await api.resetPrompt(current.key)
      setRows(prev => prev.map(r => r.key === updated.key ? updated : r))
      setMsg('已恢复系统内置默认模板')
    } catch (e: any) {
      setMsg('重置失败：' + (e?.message || '未知错误'))
    } finally { setSaving(false) }
  }

  const copy = async () => {
    if (!draft) return
    try {
      await navigator.clipboard.writeText(draft.content)
      setMsg('模板已复制')
    } catch { setMsg('复制失败，请手动选择文本') }
  }

  const th: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', fontSize: 12, color: 'var(--muted)', fontWeight: 600 }
  const td: React.CSSProperties = { padding: '8px 10px', fontSize: 12.5, verticalAlign: 'top' }

  return (
    <div className="mpm">
      <div className="mpm-head">
        <div>
          <h2>提示词管理</h2>
          <p className="muted">统一管理文案 / 图片 / 视频三类通用提示词：一句话意图、心理链条覆盖、带变量的中文模板。变量均来自系统实际生成逻辑。</p>
        </div>
      </div>

      <div className="mpm-tabs" role="tablist">
        {(meta?.types || [{ key: 'copy', label: '文案提示词' }, { key: 'image', label: '图片提示词' }, { key: 'video', label: '视频提示词' }]).map(t => (
          <button key={t.key} role="tab" aria-selected={active === t.key}
            className={`mpm-tab ${active === t.key ? 'on' : ''}`} onClick={() => setActive(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {!draft ? (
        <div className="mpm-box"><p className="muted">正在加载模板…</p></div>
      ) : (
        <>
          <section className="mpm-box">
            <h3>{typeMeta?.label || active} · 想表达什么</h3>
            <input className="mpm-input" value={draft.intent} readOnly={!canEdit}
              placeholder="一句话概括这条提示词要表达什么"
              onChange={e => setDraft({ ...draft, intent: e.target.value })} />
            {typeMeta?.desc && <p className="muted" style={{ fontSize: 12.5 }}>{typeMeta.desc}</p>}
          </section>

          <section className="mpm-box">
            <div className="mpm-row-between">
              <h3>心理链条覆盖（六层可多选）</h3>
              <div className="mpm-actions">
                {canEdit && <button className="mpm-btn ghost" onClick={autoMatch}>按产品分析自动匹配</button>}
                {canEdit && <button className="mpm-btn ghost" onClick={selectAll}>全选六层</button>}
              </div>
            </div>
            <div className="mpm-layers">
              {layers.map(l => {
                const on = draft.layers.includes(l.key)
                return (
                  <button key={l.key} type="button" disabled={!canEdit}
                    className={`mpm-layer ${on ? 'on' : ''}`} onClick={() => toggleLayer(l.key)}
                    title={l.desc}>
                    <span className={`mpm-check ${on ? 'on' : ''}`} />
                    <span><b>{l.label}</b><small>{l.desc}</small></span>
                  </button>
                )
              })}
            </div>
            {matchInfo && <p className="muted" style={{ fontSize: 12.5 }}>{matchInfo.reason}　当前覆盖：{matchInfo.labels.join(' / ') || '无'}</p>}
            <p className="muted" style={{ fontSize: 12 }}>说明：按产品分析中真实存在的字段自动匹配（有人群→渴望、有卖点→证据与能力、有竞品→痛点、有渠道→降本），效果广告一律保留行动收口；可手动全选六层。</p>
          </section>

          <section className="mpm-box">
            <div className="mpm-row-between">
              <h3>通用提示词模板（中文 · 带变量）</h3>
              <div className="mpm-actions">
                <button className="mpm-btn ghost" onClick={copy}>复制</button>
                {canEdit && <button className="mpm-btn ghost" onClick={reset} disabled={saving}>恢复默认</button>}
                {canEdit && <button className="mpm-btn primary" onClick={save} disabled={saving}>{saving ? '保存中…' : '保存'}</button>}
              </div>
            </div>
            <textarea className="mpm-template" value={draft.content} readOnly={!canEdit}
              onChange={e => setDraft({ ...draft, content: e.target.value })} />
          </section>

          <section className="mpm-box">
            <h3>变量来源（均为系统实际在用的变量名）</h3>
            <table className="mpm-table">
              <thead><tr><th style={th}>变量</th><th style={th}>来源（系统生成逻辑）</th></tr></thead>
              <tbody>
                {variables.map(v => (
                  <tr key={v.name}>
                    <td style={td}><code>{'[[' + v.name + ']]'}</code></td>
                    <td style={td}>{v.source}</td>
                  </tr>
                ))}
                {!variables.length && <tr><td colSpan={2} style={td}>暂无变量</td></tr>}
              </tbody>
            </table>
          </section>

          {msg && <div className="mpm-msg">{msg}</div>}
        </>
      )}
    </div>
  )
}
