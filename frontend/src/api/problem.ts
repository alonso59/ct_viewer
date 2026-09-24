// RFC 9457 problem details as a typed error (API.md §Errors). `type` is the slug under /problems/;
// `actions` are the next steps the UI offers as buttons (SRC-11, UI-18).
import type { Problem } from './types'

export class ProblemError extends Error {
  constructor(
    public status: number,
    public type: string,
    public title: string,
    public detail?: string,
    public actions: string[] = [],
  ) {
    super(title)
  }
}

export function toProblemError(status: number, body: unknown, fallbackTitle: string): ProblemError {
  const p = (body && typeof body === 'object' ? body : {}) as Partial<Problem> & { actions?: unknown }
  const slug = typeof p.type === 'string' ? (p.type.split('/').filter(Boolean).at(-1) ?? 'about:blank') : 'about:blank'
  const actions = Array.isArray(p.actions) ? p.actions.filter((a): a is string => typeof a === 'string') : []
  return new ProblemError(status, slug, p.title ?? fallbackTitle, p.detail, actions)
}

/** `import_as:nifti-files` → `{ name: 'import_as', arg: 'nifti-files' }` */
export function parseAction(action: string): { name: string; arg: string | null } {
  const i = action.indexOf(':')
  return i < 0 ? { name: action, arg: null } : { name: action.slice(0, i), arg: action.slice(i + 1) }
}
