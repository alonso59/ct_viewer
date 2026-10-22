// @vitest-environment jsdom
// TSK-02 / G1: fields are labelled by `title`, enum values by `x-enumNames`; an array of enum is a
// group of toggles bounded by `maxItems`, empty meaning automatic selection.
import { fireEvent, render, screen, within } from '@testing-library/react'

import '../../i18n'
import '../../i18n/lazy'
import { SchemaForm } from './SchemaForm'

const schema = {
  type: 'object',
  properties: {
    profile: { type: 'string', title: 'Model', enum: ['kits'], 'x-enumNames': ['KiTS 2023 kidney'], default: 'kits' },
    gpu_ids: {
      type: 'array',
      title: 'GPUs',
      maxItems: 1,
      items: { type: 'string', enum: ['0', '6'], 'x-enumNames': ['GPU 0 · A40', 'GPU 6 · A40 · busy'] },
    },
  },
}

test('titles, enum names and bounded GPU toggles', () => {
  const onChange = vi.fn()
  const { rerender } = render(<SchemaForm schema={schema} values={{}} errors={{}} onChange={onChange} />)
  expect(screen.getByLabelText('Model')).toHaveDisplayValue('KiTS 2023 kidney')
  const gpus = screen.getByRole('group', { name: 'GPUs' })
  expect(screen.getByText(/runner picks idle approved GPUs/)).toBeInTheDocument()
  fireEvent.click(within(gpus).getByRole('button', { name: 'GPU 6 · A40 · busy' }))
  expect(onChange).toHaveBeenLastCalledWith({ gpu_ids: ['6'] })
  rerender(<SchemaForm schema={schema} values={{ gpu_ids: ['6'] }} errors={{}} onChange={onChange} />)
  expect(within(gpus).getByRole('button', { name: 'GPU 6 · A40 · busy' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(gpus).getByRole('button', { name: 'GPU 0 · A40' })).toBeDisabled() // maxItems reached
  expect(screen.queryByText(/runner picks idle approved GPUs/)).toBeNull()
  fireEvent.click(within(gpus).getByRole('button', { name: 'GPU 6 · A40 · busy' }))
  expect(onChange).toHaveBeenLastCalledWith({ gpu_ids: [] })
})
