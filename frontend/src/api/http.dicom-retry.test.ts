import { expect, test, vi } from 'vitest'

import { createHttpApi } from './http'

test('D23 failed-series controls keep native and source-operation attempt fences', async () => {
  const requests: { path: string; body: unknown }[] = []
  const fetch = vi.fn<typeof globalThis.fetch>(async (request) => {
    if (!(request instanceof Request)) throw new Error('Expected an HTTP Request')
    requests.push({ path: new URL(request.url).pathname, body: await request.json() })
    return new Response('{}', { headers: { 'content-type': 'application/json' } })
  })
  const api = createHttpApi(fetch, 'http://local')
  const command = { expected_attempt: 2, expected_revision: 10, expected_run_attempt: 3 }
  await api.retryFailedSourceOperation('source', command)
  await api.retryFailedTaskRun('project', 'conversion', { expected_attempt: 3 })
  await api.retryFailedWorkspaceRun('conversion', { expected_attempt: 4 })
  expect(requests).toEqual([
    { path: '/api/v1/source-operations/source/retry-failed', body: command },
    { path: '/api/v1/projects/project/task-runs/conversion/retry-failed', body: { expected_attempt: 3 } },
    { path: '/api/v1/task-runs/conversion/retry-failed', body: { expected_attempt: 4 } },
  ])
})
