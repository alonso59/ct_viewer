// RFC 9457 problem details as a typed error (API.md §Errors). `type` is the slug under /problems/.
import type { Problem } from './types'

export class ProblemError extends Error {
  constructor(
    public status: number,
    public type: string,
    public title: string,
    public detail?: string,
  ) {
    super(title)
  }
}

export function toProblemError(status: number, body: unknown, fallbackTitle: string): ProblemError {
  const p = (body && typeof body === 'object' ? body : {}) as Partial<Problem>
  const slug = typeof p.type === 'string' ? (p.type.split('/').filter(Boolean).at(-1) ?? 'about:blank') : 'about:blank'
  return new ProblemError(status, slug, p.title ?? fallbackTitle, p.detail)
}
