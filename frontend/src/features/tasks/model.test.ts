// TSK-03 selection mapping and TSK-02 client checks.
import { check, defaults, toSettings } from './schema'
import { fromExplorer, parseIds, selectionFor } from './model'

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
