// @vitest-environment jsdom
// UI-25: every progress label shows the counter that means something in its stage, never "0 / 0" or "N / 0".
import { describe, expect, test } from 'vitest'

import i18n from '../../i18n'
import '../../i18n/lazy'
import type { SourceOperation } from '../../api'
import { countLabel, operationCount, runCount } from './OperationProgress'

const op = (patch: Partial<SourceOperation>) => ({ work_kind: 'inventory', progress: {}, progress_stage: null, ...patch }) as SourceOperation
const label = (count: Parameters<typeof countLabel>[1]) => countLabel(i18n.t.bind(i18n), count)

describe('source operation counters', () => {
  test.each([
    ['counting files', op({ progress_stage: 'counting', progress: { files_total: 900 } }), 'Counting files · 900 so far'],
    ['scanning against the pre-count', op({ progress: { files: 250, files_total: 1000 } }), 'Scanning source · 250 / 1,000'],
    ['scanning before a pre-count', op({ progress: { files: 20 } }), 'Scanning source · 20 so far'],
    ['an analysis listing folders', op({ work_kind: 'estimate', progress_stage: 'listing', progress: { done: 4000, total: 0 } }), 'Listing folders · 4,000 so far'],
    ['an analysis reading headers', op({ work_kind: 'estimate', progress_stage: 'reading', progress: { done: 120, total: 450 } }), 'Reading headers · 120 / 450'],
    ['an analysis that has not reported yet', op({ work_kind: 'estimate', progress_stage: 'admitted' }), 'Looking for DICOM files'],
    ['the source check before converting', op({ work_kind: 'convert' }), 'Checking the source'],
  ])('%s', (_, value, text) => expect(label(operationCount(value))).toBe(text))
})

describe('conversion run counters', () => {
  test.each([
    ['admitted', { done: 0, total: 0, stage: 'admitted', stage_done: 0, stage_total: 0 }, 'Starting'],
    ['listing patients', { done: 0, total: 0, stage: 'listing', stage_done: 40, stage_total: 0 }, 'Listing folders · 40 so far'],
    ['reading headers before the series are known', { done: 0, total: 0, stage: 'reading', stage_done: 245856, stage_total: 410517 }, 'Reading headers · 245,856 / 410,517'],
    ['fingerprinting inputs', { done: 0, total: 2506, stage: 'verifying_inputs', stage_done: 26, stage_total: 2506 }, 'Fingerprinting source files · 26 / 2,506'],
    ['converting series', { done: 12, total: 2506, stage: 'converting', stage_done: 13, stage_total: 2506 }, 'Converting series · 12 / 2,506'],
    ['analyzing phase', { done: 2506, total: 2506, stage: 'analyzing', stage_done: 3, stage_total: 10 }, 'Analyzing phase · 3 / 10'],
  ])('%s', (_, progress, text) => expect(label(runCount(progress))).toBe(text))
})
