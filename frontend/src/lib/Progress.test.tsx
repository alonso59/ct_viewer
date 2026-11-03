// @vitest-environment jsdom
// FE-08: every progress bar is named and reads its value as "N of M"; an indeterminate bar is busy.
import { render, screen } from '@testing-library/react'

import '../i18n'
import { IndeterminateProgress, Progress } from './ui'

test('a determinate bar has a name, a percentage and a readable value (FE-08)', () => {
  render(<Progress value={86} total={187} label="Full hash" />)
  const bar = screen.getByRole('progressbar', { name: 'Full hash' })
  expect(bar).toHaveAttribute('aria-valuenow', '46')
  expect(bar).toHaveAttribute('aria-valuetext', '86 of 187')
})

test('an indeterminate bar is a named, busy progressbar without a value (FE-08)', () => {
  render(<IndeterminateProgress label="Counting files" />)
  const bar = screen.getByRole('progressbar', { name: 'Counting files' })
  expect(bar).toHaveAttribute('aria-busy', 'true')
  expect(bar).not.toHaveAttribute('aria-valuenow')
})
