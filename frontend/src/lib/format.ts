// Intl-based formatting (FE-11). English format everywhere (owner 2026-09-25, AUD-A3-04): a point
// as the decimal separator on every machine; counts keep the English thousands separator, measured
// values never get one ("117583", not "117,583", which reads as 117.6 on a comma-decimal machine).
const nf = new Intl.NumberFormat('en', { maximumFractionDigits: 2, useGrouping: false })
const nf1 = new Intl.NumberFormat('en', { maximumFractionDigits: 1, useGrouping: false })
const nf0 = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })
const plain = new Intl.NumberFormat('en', { maximumFractionDigits: 20, useGrouping: false })
const df = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' })
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** A measured value with at most 2 decimals, no thousands separator */
export const fmtNum = (v: number) => (Math.abs(v) >= 1000 ? plain.format(Math.round(v)) : nf.format(v))
export const fmt1 = (v: number) => nf1.format(v)
/** A count ("1,234 items") */
export const fmtInt = (v: number) => nf0.format(v)

// ---- feature values (DB-03, AUD-A3-15) -----------------------------------------------------------
const SCI_ABOVE = 1e5
const SCI_BELOW = 1e-3
const sci = (v: number) => v.toExponential(2).replace('e+', 'e')
const needsSci = (v: number) => v !== 0 && (Math.abs(v) >= SCI_ABOVE || Math.abs(v) < SCI_BELOW)

/** 3 significant digits (whole numbers keep every integer digit), scientific above 1e5 / below 1e-3 */
export function fmtValue(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (needsSci(v)) return sci(v)
  if (Math.abs(v) >= 100) return plain.format(Math.round(v))
  return plain.format(Number(v.toPrecision(3)))
}

/** One format for a whole column: scientific for every cell once any cell is ≥ 1e5 */
export function fmtColumn(values: (number | null | undefined)[]): (v: number | null | undefined) => string {
  const big = values.some((v) => v != null && Number.isFinite(v) && Math.abs(v) >= SCI_ABOVE)
  return (v) => (big && v != null && Number.isFinite(v) && v !== 0 ? sci(v) : fmtValue(v))
}

/** Unit of a PyRadiomics feature `{image_type}_{class}_{name}`; HU for first-order intensities of
 *  the original CT image only (filtered images are not in HU). '' when unit-less. */
export function featureUnit(feature: string, modality: string | null | undefined = 'CT'): string {
  const [image, cls, name = ''] = feature.split('_')
  if (cls === 'shape' || cls === 'shape2D') {
    if (/Volume$/.test(name)) return 'mm³'
    if (/(SurfaceArea|PixelSurface|Area)$/.test(name)) return 'mm²'
    if (/(Diameter|AxisLength|Perimeter)/.test(name)) return 'mm'
    return ''
  }
  if (cls === 'firstorder' && image === 'original' && (modality ?? 'CT').toUpperCase() === 'CT') {
    if (/^(Mean|Median|Minimum|Maximum|Range|RootMeanSquared|InterquartileRange|MeanAbsoluteDeviation|RobustMeanAbsoluteDeviation|10Percentile|90Percentile|StandardDeviation)$/.test(name)) return 'HU'
    if (name === 'Variance') return 'HU²'
  }
  return ''
}

/** Parse a typed number; `,` and `.` are both a decimal point (AUD-A3-04). null when not a number */
export function parseNum(text: string): number | null {
  const s = text.trim().replace(/\s/g, '').replace(',', '.')
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}
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

/** Middle ellipsis for paths (AUD-A3-13): "/data/…/nifti/01_case_00001_0000.nii.gz"; keeps the file name */
export function midEllipsis(text: string, max = 48): string {
  if (text.length <= max) return text
  const keepEnd = Math.min(text.length - 1, Math.max(Math.ceil(max * 0.6), text.length - text.lastIndexOf('/')))
  const head = Math.max(1, max - keepEnd - 1)
  return `${text.slice(0, head)}…${text.slice(text.length - Math.min(keepEnd, max - 2))}`
}
