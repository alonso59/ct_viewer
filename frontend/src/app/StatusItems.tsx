// Core status bar items: project, live/offline, reviewer (UI-07)
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useProject } from '../api'
import { useWorkbench } from '../shell'
import { changeReviewer, useReviewer } from '../state'
import { Icon, codicon } from '../theme'

export function ProjectStatus() {
  const pid = useWorkbench((s) => s.pid) ?? ''
  const p = useProject(pid).data
  return (
    <span className="statusbar-item" title={p?.roots.map((r) => `${r.alias} → ${r.path}`).join('\n')}>
      <Icon spec={codicon('database')} />
      {p?.name}
    </span>
  )
}

export function LiveStatus() {
  const { t } = useTranslation()
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])
  return (
    <span className="statusbar-item" title={t(online ? 'status.liveHelp' : 'status.offlineHelp')}>
      <span className="dot" style={{ background: online ? 'var(--ok)' : 'var(--error)' }} />
      {t(online ? 'status.live' : 'status.offline')}
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
