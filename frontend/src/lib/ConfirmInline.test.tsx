// @vitest-environment jsdom
// UI-20 / UI-28: a costly cancel asks inline first; Escape or Keep leaves the work running.
import { fireEvent, render, screen } from '@testing-library/react'

import '../i18n'
import { ConfirmInline } from './ui'

function setup() {
  const onConfirm = vi.fn()
  render(
    <ConfirmInline question="Cancel the conversion?" confirm="Yes, cancel" onConfirm={onConfirm}
      trigger={(ask) => <button type="button" onClick={ask}>{'Cancel conversion'}</button>} />,
  )
  return onConfirm
}

test('nothing is sent until the user confirms; focus moves to the confirm (UI-28)', () => {
  const onConfirm = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel conversion' }))
  expect(onConfirm).not.toHaveBeenCalled()
  expect(screen.getByRole('note')).toHaveTextContent('Cancel the conversion?')
  expect(screen.getByRole('button', { name: 'Yes, cancel' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Yes, cancel' }))
  expect(onConfirm).toHaveBeenCalledTimes(1)
})

test('Keep and Escape leave the work running and return focus to the trigger (UI-28)', () => {
  const onConfirm = setup()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel conversion' }))
  fireEvent.click(screen.getByRole('button', { name: 'Keep running' }))
  expect(screen.getByRole('button', { name: 'Cancel conversion' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel conversion' }))
  fireEvent.keyDown(screen.getByRole('button', { name: 'Yes, cancel' }), { key: 'Escape' })
  expect(screen.getByRole('button', { name: 'Cancel conversion' })).toBeInTheDocument()
  expect(onConfirm).not.toHaveBeenCalled()
})
