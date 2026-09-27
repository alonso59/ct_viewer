// FE-02 (AUD-A6-13): every TanStack Query key is built in api/keys.ts, so renaming a key there cannot
// silently stop an invalidation elsewhere; the prefix builders match the keys they invalidate.
import { expect, test } from 'vitest'

import { keys } from './keys'

const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!./keys.ts'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

test('no literal query key outside api/keys.ts', () => {
  const literal = Object.entries(sources).filter(([, src]) => /queryKey:\s*\[/.test(src)).map(([f]) => f)
  expect(literal).toEqual([])
})

test('scope prefixes are prefixes of the keys they invalidate', () => {
  const prefix = (p: readonly unknown[], k: readonly unknown[]) => p.every((x, i) => k[i] === x)
  expect(prefix(keys.scope('p', 'cases'), keys.cases('p', { q: 'x' }))).toBe(true)
  expect(prefix(keys.scope('p', 'case'), keys.case('p', 'c1'))).toBe(true)
  expect(prefix(keys.scope('p', 'item'), keys.dicomTags('p', 'i1'))).toBe(true)
  expect(prefix(keys.scope('p', 'curation'), keys.queue('p'))).toBe(true)
  expect(prefix(keys.scope('p', 'labeling'), keys.labelCells('p', 't'))).toBe(true)
  expect(prefix(keys.scope('p', 'run'), keys.view('p', 'r', 'outliers', {}))).toBe(true)
  expect(prefix(keys.allJobs(), keys.jobs('p'))).toBe(true)
  expect(prefix(keys.projects(), keys.projects(true))).toBe(true)
  expect(prefix(keys.variables('p'), keys.brokenDerived('p'))).toBe(true)
})
