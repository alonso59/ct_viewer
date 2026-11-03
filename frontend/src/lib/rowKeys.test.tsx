// @vitest-environment jsdom
// DB-03: table rows that open something work from the keyboard: one Tab stop per table, arrows
// move between the rows that open something, Enter acts as the click, Shift+F10 opens the row's menu.
import { fireEvent, render, screen } from '@testing-library/react'

import { useRowKeys } from './rowKeys'

function Table({ ids, onOpen, onMenu }: { ids: string[]; onOpen: (id: string) => void; onMenu?: (id: string) => void }) {
  // `note` rows open nothing, like an error without an item
  const rowKeys = useRowKeys(ids.filter((id) => !id.startsWith('note')))
  return (
    <table>
      <tbody>
        {ids.map((id) =>
          id.startsWith('note') ? (
            <tr key={id}>
              <td>{id}</td>
            </tr>
          ) : (
            <tr
              key={id}
              onClick={() => onOpen(id)}
              onContextMenu={
                onMenu
                  ? (e) => {
                      e.preventDefault()
                      onMenu(id)
                    }
                  : undefined
              }
              {...rowKeys(id)}
            >
              <td>
                {id}
                <button type="button">in {id}</button>
              </td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  )
}

const row = (id: string) => screen.getByText(id, { selector: 'td' }).closest('tr') as HTMLElement

test('one Tab stop per table; arrows skip rows that open nothing and move the stop (DB-03)', () => {
  render(<Table ids={['note-0', 'a', 'note-1', 'b', 'c']} onOpen={() => {}} />)
  expect(['a', 'b', 'c'].map((id) => row(id).getAttribute('tabindex'))).toEqual(['0', '-1', '-1'])
  expect(row('note-1').hasAttribute('tabindex')).toBe(false)
  row('a').focus()
  fireEvent.keyDown(row('a'), { key: 'ArrowDown' })
  expect(document.activeElement).toBe(row('b'))
  expect(['a', 'b', 'c'].map((id) => row(id).getAttribute('tabindex'))).toEqual(['-1', '0', '-1'])
  fireEvent.keyDown(row('b'), { key: 'End' })
  expect(document.activeElement).toBe(row('c'))
  fireEvent.keyDown(row('c'), { key: 'Home' })
  expect(document.activeElement).toBe(row('a'))
  fireEvent.keyDown(row('a'), { key: 'ArrowUp' })
  expect(document.activeElement).toBe(row('a'))
})

test('Enter opens the row; Shift+F10 opens its menu instead of the browser menu (DB-03)', () => {
  const onOpen = vi.fn()
  const onMenu = vi.fn()
  render(<Table ids={['a', 'b']} onOpen={onOpen} onMenu={onMenu} />)
  fireEvent.keyDown(row('b'), { key: 'Enter' })
  expect(onOpen).toHaveBeenCalledWith('b')
  expect(fireEvent.keyDown(row('a'), { key: 'F10', shiftKey: true })).toBe(false)
  expect(onMenu).toHaveBeenCalledWith('a')
  expect(fireEvent.keyDown(row('b'), { key: 'ContextMenu' })).toBe(false)
  expect(onMenu).toHaveBeenLastCalledWith('b')
})

test('a row without its own menu leaves the menu key alone; keys of a control in a row stay with it (DB-03)', () => {
  const onOpen = vi.fn()
  render(<Table ids={['a', 'b']} onOpen={onOpen} />)
  expect(fireEvent.keyDown(row('a'), { key: 'F10', shiftKey: true })).toBe(true)
  fireEvent.keyDown(screen.getByRole('button', { name: 'in a' }), { key: 'Enter' })
  fireEvent.keyDown(screen.getByRole('button', { name: 'in a' }), { key: 'ArrowDown' })
  expect(onOpen).not.toHaveBeenCalled()
  expect(document.activeElement).not.toBe(row('b'))
})
