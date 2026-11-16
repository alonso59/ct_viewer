// @vitest-environment jsdom
// PHS-01/04 helpers.
import { guessAccept, guessRun, phaseOptions } from './model'

test('phase options fall back to the default vocabulary', () => {
  expect(phaseOptions(['NC', 'ART'])).toEqual(['NC', 'ART'])
  expect(phaseOptions([])).toContain('NP')
})

test('a guess can be accepted only from the active analyzer run', () => {
  expect(guessRun({ source: 'analyzer:R1' }, 'R1')).toBe('R1')
  expect(guessRun({ source: 'analyzer:R1' }, 'R2')).toBeNull()
  expect(guessRun({ source: 'metadata' }, 'R1')).toBeNull()
  expect(guessRun({ source: 'manual' }, null)).toBeNull()
})

test('accept guess records the active run, or the metadata phase_guess', () => {
  expect(guessAccept({ source: 'analyzer:R1' }, 'R1')).toEqual({ source: 'analyzer_accept', accepted_run_id: 'R1' })
  expect(guessAccept({ source: 'phase_guess' }, null)).toEqual({ source: 'guess_accept' })
  expect(guessAccept({ source: 'phase' }, null)).toBeNull()
  expect(guessAccept({ source: 'manual' }, 'R1')).toBeNull()
})
