// Native phase selection (PHASE.md PHS-01/04/07, ADR-0026): one button per vocabulary value; a
// click sets the scan's phase at once. The active analyzer run's guess can be accepted as is.
// Always available (not a plugin); hidden on view-only links (read-only chips instead).
import { useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ReviewerCancelled, ProblemError, useAppendPhase, usePhaseEvents, useProject, type ItemRecord, type NewPhaseEvent } from '../../api'
import { Dialog, PhaseChip, fmtAgo } from '../../lib'
import { registry, toast } from '../../shell'
import { Icon, codicon } from '../../theme'
import { guessRun, phaseOptions } from './model'
import './phase.css'

type Scan = Pick<ItemRecord, 'case_id' | 'scan_idx' | 'phase'>

// Inside an Explorer row: a click or key here must not also open the row
const stop = (e: SyntheticEvent) => e.stopPropagation()

export function PhaseButtons({ pid, scan, className }: { pid: string; scan: Scan; className?: string }) {
  const { t } = useTranslation()
  const project = useProject(pid).data
  const append = useAppendPhase(pid)
  const cur = scan.phase
  const run = guessRun(cur, project?.annotation_sources?.phase)
  const set = (value: string, extra: Partial<NewPhaseEvent> = {}) =>
    append.mutate(
      { case_id: scan.case_id, scan_idx: scan.scan_idx, value, source: 'manual', ...extra },
      {
        onError: (e) => {
          if (!(e instanceof ReviewerCancelled)) toast({ message: e instanceof ProblemError ? (e.detail ?? e.title) : t('common.saveFailed'), tone: 'error' })
        },
      },
    )
  const was = cur.source === 'manual' ? cur.resolved?.canonical : null
  if (registry.readOnly) return <PhaseChip phase={cur.canonical} />
  return (
    <span role="group" aria-label={t('phaseSel.group', { scan: `${scan.case_id} · ${scan.scan_idx}` })} className={`phase-buttons ${className ?? ''}`} onClick={stop} onDoubleClick={stop} onKeyDown={stop}>
      {phaseOptions(project?.phase_vocabulary).map((p) => (
        <PhaseChip key={p} phase={p} active={cur.canonical === p} onClick={() => (cur.canonical === p && cur.source === 'manual' ? undefined : set(p))} />
      ))}
      {run ? (
        <button type="button" className="badge" title={t('phaseSel.acceptHelp', { phase: cur.canonical })} disabled={append.isPending} onClick={() => set(cur.canonical, { source: 'analyzer_accept', accepted_run_id: run })}>
          <Icon spec={codicon('check')} />
          {t('phaseSel.accept')}
        </button>
      ) : null}
      {was != null && was !== cur.canonical ? <span className="muted phase-was" title={t('phaseSel.wasHelp')}>{t('phaseSel.was', { phase: was })}</span> : null}
    </span>
  )
}

/** PHS-07: the scan's selections, newest first */
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
