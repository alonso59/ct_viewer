// @vitest-environment jsdom
// UI-06: a toolbar is one Tab stop; arrows, Home and End move between its controls, a field keeps
// its own arrows, and Tab leaves the toolbar.
import { fireEvent, render, screen } from '@testing-library/react'

import { toolbarKeyDown } from './toolbarKeys'

beforeAll(() => {
  // jsdom lays nothing out: every element counts as shown
  Element.prototype.getClientRects = () => [{}] as unknown as DOMRectList
})

test('arrows move inside the toolbar, a field keeps them, Tab leaves it', () => {
  render(
    <>
      <div role="toolbar" aria-label="Tools" onKeyDown={toolbarKeyDown}>
        <button type="button">One</button>
        <button type="button" disabled>Off</button>
        <input aria-label="Width" />
        <button type="button">Two</button>
      </div>
      <button type="button">After</button>
    </>,
  )
  const [one, two, width, after] = ['One', 'Two', 'Width', 'After'].map((name) => (name === 'Width' ? screen.getByRole('textbox', { name }) : screen.getByRole('button', { name })))
  one!.focus()
  fireEvent.keyDown(one!, { key: 'ArrowRight' })
  expect(width).toHaveFocus()
  fireEvent.keyDown(width!, { key: 'ArrowRight' })
  expect(width).toHaveFocus()
  two!.focus()
  fireEvent.keyDown(two!, { key: 'ArrowRight' })
  expect(one).toHaveFocus()
  fireEvent.keyDown(one!, { key: 'End' })
  expect(two).toHaveFocus()
  fireEvent.keyDown(two!, { key: 'Tab' })
  expect(after).toHaveFocus()
})
