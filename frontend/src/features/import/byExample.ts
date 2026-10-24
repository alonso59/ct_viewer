// SRC-17 pattern by example: the user marks the pieces of one real image path (folders, and the
// file name's `_`/`-`/`.` tokens) as case, scan, side, channel, fixed text or "any", and points
// at that image's mask; the `pattern` regex and the `mask_template` are generated from that, so
// nobody has to write either by hand. Both stay ordinary `nifti-files` options (SRC-04).
import { stemOf, toJsRegex } from './patternSuggest'

export const ROLES = ['case_id', 'scan_idx', 'side', 'channel', 'fixed', 'any'] as const
export type Role = (typeof ROLES)[number]
const GROUPS = new Set<Role>(['case_id', 'scan_idx', 'side', 'channel'])

export interface Token {
  text: string
  /** A folder of the path (the file name's tokens are not) */
  folder: boolean
  /** What follows it: `/` after a folder, the separator after a name token, '' at the end */
  sep: string
  /** Offset in the path */
  at: number
}

/** A path without extension, split into its folders and the file name's tokens */
export function tokenize(path: string): Token[] {
  const out: Token[] = []
  const cut = path.lastIndexOf('/') + 1
  let at = 0
  for (const dir of path.slice(0, cut).split('/').slice(0, -1)) {
    out.push({ text: dir, folder: true, sep: '/', at })
    at += dir.length + 1
  }
  for (const m of path.slice(cut).matchAll(/([^_.-]+)([_.-]?)/g)) {
    out.push({ text: m[1] ?? '', folder: false, sep: m[2] ?? '', at: cut + (m.index ?? 0) })
  }
  return out
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const shape = (t: string) => (/^\d+$/.test(t) ? '\\d+' : /^[A-Za-z]+$/.test(t) ? '[A-Za-z]+' : '[A-Za-z0-9]+')

function piece(t: Token, role: Role): string {
  if (role === 'fixed') return escape(t.text)
  if (role === 'side') return '[LR]'
  if (role === 'channel') return '\\d{4}'
  return t.folder ? '[^/]+' : shape(t.text)
}

/** Defaults before the user marks anything: folders vary, the file name's tokens are fixed text */
export const defaultRole = (t: Token): Role => (t.folder ? 'any' : 'fixed')

/**
 * The Python pattern for these roles, or null without a case. Neighbouring name tokens with the
 * same group form one group (`case` + `00012` → `case_00012`); a group used again further on is
 * "any", as a name can only be used once. With every folder "any" the folders are left out, so
 * the pattern matches the file name wherever it is (SRC-04: no `/`, the stem).
 */
export function buildPattern(tokens: Token[], roles: Role[]): string | null {
  const keepFolders = tokens.some((t, i) => t.folder && roles[i] !== 'any')
  const sep = (t: Token | null) => (t === null ? '' : t.sep === '/' ? '/' : escape(t.sep))
  const used = new Set<Role>()
  let rx = ''
  let open: Role | null = null
  let prev: Token | null = null
  for (const [i, t] of tokens.entries()) {
    if (t.folder && !keepFolders) continue
    let role = roles[i] ?? defaultRole(t)
    const joins = open !== null && role === open && !t.folder && prev !== null && !prev.folder
    if (!joins && GROUPS.has(role) && used.has(role)) role = 'any'
    rx += (open !== null && !joins ? ')' : '') + sep(prev)
    if (open !== null && !joins) open = null
    if (GROUPS.has(role) && !joins) {
      rx += `(?P<${role}>`
      used.add(role)
      open = role
    }
    rx += piece(t, role)
    prev = t
  }
  rx += (open !== null ? ')' : '') + sep(prev)
  return used.has('case_id') ? `^${rx}$` : null
}

/** The roles a pattern gives the example's tokens (a token inside a group gets that group) */
export function rolesFrom(pattern: string | undefined, path: string, tokens: Token[]): Role[] {
  const base = pattern?.includes('/') ? 0 : path.lastIndexOf('/') + 1
  const spans = Object.entries((pattern && safeExec(pattern, path.slice(base))?.indices?.groups) ?? {})
  return tokens.map((t) => {
    const hit = spans.find(([, s]) => s && t.at - base >= s[0] && t.at - base + t.text.length <= s[1])
    return hit && GROUPS.has(hit[0] as Role) ? (hit[0] as Role) : defaultRole(t)
  })
}

function safeExec(pattern: string, subject: string): RegExpExecArray | null {
  try {
    return toJsRegex(pattern).exec(subject)
  } catch {
    return null
  }
}

/** Does this sampled path (without extension) match the pattern, as the backend fullmatches it */
export const matches = (pattern: string, path: string) => safeExec(pattern, pattern.includes('/') ? path : path.slice(path.lastIndexOf('/') + 1)) !== null

/**
 * The mask template from one example: the mask path the user picked for the example image, with
 * each of the image's group values put back as its field (longest first). Null when the picked
 * path holds none of them: every image would point at the same mask.
 */
export function templateFrom(pattern: string, image: string, mask: string): string | null {
  const m = safeExec(pattern, pattern.includes('/') ? image : image.slice(image.lastIndexOf('/') + 1))
  const values = Object.entries(m?.groups ?? {}).filter((e): e is [string, string] => !!e[1]).sort((a, b) => b[1].length - a[1].length)
  let out = mask
  for (const [name, value] of values) out = out.split(value).join(`{${name}}`)
  return out === mask ? null : out
}

/** The mask path a template names for one image path, or null when the pattern does not match */
export function maskFor(pattern: string, template: string, path: string): string | null {
  const m = safeExec(pattern, pattern.includes('/') ? path : path.slice(path.lastIndexOf('/') + 1))
  return m ? template.replace(/\{(\w+)\}/g, (_, k: string) => m.groups?.[k] ?? `{${k}}`) : null
}

/** The paths (without extension) a template makes masks of: they are not images to match */
export function templatedMasks(pattern: string, template: string, paths: string[]): Set<string> {
  const out = new Set<string>()
  for (const p of paths) {
    const target = maskFor(pattern, template, p)
    if (target === null) continue
    out.add(stemOf(target))
    for (const q of paths) if (q.startsWith(`${target}/`)) out.add(q)
  }
  return out
}

const IMAGES = /^images?/i
const LABELS = /^(labels?|masks?|segmentations?)/i

/**
 * SRC-17 paired folders (`ImageTr` + `LabelTr`, `imagesTr` + `labelsTr`): when the sample is
 * exactly an image folder and its label folder side by side, the pattern and the mask template
 * that pair them. One case folder per image (`ImageTr/{case}/ct`) with a mask file or a mask set
 * folder at the same place under the label folder, or flat files (`imagesTr/{case}[_0000]`) with
 * `labelsTr/{case}`. Anything else: null.
 */
export function pairedFolders(names: string[]): { pattern: string; mask_template: string } | null {
  const parts = names.map((n) => n.split('/'))
  const at = parts[0]?.findIndex((p) => IMAGES.test(p) || LABELS.test(p)) ?? -1
  if (at < 0) return null
  const prefix = parts[0]?.slice(0, at).join('/') ?? ''
  if (!parts.every((p) => p.length > at + 1 && p.slice(0, at).join('/') === prefix)) return null
  const dirs = [...new Set(parts.map((p) => p[at] ?? ''))]
  const img = dirs.find((d) => IMAGES.test(d))
  const lbl = dirs.find((d) => LABELS.test(d))
  if (dirs.length !== 2 || !img || !lbl || img.replace(IMAGES, '').toLowerCase() !== lbl.replace(LABELS, '').toLowerCase()) return null
  const under = (d: string) => parts.filter((p) => p[at] === d).map((p) => p.slice(at + 1))
  const imgs = under(img)
  const lbls = under(lbl)
  const lead = prefix ? `${escape(prefix)}/` : ''
  const root = prefix ? `${prefix}/` : ''
  const one = <T>(xs: T[]) => (new Set(xs).size === 1 ? xs[0] : undefined)
  if (imgs.every((p) => p.length === 2)) {
    const file = one(imgs.map((p) => stemOf(p[1] ?? '')))
    // a folder of masks (a mask set) or one mask file per case, the same for every case
    const rest = one(lbls.map((p) => (p.length > 2 ? p.slice(1, -1).join('/') : p.length === 2 ? `=${p[1]}` : '')))
    if (!file || !rest) return null
    const tail = rest.startsWith('=') ? rest.slice(1) : rest
    return { pattern: `^${lead}${escape(img)}/(?P<case_id>[^/]+)/${escape(file)}$`, mask_template: `${root}${lbl}/{case_id}/${tail}` }
  }
  if (imgs.every((p) => p.length === 1) && lbls.every((p) => p.length === 1)) {
    const ext = one(lbls.map((p) => /\.(nii\.gz|nii)$/i.exec(p[0] ?? '')?.[0] ?? ''))
    if (!ext) return null
    const channel = imgs.every((p) => /_\d{4}$/.test(stemOf(p[0] ?? '')))
    return {
      pattern: `^${lead}${escape(img)}/(?P<case_id>[^/]+?)${channel ? '_(?P<channel>\\d{4})' : ''}$`,
      mask_template: `${root}${lbl}/{case_id}${ext}`,
    }
  }
  return null
}
