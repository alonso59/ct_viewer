// TST-04 / FE-03 (AUD-A6-03): the mock is a replay of the real API. Every recorded exchange is an
// operation of the OpenAPI snapshot, the recording holds no absolute host path (R1, NFR-17), and a
// request the recording does not have is a problem, not an invented answer.
import { expect, test } from 'vitest'

import openapi from '../../../../backend/tests/openapi.snapshot.json'
import { exchanges, RECORDED_PID, replayFetch } from './replay'

const spec = openapi as unknown as { paths: Record<string, Record<string, unknown>> }
const routes = Object.entries(spec.paths).map(([path, ops]) => ({
  re: new RegExp(`^${path.replace(/\{[^}]+\}/g, '[^/]+')}$`),
  methods: new Set(Object.keys(ops).map((m) => m.toUpperCase())),
}))

test('every recorded exchange is an operation of the OpenAPI snapshot', () => {
  expect(exchanges.length).toBeGreaterThan(100)
  const unknown = exchanges.filter((e) => !routes.some((r) => r.re.test(e.path) && r.methods.has(e.method))).map((e) => `${e.method} ${e.path}`)
  expect(unknown).toEqual([])
})

test('the recording is redacted: fixed project id, no absolute host paths', () => {
  const text = JSON.stringify(exchanges)
  expect(text).toContain(RECORDED_PID)
  expect(text).not.toMatch(/\/(Users|Volumes|home|private|tmp|var\/folders)\//)
})

test('an unrecorded request is a not-recorded problem', async () => {
  const r = await replayFetch('http://mock.invalid/api/v1/projects/nope/cases')
  expect(r.status).toBe(501)
  expect(await r.json()).toMatchObject({ type: '/problems/not-recorded' })
})

test('paging parameters do not change the answer; the body picks among recorded writes', async () => {
  const url = `http://mock.invalid/api/v1/projects/${RECORDED_PID}/cases`
  const a = await (await replayFetch(`${url}?limit=5`)).json()
  const b = await (await replayFetch(`${url}?limit=2000&cursor=x`)).json()
  expect(a).toEqual(b)
  // the stale settings write is recorded as the 412 it got; another body gets the fresh write
  const patch = (body: unknown) => replayFetch(`http://mock.invalid/api/v1/projects/${RECORDED_PID}`, { method: 'PATCH', body: JSON.stringify(body) })
  expect((await patch({ description: 'stale' })).status).toBe(412)
  expect((await patch({ description: 'anything' })).status).toBe(200)
})
