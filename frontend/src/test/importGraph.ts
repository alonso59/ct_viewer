// The static import graph of `src/` (non-test modules), for the boundary and cycle checks
// (FE-ARCH §Boundaries, AUD-A6-10/11). Relative imports only; `import type` is left out (erased).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'

export const SRC = resolve(__dirname, '..')

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && !name.endsWith('.d.ts')) out.push(p)
  }
  return out
}

function resolveImport(from: string, spec: string): string | null {
  const base = resolve(dirname(from), spec)
  for (const c of [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts'), join(base, 'index.tsx')])
    if (existsSync(c) && statSync(c).isFile()) return c
  return null
}

const IMPORT = /^\s*(import|export)\s+(type\s+)?(?:[^'";]*?\sfrom\s+)?['"](\.[^'"]+)['"]/gm
// a lazy `import('./x')` is an edge too: it still ties the two modules together (madge counts it)
const DYNAMIC = /\bimport\(\s*['"](\.[^'"]+)['"]\s*\)/g

/** module (path relative to src/) → the modules it imports at runtime */
export function importGraph(): Map<string, string[]> {
  const g = new Map<string, string[]>()
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf8')
    const deps: string[] = []
    for (const m of text.matchAll(IMPORT)) {
      if (m[2]) continue // `import type` / `export type`
      const target = resolveImport(file, m[3] ?? '')
      if (target && /\.(ts|tsx)$/.test(target)) deps.push(relative(SRC, target))
    }
    for (const m of text.matchAll(DYNAMIC)) {
      const target = resolveImport(file, m[1] ?? '')
      if (target && /\.(ts|tsx)$/.test(target)) deps.push(relative(SRC, target))
    }
    g.set(relative(SRC, file), deps)
  }
  return g
}

/** Strongly connected components with more than one module (Tarjan) */
export function cycles(g: Map<string, string[]>): string[][] {
  let index = 0
  const idx = new Map<string, number>()
  const low = new Map<string, number>()
  const stack: string[] = []
  const on = new Set<string>()
  const out: string[][] = []
  const visit = (v: string) => {
    idx.set(v, index)
    low.set(v, index++)
    stack.push(v)
    on.add(v)
    for (const w of g.get(v) ?? []) {
      if (!idx.has(w)) {
        visit(w)
        low.set(v, Math.min(low.get(v)!, low.get(w)!))
      } else if (on.has(w)) low.set(v, Math.min(low.get(v)!, idx.get(w)!))
    }
    if (low.get(v) === idx.get(v)) {
      const scc: string[] = []
      let w: string
      do {
        w = stack.pop()!
        on.delete(w)
        scc.push(w)
      } while (w !== v)
      if (scc.length > 1) out.push(scc.sort())
    }
  }
  for (const v of g.keys()) if (!idx.has(v)) visit(v)
  return out
}
