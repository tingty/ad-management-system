/**
 * V4.137：全系统时间展示统一为东八区北京时间。
 *
 * 背景：后端数据库统一存 UTC，SQLite 取回后丢失 tzinfo，多数接口直接输出
 * "2026-11-25T02:51:00" 这类**不带时区后缀**的字符串。浏览器会把这种字符串
 * 当作"本地时间"解析，界面显示的其实是 UTC 钟点，比北京时间少 8 小时。
 *
 * 统一口径：
 *   1. 无时区后缀 → 视为 UTC，补 Z 后解析（这是后端 naive UTC 的真实含义）；
 *   2. 带 Z / +08:00 等后缀 → 原样解析；
 *   3. 纯日期 YYYY-MM-DD → 按北京时间当天 00:00 处理，避免 UTC 解析跨日；
 *   4. 展示一律用 Intl.DateTimeFormat 强制 timeZone=Asia/Shanghai，
 *      即使浏览器运行在 UTC 环境也稳定显示北京时间。
 */
export const BEIJING_TIME_ZONE = 'Asia/Shanghai'

const HAS_TZ = /(?:Z|[+-]\d{2}:?\d{2})$/i
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/** 把后端返回的时间值解析为真实时刻；无法解析返回 null。 */
export function parseBackendTime(
  value: string | number | Date | null | undefined,
): Date | null {
  if (value === null || value === undefined || value === '') return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const s = String(value).trim()
  if (!s) return null
  // 纯日期（如 event_date）按北京当天零点，不套 UTC，避免日期整体偏移一天。
  if (DATE_ONLY.test(s)) {
    const d = new Date(`${s}T00:00:00+08:00`)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const normalized = HAS_TZ.test(s) ? s : `${s.replace(' ', 'T')}Z`
  const d = new Date(normalized)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 解析为毫秒时间戳，供计时 / 比较使用（与展示同一口径）。 */
export function parseBackendMs(
  value: string | number | Date | null | undefined,
): number {
  const d = parseBackendTime(value)
  return d ? d.getTime() : NaN
}

const formatter = (withSeconds: boolean) =>
  new Intl.DateTimeFormat('en-US', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hourCycle: 'h23',
  })

const p2 = (n: string) => n.padStart(2, '0')

/** 统一格式化为北京时间 YYYY-MM-DD HH:mm[:ss]；空值/非法值返回 fallback。 */
export function fmtBeijing(
  value: string | number | Date | null | undefined,
  opts?: { seconds?: boolean; fallback?: string },
): string {
  const fallback = opts?.fallback ?? '—'
  const d = parseBackendTime(value)
  if (!d) return fallback
  const parts = formatter(!!opts?.seconds).formatToParts(d)
  const get = (type: string) => parts.find(p => p.type === type)?.value || ''
  const date = `${get('year')}-${p2(get('month'))}-${p2(get('day'))}`
  const time = `${p2(get('hour'))}:${p2(get('minute'))}${opts?.seconds ? `:${p2(get('second'))}` : ''}`
  return `${date} ${time}`
}

/** 北京时间当天的 YYYY-MM-DD（用于查询窗口默认值，不受浏览器时区影响）。 */
export function beijingToday(offsetDays = 0): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date())
  const get = (type: string) => parts.find(p => p.type === type)?.value || ''
  const d = new Date(`${get('year')}-${p2(get('month'))}-${p2(get('day'))}T00:00:00+08:00`)
  d.setDate(d.getDate() + offsetDays)
  return fmtBeijing(d).slice(0, 10)
}
