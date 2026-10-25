// API-19/69, SRC-19: actual recorded discovery results through the HTTP binding.
import { expect, test } from 'vitest'

import { mockServer } from './mock/server'

test('durable detection returns the recorded complete mixed inventory and bounded sample', async () => {
  const result = await mockServer.sourceOperationDetection('01JSYNTHDISCOVERY000000000')
  expect(result.counts.nifti).toBe(503)
  expect(result.counts.dicom).toBe(3)
  expect(result.truncated).toBe(false)
  expect(result.candidates.map((candidate) => candidate.adapter)).toEqual(['nifti-files', 'dicom.convert', 'open'])
  const sample = result.candidates.find((candidate) => candidate.adapter === 'nifti-files')?.sample
  expect(sample).toHaveLength(50)
  expect(sample?.[0]).toBe('0000.nii.gz')
  expect(sample?.at(-1)).toBe('0492.nii.gz')
})
