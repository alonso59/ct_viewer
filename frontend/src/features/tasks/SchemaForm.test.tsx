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

test('titles, enum names and bounded GPU checkboxes', () => {
  const onChange = vi.fn()
  const { rerender } = render(<SchemaForm schema={schema} values={{}} errors={{}} onChange={onChange} />)
  expect(screen.getByLabelText('Model')).toHaveDisplayValue('KiTS 2023 kidney')
  const gpus = screen.getByRole('group', { name: 'GPUs' })
  expect(screen.getByText(/runner picks idle approved GPUs/)).toBeInTheDocument()
  fireEvent.click(within(gpus).getByRole('checkbox', { name: 'GPU 6 · A40 · busy' }))
  expect(onChange).toHaveBeenLastCalledWith({ gpu_ids: ['6'] })
  rerender(<SchemaForm schema={schema} values={{ gpu_ids: ['6'] }} errors={{}} onChange={onChange} />)
  expect(within(gpus).getByRole('checkbox', { name: 'GPU 6 · A40 · busy' })).toBeChecked()
  expect(within(gpus).getByRole('checkbox', { name: 'GPU 0 · A40' })).toBeDisabled() // maxItems reached
  expect(screen.queryByText(/runner picks idle approved GPUs/)).toBeNull()
  fireEvent.click(within(gpus).getByRole('checkbox', { name: 'GPU 6 · A40 · busy' }))
  expect(onChange).toHaveBeenLastCalledWith({ gpu_ids: [] })
})

test('GPU states show an icon in the list and an unavailable GPU cannot be picked', () => {
  const states = { type: 'object', properties: { gpu_ids: { type: 'array', title: 'GPUs', maxItems: 2, items: { type: 'string', enum: ['0', '1', '2'], 'x-enumNames': ['GPU 0', 'GPU 1', 'GPU 2'], 'x-enumStatus': ['ready', 'warning', 'unavailable'] } } } }
  render(<SchemaForm schema={states} values={{}} errors={{}} onChange={vi.fn()} />)
  const gpus = screen.getByRole('group', { name: 'GPUs' })
  expect(within(gpus).getByRole('checkbox', { name: /GPU 0/ })).toBeEnabled()
  expect(within(gpus).getByRole('checkbox', { name: /GPU 1/ })).toBeEnabled()
  expect(within(gpus).getByRole('checkbox', { name: /GPU 2/ })).toBeDisabled()
  expect(within(gpus).getByLabelText('Ready')).toBeInTheDocument()
  expect(within(gpus).getByLabelText('Shared with other work')).toBeInTheDocument()
  expect(within(gpus).getByLabelText('Unavailable')).toBeInTheDocument()
})

test('never offers the folder list a batch plan sets', () => {
  const withFolders = { type: 'object', properties: { ...schema.properties, patient_folders: { type: 'array', title: 'Patient folders', items: { type: 'string' }, 'x-advanced': true } } }
  render(<SchemaForm schema={withFolders} values={{}} errors={{}} onChange={vi.fn()} />)
  expect(screen.queryByRole('button', { name: /advanced/i })).toBeNull()
  expect(screen.queryByText('Patient folders')).toBeNull()
})

// TSK-02 / UI-20 (accessible schema form): help, default and error are linked to the field; an error
// shows once the field is left, not while typing; a required field is marked; without a title the
// property name reads as words and a unit suffix becomes the unit
test('linked help, errors after leaving a field, required fields and readable titles', () => {
  const s = {
    type: 'object',
    required: ['patient_limit'],
    properties: {
      patient_limit: { type: 'integer', minimum: 1, 'x-help': 'Patients per batch' },
      delay_s: { type: 'integer', minimum: 0, maximum: 30, default: 0 },
    },
  }
  render(<SchemaForm schema={s} values={{ delay_s: 99 }} errors={{ delay_s: 'tasks.err.max' }} onChange={vi.fn()} />)
  const limit = screen.getByRole('spinbutton', { name: 'Patient limit' })
  expect(limit).toHaveAttribute('aria-required', 'true')
  expect(limit).toHaveAccessibleDescription('Patients per batch')
  expect(screen.getByText('required')).toBeInTheDocument()
  const delay = screen.getByRole('spinbutton', { name: 'Delay' })
  expect(screen.getByText('s')).toBeInTheDocument()
  expect(delay).toHaveAccessibleDescription('Default: 0')
  expect(screen.queryByText('Must be ≤ 30')).toBeNull()
  fireEvent.blur(delay)
  expect(screen.getByText('Must be ≤ 30')).toBeInTheDocument()
  expect(delay).toHaveAttribute('aria-invalid', 'true')
  expect(delay).toHaveAccessibleDescription('Default: 0 Must be ≤ 30')
})

// an untouched invalid field shows its error once the form says so (its action is blocked); a choice
// with no default reads "Choose…" when required, "From the project preset" otherwise
test('showAllErrors marks fields never left; an enum without default names what is missing', () => {
  const s = {
    type: 'object',
    required: ['patient_limit', 'model'],
    properties: {
      patient_limit: { type: 'integer', minimum: 1 },
      model: { type: 'string', title: 'Model', enum: ['a', 'b'] },
      target: { type: 'string', title: 'Target', enum: ['x'] },
    },
  }
  const errors = { patient_limit: 'tasks.err.required' }
  const { rerender } = render(<SchemaForm schema={s} values={{}} errors={errors} onChange={vi.fn()} />)
  expect(screen.queryByText('Required')).toBeNull()
  rerender(<SchemaForm schema={s} values={{}} errors={errors} showAllErrors onChange={vi.fn()} />)
  expect(screen.getByRole('spinbutton', { name: /Patient limit/ })).toHaveAttribute('aria-invalid', 'true')
  expect(within(screen.getByLabelText(/Model/)).getByRole('option', { name: 'Choose…' })).toBeInTheDocument()
  expect(within(screen.getByLabelText('Target')).getByRole('option', { name: 'From the project preset' })).toBeInTheDocument()
})
