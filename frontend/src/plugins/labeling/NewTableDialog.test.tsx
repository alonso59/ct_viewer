// @vitest-environment jsdom
// ADR-0046 §4 (K2.2): a pack's clinical table templates fill the New table form; only the applied
// packs' templates are offered, and the form stays editable.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { keys, type PackInfo, type Project } from '../../api'
import { DEMO_PID } from '../../api/mock/server'
import { NewTableDialog } from './NewTableDialog'

const PACKS = [
  {
    pack_id: 'ccrcc', title: 'ccRCC', plugin: 'ccrcc', description: '', labels: [], phase_vocabulary: [], target_profile: 'kidneys',
    clinical_tables: [{ name: 'Clinical data', level: 'case', columns: [{ name: 'Histology', type: 'category', levels: ['Clear cell', 'Papillary'] }, { name: 'Tumor size', type: 'number', unit: 'mm' }] }],
  },
  { pack_id: 'other', title: 'Other', plugin: 'o', description: '', labels: [], phase_vocabulary: [], target_profile: 'generic', clinical_tables: [{ name: 'Hidden', level: 'case', columns: [] }] },
] as unknown as PackInfo[]

function renderDialog(applied: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.packs(), PACKS)
  qc.setQueryData(keys.project(DEMO_PID), { project_id: DEMO_PID, packs: applied } as unknown as Project)
  qc.setQueryData(keys.variables(DEMO_PID), [])
  return render(<QueryClientProvider client={qc}><NewTableDialog pid={DEMO_PID} labels={[]} onClose={() => {}} /></QueryClientProvider>)
}

test('a template of an applied pack fills the name, level and columns', async () => {
  renderDialog(['ccrcc'])
  const choice = await screen.findByRole('combobox', { name: 'Start from a template' })
  expect(screen.queryByRole('option', { name: /Hidden/ })).not.toBeInTheDocument()
  fireEvent.change(choice, { target: { value: '0' } })
  expect(screen.getByRole('textbox', { name: 'Table name' })).toHaveValue('Clinical data')
  expect(screen.getByDisplayValue('Histology')).toBeInTheDocument()
  expect(screen.getByDisplayValue('Clear cell, Papillary')).toBeInTheDocument()
  expect(screen.getByDisplayValue('mm')).toBeInTheDocument()
})

test('no template choice when no applied pack offers one', () => {
  renderDialog([])
  expect(screen.queryByRole('combobox', { name: 'Start from a template' })).not.toBeInTheDocument()
})
