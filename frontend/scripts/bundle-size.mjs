// NFR-07 / FE-05 / REL-04 gate: initial JS = the entry script of dist/index.html plus its
// `modulepreload` set, each file gzip -9, summed. Budget in KiB (1 KiB = 1024 B).
// Usage: node scripts/bundle-size.mjs [distDir] [--budget-kib 300] [--top 0]
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const args = process.argv.slice(2)
const opt = (name, dflt) => {
  const i = args.indexOf(name)
  return i >= 0 ? args[i + 1] : dflt
}
const dist = resolve(args.find((a, i) => !a.startsWith('--') && !args[i - 1]?.startsWith('--')) ?? 'dist')
const budgetKiB = Number(opt('--budget-kib', 300))
const top = Number(opt('--top', 8))

const html = readFileSync(join(dist, 'index.html'), 'utf8')
const entry = [...html.matchAll(/<script[^>]+type="module"[^>]+src="([^"]+)"/g)].map((m) => m[1])
const preload = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g)].map((m) => m[1])
const files = [...new Set([...entry, ...preload])]
if (entry.length === 0) {
  console.error(`bundle-size: no module entry script in ${join(dist, 'index.html')}`)
  process.exit(2)
}
const sizes = files
  .map((f) => ({ f, gz: gzipSync(readFileSync(join(dist, f.replace(/^\//, ''))), { level: 9 }).length }))
  .sort((a, b) => b.gz - a.gz)
const total = sizes.reduce((s, x) => s + x.gz, 0)
const kib = total / 1024
for (const { f, gz } of sizes.slice(0, top)) console.log(`  ${(gz / 1024).toFixed(1).padStart(7)} KiB  ${f}`)
const verdict = kib <= budgetKiB ? 'ok' : 'OVER BUDGET'
console.log(`bundle-size: initial JS ${kib.toFixed(1)} KiB gzip (${total} B, ${files.length} files) / budget ${budgetKiB} KiB: ${verdict} (NFR-07)`)
process.exit(kib <= budgetKiB ? 0 : 1)
