// Mock tasks (API-42..47) and segmentation sets (API-27): manifests, validation, preflight, a
// segmentation run that needs a derived root and registers a set (TSK-04/09, PRJ-13, ADR-0015).
import { DEMO_PID, mockServer as api } from './server'

async function settle<T>(p: Promise<T>, ms = 5_000): Promise<T> {
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

test('catalog lists radiomics and the CI plugin; settings validate against the schema', async () => {
  const list = await settle(api.listTasks())
  expect(list.tasks.map((t) => t.manifest.id)).toEqual(['radiomics.pyradiomics', 'segment.threshold'])
  const ok = await settle(api.validateTask('segment.threshold', {}))
  expect(ok).toMatchObject({ ok: true, settings: { threshold: 0, label: 1 } })
  const bad = await settle(api.validateTask('segment.threshold', { label: 0, nope: 1 }))
  expect(bad.ok).toBe(false)
  expect(bad.issues.map((i) => i.rule).sort()).toEqual(['range', 'unknown'])
})

test('a segmentation run needs a derived root, then registers a segmentation set', async () => {
  const pre = await settle(api.preflightTask(DEMO_PID, 'segment.threshold', { item_ids: ['case_00001.01.complete.-'] }))
  expect(pre).toMatchObject({ n_selected: 1, n_ready: 1, derived_root_required: true })
  await expect(settle(api.startTaskRun(DEMO_PID, { task_id: 'segment.threshold', selection: { item_ids: ['case_00001.01.complete.-'] } }))).rejects.toMatchObject({
    type: 'derived-root-required',
  })
  await settle(api.setDerivedRoot(DEMO_PID, '/derived'))
  const started = await settle(api.startTaskRun(DEMO_PID, { task_id: 'segment.threshold', settings: { seg_id: 'thr-demo' }, selection: { item_ids: ['case_00001.01.complete.-'] } }))
  const run = await settle(api.getTaskRun(DEMO_PID, started.run_id))
  expect(run.status).toBe('completed')
  const sets = await settle(api.listSegmentations(DEMO_PID))
  expect(sets.find((s) => s.seg_id === 'thr-demo')).toMatchObject({ kind: 'task', n_items: 1, is_default: false })
  const project = await settle(api.setDefaultSeg(DEMO_PID, 'thr-demo'))
  expect(project.default_seg).toBe('thr-demo')
  const item = await settle(api.getItem(DEMO_PID, 'case_00001.01.complete.-'))
  expect(item.mask).toEqual(item.masks['thr-demo'])
})
