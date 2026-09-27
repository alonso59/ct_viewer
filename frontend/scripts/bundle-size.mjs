// NFR-07 / FE-05 / REL-04 gate: initial JS = the entry script of dist/index.html plus its
// `modulepreload` set, each file gzip -9, summed. Budget in KiB (1 KiB = 1024 B): above it the gate
// fails. Growth over the committed baseline (`bundle-baseline.json`) by more than `--warn-kib`
// prints a warning but does not fail; `--write-baseline` records the current size as the baseline.
// Usage: node scripts/bundle-size.mjs [distDir] [--budget-kib 400] [--baseline file] [--warn-kib 25]
//        [--write-baseline] [--top 8]
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const args = process.argv.slice(2)
const opt = (name, dflt) => {
  const i = args.indexOf(name)
  return i >= 0 ? args[i + 1] : dflt
}
const valued = new Set(['--budget-kib', '--baseline', '--warn-kib', '--top'])
const dist = resolve(args.find((a, i) => !a.startsWith('--') && !valued.has(args[i - 1])) ?? 'dist')
const budgetKiB = Number(opt('--budget-kib', 400))
const baselineFile = opt('--baseline', null)
const warnKiB = Number(opt('--warn-kib', 25))
const writeBaseline = args.includes('--write-baseline')
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
if (baselineFile && writeBaseline) {
  const note = 'NFR-07 baseline: initial JS gzip -9 bytes; update with `make bundle-baseline` when growth is intended'
  writeFileSync(baselineFile, `${JSON.stringify({ note, initial_js_bytes: total }, null, 2)}\n`)
  console.log(`bundle-size: baseline written to ${baselineFile}`)
} else if (baselineFile && existsSync(baselineFile)) {
  const base = JSON.parse(readFileSync(baselineFile, 'utf8')).initial_js_bytes
  const growKiB = (total - base) / 1024
  if (growKiB > warnKiB)
    console.log(`bundle-size: WARNING initial JS grew ${growKiB.toFixed(1)} KiB over the baseline (${(base / 1024).toFixed(1)} KiB, warn above +${warnKiB} KiB); add a lazy boundary or run make bundle-baseline (NFR-07)`)
  else console.log(`bundle-size: ${growKiB >= 0 ? '+' : ''}${growKiB.toFixed(1)} KiB against the baseline (${(base / 1024).toFixed(1)} KiB)`)
} else if (baselineFile) console.log(`bundle-size: no baseline at ${baselineFile}; run make bundle-baseline`)
process.exit(kib <= budgetKiB ? 0 : 1)
