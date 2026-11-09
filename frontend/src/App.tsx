import { useEffect, useState, Fragment } from 'react'
import type { ReactNode } from 'react'
import { api, clearToken, getToken, User } from './api'
import { bindSessionUser } from './creationSession'
import CreationTaskDock from './CreationTaskDock'
import MaterialCreation from './pages/MaterialCreation'
import MaterialPromptLibrary from './pages/MaterialPromptLibrary'
import MaterialHistory from './pages/MaterialHistory'
import Login from './pages/Login'
import LLMSettings from './pages/LLMSettings'
import Accounts from './pages/Accounts'
import Logs from './pages/Logs'
import ReleaseNotes from './pages/ReleaseNotes'

/* V4.37：移除「素材管理」（创作工作台 / 批量生成 / 素材库 / 规格库）
   与系统设置中的「提示词管理」；保留「素材创作平台」与必要的系统设置。 */
type Tab = 'creation' | 'matprompts' | 'history'
  | 'llm' | 'accounts' | 'logs' | 'releasenotes'

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', manager: '投放经理', editor: '投放执行', viewer: '只读',
}

const TABS: Tab[] = ['creation', 'matprompts', 'history', 'llm', 'accounts', 'logs', 'releasenotes']
const SB_KEY = 'admb_sidebar'

/* ---------------- 菜单结构：一级 → 二级 ---------------- */

type NavItem = { key: Tab; label: string; desc: string; icon: string }
type NavGroup = { name: string; icon: string; items: NavItem[] }

const GROUP_CREATION: NavGroup = {
  name: '素材创作平台',
  icon: 'wand',
  items: [
    { key: 'creation', label: '素材创作', icon: 'sparkles',
      desc: '输入落地页链接或正文，调用已配置的大模型推理，输出 8 项关键分析并标注实际调用模型；分析完成后，直接在本模块内基于分析结论进行营销推广设置（选平台 → 文案 → 生成推广图片）' },
    { key: 'matprompts', label: '素材提示词', icon: 'tags',
      desc: '集中管理「素材创作」全部提示词：按功能类型 / 使用类型分类检索与编辑；内置广告推广文案与推广图片的优秀提示词总结库，可按类型 / 风格 / 场景 / 覆盖对象四维筛选并选择系统默认，保存即生效' },
    { key: 'history', label: '素材历史', icon: 'history',
      desc: '归档已分析整理的网站、广告文案与推广图片；可放大查阅、单张或打包再下载，复用分析结论继续创作以避免重复生成，并支持批量删除历史信息' },
  ],
}

const GROUP_SYSTEM: NavGroup = {
  name: '系统设置',
  icon: 'gear',
  items: [
    { key: 'llm', label: '大模型配置', icon: 'cpu',
      desc: '按用途（分析 / 文案 / 图片 / 视频）配置大模型接口，保存即热切换，可测试连通性' },
    { key: 'accounts', label: '账号', icon: 'user',
      desc: '创建与管理账号、分配角色权限；创建或编辑在弹窗中完成' },
    { key: 'logs', label: '日志', icon: 'filetext',
      desc: '审计日志：登录、配置变更、账号操作、提示词修改等关键动作可追溯' },
    { key: 'releasenotes', label: '新版通知', icon: 'bell',
      desc: '每次优化与变更按版本汇总：涉及模块、变更类型、功能说明、影响范围与验证结果；发版前整理并发布，存在未读新版本时菜单项显示红点提示' },
  ],
}

/* ---------------- 图标 ---------------- */

const PATHS: Record<string, ReactNode> = {
  gear: <>
    <circle cx="12" cy="12" r="3.1" />
    <path d="M19.5 14.2a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V20a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H4a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H10a1.7 1.7 0 0 0 1-1.55V4a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V10a1.7 1.7 0 0 0 1.55 1H20a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
  </>,
  chevL: <path d="M15 6 9 12l6 6" />,
  caret: <path d="M6 9l6 6 6-6" />,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></>,
  cpu: <>
    <rect x="5" y="5" width="14" height="14" rx="2" />
    <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
    <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
  </>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-3.9 3.6-6.5 8-6.5s8 2.6 8 6.5" /></>,
  filetext: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h6" /></>,
  sparkles: <><path d="M12 3l1.8 4.8L18.6 9.6 13.8 11.4 12 16.2 10.2 11.4 5.4 9.6 10.2 7.8z" /><path d="M19 14l.9 2.3 2.3.9-2.3.9L19 21l-.9-2.3-2.3-.9 2.3-.9z" /></>,
  wand: <><path d="M5.5 18.5 14 10" /><path d="M15 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1z" /></>,
  tags: <><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7.2-7.2A2 2 0 0 1 3 11.8V5a2 2 0 0 1 2-2h6.8a2 2 0 0 1 1.4.6l7.4 7.4a2 2 0 0 1 0 2.8z" /><circle cx="7.5" cy="7.5" r="1.5" /></>,
  bell: <><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></>,
  history: <><path d="M3.2 8A9 9 0 1 1 3 12" /><path d="M3 3v5h5" /><path d="M12 7v5l3.2 2" /></>,
}

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  )
}

/* ---------------- 路由（hash 同步，刷新/后退不丢位置） ---------------- */

function tabFromHash(): Tab | null {
  const h = location.hash.replace(/^#\/?/, '').split('?')[0]
  return (TABS as string[]).includes(h) ? (h as Tab) : null
}

function allowedTabs(user: User): Tab[] {
  const canEdit = ['admin', 'manager', 'editor'].includes(user.role)
  return [
    ...(canEdit ? (['creation', 'matprompts', 'history'] as Tab[]) : []),
    ...(user.role === 'admin' ? (['llm', 'accounts', 'logs'] as Tab[]) : []),
    // 「新版通知」对所有角色开放，方便用户随时查阅每次优化与变更的版本内容
    'releasenotes',
  ]
}

function readCollapsed(): boolean {
  const v = localStorage.getItem(SB_KEY)
  if (v === '1') return true
  if (v === '0') return false
  return window.innerWidth < 1180
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [booting, setBooting] = useState(true)
  const [tab, setTab] = useState<Tab>(() => tabFromHash() || 'creation')
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed)
  const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>({ creation: true, system: true })
  // 版本发布「新版通知」红点：记录最新版本号 + 已读事件触发重算
  const [releaseLatest, setReleaseLatest] = useState<string | null>(null)
  const [seenTick, setSeenTick] = useState(0)

  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('admb:unauthorized', onUnauthorized)
    return () => window.removeEventListener('admb:unauthorized', onUnauthorized)
  }, [])

  // V4.38：创作会话按登录用户隔离持久化；切换账号不会串会话，重新登录可恢复上次进度。
  useEffect(() => { bindSessionUser(user?.id ?? null) }, [user?.id])

  useEffect(() => {
    if (!getToken()) { setBooting(false); return }
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setBooting(false))
  }, [])

  // 拉取最新版本号，用于「新版通知」红点提示
  useEffect(() => {
    if (!user) return
    api.releaseNotes().then((d) => setReleaseLatest(d.latest)).catch(() => {})
  }, [user])

  // ReleaseNotes 页打开即视为已读，触发红点重算
  useEffect(() => {
    const onSeen = () => setSeenTick((t) => t + 1)
    window.addEventListener('admb:releaseSeen', onSeen)
    return () => window.removeEventListener('admb:releaseSeen', onSeen)
  }, [])

  useEffect(() => {
    const onHash = () => { const t = tabFromHash(); if (t) setTab(t) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // 窗口变窄自动收起；变宽时只有用户没手动设置过才自动展开，尊重手动选择
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1180) setCollapsed(true)
      else if (localStorage.getItem(SB_KEY) === null) setCollapsed(false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const toggleSidebar = (v: boolean) => {
    setCollapsed(v)
    localStorage.setItem(SB_KEY, v ? '1' : '0')
  }

  const go = (t: Tab) => {
    setTab(t)
    if (tabFromHash() !== t) location.hash = '#/' + t
  }

  const logout = () => {
    clearToken()
    setUser(null)
    setTab('creation')
    location.hash = ''
  }

  useEffect(() => {
    if (!user) return
    const allowed = allowedTabs(user)
    if (!allowed.includes(tab)) { go(allowed[0]); return }
    // 直接访问 / 刷新时 URL 可能没有 hash，补上让地址栏与当前页保持一致
    if (!tabFromHash()) location.hash = '#/' + tab
  }, [user, tab])

  const isEditor = !!user && ['admin', 'manager', 'editor'].includes(user.role)
  const isAdmin = user?.role === 'admin'

  const visibleGroups: NavGroup[] = [GROUP_CREATION, GROUP_SYSTEM]
    .map(g => ({
      ...g,
      items: g.items.filter(it =>
        it.key === 'releasenotes' ? true : (g === GROUP_CREATION ? isEditor : isAdmin)),
    }))
    .filter(g => g.items.length > 0)
  const allItems: NavItem[] = visibleGroups.flatMap(g => g.items)
  const cur: NavItem = allItems.find(i => i.key === tab) || allItems[0] || GROUP_CREATION.items[0]
  const curGroup = visibleGroups.find(g => g.items.some(i => i.key === tab))

  useEffect(() => {
    if (user) document.title = `${cur.label} · 广告管理系统`
  }, [user, cur.label])

  if (booting) return <div className="app"><div className="card">加载中…</div></div>
  if (!user) return <Login onLogin={setUser} />

  const shownName = user.display_name || user.username
  const roleText = ROLE_LABEL[user.role] !== shownName ? (ROLE_LABEL[user.role] || '') : ''

  const lastSeen = localStorage.getItem('admb_lastRelease')
  const hasNewRelease = !!releaseLatest && releaseLatest !== lastSeen

  const renderItem = (it: NavItem) => (
    <button
      key={it.key}
      className={`sb-item ${tab === it.key ? 'active' : ''}`}
      onClick={() => go(it.key)}
      title={collapsed ? it.label : undefined}
    >
      <Icon name={it.icon} size={18} />
      {!collapsed && <span className="sb-label">{it.label}</span>}
      {it.key === 'releasenotes' && hasNewRelease && (
        <span className="sb-dot" title="有未读的新版本" />
      )}
    </button>
  )

  return (
    <div className={`shell ${collapsed ? 'sb-collapsed' : ''}`}>
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
        <div className="sb-brand">
          <button
            className={`sb-logo ${collapsed ? 'clickable' : ''}`}
            onClick={collapsed ? () => toggleSidebar(false) : undefined}
            title={collapsed ? '展开菜单' : '广告管理系统'}
          >
            广
          </button>
          {!collapsed && (
            <div className="sb-brand-txt">
              <b>广告管理系统</b>
              <span>素材创作 · 版本通知</span>
            </div>
          )}
          {!collapsed && (
            <button className="sb-mini" title="收起菜单" onClick={() => toggleSidebar(true)}>
              <Icon name="chevL" size={16} />
            </button>
          )}
        </div>

        <nav className="sb-nav">
          {visibleGroups.map((g, i) => {
            const openKey = g === GROUP_CREATION ? 'creation' : 'system'
            return (
              <Fragment key={openKey}>
                {i > 0 && <div className="sb-sep" />}
                <div className={`sb-group ${!collapsed && !groupOpen[openKey] ? 'closed' : ''}`}>
                  <button
                    className="sb-group-head"
                    title={collapsed ? g.name : `折叠 / 展开「${g.name}」`}
                    onClick={() => (collapsed ? toggleSidebar(false) : setGroupOpen(v => ({ ...v, [openKey]: !v[openKey] })))}
                  >
                    <Icon name={g.icon} size={16} />
                    {!collapsed && <span className="sb-gname">{g.name}</span>}
                    {!collapsed && <span className="sb-caret"><Icon name="caret" size={14} /></span>}
                  </button>
                  <div className="sb-items" hidden={!collapsed && !groupOpen[openKey]}>
                    {g.items.map(renderItem)}
                  </div>
                </div>
              </Fragment>
            )
          })}
        </nav>

        <div className="sb-foot">
          <div className="sb-avatar" title={shownName}>{shownName.slice(0, 1)}</div>
          {!collapsed && (
            <div className="sb-user-txt">
              <b>{shownName}</b>
              {roleText && <span>{roleText}</span>}
            </div>
          )}
          <button className="sb-logout" onClick={logout} title="退出登录">
            <Icon name="logout" size={16} />
            {!collapsed && <span>退出</span>}
          </button>
        </div>
      </aside>

      <main className="main">
        <div className="main-inner">
          <header className="page-head">
            <div className="ph-left">
              <div className="page-kicker">{curGroup?.name || '素材创作平台'}</div>
              <h1 className="page-title">{cur.label}</h1>
              <p className="page-desc">{cur.desc}</p>
            </div>
            <div className="ph-right">
              {!isEditor && <span className="pill off">只读账号</span>}
            </div>
          </header>

          {!isEditor && (
            <div className="card">
              <div className="muted">只读账号：可查阅「新版通知」与版本更新内容；素材创作与系统设置需相应权限。</div>
            </div>
          )}

          {/* V4.38：「素材创作」常驻挂载。切到其它菜单只是隐藏，不会卸载组件，
              因此正在进行的分析 / 文案 / 图片请求继续运行，回来后状态与结果完整保留。 */}
          {isEditor && (
            <div style={{ display: tab === 'creation' ? undefined : 'none' }}>
              <MaterialCreation />
            </div>
          )}
          {tab === 'matprompts' && isEditor && <MaterialPromptLibrary isAdmin={isAdmin} />}
          {tab === 'history' && isEditor && <MaterialHistory />}
          {tab === 'llm' && isAdmin && <LLMSettings />}
          {tab === 'accounts' && isAdmin && <Accounts />}
          {tab === 'logs' && isAdmin && <Logs />}
          {tab === 'releasenotes' && <ReleaseNotes />}
        </div>
      </main>

      {/* V4.38：全局创作任务浮窗，任意页面都能查阅进度并一键返回工作台 */}
      {isEditor && <CreationTaskDock onBack={() => go('creation')} />}
    </div>
  )
}
