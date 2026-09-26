// Primer "Label" pills for curation status, phase and QC severity (UI_SHELL §Theme tokens).
import { useTranslation } from 'react-i18next'

import type { CaseRollup, CaseSummary, Phase } from '../api'
import { Icon } from '../theme'

type Tone = 'ok' | 'warn' | 'error' | 'done' | 'accent' | undefined

export const STATUS_TONE: Record<CaseRollup, Tone> = {
  accepted: 'ok',
  needs_minor_correction: 'warn',
  wrong_side_suspected: 'warn',
  needs_major_correction: 'error',
  rejected: 'error',
  missing: 'error',
  cannot_assess: undefined,
  partially_reviewed: 'accent',
  not_reviewed: undefined,
}

const STATUS_ICON: Record<CaseRollup, string> = {
  accepted: 'pass',
  needs_minor_correction: 'warning',
  wrong_side_suspected: 'arrow-swap',
  needs_major_correction: 'error',
  rejected: 'circle-slash',
  missing: 'circle-large-outline',
  cannot_assess: 'eye-closed',
  partially_reviewed: 'pie-chart',
  not_reviewed: 'circle-large-outline',
}

export function StatusIcon({ status }: { status: CaseRollup }) {
  const tone = STATUS_TONE[status]
  return (
    <span style={{ color: tone ? `var(--${tone})` : 'var(--fg-muted)', display: 'inline-flex' }}>
      <Icon spec={{ codicon: STATUS_ICON[status] }} />
    </span>
  )
}

export function StatusBadge({ status, compact, title }: { status: CaseRollup; compact?: boolean; title?: string }) {
  const { t } = useTranslation()
  return (
    <span className="badge" data-tone={STATUS_TONE[status]} title={title ?? t(`status.${status}`)}>
      {compact ? t(`statusShort.${status}`) : t(`status.${status}`)}
    </span>
  )
}

type Rollup = Pick<CaseSummary, 'curation_status' | 'review_state' | 'n_items_reviewed' | 'n_items_active'>

/** CUR-08 tooltip of a case rollup: "n of m items reviewed" while partial (AUD-A5-15) */
export function rollupTitle(t: (k: string, o?: Record<string, unknown>) => string, c: Rollup): string {
  const status = t(`status.${c.curation_status}`)
  return c.review_state === 'partial' ? t('status.partialOf', { status, done: c.n_items_reviewed, total: c.n_items_active }) : status
}

/** CUR-08 case badge */
export function CaseRollupBadge({ summary, compact }: { summary: Rollup; compact?: boolean }) {
  const { t } = useTranslation()
  return <StatusBadge status={summary.curation_status} compact={compact} title={rollupTitle(t, summary)} />
}

export function PhaseChip({ phase, active, onClick }: { phase: Phase; active?: boolean; onClick?: () => void }) {
  const { t } = useTranslation()
  const tone = phase === 'UNK' ? 'warn' : active ? 'accent' : undefined
  if (!onClick)
    return (
      <span className="badge" data-tone={tone} title={t(`phase.${phase}`)}>
        {phase}
      </span>
    )
  return (
    <button
      type="button"
      className="badge"
      data-tone={tone}
      aria-pressed={active}
      title={t(`phase.${phase}`)}
      onClick={onClick}
      style={{ cursor: 'pointer', background: active ? 'var(--bg-selected)' : 'transparent' }}
    >
      {phase}
    </button>
  )
}

export function SeverityIcon({ severity }: { severity: 'error' | 'warning' | 'info' }) {
  const tone = severity === 'error' ? 'var(--error)' : severity === 'warning' ? 'var(--warn)' : 'var(--fg-muted)'
  return (
    <span style={{ color: tone, display: 'inline-flex' }}>
      <Icon spec={{ codicon: severity }} />
    </span>
  )
}
