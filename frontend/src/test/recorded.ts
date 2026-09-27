// Unit-test helpers over the recorded API (TST-04, AUD-A6-03): the problem a recorded request got.
import { toProblemError, type ProblemError } from '../api/problem'
import { lookup } from '../api/mock/replay'

/** The recorded answer to `method path` (with `body`) as the error the HTTP binding throws */
export function recordedProblem(method: string, path: string, body: unknown = null): ProblemError {
  const hit = lookup(method, new URL(path, 'http://mock.invalid'), body)
  if (!hit || hit.status < 400) throw new Error(`no recorded problem for ${method} ${path}`)
  return toProblemError(hit.status, hit.response, 'recorded')
}
