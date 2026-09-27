// FE-11: every translation key used in the source exists in en.json (static keys + enum families).
import { CASE_ROLLUPS, PHASES } from '../api/types'
import { RUN_STATES } from '../lib/badges'
import { MENUS, SUBMENUS } from '../shell/menus'
import { WL_PRESETS } from '../state/viewerSync'
import en from './en.json'
import enLazy from './en.lazy.json'

type Tree = { [k: string]: string | Tree }
// en.lazy.json is deep-merged at runtime by the lazy chunks (i18n/lazy.ts)
const tree = merge(en as Tree, enLazy as Tree)

function merge(a: Tree, b: Tree): Tree {
  const out: Tree = { ...a }
  for (const [k, v] of Object.entries(b)) {
    const cur = out[k]
    out[k] = typeof v === 'object' && typeof cur === 'object' ? merge(cur, v) : v
  }
  return out
}

function has(key: string): boolean {
  let node: string | Tree | undefined = tree
  const parts = key.split('.')
  for (let i = 0; i < parts.length; i++) {
    if (typeof node !== 'object') return false
    const part = parts[i] ?? ''
    // i18next plurals: `x` resolves to `x_one` / `x_other`
    node = node[part] ?? (i === parts.length - 1 ? (node[`${part}_other`] as string | undefined) : undefined)
  }
  return typeof node === 'string'
}

// Source text of every module under src/ (Vite raw imports; no Node APIs in the app tsconfig)
const files = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../api/mock/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('static keys exist', () => {
  const namespaces = new Set(Object.keys(tree))
  const missing = new Set<string>()
  for (const [file, src] of Object.entries(files)) {
    // Translation contexts only: t(...) arguments (incl. ternaries) and registry title/category fields
    const contexts = [...src.matchAll(/\bt\(([^()]*)/g), ...src.matchAll(/(?:title|category): ('[^']*')/g)].map((m) => m[1] ?? '')
    for (const ctx of contexts)
      for (const m of ctx.matchAll(/'([a-zA-Z]+(?:\.[a-zA-Z0-9_-]+)+)'/g)) {
        const key = m[1] ?? ''
        if (namespaces.has(key.split('.')[0] ?? '') && !has(key)) missing.add(`${key} (${file})`)
      }
  }
  expect([...missing]).toEqual([])
})

// UI-23 (AUD-A3-07): a template key `t(\`ns.group.${x}\`)` needs its `ns.group` object; a wrong
// prefix (e.g. `viewer.layouts.` for `viewer.layout.`) shows raw keys on screen
test('every t() template prefix exists', () => {
  const namespaces = new Set(Object.keys(tree))
  const node = (key: string): string | Tree | undefined => {
    let n: string | Tree | undefined = tree
    for (const part of key.split('.')) n = typeof n === 'object' ? n[part] : undefined
    return n
  }
  const missing = new Set<string>()
  for (const [file, src] of Object.entries(files))
    for (const m of src.matchAll(/\bt\(`([a-zA-Z]+(?:\.[a-zA-Z0-9_-]+)*)\.\$\{/g)) {
      const prefix = m[1] ?? ''
      if (namespaces.has(prefix.split('.')[0] ?? '') && typeof node(prefix) !== 'object') missing.add(`${prefix} (${file})`)
    }
  expect([...missing]).toEqual([])
})

// R8 (AUD-A1-14): requirement and ADR IDs ("PRJ-17", "ADR-0004") belong to the docs, never to
// user-facing text; SHA-256 is a hash name, not an ID
test('no requirement or ADR IDs in user-facing strings', () => {
  const leaks: string[] = []
  const walk = (n: Tree, path: string) => {
    for (const [k, v] of Object.entries(n)) {
      if (typeof v === 'object') walk(v, `${path}${k}.`)
      else if (/\b(?!SHA-)[A-Z]{2,4}-\d+/.test(v)) leaks.push(`${path}${k}: ${v}`)
    }
  }
  walk(tree, '')
  expect(leaks).toEqual([])
})

test('enum families are complete', () => {
  const warnings = ['missing_path', 'unreadable_file', 'outside_root', 'missing_seg', 'missing_voi_image', 'missing_voi_mask', 'missing_affine', 'affine_mismatch', 'shape_mismatch', 'ambiguous_phase', 'ambiguous_side', 'duplicate_row_identity', 'fingerprint_changed']
  const families: [string, readonly string[]][] = [
    ['status', CASE_ROLLUPS],
    ['statusShort', CASE_ROLLUPS],
    ['phase', PHASES],
    ['warning', warnings],
    // AUD-A3-10 (UI-15): one run / job state vocabulary for every view
    ['runStatus', RUN_STATES],
    ['viewer.layout', ['four-up', 'conventional', 'three-mpr', 'one-up-axial', 'one-up-sagittal', 'one-up-coronal', 'one-up-3d']],
    ['viewer.preset', Object.keys(WL_PRESETS)],
    ['viewer.plane', ['axial', 'sagittal', 'coronal', '3d']],
    ['viewer.tool', ['pan', 'window', 'crosshair', 'zoom']],
    // AUD-A1-09: every derived menu and submenu has a label
    ['menu', MENUS.map((m) => m.id)],
    ['menu.sub', [...SUBMENUS].map((c) => c.slice(4))],
    ['cat', MENUS.flatMap((m) => m.categories.map((c) => c.slice(4)))],
    ['priority', ['low', 'medium', 'high']],
  ]
  const missing = families.flatMap(([ns, values]) => values.map((v) => `${ns}.${v}`).filter((k) => !has(k)))
  expect(missing).toEqual([])
})
