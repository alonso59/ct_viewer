// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'

import '../i18n'
import { SchedulerLine, schedulerOf } from './SchedulerLine'

test('the run shows what the scheduler reported, and nothing it did not', () => {
  const status = schedulerOf({ scheduler: { job_id: '41', state: 'PENDING', pending_reason: 'Priority', node: null, elapsed: '0:00', time_limit: '8:00:00', profile: 'One A100' } })
  expect(status).not.toBeNull()
  render(<SchedulerLine status={status!} />)
  expect(screen.getByRole('status')).toHaveTextContent('Scheduler: PENDING (Priority) · job 41 · 0:00 of 8:00:00 · profile One A100')
  expect(screen.queryByText(/node/)).toBeNull()
})

test('accounting and efficiency appear once the job has ended', () => {
  render(<SchedulerLine status={{ state: 'COMPLETED', accounting: { state: 'COMPLETED', elapsed: '01:02:03', exit_code: '0:0' }, efficiency: 'CPU Efficiency: 80%' }} />)
  expect(screen.getByText('Accounting: COMPLETED · 01:02:03 · exit 0:0')).toBeInTheDocument()
  expect(screen.getByText('Efficiency report')).toBeInTheDocument()
})

test('a run without a scheduler record has no line', () => {
  expect(schedulerOf(null)).toBeNull()
  expect(schedulerOf({ scheduler: 'x' })).toBeNull()
  expect(schedulerOf({ phase_step: true })).toBeNull()
})
