// The CTFlow console's pure parts: what a result prints and what Tab completes. The server owns
// every command (CTF-01); nothing here interprets a line.
import type { ConsoleCommand, ConsoleResult, WorkRef } from '../../api'
import type { LogKind } from '../../api/surface'

export interface TranscriptLine {
  kind: 'in' | 'out' | 'err' | 'note'
  text: string
  /** Work this line started: it can be followed in the Output tab */
  work?: WorkRef
}

/** Commands that only read: they run without asking for the reviewer name */
export const READS = new Set(['help', 'cases', 'runs', 'status', 'scripts', 'project'])

/** Lines for one result, in the order the server ran them */
export function resultLines(result: ConsoleResult): TranscriptLine[] {
  const text = result.text ?? []
  const out: TranscriptLine[] = text.map((line) => ({ kind: 'out', text: line }))
  for (const step of result.steps ?? []) {
    for (const issue of step.plan?.issues ?? []) out.push({ kind: 'err', text: `${step.command}: ${issue.loc.join('.')}: ${issue.msg}` })
    for (const [reason, n] of Object.entries(step.plan?.preflight?.missing ?? {})) out.push({ kind: 'note', text: `${step.command}: ${n} skipped: ${reason}` })
    if (step.started) out.push({ kind: 'note', text: `${step.started.kind} ${step.started.id}`, work: step.started })
  }
  if (result.plan_stopped) out.push({ kind: 'note', text: result.plan_stopped })
  if (result.value && text.length === 0) out.push({ kind: 'out', text: result.value })
  if (result.error) {
    const where = result.error.line ? `line ${result.error.line}: ` : ''
    out.push({ kind: 'err', text: `${result.error.title}: ${where}${result.error.detail}` })
    for (const e of result.error.errors ?? []) out.push({ kind: 'err', text: `  ${String((e as { msg?: unknown }).msg ?? '')}` })
  }
  return out
}

/** The API-71 log of a work reference: a project task run reads as `project-run` */
export function logOf(work: WorkRef): { kind: LogKind; ref: string; project?: string } {
  if (work.kind === 'task-run') return { kind: 'project-run', ref: work.id, project: work.project_id ?? undefined }
  return { kind: work.kind, ref: work.id }
}

/** Tab: the completed input, and the candidates when more than one matches */
export function complete(input: string, commands: ConsoleCommand[]): { input: string; candidates: string[] } {
  const words = input.split(/\s+/)
  const current = words.at(-1) ?? ''
  const names = commands.map((c) => c.name)
  let pool: string[] = []
  if (words.length === 1) pool = ['plan', ...names]
  else if (current.startsWith('-')) {
    const name = words[0] === 'plan' ? words[1] : words[0]
    pool = (commands.find((c) => c.name === name)?.options ?? []).map((o) => `-${o.name}`)
  }
  const candidates = [...new Set(pool.filter((n) => n.startsWith(current)))].sort()
  if (candidates.length === 0) return { input, candidates }
  const prefix = candidates.reduce((a, b) => {
    let i = 0
    while (i < a.length && a[i] === b[i]) i++
    return a.slice(0, i)
  })
  const done = candidates.length === 1 ? `${prefix} ` : prefix
  return { input: [...words.slice(0, -1), done].join(' '), candidates: candidates.length > 1 ? candidates : [] }
}
