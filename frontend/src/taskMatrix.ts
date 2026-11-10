/**
 * V4.40 / F07 · 版位任务矩阵（纯函数，可独立单测）
 *
 * 旧实现的三个问题：
 *  1) buildSlots() 把所选版位的所有尺寸展开后 `slice(0, count)`，Facebook 默认
 *     count=3 时 Stories 被静默截掉、Google 的 UAC 版位被截掉；
 *  2) 副文案池把 description / body / primary_text 混在一起取模拼接，主标题与证据
 *     可能来自完全不同的概念；
 *  3) 后端按版位顺序轮换整组文案，无法在出图前确认「哪张图用哪个概念」。
 *
 * 现在：
 *  - 适配清单 = 选中版位 × 尺寸的全量展开，只按「尺寸 + 资产角色」去重；
 *  - 概念 = 同一来源位置的标题 / 证据 / CTA，平台正文（primary_text）不进图内文案；
 *  - 概念数、每概念标题变体数、适配数与生成预算分别受控，预算不足**明确提示并禁止出图**，
 *    绝不静默截断；预览的任务数与实际请求的任务数完全一致。
 */
import type { MediaCopyResult, MediaPlatform, CopyVariant } from './api'

export interface CopyItemLike {
  key: string
  index: number
  text: string
  selected: boolean
}

export interface TaskConcept {
  id: number
  key: string
  label: string
  headline: string
  sub: string
  cta: string
  brand: string
  headlineVariants: string[]
  /** 每个字段实际取自第几条原文；0 表示复用首条（共享证据），不做取模错配 */
  sourceIndices: { headline: number; sub: number; cta: number }
  subKey: string
}

export interface TaskAdaptation {
  key: string
  placementId: string
  placement: string
  size: string
  adProduct: string
  assetRole: string
  os: string
  specVersion: string
}

export interface TaskRow {
  size: string
  placement: string
  placement_id: string
  concept_index: number
  concept_id: string
  ad_product: string
  asset_role: string
  os: string
  spec_version: string
}

export interface TaskMatrix {
  adaptations: TaskAdaptation[]
  allConcepts: TaskConcept[]
  concepts: TaskConcept[]
  tasks: TaskRow[]
  required: number
  budget: number
  budgetOk: boolean
  warnings: string[]
  droppedDuplicates: TaskAdaptation[]
  conceptCount: number
  variantsPerConcept: number
  adaptationCount: number
  assignment: 'round_robin' | 'full_cover'
  specVersion: string
}

/** 把可编辑文案摊平成逐条条目；未记录的勾选状态默认视为已选。 */
export function flatCopyItems(
  copy: MediaCopyResult | null,
  copyEdit: Record<string, any>,
  selectedCopy: Record<string, boolean[]>,
): CopyItemLike[] {
  if (!copy) return []
  const out: CopyItemLike[] = []
  for (const f of copy.schema || []) {
    const raw = (copyEdit || {})[f.key]
    const arr: any[] = Array.isArray(raw) ? raw : [raw ?? '']
    arr.forEach((v, i) => out.push({
      key: f.key,
      index: i,
      text: String(v ?? ''),
      selected: selectedCopy?.[f.key]?.[i] ?? true,
    }))
  }
  return out
}

/**
 * 由勾选文案构造「概念」：同一概念的主标题、证据（副标）与 CTA 取自同一来源位置。
 * 关键改动：
 *  - 平台正文 primary_text 不再混入图内副标（V4.39 已分离平台正文与图内文字）；
 *  - 只在 description / body 中选**一个**字段，不与其它字段混池；
 *  - 字段条数不足时复用首条（共享证据），不做 `i % len` 回绕造成的机械错配；
 *  - variantsPerConcept 把多条标题归为同一概念的标题变体，不拆成互斥概念。
 */
export function buildConcepts(args: {
  copy: MediaCopyResult | null
  copyEdit: Record<string, any>
  selectedCopy: Record<string, boolean[]>
  brand: string
  variantsPerConcept?: number
}): TaskConcept[] {
  const picked = flatCopyItems(args.copy, args.copyEdit, args.selectedCopy)
    .filter(x => x.selected && x.text.trim())
  const byKey: Record<string, CopyItemLike[]> = {}
  for (const x of picked) (byKey[x.key] ||= []).push(x)

  const headKey = ['headline', 'title'].find(k => (byKey[k] || []).length) || ''
  const subKey = ['description', 'body'].find(k => (byKey[k] || []).length) || ''
  const heads = headKey ? byKey[headKey] : []
  const subs = subKey ? byKey[subKey] : []
  const ctas = byKey['cta'] || []
  if (!heads.length && !subs.length && !ctas.length) return []

  const per = Math.max(1, Math.min(4, Math.floor(args.variantsPerConcept || 1)))
  const groups: CopyItemLike[][] = []
  for (let i = 0; i < heads.length; i += per) groups.push(heads.slice(i, i + per))
  const count = Math.max(groups.length, subs.length, ctas.length, 1)

  const out: TaskConcept[] = []
  for (let i = 0; i < count; i++) {
    const group = groups[i] || groups[0] || []
    const head = group[0] || heads[0]
    const sub = subs[i] || subs[0]
    const cta = ctas[i] || ctas[0]
    out.push({
      id: i + 1,
      key: `C${i + 1}`,
      label: `概念 ${i + 1}`,
      headline: head?.text.trim() || '',
      sub: sub?.text.trim() || '',
      cta: cta?.text.trim() || '',
      brand: args.brand || '',
      headlineVariants: group.map(x => x.text.trim()),
      sourceIndices: {
        headline: head?.index ?? 0,
        sub: sub?.index ?? 0,
        cta: cta?.index ?? 0,
      },
      subKey,
    })
  }
  return out.slice(0, 40)
}

export function toCopyVariants(concepts: TaskConcept[]): CopyVariant[] {
  return concepts.map(c => ({
    headline: c.headline,
    sub: c.sub,
    cta: c.cta,
    brand: c.brand,
    label: c.label,
    concept_id: c.key,
  }))
}

/** 选中版位 × 尺寸的全量适配清单；默认按「尺寸 + 资产角色 + OS」去重。 */
export function buildAdaptations(
  spec: MediaPlatform | null,
  selectedPlacementIds: string[],
  keepDistinctRoles = false,
): { adaptations: TaskAdaptation[]; droppedDuplicates: TaskAdaptation[] } {
  if (!spec) return { adaptations: [], droppedDuplicates: [] }
  const out: TaskAdaptation[] = []
  const droppedDuplicates: TaskAdaptation[] = []
  const seen = new Set<string>()
  for (const id of selectedPlacementIds) {
    const pl = (spec.placements || []).find(p => p.id === id)
    if (!pl) continue
    for (const size of pl.sizes || []) {
      const row: TaskAdaptation = {
        key: `${id}:${size}`,
        placementId: id,
        placement: pl.name,
        size,
        adProduct: (pl as any).ad_product || '',
        assetRole: (pl as any).asset_role || 'unspecified',
        os: (pl as any).os || 'unknown',
        specVersion: (spec as any).spec_version || '',
      }
      const key = keepDistinctRoles
        ? `${size}|${row.assetRole}|${row.adProduct}|${id}`
        : `${size}|${row.assetRole}|${row.os}`
      if (seen.has(key)) {
        droppedDuplicates.push(row)
        continue
      }
      seen.add(key)
      out.push(row)
    }
  }
  return { adaptations: out, droppedDuplicates }
}

export function buildTaskMatrix(args: {
  spec: MediaPlatform | null
  selectedPlacementIds: string[]
  keepDistinctRoles: boolean
  concepts: TaskConcept[]
  conceptCount: number
  assignment: 'round_robin' | 'full_cover'
  budget: number
}): TaskMatrix {
  const { adaptations, droppedDuplicates } = buildAdaptations(
    args.spec, args.selectedPlacementIds, args.keepDistinctRoles)
  const allConcepts = args.concepts
  const wanted = Math.max(1, Math.min(allConcepts.length || 1,
    Math.floor(args.conceptCount || 1)))
  const concepts = allConcepts.slice(0, wanted)
  const specVersion = (args.spec as any)?.spec_version || ''
  const tasks: TaskRow[] = []
  const push = (a: TaskAdaptation, ci: number) => tasks.push({
    size: a.size,
    placement: a.placement,
    placement_id: a.placementId,
    concept_index: ci,
    concept_id: concepts[ci]?.key || '',
    ad_product: a.adProduct,
    asset_role: a.assetRole,
    os: a.os,
    spec_version: specVersion,
  })

  if (args.assignment === 'full_cover' && concepts.length) {
    // 每个概念覆盖全部所选版位：便于横向比较同一承诺在不同版位的表达
    for (let ci = 0; ci < concepts.length; ci++)
      for (const a of adaptations) push(a, ci)
  } else {
    // 默认：先覆盖全部版位，概念按清单顺序分配（预览即实际结果）
    for (let i = 0; i < adaptations.length; i++)
      push(adaptations[i], concepts.length ? i % concepts.length : 0)
  }

  const budget = Math.max(1, Math.floor(args.budget || 1))
  const required = tasks.length
  const budgetOk = required <= budget
  const warnings: string[] = []
  if (!budgetOk) {
    warnings.push(`预算不足：任务清单需要 ${required} 个任务，当前预算 ${budget} 张。`
      + '系统不会静默截断版位，请提高「生成预算」或减少勾选版位后再出图。')
  }
  if (droppedDuplicates.length) {
    warnings.push(`已合并 ${droppedDuplicates.length} 个同尺寸且同资产角色的重复任务；`
      + '如确需保留不同广告产品的同尺寸素材，请开启「保留同尺寸不同广告产品」。')
  }
  if (!allConcepts.length) {
    warnings.push('尚未勾选任何创意文案，请先回到文案区至少选择一条标题 / 描述 / 正文 / CTA。')
  }
  if (args.assignment === 'round_robin' && concepts.length > adaptations.length && adaptations.length) {
    warnings.push(`本批只有 ${adaptations.length} 个版位任务，`
      + `${concepts.length} 个概念无法全部覆盖；可改用「每个概念覆盖全部版位」。`)
  }
  if (specVersion && (args.spec as any)?.spec_verified_on === '') {
    warnings.push(`媒体规则 ${specVersion} 为内部整理、尚未按平台官方文档核验；`
      + '导出会标注规则版本，不宣称符合平台审核规范。')
  }

  return {
    adaptations, allConcepts, concepts, tasks,
    required, budget, budgetOk, warnings, droppedDuplicates,
    conceptCount: concepts.length,
    variantsPerConcept: 0,
    adaptationCount: adaptations.length,
    assignment: args.assignment,
    specVersion,
  }
}

/** 供后端请求使用的精简 slots（不把前端展示字段发给服务端重新信任）。 */
export function toSlots(tasks: TaskRow[]): {
  size: string; placement: string; placement_id: string
  concept_index: number; concept_id: string
}[] {
  return tasks.map(t => ({
    size: t.size,
    placement: t.placement,
    placement_id: t.placement_id,
    concept_index: t.concept_index,
    concept_id: t.concept_id,
  }))
}
