// D29 / API-46/62: phase controls target the child run and carry its attempt fence.
import { expect, test, vi } from 'vitest'

import { createHttpApi } from './http'

test('project and workspace controls serialize the expected attempt', async () => {
  const bodies: unknown[] = []
  const paths: string[] = []
  const fetch = vi.fn<typeof globalThis.fetch>(async (request) => {
    if (!(request instanceof Request)) throw new Error('Expected an HTTP Request')
    bodies.push(await request.json())
    paths.push(new URL(request.url).pathname)
    return new Response('{}', { headers: { 'content-type': 'application/json' } })
  })
  const api = createHttpApi(fetch, 'http://local')
  await api.resumeTaskRun('p', 'phase', { expected_attempt: 2 })
  await api.cancelTaskRun('p', 'phase', { expected_attempt: 3 })
  await api.resumeWorkspaceRun('phase', { expected_attempt: 4 })
  await api.cancelWorkspaceRun('phase', { expected_attempt: 5 })
  expect(paths).toEqual(['/api/v1/projects/p/task-runs/phase/resume', '/api/v1/projects/p/task-runs/phase/cancel', '/api/v1/task-runs/phase/resume', '/api/v1/task-runs/phase/cancel'])
  expect(bodies).toEqual([2, 3, 4, 5].map((expected_attempt) => ({ expected_attempt })))
})
