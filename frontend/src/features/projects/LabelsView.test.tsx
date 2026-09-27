// @vitest-environment jsdom
// PRJ-07 / PRJ-15 (AUD-A5-07) on the recorded API (TST-04): typing a label name saves once, on
// blur, with every character; a stale version (the recorded 412) shows the conflict and "Reload
// and reapply" sends the same edit again on the reloaded version.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'

import '../../i18n'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { recordedProblem } from '../../test/recorded'
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
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
  expect(spy.mock.calls[0]?.[1][0]?.name).toBe(`${before}abcdefghij`)
  spy.mockRestore()
})

test('a stale version shows the conflict; reload and reapply keeps the other edit', async () => {
  const project = await api.getProject(DEMO_PID)
  const spy = vi.spyOn(api, 'updateLabelMap').mockRejectedValueOnce(recordedProblem('PATCH', `/api/v1/projects/${DEMO_PID}`, { description: 'stale' }))
  renderView()
  const [, second] = await screen.findAllByRole('textbox', { name: 'Label name' })
  fireEvent.change(second!, { target: { value: 'mine' } })
  fireEvent.keyDown(second!, { key: 'Enter' })
  expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reload and reapply' }))
  // the edit goes again, on the reloaded map and version; the other labels are the server's
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  const [, labels, etag] = spy.mock.calls[1]!
  expect(labels.map((l) => l.name)).toEqual(project.label_map.map((l, i) => (i === 1 ? 'mine' : l.name)))
  expect(etag).toBe(project.etag)
  spy.mockRestore()
})
