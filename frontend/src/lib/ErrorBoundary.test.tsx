// @vitest-environment jsdom
// FE-09: a render failure stays inside its region and offers Try again / Reload the app.
import { fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'

import '../i18n'
import { ErrorBoundary } from './ErrorBoundary'

let broken = true
function Fragile() {
  if (broken) throw new Error('boom')
  return <p>{'ok'}</p>
}

test('a failing child shows the cause and next steps; siblings keep rendering (FE-09)', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <>
      <ErrorBoundary><Fragile /></ErrorBoundary>
      <p>{'sibling'}</p>
    </>,
  )
  expect(screen.getByRole('alert')).toHaveTextContent('This part of the window stopped working')
  expect(screen.getByRole('alert')).toHaveTextContent('boom')
  expect(screen.getByText('sibling')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reload the app' })).toBeInTheDocument()
  broken = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(screen.getByText('ok')).toBeInTheDocument()
})

test('an effect cleanup that is not a function is contained by the boundary (FE-09)', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  function BadEffect() {
    const [n, setN] = useState(0)
    useEffectReturningPromise(n)
    return <button type="button" onClick={() => setN(n + 1)}>{'again'}</button>
  }
  render(<ErrorBoundary><BadEffect /></ErrorBoundary>)
  fireEvent.click(screen.getByRole('button', { name: 'again' }))
  expect(screen.getByRole('alert')).toHaveTextContent('This part of the window stopped working')
})

/** The shape Chromium 153 produced when an effect returned scrollIntoView() */
function useEffectReturningPromise(dep: number) {
  // eslint-disable-next-line no-restricted-syntax -- the failure this boundary contains
  useEffect(() => Promise.resolve() as unknown as () => void, [dep])
}
