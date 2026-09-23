// TST-09 viewer bench (NFR-01/02) against the reference volume in the harness.
// Prereqs: node src/features/viewer/harness/make-reference.mjs  (once)
//          npx vite --config src/features/viewer/harness/vite.config.ts  (harness on :5175)
// Run:     node src/features/viewer/harness/bench.mjs [--url http://127.0.0.1:5175] [--headed]
//          CHROME=/path/to/chrome overrides the Playwright browser. Exit 1 if a target fails.
import { chromium } from '@playwright/test'

const arg = (k, d) => {
  const i = process.argv.indexOf(k)
  return i > 0 ? process.argv[i + 1] : d
}
const base = arg('--url', 'http://127.0.0.1:5175')
const layout = arg('--layout', 'four-up')
const FRAMES = Number(arg('--frames', 180))
const TARGET = { firstSliceMs: 3000, minFps: 30 }

const browser = await chromium.launch({
  headless: !process.argv.includes('--headed'),
  executablePath: process.env.CHROME || undefined,
  args: ['--ignore-gpu-blocklist', '--enable-gpu-rasterization'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: Number(arg('--dpr', 2)) })
page.on('pageerror', (e) => console.error('pageerror', e.message))

await page.goto(`${base}/src/features/viewer/harness/index.html?src=reference&layout=${layout}`)
await page.waitForFunction(() => performance.getEntriesByName('rw:mask').length > 0, null, { timeout: 120_000 })
const renderer = await page.evaluate(() => {
  const gl = document.createElement('canvas').getContext('webgl2')
  const d = gl?.getExtension('WEBGL_debug_renderer_info')
  return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'unknown'
})
const load = await page.evaluate(() => {
  const m = (n) => performance.getEntriesByName(n)[0]?.startTime ?? NaN
  return { loadStart: m('rw:load-start'), firstSlice: m('rw:first-slice'), mask: m('rw:mask') }
})

/** Runs `op(i)` once per animation frame; returns rAF-interval fps and GPU-synced frame cost. */
const run = (name, op) =>
  page.evaluate(
    ([name, op, n]) =>
      new Promise((resolve) => {
        const v = window.__viewer
        const fn = new Function('v', 'i', op)
        v.stats.sync = false
        const stamps = []
        let i = 0
        const tick = (t) => {
          stamps.push(t)
          if (i < n) {
            fn(v, i++)
            requestAnimationFrame(tick)
            return
          }
          // Second pass with GPU sync for the true per-frame cost
          v.stats.sync = true
          const costs = []
          let j = 0
          let last = v.stats.frames
          const tick2 = () => {
            if (v.stats.frames !== last) {
              costs.push(v.stats.lastFrameMs)
              last = v.stats.frames
            }
            if (j < 60) {
              fn(v, j++)
              requestAnimationFrame(tick2)
              return
            }
            v.stats.sync = false
            const dts = stamps.slice(1).map((s, k) => s - (stamps[k] ?? s)).sort((a, b) => a - b)
            costs.sort((a, b) => a - b)
            const q = (a, p) => a[Math.min(a.length - 1, Math.floor(p * a.length))] ?? NaN
            const mean = dts.reduce((a, b) => a + b, 0) / Math.max(1, dts.length)
            resolve({ name, fps: 1000 / mean, p95FrameMs: q(dts, 0.95), gpuMedianMs: q(costs, 0.5), gpuP95Ms: q(costs, 0.95) })
          }
          requestAnimationFrame(tick2)
        }
        requestAnimationFrame(tick)
      }),
    [name, op, FRAMES],
  )

const results = [
  await run('scroll axial', "v.step('axial', i % 120 < 60 ? 1 : -1)"),
  await run('scroll sagittal', "v.step('sagittal', i % 120 < 60 ? 1 : -1)"),
  await run('window/level drag', 'v.setWindow(400 + (i % 60) * 10, 50 + (i % 30) * 4)'),
  await run('overlay opacity', 'v.setOverlay({ opacity: 0.3 + (i % 10) / 15 })'),
]
const memory = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null)
await browser.close()

const firstSliceMs = load.firstSlice - load.loadStart
const out = {
  renderer,
  layout,
  nfr01: { firstSliceMs: Math.round(firstSliceMs), maskMs: Math.round(load.mask - load.loadStart), targetMs: TARGET.firstSliceMs, pass: firstSliceMs < TARGET.firstSliceMs },
  nfr02: results.map((r) => ({ ...r, fps: Math.round(r.fps), pass: r.fps >= TARGET.minFps })),
  jsHeapMB: memory ? Math.round(memory / 1e6) : null,
}
console.log(JSON.stringify(out, (_, v) => (typeof v === 'number' ? Math.round(v * 10) / 10 : v), 1))
process.exit(out.nfr01.pass && out.nfr02.every((r) => r.pass) ? 0 : 1)
