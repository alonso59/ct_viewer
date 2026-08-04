import { describe, expect, it } from 'vitest'

import { routeUsesStandaloneShell } from './applicationShell'

describe('application shell routing', () => {
  it('uses the standalone Open Dataset surface only at the root route', () => {
    expect(routeUsesStandaloneShell('/')).toBe(true)
    expect(routeUsesStandaloneShell('/datasets/Dataset420/cases')).toBe(false)
    expect(routeUsesStandaloneShell('/datasets/Dataset420/patients')).toBe(false)
    expect(
      routeUsesStandaloneShell('/datasets/Dataset420/patients/case_00001/viewer'),
    ).toBe(false)
  })
})
