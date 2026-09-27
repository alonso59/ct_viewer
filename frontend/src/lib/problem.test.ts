// UI-18 / FE-09 (AUD-A6-12): one helper words every problem for toasts and notes, with its actions.
import { expect, test } from 'vitest'

import '../i18n'
import { ProblemError, toProblemError } from '../api/problem'
import { problemActions, problemMessage, problemToastText } from './problem'

test('the cause first, then the plain title; other errors use the fallback or their message', () => {
  expect(problemMessage(new ProblemError(409, 'conflict', 'Conflict', 'Another derived variable uses "x"'))).toBe('Another derived variable uses "x"')
  const generic = toProblemError(409, { type: '/problems/derived-root-required', title: 'Derived root required' }, 'x')
  expect(problemMessage(generic)).not.toBe('')
  expect(problemMessage(new TypeError('Failed to fetch'), 'Could not save')).toBe('Could not save')
  expect(problemMessage(new Error('boom'))).toBe('boom')
  expect(problemMessage('?')).toBe('Something went wrong')
})

test('a toast names the next steps', () => {
  const e = toProblemError(409, { type: '/problems/derived-root-required', title: 't', detail: 'Choose a derived folder first', actions: ['choose_derived_root'] }, 'x')
  expect(problemActions(e)).toEqual(['Choose the derived folder'])
  expect(problemToastText(e)).toBe('Choose a derived folder first Next: Choose the derived folder.')
  expect(problemToastText(new Error('boom'))).toBe('boom')
})
