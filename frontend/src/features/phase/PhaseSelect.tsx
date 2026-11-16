import { useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ReviewerCancelled, useAppendPhase, usePhaseEvents, useProject, type ItemRecord, type NewPhaseEvent } from '../../api'
import { Dialog, PhaseChip, ProblemCard, fmtAgo } from '../../lib'
import { registry, toast, toastProblem } from '../../shell'
import { Icon, codicon } from '../../theme'
import { guessAccept, phaseOptions } from './model'
import './phase.css'

type Scan = Pick<ItemRecord, 'case_id' | 'scan_idx' | 'phase'>

// Keep phase controls from triggering surrounding viewer navigation or shortcuts.
const stop = (e: SyntheticEvent) => e.stopPropagation()

/** The project's phases in one drop-down: choosing one writes the scan's phase at once; the toast
 *  offers Undo */
export function PhaseSelect({ pid, scan, className }: { pid: string; scan: Scan; className?: string }) {
  const { t } = useTranslation()
  const project = useProject(pid).data
  const append = useAppendPhase(pid)
  const cur = scan.phase
  const accept = guessAccept(cur, project?.annotation_sources?.phase)
  const name = `${scan.case_id} · ${scan.scan_idx}`
  const failed = (e: unknown) => {
    if (!(e instanceof ReviewerCancelled)) toastProblem(e, t('common.saveFailed'))
  }
  const write = (value: string, extra: Partial<NewPhaseEvent> = {}) => append.mutateAsync({ case_id: scan.case_id, scan_idx: scan.scan_idx, value, source: 'manual', ...extra })
  const set = (value: string, extra: Partial<NewPhaseEvent> = {}) => {
    const before = cur.canonical
    write(value, extra).then(
      () =>
        toast({
          message: t('phaseSel.setTo', { scan: name, phase: value }),
          tone: 'ok',
          // the previous phase again as a new event; the history keeps both
          action: before !== value ? { label: t('common.undo'), run: () => void write(before).then(() => toast({ message: t('phaseSel.setTo', { scan: name, phase: before }), tone: 'ok' }), failed) } : undefined,
        }),
      failed,
    )
  }
  const was = cur.source === 'manual' ? cur.resolved?.canonical : null
  if (registry.readOnly) return <PhaseChip phase={cur.canonical} />
  const vocabulary = phaseOptions(project?.phase_vocabulary)
  // a value outside the vocabulary (raw metadata) stays visible as the current choice
  const options = vocabulary.includes(cur.canonical) ? vocabulary : [cur.canonical, ...vocabulary]
  return (
    <span className={`phase-select ${className ?? ''}`} onClick={stop} onDoubleClick={stop} onKeyDown={stop}>
      <select
        className="select input-sm"
        aria-label={t('phaseSel.group', { scan: name })}
        data-tone={cur.canonical === 'UNK' ? 'warn' : undefined}
        value={cur.canonical}
        disabled={append.isPending}
        onChange={(e) => set(e.target.value)}
      >
        {options.map((p) => (
          <option key={p} value={p}>{t('search.phaseOption', { code: p, name: t(`phase.${p}`, { defaultValue: p }) })}</option>
        ))}
      </select>
      {accept ? (
        <button type="button" className="badge" title={t('phaseSel.acceptHelp', { phase: cur.canonical })} disabled={append.isPending} onClick={() => set(cur.canonical, accept)}>
          <Icon spec={codicon('check')} />
          {t('phaseSel.accept')}
        </button>
      ) : null}
      {was != null && was !== cur.canonical ? <span className="muted phase-was" title={t('phaseSel.wasHelp')}>{t('phaseSel.was', { phase: was })}</span> : null}
    </span>
  )
}

/** The scan's selections, newest first */
export function PhaseHistoryButton({ pid, caseId, scanIdx }: { pid: string; caseId: string; scanIdx: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const events = usePhaseEvents(pid, open ? caseId : null, scanIdx)
  return (
    <>
      <button type="button" className="icon-btn" aria-label={t('phaseSel.history')} title={t('phaseSel.history')} onClick={() => setOpen(true)}>
        <Icon spec={codicon('history')} />
      </button>
      {open ? (
        <Dialog open onOpenChange={(o) => !o && setOpen(false)} title={t('phaseSel.historyOf', { scan: `${caseId} · ${scanIdx}` })} icon={codicon('history')}>
          {events.isLoading ? <p className="muted">{t('common.loading')}</p> : null}
          {events.isError ? <ProblemCard error={events.error} onRetry={() => void events.refetch()} /> : null}
          {events.data && !events.data.length ? <p className="muted">{t('phaseSel.noHistory')}</p> : null}
          <ol className="phase-history">
            {(events.data ?? []).map((e) => (
              <li key={e.event_id}>
                <PhaseChip phase={e.value} />
                <span className="muted">{t(`phaseSel.source.${e.source}`)}</span>
                <span className="muted phase-by">{t('phaseSel.by', { reviewer: e.reviewer, ago: fmtAgo(e.at) })}</span>
              </li>
            ))}
          </ol>
        </Dialog>
      ) : null}
    </>
  )
}
