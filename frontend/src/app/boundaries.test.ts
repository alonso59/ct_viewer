// FE-ARCH §Boundaries (AUD-A6-10, AUD-A6-11): the import graph of src/ has no cycles, the feature /
// plugin slices depend on each other one way only, and a slice reaches another only through its
// index.ts (plugins/host.ts and plugins/index.ts are the plugin host, open to all). This test is the
// check `npm run lint` would otherwise need madge / an import plugin for (no new dependency).
import { expect, test } from 'vitest'

import { cycles, importGraph } from '../test/importGraph'

const g = importGraph()
const sliceOf = (m: string) => /^(features|plugins)\/([^/.]+)\//.exec(m)?.slice(1, 3).join('/') ?? null
const HOST = new Set(['plugins/host.ts', 'plugins/index.ts'])

test('no import cycles between modules', () => {
  expect(g.size).toBeGreaterThan(150)
  expect(cycles(g)).toEqual([])
})

test('feature and plugin slices depend on each other one way only', () => {
  const slices = new Map<string, string[]>()
  for (const [m, deps] of g) {
    const a = sliceOf(m)
    if (!a) continue
    const out = slices.get(a) ?? []
    for (const d of deps) {
      const b = sliceOf(d)
      if (b && b !== a && !out.includes(b)) out.push(b)
    }
    slices.set(a, out)
  }
  expect(cycles(slices)).toEqual([])
})

test('a slice uses another slice only through its index.ts', () => {
  const bad: string[] = []
  for (const [m, deps] of g) {
    const a = sliceOf(m)
    if (!a) continue
    for (const d of deps) {
      const b = sliceOf(d)
      if (!b || b === a || HOST.has(d)) continue
      if (d !== `${b}/index.ts` && d !== `${b}/index.tsx`) bad.push(`${m} → ${d}`)
    }
  }
  expect(bad).toEqual([])
})
