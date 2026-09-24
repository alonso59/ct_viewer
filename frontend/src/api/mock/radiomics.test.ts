// Mock radiomics members (API-30..37) behave like the server: live schema, rule-based validation,
// hash-identified profiles, estimate, and a run that completes, cancels and resumes.
import type { RadiomicsSettings } from '../types'
import { profileHash } from './radiomics'
import { DEMO_PID, mockServer as api } from './server'

/** Resolve a mock call while advancing its simulated latency and job timers */
async function settle<T>(p: Promise<T>, ms = 2_000): Promise<T> {
  const outcome = p.then(
    (value) => ({ value }),
    (error: unknown) => ({ error }),
  )
  await vi.advanceTimersByTimeAsync(ms)
  const r = await outcome
  if ('error' in r) throw r.error
  return r.value
}

beforeEach(() => {
  vi.useFakeTimers()
  api.reset()
})
afterEach(() => vi.useRealTimers())

test('schema is the live engine schema', async () => {
  const s = await settle(api.radiomicsSchema())
  expect(s.engine.name).toBe('pyradiomics')
  expect(s.groups.length).toBeGreaterThan(0)
  expect(s.options.some((o) => o.name === 'binWidth')).toBe(true)
})

test('validation: defaults pass with a hash; server-like issues otherwise', async () => {
  const { defaults } = await settle(api.radiomicsSchema())
  const ok = await settle(api.validateRadiomics(defaults, [1], 10))
  expect(ok).toMatchObject({ ok: true, issues: [] })
  expect(ok.profile_hash).toMatch(/^sha256:[0-9a-f]{64}$/)

  const both: RadiomicsSettings = { ...defaults, settings: { ...defaults.settings, binWidth: 25, binCount: 32 } }
  const bad = await settle(api.validateRadiomics(both, [1], 0))
  expect(bad.ok).toBe(false)
  expect(bad.profile_hash).toBeNull()
  expect(bad.issues).toContainEqual({ loc: ['settings', 'binCount'], rule: 'bin_xor', severity: 'error', msg: 'Choose bin width or bin count' })
  expect(bad.issues.some((i) => i.loc[0] === 'n_items' && i.rule === 'nothing')).toBe(true)
})

test('profiles: seeded defaults, save is idempotent per settings hash, rename, delete', async () => {
  const { defaults } = await settle(api.radiomicsSchema())
  const [seeded] = await settle(api.listProfiles(DEMO_PID))
  expect(seeded?.name).toBe('Engine defaults')
  expect(seeded?.profile_hash).toBe((await settle(api.validateRadiomics(defaults, [1], null))).profile_hash)

  const coarse: RadiomicsSettings = { ...defaults, settings: { ...defaults.settings, binWidth: 50 } }
  const saved = await settle(api.saveProfile(DEMO_PID, 'Coarse', coarse))
  expect(saved.profile_hash).not.toBe(seeded?.profile_hash)
  expect(saved.engine.major).toBe('3')
  const again = await settle(api.saveProfile(DEMO_PID, 'Other name', coarse))
  expect(again).toMatchObject({ profile_hash: saved.profile_hash, name: 'Coarse' })
  expect(await settle(api.listProfiles(DEMO_PID))).toHaveLength(2)

  expect((await settle(api.renameProfile(DEMO_PID, saved.profile_hash, 'Coarse bins'))).name).toBe('Coarse bins')
  const rest = await settle(api.deleteProfile(DEMO_PID, saved.profile_hash))
  expect(rest.map((p) => p.name)).toEqual(['Engine defaults'])
  await expect(settle(api.renameProfile(DEMO_PID, 'sha256:missing', 'x'))).rejects.toMatchObject({ status: 404 })
})

test('estimate, run to completion, export, cancel and resume', async () => {
  const { defaults } = await settle(api.radiomicsSchema())
  const est = await settle(api.estimate(DEMO_PID, defaults, { scope: 'complete', labels: [1, 2] }))
  expect(est.n_items).toBeGreaterThan(1)
  expect(est.n_units).toBe(est.n_items * 2)
  const ids = est.sample_item_ids.slice(0, 2)
  expect((await settle(api.estimate(DEMO_PID, defaults, { item_ids: ids, labels: [2] }))).n_units).toBe(2)

  const started = await settle(api.startRun(DEMO_PID, { name: 'Two items', settings: defaults, selection: { item_ids: ids, labels: [2] } }, 'AP'), 300)
  expect(started).toMatchObject({ name: 'Two items', status: 'running', reviewer: 'AP', profile_hash: profileHash(defaults) })
  expect(started.selection.item_ids).toEqual(ids)
  expect(started.job_id).toBeTruthy()

  await vi.advanceTimersByTimeAsync(2_000)
  const done = await settle(api.getRun(DEMO_PID, started.run_id))
  expect(['completed', 'completed_with_errors']).toContain(done.status)
  expect(done.counts.items).toBe(2)
  const runs = await settle(api.listRuns(DEMO_PID))
  expect(runs[0]?.run_id).toBe(started.run_id)
  expect(runs[0]).not.toHaveProperty('settings')
  expect(await settle(api.runErrors(DEMO_PID, started.run_id))).toEqual(expect.any(Array))
  expect(decodeURIComponent(api.runExportUrl(DEMO_PID, started.run_id, 'csv', 'long'))).toMatch(/^data:text\/csv;charset=utf-8,item_id,case_id,/)

  const next = await settle(api.startRun(DEMO_PID, { name: 'Stopped', settings: defaults, selection: { item_ids: ids, labels: [1, 2] } }, 'AP'), 300)
  expect((await settle(api.cancelRun(DEMO_PID, next.run_id), 300)).status).toBe('cancelled')
  await expect(settle(api.cancelRun(DEMO_PID, next.run_id), 300)).rejects.toMatchObject({ status: 409 })
  expect((await settle(api.resumeRun(DEMO_PID, next.run_id), 300)).status).toBe('running')
  await vi.advanceTimersByTimeAsync(3_000)
  expect((await settle(api.getRun(DEMO_PID, next.run_id))).finished_at).not.toBeNull()
})
