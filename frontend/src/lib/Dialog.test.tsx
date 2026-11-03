// @vitest-environment jsdom
// FE-08, FE-11: closing a dialog gives focus back to the control that opened it; the close
// button is translated and a description is wired only when there is one.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'

import '../i18n'
import { Dialog } from './ui'

function Opener({ description }: { description?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open settings
      </button>
      <Dialog open={open} onOpenChange={setOpen} title="Settings" description={description}>
        <input aria-label="Name" />
      </Dialog>
    </>
  )
}

test('Escape and the close button give focus back to the invoking button (FE-08)', async () => {
  render(<Opener />)
  const invoker = screen.getByRole('button', { name: 'Open settings' })
  invoker.focus()
  fireEvent.click(invoker)
  await screen.findByRole('dialog', { name: 'Settings' })
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(document.activeElement).toBe(invoker))
  fireEvent.click(invoker)
  fireEvent.click(await screen.findByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(document.activeElement).toBe(invoker))
})

test('a description describes the dialog; without one nothing is referenced (FE-11)', async () => {
  const first = render(<Opener description="Change how the app looks." />)
  fireEvent.click(screen.getByRole('button', { name: 'Open settings' }))
  expect(await screen.findByRole('dialog', { name: 'Settings' })).toHaveAccessibleDescription('Change how the app looks.')
  first.unmount()
  render(<Opener />)
  fireEvent.click(screen.getByRole('button', { name: 'Open settings' }))
  expect((await screen.findByRole('dialog', { name: 'Settings' })).hasAttribute('aria-describedby')).toBe(false)
})

// FE-08: a caller that renders the dialog only while open (New project…) removes it at once; focus
// still goes back to the invoking button (Radix restores it on removal)
test('a dialog removed on close gives focus back too', async () => {
  function RenderedWhileOpen() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          New project
        </button>
        {open ? (
          <Dialog open onOpenChange={setOpen} title="New project">
            <input aria-label="Project name" />
          </Dialog>
        ) : null}
      </>
    )
  }
  render(<RenderedWhileOpen />)
  const invoker = screen.getByRole('button', { name: 'New project' })
  invoker.focus()
  fireEvent.click(invoker)
  await screen.findByRole('dialog', { name: 'New project' })
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(invoker).toHaveFocus())
})

// FE-08: a field that takes focus with autoFocus as the dialog opens (New project…) does not hide
// the invoker; closing still gives focus back to it
test('a dialog with an autoFocus field gives focus back to its invoker', async () => {
  function AutoFocusDialog() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Rename
        </button>
        {open ? (
          <Dialog open onOpenChange={setOpen} title="Rename">
            <input aria-label="New name" autoFocus />
          </Dialog>
        ) : null}
      </>
    )
  }
  render(<AutoFocusDialog />)
  const invoker = screen.getByRole('button', { name: 'Rename' })
  invoker.focus()
  fireEvent.click(invoker)
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'New name' })).toHaveFocus())
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(invoker).toHaveFocus())
})

