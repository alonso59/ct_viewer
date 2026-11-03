import { useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ProblemError, useConsoleCommands, type WorkRef } from '../../api'
import '../../i18n/lazy'
import { showOutput } from '../jobs'
import { useWorkbench } from '../../shell'
import { requireReviewer, useReviewer } from '../../state'
import { READS, complete, logOf, resultLines, type TranscriptLine } from './console'
import './console.css'

const KEEP = 2000 // transcript lines kept in the panel

function problemLines(e: unknown): TranscriptLine[] {
  if (!(e instanceof ProblemError)) return [{ kind: 'err', text: e instanceof Error ? e.message : String(e) }]
  return [
    { kind: 'err', text: e.detail ? `${e.title}: ${e.detail}` : e.title },
    ...e.errors.map((x) => ({ kind: 'err' as const, text: `  ${x.msg}` })),
    ...(e.actions.length ? [{ kind: 'note' as const, text: `  next: ${e.actions.join(', ')}` }] : []),
  ]
}

/** The CTFlow console (CTF-19): lines go to the server's interpreter in one session; started
 *  work is followed in the Output tab, from the same records and logs as everywhere else. */
export function ConsolePanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid)
  const commands = useConsoleCommands()
  const [lines, setLines] = useState<TranscriptLine[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const session = useRef<string | null>(null)
  const history = useRef<string[]>([])
  const back = useRef(-1)
  const end = useRef<HTMLDivElement>(null)

  const append = (more: TranscriptLine[]) => {
    setLines((prev) => [...prev, ...more].slice(-KEEP))
    requestAnimationFrame(() => end.current?.scrollIntoView?.({ block: 'end' }))
  }

  async function run(text: string) {
    const plan = text.split(/\s+/)[0] === 'plan'
    const line = plan ? text.replace(/^plan\s*/, '') : text
    const first = line.trim().split(/\s+/)[0] ?? ''
    const reviewer = READS.has(first) ? useReviewer.getState().name || undefined : await requireReviewer()
    if (reviewer === null) {
      append([{ kind: 'note', text: t('console.needsReviewer') }])
      return
    }
    const send = () => api.consoleEval({ line, session: session.current, project_id: pid, plan }, reviewer)
    try {
      let result
      try {
        result = await send()
      } catch (e) {
        if (!(e instanceof ProblemError && e.actions.includes('new_session') && session.current)) throw e
        append([{ kind: 'note', text: t('console.sessionEnded') }])
        session.current = null
        result = await send()
      }
      session.current = result.session
      append(resultLines(result))
    } catch (e) {
      append(problemLines(e))
    }
  }

  async function submit() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    history.current = [...history.current.filter((h) => h !== text), text].slice(-200)
    back.current = -1
    append([{ kind: 'in', text }])
    setBusy(true)
    try {
      await run(text)
    } finally {
      setBusy(false)
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void submit()
    } else if (e.key === 'Tab' && input.trim()) {
      e.preventDefault()
      const done = complete(input, commands.data ?? [])
      setInput(done.input)
      if (done.candidates.length) append([{ kind: 'note', text: done.candidates.join('  ') }])
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      const all = history.current
      if (!all.length) return
      e.preventDefault()
      const at = e.key === 'ArrowUp' ? (back.current < 0 ? all.length - 1 : Math.max(0, back.current - 1)) : back.current + 1
      back.current = at >= all.length ? -1 : at
      setInput(back.current < 0 ? '' : (all[back.current] ?? ''))
    } else if (e.key === 'Escape' && input) {
      e.preventDefault()
      setInput('')
    }
  }

  const follow = (work: WorkRef) => showOutput({ id: `ctflow.${work.id}`, label: t('console.channel', { id: work.id }), ...logOf(work) })

  return (
    <div className="ct-console">
      <div className="ct-transcript" role="log" aria-live="polite" aria-label={t('console.transcript')}>
        {lines.length === 0 ? <p className="ct-hint">{t('console.hint')}</p> : null}
        {lines.map((l, i) => (
          <div key={i} className={`ct-line ct-${l.kind}`}>
            <span>{l.text}</span>
            {l.work ? (
              <button type="button" className="ct-follow" onClick={() => follow(l.work as WorkRef)}>
                {t('console.follow')}
              </button>
            ) : null}
          </div>
        ))}
        <div ref={end} />
      </div>
      <div className="ct-input">
        <label htmlFor="ct-line" className="ct-prompt">
          {t('console.prompt')}
        </label>
        <input
          id="ct-line"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          spellCheck={false}
          autoComplete="off"
          aria-describedby="ct-help"
          aria-busy={busy}
          placeholder={busy ? t('console.running') : t('console.placeholder')}
        />
        <span id="ct-help" className="ct-hint">
          {t('console.keys')}
        </span>
      </div>
    </div>
  )
}
