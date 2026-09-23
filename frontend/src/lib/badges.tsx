// Primer "Label" pills for curation status, phase and QC severity (UI_SHELL §Theme tokens).
import { useTranslation } from 'react-i18next'

import type { CurationStatus, Phase } from '../api'
import { Icon } from '../theme'

type Tone = 'ok' | 'warn' | 'error' | 'done' | 'accent' | undefined

export const STATUS_TONE: Record<CurationStatus, Tone> = {
  accepted: 'ok',
  needs_minor_correction: 'warn',
  wrong_phase_suspected: 'warn',
  wrong_side_suspected: 'warn',
  needs_major_correction: 'error',
  rejected: 'error',
  missing: 'error',
  cannot_assess: undefined,
  not_reviewed: undefined,
}

const STATUS_ICON: Record<CurationStatus, string> = {
  accepted: 'pass',
  needs_minor_correction: 'warning',
  wrong_phase_suspected: 'question',
  wrong_side_suspected: 'arrow-swap',
  needs_major_correction: 'error',
  rejected: 'circle-slash',
  missing: 'circle-large-outline',
  cannot_assess: 'eye-closed',
  not_reviewed: 'circle-large-outline',
}

export function StatusIcon({ status }: { status: CurationStatus }) {
  const tone = STATUS_TONE[status]
  return (
    <span style={{ color: tone ? `var(--${tone})` : 'var(--fg-muted)', display: 'inline-flex' }}>
      <Icon spec={{ codicon: STATUS_ICON[status] }} />
    </span>
  )
}

export function StatusBadge({ status, compact }: { status: CurationStatus; compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <span className="badge" data-tone={STATUS_TONE[status]} title={t(`status.${status}`)}>
      {compact ? t(`statusShort.${status}`) : t(`status.${status}`)}
    </span>
  )
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
