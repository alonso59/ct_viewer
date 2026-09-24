// FE-11: every translation key used in the source exists in en.json (static keys + enum families).
import { CURATION_STATUSES, PHASES } from '../api/types'
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

test('enum families are complete', () => {
  const warnings = ['missing_path', 'unreadable_file', 'outside_root', 'missing_seg', 'missing_voi_image', 'missing_voi_mask', 'missing_affine', 'affine_mismatch', 'shape_mismatch', 'ambiguous_phase', 'ambiguous_side', 'duplicate_row_identity', 'fingerprint_changed']
  const families: [string, readonly string[]][] = [
    ['status', CURATION_STATUSES],
    ['statusShort', CURATION_STATUSES],
    ['phase', PHASES],
    ['warning', warnings],
    ['runStatus', ['queued', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled', 'interrupted']],
    ['viewer.layout', ['four-up', 'conventional', 'three-mpr', 'one-up-axial', 'one-up-sagittal', 'one-up-coronal', 'one-up-3d']],
    ['viewer.preset', Object.keys(WL_PRESETS)],
    ['viewer.plane', ['axial', 'sagittal', 'coronal', '3d']],
    ['viewer.tool', ['pan', 'window', 'crosshair', 'zoom']],
    ['menu', ['file', 'edit', 'view', 'project', 'radiomics', 'help']],
    ['priority', ['low', 'medium', 'high']],
  ]
  const missing = families.flatMap(([ns, values]) => values.map((v) => `${ns}.${v}`).filter((k) => !has(k)))
  expect(missing).toEqual([])
})
