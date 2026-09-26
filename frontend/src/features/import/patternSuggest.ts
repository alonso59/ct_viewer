// SRC-17 pattern suggester: candidate `nifti-files` patterns derived only from the sampled file
// names (no per-dataset presets, ADR-0024). Patterns use Python syntax, as the backend fullmatches
// them against each file stem (SRC-04); `toJsRegex` converts one for highlighting in the browser.

export interface PatternCandidate {
  /** Python regex for the `pattern` field */
  pattern: string
  /** Named groups, in order of appearance */
  groups: string[]
  /** Sampled stems it matches */
  matched: number
}

const EXT = /\.(nii\.gz|nii|npy)$/i
// SRC-04 default mask conventions: `_seg` / `_mask` stems are masks, not items
const MASK = /_(seg|mask)$/i
const MAX = 3

export const stemOf = (name: string) => name.replace(EXT, '')

/** Image stems of a folder listing: accepted extensions only, masks left out */
export const sampleStems = (names: string[]) =>
  names.filter((n) => EXT.test(n)).map(stemOf).filter((s) => !MASK.test(s))

export const toJsRegex = (pattern: string) => new RegExp(pattern.replace(/\(\?P</g, '(?<'), 'd')

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The most common `case` literal (with its separator) in front of digits, e.g. `case_` */
function caseLiteral(stems: string[]): string | null {
  const counts = new Map<string, number>()
  for (const s of stems) {
    const m = /(case[_-]?)\d+/i.exec(s)
    if (m?.[1]) counts.set(m[1], (counts.get(m[1]) ?? 0) + 1)
  }
  const best = [...counts].sort((a, b) => b[1] - a[1])[0]
  return best ? best[0] : null
}

const PIECES = {
  scan_idx: { test: /^\d{1,3}_/, rx: '(?P<scan_idx>\\d{1,3})_' },
  side: { test: /_[LR](_\d{4})?$/, rx: '_(?P<side>[LR])' },
  channel: { test: /_\d{4}$/, rx: '_(?P<channel>\\d{4})' },
} as const
type Piece = keyof typeof PIECES

/**
 * Up to 3 candidates, most matched names first (then more groups). A group is only proposed when
 * some sampled name has that piece, and a candidate must match at least half of the sample; the
 * default one-case-per-stem pattern is never proposed. No sample, no candidates.
 */
export function suggestPatterns(stems: string[]): PatternCandidate[] {
  if (!stems.length) return []
  const lit = caseLiteral(stems)
  const present = (Object.keys(PIECES) as Piece[]).filter((k) => stems.some((s) => PIECES[k].test.test(s)))
  const out = new Map<string, PatternCandidate>()
  // every subset of the pieces the sample shows
  for (let mask = 0; mask < 1 << present.length; mask++) {
    const use = present.filter((_, i) => mask & (1 << i))
    if (!lit && !use.length) continue // that would be the default pattern
    const has = (k: Piece) => use.includes(k)
    const caseRx = lit ? `(?:.*_)?(?P<case_id>${escape(lit)}\\d+)` : '(?P<case_id>.+?)'
    const pattern = `^${has('scan_idx') ? PIECES.scan_idx.rx : ''}${caseRx}${has('side') ? PIECES.side.rx : ''}${has('channel') ? PIECES.channel.rx : ''}$`
    const rx = toJsRegex(pattern)
    const matched = stems.filter((s) => rx.test(s)).length
    if (matched * 2 < stems.length) continue
    const groups = [...pattern.matchAll(/\(\?P<(\w+)>/g)].map((m) => m[1] ?? '')
    out.set(pattern, { pattern, groups, matched })
  }
  return [...out.values()].sort((a, b) => b.matched - a.matched || b.groups.length - a.groups.length || a.pattern.length - b.pattern.length).slice(0, MAX)
}

/** A stem split into plain text and named-group parts, for highlighting */
export function segments(pattern: string, stem: string): { text: string; group?: string }[] | null {
  const m = toJsRegex(pattern).exec(stem)
  if (!m?.indices?.groups) return null
  const spans = Object.entries(m.indices.groups)
    .filter((e): e is [string, [number, number]] => e[1] !== undefined && e[1][1] > e[1][0])
    .sort((a, b) => a[1][0] - b[1][0])
  const out: { text: string; group?: string }[] = []
  let at = 0
  for (const [group, [from, to]] of spans) {
    if (from > at) out.push({ text: stem.slice(at, from) })
    out.push({ text: stem.slice(from, to), group })
    at = to
  }
  if (at < stem.length) out.push({ text: stem.slice(at) })
  return out
}

/**
 * The converter's own file naming `{scan_idx}_[{MOD}_]{case_id}_{channel}` (DICOM_CONVERTER,
 * kept by ADR-0024 §3). The wizard pre-fills it, visible and editable, only when every sampled
 * image stem follows it (ADR-0027, AUD-A2-12); otherwise the default (one case per stem) stays.
 */
export const CONVERTER_PATTERN = '^(?P<scan_idx>\\d+)_(?:(?P<modality>[A-Z]{2,3})_)?(?P<case_id>.+)_(?P<channel>\\d{4})$'

export function converterPattern(stems: string[]): string | null {
  const rx = toJsRegex(CONVERTER_PATTERN)
  return stems.length > 0 && stems.every((s) => rx.test(s)) ? CONVERTER_PATTERN : null
}
