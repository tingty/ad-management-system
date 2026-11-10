/**
 * V4.45 / A01 / A02 / A13 / D3：真实运行打包后的 creationSession.ts。
 *
 * 由 tests/test_auto_creation.py 通过 esbuild 打包后用 node 执行；
 * 只测纯前端会话状态与 localStorage 迁移，不发请求、不触发任何收费任务。
 */
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

const store = new Map()
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
}

const mod = await import(pathToFileURL(process.argv[2]).href)
const {
  bindSessionUser, clearSession, getSession, updateSession,
  setCreationMode, updateWorkspaceDefaults, planVersion, defaultWorkspace,
} = mod

const results = []
function check(name, fn) {
  fn()
  results.push(name)
}

/* A01：新建会话默认 auto，推荐结果尚未生成，不隐式收费 */
check('A01_new_session_defaults_to_auto', () => {
  bindSessionUser(101)
  const s = getSession()
  assert.equal(s.mode, 'auto')
  assert.equal(s.showAdvanced, false)
  assert.equal(s.autoContinue, false)
  assert.equal(s.recommendation, null)
  assert.equal(s.running, false)
  assert.equal(s.workspaceDefaults.country, 'US')
  assert.equal(s.workspaceDefaults.budget_cap, 0)
  assert.equal(s.workspaceDefaults.concept_count, 1)
  assert.equal(defaultWorkspace().goal, 'conversion')
})

/* A01：分析完成后写入推荐，不改动用户输入，也不会自动置 autoContinue */
check('A01_recommendation_does_not_start_task', () => {
  updateSession({
    urlInput: 'https://example.com/product',
    analysis: { url: 'https://example.com/product', evidence_snapshot_id: 'evs_test' },
    recommendation: { plan_hash: 'ph1', status: 'draft_only', delivery_grade: 'draft' },
  })
  const s = getSession()
  assert.equal(s.analysis.url, 'https://example.com/product')
  assert.equal(s.recommendation.plan_hash, 'ph1')
  assert.equal(s.autoContinue, false)
  assert.equal(s.running, false)
})

/* A13：影响策划的默认值 / 模式变化必须让计划版本失效 */
check('A13_plan_version_tracks_planning_inputs', () => {
  const before = planVersion(getSession())
  assert.equal(before, planVersion(getSession()))
  updateWorkspaceDefaults({ country: 'BR' })
  const after = planVersion(getSession())
  assert.notEqual(before, after)
  // 修改默认值后原推荐与自动继续标记必须失效，等待重新确认
  assert.equal(getSession().recommendation, null)
  assert.equal(getSession().autoContinue, false)
  setCreationMode('custom')
  assert.notEqual(planVersion(getSession()), after)
})

/* D3：模式切换不清空输入 / 既有素材，也不发起任务 */
check('D3_mode_switch_preserves_state', () => {
  updateSession({
    images: [{ id: 'i1', url: '/x.png' }],
    copy: { schema: [], fields: {} },
    autoContinue: true,
  })
  setCreationMode('auto')
  const s = getSession()
  assert.equal(s.mode, 'auto')
  assert.equal(s.images.length, 1)
  assert.equal(s.autoContinue, false)
  assert.equal(s.running, false)
  assert.ok(s.copy)
})

/* A02：旧 v2 定制会话固定迁移为 custom，输入 / 历史 / 分析全部保留，且不自动收费 */
check('A02_legacy_v2_session_migrates_to_custom', () => {
  const legacy = {
    version: 2,
    urlInput: 'https://legacy.example.com',
    textInput: '旧会话正文',
    analysis: { url: 'https://legacy.example.com', industry: 'ecommerce' },
    historyId: 4242,
    copy: { schema: [], fields: { headline: '旧文案' } },
    images: [{ id: 'old', url: '/old.png' }],
    stage: 'images_ready',
    running: true,
    jobId: 'job-legacy',
    jobSeq: 3,
    taskLogs: [{ at: 1, text: '旧日志', kind: 'ok' }],
  }
  store.set('admb:creationSession:v2:202', JSON.stringify(legacy))
  bindSessionUser(202)
  const s = getSession()
  assert.equal(s.version, 3)
  assert.equal(s.mode, 'custom')
  assert.equal(s.showAdvanced, true)
  assert.equal(s.autoContinue, false)
  assert.equal(s.recommendation, null)
  assert.equal(s.urlInput, 'https://legacy.example.com')
  assert.equal(s.textInput, '旧会话正文')
  assert.equal(s.historyId, 4242)
  assert.equal(s.copy.fields.headline, '旧文案')
  assert.equal(s.images.length, 1)
  assert.equal(s.jobId, 'job-legacy')
  assert.equal(s.jobSeq, 3)
  assert.equal(s.running, false, '刷新后不得把 running 永久卡住')
  assert.ok(s.taskLogs.some(l => l.text.includes('旧日志')))
  assert.equal(s.workspaceDefaults.country, 'US')
})

/* A02：storage key 不变，旧会话写入后仍能被同一账号再次读到 */
check('A02_storage_key_is_stable', () => {
  assert.ok(store.has('admb:creationSession:v2:202'))
  const raw = JSON.parse(store.get('admb:creationSession:v2:202'))
  assert.equal(raw.mode, 'custom')
  assert.equal(raw.version, 3)
})

/* 开发期 / 旧版半成品推荐快照必须被丢弃，不能让自动面板渲染 undefined 字段 */
check('A01_stale_recommendation_snapshot_is_discarded', () => {
  store.set('admb:creationSession:v2:303', JSON.stringify({
    version: 3, mode: 'auto',
    recommendation: { plan_hash: 'legacy', status: 'draft_only' },
    analysis: { url: 'https://example.com' },
  }))
  bindSessionUser(303)
  assert.equal(getSession().recommendation, null)
  assert.equal(getSession().mode, 'auto')
  assert.equal(getSession().analysis.url, 'https://example.com')
})

clearSession()
console.log(JSON.stringify({ ok: true, checks: results }))
