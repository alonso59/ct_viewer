// Intl-based formatting (FE-11). English locale in v3.
const nf = new Intl.NumberFormat('en', { maximumFractionDigits: 2 })
const nf1 = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })
const nf0 = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })
const df = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' })
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

export const fmtNum = (v: number) => (Math.abs(v) >= 1000 ? nf0.format(v) : nf.format(v))
export const fmt1 = (v: number) => nf1.format(v)
export const fmtInt = (v: number) => nf0.format(v)
export const fmtDate = (iso: string) => df.format(new Date(iso))

export function fmtAgo(iso: string, now = Date.now()): string {
  const s = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(s)
  if (abs < 60) return rtf.format(s, 'second')
  if (abs < 3600) return rtf.format(Math.round(s / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(s / 3600), 'hour')
  return rtf.format(Math.round(s / 86400), 'day')
}

export function fmtDuration(sec: number): string {
  if (sec < 60) return `${Math.round(sec)} s`
  const m = Math.floor(sec / 60)
  return `${m} min ${Math.round(sec % 60)} s`
}

/** Bytes with the unit that fits (decimal units, as file managers show them; AUD-A2-13) */
export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let u = 0
  while (v >= 1000 && u < units.length - 1) {
    v /= 1000
    u++
  }
  return `${u === 0 ? Math.round(v) : nf1.format(v)} ${units[u]}`
}

/** Robust z-score (median / MAD), as used by the outlier views (DASHBOARD §Views) */
export function robustZ(values: number[]): (v: number) => number {
  const sorted = [...values].sort((a, b) => a - b)
  const med = sorted[Math.floor(sorted.length / 2)] ?? 0
  const dev = sorted.map((v) => Math.abs(v - med)).sort((a, b) => a - b)
  const mad = (dev[Math.floor(dev.length / 2)] ?? 0) * 1.4826
  // MAD is 0 when more than half the values are equal; fall back to the mean absolute deviation
  const meanAd = (dev.reduce((s, d) => s + d, 0) / (dev.length || 1)) * 1.2533
  const scale = mad > 0 ? mad : meanAd
  return (v) => (scale > 0 ? (v - med) / scale : 0)
}
