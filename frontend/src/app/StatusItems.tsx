// Core status bar items: project, live/offline SSE state, reviewer (UI-07)
import { useTranslation } from 'react-i18next'

import { useConnection, useHealth, useProject } from '../api'
import { useWorkbench } from '../shell'
import { changeReviewer, useReviewer } from '../state'
import { Icon, codicon } from '../theme'

export function ProjectStatus() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const p = useProject(pid).data
  // AUD-A4-05 (NFR-16): the version and "Research use only" in the tooltip too
  const about = t('about.statusTip', { version: useHealth().data?.version ?? '—' })
  return (
    <span className="statusbar-item" title={[about, ...(p?.path_roots.map((r) => `${r.alias} → ${r.path}`) ?? [])].join('\n')}>
      <Icon spec={codicon('database')} />
      {p?.name}
    </span>
  )
}

const LIVE_TONE = { live: 'var(--ok)', connecting: 'var(--warn)', offline: 'var(--error)' } as const

export function LiveStatus() {
  const { t } = useTranslation()
  const state = useConnection((s) => s.state)
  return (
    <span className="statusbar-item" title={t(`status.${state}Help`)} data-state={state}>
      <span className="dot" style={{ background: LIVE_TONE[state] }} />
      {t(`status.${state}`)}
    </span>
  )
}

export function ReviewerStatus() {
  const { t } = useTranslation()
  const name = useReviewer((s) => s.name)
  return (
    <button
      type="button"
      className="statusbar-item"
      title={t('status.reviewerHelp')}
      onClick={() => void changeReviewer()}
    >
      <Icon spec={codicon('account')} />
      {name || t('status.noReviewer')}
    </button>
  )
}
