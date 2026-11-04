// @vitest-environment jsdom
// DCM-34: an incomplete converter dataset shows its converted / failed / pending counts and asks
// for an explicit acknowledgment before the import can be committed.
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import '../../../i18n'
import type { ImportPreview } from '../../../api'
import { PreviewStep } from './PreviewStep'

const preview = (incomplete: ImportPreview['incomplete']): ImportPreview => ({
  preview_id: 'p',
  root: '/data/dataset',
  alias: 'DATA',
  files: [],
  counts: { scan_rows: 2, voi_rows: 0, cases: 1, excluded_upstream: 1, excluded_cases: 0 },
  errors: [],
  n_errors: 0,
  field_mapping: { image: 'relative_path', seg: null, phase: [], side: null },
  adapter: 'metadata-v1',
  options: {},
  sample: [],
  unmatched: [],
  orphan_masks: [],
  ignored: {},
  source_key: null,
  incomplete,
})

test('an incomplete dataset asks for acknowledgment with its counts', () => {
  const acknowledge = vi.fn()
  render(<PreviewStep p={preview({ converted: 3, failed: 1, pending: 2 })} acknowledged={false} onAcknowledge={acknowledge} />)
  expect(screen.getByRole('alert').textContent).toContain('3 series converted, 1 failed, 2 not converted yet')
  fireEvent.click(screen.getByRole('checkbox', { name: 'Import the converted series of this incomplete dataset' }))
  expect(acknowledge).toHaveBeenCalledWith(true)
})

test('a complete dataset shows no acknowledgment', () => {
  render(<PreviewStep p={preview(null)} />)
  expect(screen.queryByRole('checkbox', { name: /incomplete dataset/ })).toBeNull()
})
