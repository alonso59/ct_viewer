// @vitest-environment jsdom
// UI-18 / SRC-11: a problem shows its cause and its next actions as buttons.
import { fireEvent, render, screen } from '@testing-library/react'

import '../i18n'
import { ProblemError, parseAction, toProblemError } from '../api/problem'
import { ProblemCard } from './ProblemCard'

test('toProblemError keeps detail and actions', () => {
  const e = toProblemError(422, { type: '/problems/validation', title: 'Validation failed', status: 422, detail: 'No metadata.jsonl under the root; 11 NIfTI files found', actions: ['import_as:nifti-files', 'open', 3] }, 'x')
  expect(e).toMatchObject({ type: 'validation', detail: 'No metadata.jsonl under the root; 11 NIfTI files found', actions: ['import_as:nifti-files', 'open'] })
  expect(parseAction('import_as:nifti-files')).toEqual({ name: 'import_as', arg: 'nifti-files' })
  expect(parseAction('open')).toEqual({ name: 'open', arg: null })
})

test('actions with a handler are buttons; the rest are hints', () => {
  const importAs = vi.fn()
  const err = new ProblemError(422, 'validation', 'Validation failed', 'No metadata.jsonl', ['import_as:nifti-files', 'configure:ALLOWED_DERIVED_ROOTS'])
  render(<ProblemCard error={err} onAction={{ import_as: importAs }} />)
  expect(screen.getByRole('alert')).toHaveTextContent('No metadata.jsonl')
  fireEvent.click(screen.getByRole('button', { name: 'Import as nifti-files' }))
  expect(importAs).toHaveBeenCalledWith('nifti-files')
  expect(screen.queryByRole('button', { name: /ALLOWED_DERIVED_ROOTS/ })).toBeNull()
  expect(screen.getByText('Ask the admin to set ALLOWED_DERIVED_ROOTS')).toBeInTheDocument()
})

test('the title is the problem in plain words; the raw message is never the title (AUD-A2-07, AUD-A3-03)', () => {
  const err = toProblemError(403, { type: '/problems/path-outside-root', title: 'Path outside allowed roots', status: 403, detail: 'The server does not share this folder with the app.', actions: ['choose_another_path', 'home'] }, 'x')
  const { unmount } = render(<ProblemCard error={err} onAction={{ choose_another_path: vi.fn(), home: vi.fn() }} />)
  expect(screen.getByRole('alert')).toHaveTextContent('This folder is not shared with the app')
  expect(screen.queryByText('path-outside-root')).toBeNull() // no slug chip (UI-18)
  expect(screen.getByRole('button', { name: 'Go to the workspace home' })).toBeInTheDocument()
  unmount()
  render(<ProblemCard error={new Error('HeaderError: /data/secret/a.nii.gz: bad magic')} />)
  expect(screen.getByRole('alert').querySelector('strong')).toHaveTextContent('Something went wrong')
  expect(screen.getByRole('alert')).toHaveTextContent('bad magic')
})

test('a title the app wrote itself is kept', () => {
  render(<ProblemCard error={new ProblemError(404, 'not-found', 'No Open session', 'Open a file or folder.')} />)
  expect(screen.getByRole('alert').querySelector('strong')).toHaveTextContent('No Open session')
})
