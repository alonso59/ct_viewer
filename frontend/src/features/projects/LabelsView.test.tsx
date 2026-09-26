// PRJ-07 / PRJ-15 (AUD-A5-07) on the mock API: typing a label name saves once, on blur, with every
// character; a stale version shows the conflict and "Reload and reapply" keeps both edits.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { useWorkbench } from '../../shell'
import { LabelsView } from './LabelsView'

function renderView() {
  useWorkbench.setState({ pid: DEMO_PID })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LabelsView />
    </QueryClientProvider>,
  )
}

test('keystrokes stay a local draft; blur saves the whole name in one write', async () => {
  const spy = vi.spyOn(api, 'updateLabelMap')
  renderView()
  const first = (await screen.findAllByRole('textbox', { name: 'Label name' }))[0]!
  const before = (first as HTMLInputElement).value
  let typed = before
  for (const ch of 'abcdefghij') {
    typed += ch
    fireEvent.change(first, { target: { value: typed } })
  }
  expect(spy).not.toHaveBeenCalled()
  fireEvent.blur(first)
  await waitFor(async () => expect((await api.getProject(DEMO_PID)).label_map[0]?.name).toBe(`${before}abcdefghij`))
  expect(spy).toHaveBeenCalledTimes(1)
  spy.mockRestore()
})

test('a stale version shows the conflict; reload and reapply keeps the other edit', async () => {
  renderView()
  const [, second] = await screen.findAllByRole('textbox', { name: 'Label name' })
  const other = await api.getProject(DEMO_PID)
  await api.updateLabelMap(DEMO_PID, other.label_map.map((l, i) => (i === 0 ? { ...l, name: 'by someone else' } : l)), other.etag)
  fireEvent.change(second!, { target: { value: 'mine' } })
  fireEvent.keyDown(second!, { key: 'Enter' })
  expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reload and reapply' }))
  await waitFor(async () => expect((await api.getProject(DEMO_PID)).label_map.map((l) => l.name).slice(0, 2)).toEqual(['by someone else', 'mine']))
})
