// @vitest-environment jsdom
import '../../i18n'
import { bootstrap } from '../../app/bootstrap'
import { registry } from '../../shell'

test('Cohort registers its navigator view, editor and open command', () => {
  bootstrap()
  const view = registry.views.find((v) => v.id === 'cohort')
  expect(view).toBeDefined()
  expect(view?.title).toBe('view.cohort')
  expect(view?.hideImageSection).toBe(true)
  // The cohort itself reads; the queue action in its cell menu carries the write gate
  expect(view?.writes).toBeUndefined()
  expect(registry.commands.get('view.show.cohort')).toBeDefined()

  const editor = registry.getEditor('cohort')
  expect(editor).toBeDefined()
  expect(editor?.id({})).toBe('cohort')
  expect(editor?.path?.('p1', {})).toBe('/p/p1/cohort')
  expect(editor?.match?.('/cohort', new URLSearchParams())).toEqual({})
  expect(editor?.match?.('/case/x', new URLSearchParams())).toBeNull()
  expect(editor?.writes).toBeUndefined()

  const open = registry.commands.get('cohort.open')
  expect(open).toBeDefined()
  expect(open?.category).toBe('cat.navigate')
  expect(open?.writes).toBeUndefined()
})
