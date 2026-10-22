// TSK-03 selection mapping and TSK-02 client checks.
import { check, defaults, toSettings } from './schema'
import { fromExplorer, parseIds, runActions, selectionFor } from './model'

test('explorer filter → task selection', () => {
  expect(fromExplorer({ itemIds: ['a.01.complete.-'] })).toEqual({ item_ids: ['a.01.complete.-'] })
  expect(fromExplorer({ phase: 'NP', vars: { sex: 'F', age: '40..60' } })).toEqual({ filter: { phase: ['NP'], var: { sex: ['F'] } } })
  expect(fromExplorer({})).toEqual({})
  expect(selectionFor('list', {}, 'a, b\nb', { seg_id: 'imported' })).toEqual({ item_ids: ['a', 'b'], seg_id: 'imported' })
  expect(parseIds(' x ;y ')).toEqual(['x', 'y'])
})

test('schema subset: defaults, checks, only set values are sent', () => {
  const schema = { type: 'object', properties: { label: { type: 'integer', minimum: 1, maximum: 9, default: 1 }, mode: { type: 'string', enum: ['a', 'b'] }, id: { type: 'string', pattern: '^[a-z]+$' } } }
  expect(defaults(schema)).toEqual({ label: 1 })
  expect(check(schema, { label: 0, mode: 'c', id: 'A' })).toEqual({ label: 'tasks.err.min', mode: 'tasks.err.enum', id: 'tasks.err.pattern' })
  expect(check(schema, { label: 2.5 })).toEqual({ label: 'tasks.err.integer' })
  expect(toSettings({ a: 1, b: undefined, c: '' })).toEqual({ a: 1 })
})

test('GPU choices enforce membership, uniqueness and the four-device maximum', () => {
  const schema = { type: 'object', properties: { gpu_ids: { type: 'array', items: { type: 'string', enum: ['0', '1', '2', '3', '4', '5', '6'] }, maxItems: 4, uniqueItems: true, default: [] } } }
  expect(defaults(schema)).toEqual({ gpu_ids: [] })
  expect(check(schema, { gpu_ids: ['0', '6'] })).toEqual({})
  expect(check(schema, { gpu_ids: ['7'] })).toEqual({ gpu_ids: 'tasks.err.enum' })
  expect(check(schema, { gpu_ids: ['0', '0'] })).toEqual({ gpu_ids: 'tasks.err.enum' })
  expect(check(schema, { gpu_ids: ['0', '1', '2', '3', '4'] })).toEqual({ gpu_ids: 'tasks.err.max' })
})

// TSK-15 / U1: lifecycle actions follow the run state; pending controls are never "done".
test('supervised lifecycle actions by state; none on view-only links', () => {
  const run = (status: string, extra: object = {}) =>
    ({ status, supervised: true, archived: false, control: null, task: { id: 'segment.nnunet' }, ...extra }) as Parameters<typeof runActions>[0]
  expect(runActions(run('running'), false)).toEqual(['pause', 'cancel'])
  expect(runActions(run('waiting_for_resources'), false)).toEqual(['pause', 'cancel'])
  expect(runActions(run('pausing', { control: { action: 'pause', acknowledged_at: null } }), false)).toEqual(['cancel'])
  expect(runActions(run('cancelling', { control: { action: 'cancel', acknowledged_at: null } }), false)).toEqual([])
  expect(runActions(run('cleanup_pending', { control: { action: 'pause', acknowledged_at: null } }), false)).toEqual(['cancel'])
  expect(runActions(run('paused'), false)).toEqual(['resume', 'archive'])
  expect(runActions(run('completed_with_errors'), false)).toEqual(['resume', 'archive'])
  expect(runActions(run('completed'), false)).toEqual(['archive'])
  expect(runActions(run('paused', { archived: true }), false)).toEqual([])
  expect(runActions(run('running'), true)).toEqual([])
  // builtin / unsupervised runs keep cancel + resume only
  expect(runActions(run('running', { supervised: false }), false)).toEqual(['cancel'])
  expect(runActions(run('failed', { supervised: false }), false)).toEqual(['resume'])
  expect(runActions(run('completed_with_errors', { supervised: false }), false)).toEqual([])
})
