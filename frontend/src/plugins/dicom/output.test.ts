// @vitest-environment jsdom
// UI-29: a DICOM operation follows its workspace conversion's log once one runs.
import '../../i18n'
import { afterEach, expect, test } from 'vitest'

import { api, type SourceOperation } from '../../api'
import { registerJobs } from '../../features/jobs'
import { registry } from '../../shell'
import { showOperationOutput } from './output'

afterEach(() => {
  for (const c of registry.outputChannels) registry.removeOutputChannel(c.id)
})

test('maps an operation to its workspace run, else to itself', async () => {
  registerJobs()
  const [first] = await api.listSourceOperations()
  if (!first) throw new Error('No recorded source operation')
  const full = await api.getSourceOperation(first.operation_id)
  const base: SourceOperation = { ...full, project_id: null, dataset_name: 'ds' }
  showOperationOutput({ ...base, conversion_run: null })
  expect(registry.outputChannels).toEqual([
    { id: `dicom.${base.operation_id}`, label: 'ds · output', kind: 'source-operation', ref: base.operation_id },
  ])
  if (full.conversion_run) {
    showOperationOutput({ ...base, conversion_run: full.conversion_run })
    expect(registry.outputChannels).toEqual([
      { id: `dicom.${base.operation_id}`, label: 'ds · output', kind: 'workspace-run', ref: full.conversion_run.run_id },
    ])
  }
})
