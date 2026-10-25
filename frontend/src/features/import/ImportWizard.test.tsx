// @vitest-environment jsdom
// SRC-19/U08: asynchronous import discovery returns through the existing adapter wizard.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import '../../i18n'
import '../../i18n/lazy'
import { api } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { plugin } from '../../plugins/dicom'
import { useConverter } from '../../plugins/dicom/store'
import { registry } from '../../shell'
import Wizard from './ImportWizard'
import { useImportWizard, type WizardPrefill } from './store'

const ID = '01JSYNTHDISCOVERY000000000'
function show(prefill: WizardPrefill) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><Wizard pid={DEMO_PID} prefill={prefill} /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { useConverter.getState().close(); useImportWizard.getState().close(); vi.restoreAllMocks() })

test('reuses completed detection rather than rescanning when returning to the wizard', async () => {
  const legacy = vi.spyOn(api, 'detectSource')
  show({ path: '/open-data/images', kind: 'folder', discoveryId: ID, alias: 'IMAGES' })
  await screen.findByText('503 NIfTI files')
  expect(legacy).not.toHaveBeenCalled()
})

test('starts discovery with its project and import choices, then opens the shared window', async () => {
  const record = await api.getSourceOperation(ID)
  const start = vi.spyOn(api, 'startSourceOperation').mockResolvedValue({ ...record, project_id: DEMO_PID })
  const legacy = vi.spyOn(api, 'detectSource')
  plugin.activate({ registry, revealView: () => undefined })
  show({ path: '/open-data/images', alias: 'SCANS', add: true, modality: 'MR', options: { include: ['0000.nii.gz'] } })
  await waitFor(() => expect(start).toHaveBeenCalled())
  expect(start).toHaveBeenCalledWith(expect.objectContaining({
    path: '/open-data/images', project_id: DEMO_PID, purpose: 'discover', prepare_plan: false,
    import_context: { alias: 'SCANS', adapter: null, add: true, options: { include: ['0000.nii.gz'], modality: 'MR' } },
    idempotency_key: expect.any(String),
  }))
  expect(legacy).not.toHaveBeenCalled()
  expect(useConverter.getState().operationId).toBe(ID)
})

test('DICOM hands off to a durable dry run before any conversion is launched', async () => {
  const record = await api.getSourceOperation(ID)
  const start = vi.spyOn(api, 'startSourceOperation').mockResolvedValue({ ...record, project_id: DEMO_PID })
  const native = vi.spyOn(api, 'startTaskRun')
  plugin.activate({ registry, revealView: () => undefined })
  show({ path: '/open-data/images', kind: 'folder', discoveryId: ID })
  await screen.findByText('503 NIfTI files')
  fireEvent.click(screen.getByRole('radio', { name: /DICOM/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({ purpose: 'convert', prepare_plan: true, project_id: DEMO_PID })))
  expect(native).not.toHaveBeenCalled()
})
