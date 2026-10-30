import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, clearToken, getToken, Meta, User } from './api'
import Workspace from './pages/Workspace'
import Batch from './pages/Batch'
import Library from './pages/Library'
import Login from './pages/Login'
import Settings from './pages/Settings'
import Specs from './pages/Specs'

type Tab = 'workspace' | 'batch' | 'library' | 'specs' | 'settings'

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', manager: '投放经理', editor: '投放执行', viewer: '只读',
}

const TABS: Tab[] = ['workspace', 'batch', 'library', 'specs', 'settings']
const SB_KEY = 'admb_sidebar'

/* ---------------- 菜单结构：一级 → 二级 ---------------- */

type NavItem = { key: Tab; label: string; desc: string; icon: string }

const GROUP_MATERIAL: { name: string; icon: string; items: NavItem[] } = {
  name: '素材管理',
  icon: 'layers',
  items: [
    { key: 'workspace', label: '创作工作台', icon: 'pen',
      desc: '粘贴落地页链接 → 分析产品 → 定投放平台 → 生成素材 → 按指令优化 → 下载投放包' },
    { key: 'batch', label: '批量生成', icon: 'grid',
      desc: 'CSV 一次导入多个产品与投放组合，后台异步产出，适合批量上新与批量测试' },
    { key: 'library', label: '素材库', icon: 'image',
      desc: '按产品名 / 平台检索历史批次，查看每个方向的最新版本、校验结果与审阅状态' },
    { key: 'specs', label: '规格库', icon: 'ruler',
      desc: '各平台广告位的图片尺寸、文案字数红线与校验规则，直接约束生成结果' },
  ],
}

const SETTINGS_ITEM: NavItem = {
  key: 'settings', label: '设置', icon: 'gear',
  desc: '按用途配置大模型接口（分析 / 文案 / 图片 / 视频），并管理账号与角色权限',
}

/* ---------------- 图标 ---------------- */

const PATHS: Record<string, ReactNode> = {
  pen: <><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></>,
  grid: <>
    <rect x="3" y="3" width="7.5" height="7.5" rx="1.6" />
    <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6" />
    <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6" />
    <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6" />
  </>,
  image: <>
    <rect x="3" y="4" width="18" height="16" rx="2.4" />
    <circle cx="8.4" cy="9.4" r="1.6" />
    <path d="M21 15.6 16.4 11 7 20.4" />
  </>,
  ruler: <><path d="M3 15.6 15.6 3l5.4 5.4L8.4 21z" /><path d="M7.2 11.6l2 2M10.3 8.5l2 2M13.4 5.4l2 2" /></>,
  gear: <>
    <circle cx="12" cy="12" r="3.1" />
    <path d="M19.5 14.2a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V20a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H4a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H10a1.7 1.7 0 0 0 1-1.55V4a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V10a1.7 1.7 0 0 0 1.55 1H20a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
  </>,
  layers: <><path d="M12 3 21 8l-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></>,
  chevL: <path d="M15 6 9 12l6 6" />,
  chevR: <path d="M9 6l6 6-6 6" />,
  caret: <path d="M6 9l6 6 6-6" />,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></>,
  menu: <path d="M3 6h18M3 12h18M3 18h18" />,
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
    ...(canEdit ? (['workspace', 'batch'] as Tab[]) : []),
    'library', 'specs',
    ...(user.role === 'admin' ? (['settings'] as Tab[]) : []),
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
  const [tab, setTab] = useState<Tab>(() => tabFromHash() || 'workspace')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed)
  const [groupOpen, setGroupOpen] = useState(true)

  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('admb:unauthorized', onUnauthorized)
    return () => window.removeEventListener('admb:unauthorized', onUnauthorized)
  }, [])

  useEffect(() => {
    if (!getToken()) { setBooting(false); return }
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setBooting(false))
  }, [])

  useEffect(() => {
    if (user) api.meta().then(setMeta).catch(() => {})
  }, [user])

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
    setTab('workspace')
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
  const canReview = !!user && ['admin', 'manager'].includes(user.role)
  const isAdmin = user?.role === 'admin'

  const visibleItems = GROUP_MATERIAL.items.filter(it => isEditor || ['library', 'specs'].includes(it.key))
  const cur: NavItem = [...GROUP_MATERIAL.items, SETTINGS_ITEM].find(i => i.key === tab) || GROUP_MATERIAL.items[0]

  useEffect(() => {
    if (user) document.title = `${cur.label} · 广告管理系统`
  }, [user, cur.label])

  if (booting) return <div className="app"><div className="card">加载中…</div></div>
  if (!user) return <Login onLogin={setUser} />

  const shownName = user.display_name || user.username
  const roleText = ROLE_LABEL[user.role] !== shownName ? (ROLE_LABEL[user.role] || '') : ''

  const renderItem = (it: NavItem) => (
    <button
      key={it.key}
      className={`sb-item ${tab === it.key ? 'active' : ''}`}
      onClick={() => go(it.key)}
      title={collapsed ? it.label : undefined}
    >
      <Icon name={it.icon} size={18} />
      {!collapsed && <span className="sb-label">{it.label}</span>}
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
              <span>素材生产 · 投放包交付</span>
            </div>
          )}
          {!collapsed && (
            <button className="sb-mini" title="收起菜单" onClick={() => toggleSidebar(true)}>
              <Icon name="chevL" size={16} />
            </button>
          )}
        </div>

        <nav className="sb-nav">
          <div className={`sb-group ${!collapsed && !groupOpen ? 'closed' : ''}`}>
            <button
              className="sb-group-head"
              title={collapsed ? GROUP_MATERIAL.name : '折叠 / 展开「素材管理」'}
              onClick={() => (collapsed ? toggleSidebar(false) : setGroupOpen(v => !v))}
            >
              <Icon name={GROUP_MATERIAL.icon} size={16} />
              {!collapsed && <span className="sb-gname">{GROUP_MATERIAL.name}</span>}
              {!collapsed && <span className="sb-caret"><Icon name="caret" size={14} /></span>}
            </button>
            <div className="sb-items" hidden={!collapsed && !groupOpen}>
              {visibleItems.map(renderItem)}
            </div>
          </div>

          {isAdmin && (
            <>
              <div className="sb-sep" />
              {renderItem(SETTINGS_ITEM)}
            </>
          )}
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
              <div className="page-kicker">{tab === 'settings' ? '系统' : '素材管理'}</div>
              <h1 className="page-title">{cur.label}</h1>
              <p className="page-desc">{cur.desc}</p>
            </div>
            <div className="ph-right">
              {!isEditor && <span className="pill off">只读账号</span>}
            </div>
          </header>

          {!isEditor && (
            <div className="card">
              <div className="muted">只读账号：可查看素材库与规格库。生成/编辑需「投放执行」及以上角色。</div>
            </div>
          )}

          {tab === 'workspace' && isEditor && (
            <Workspace meta={meta} onOpenLibrary={() => go('library')} />
          )}
          {tab === 'batch' && isEditor && <Batch meta={meta} />}
          {tab === 'library' && <Library user={user} canReview={canReview} isEditor={isEditor} />}
          {tab === 'specs' && <Specs canEdit={canReview} />}
          {tab === 'settings' && isAdmin && <Settings />}
        </div>
      </main>
    </div>
  )
}
