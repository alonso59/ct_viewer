// Status bar items: cursor ijk / RAS / HU / label and W/L (UI-07, VW-08)
import { useTranslation } from 'react-i18next'

import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

export function CursorStatus() {
  const { t } = useTranslation()
  const cursor = useViewerSync((s) => s.cursor)
  const isCase = useWorkbench((s) => s.active?.type === 'case')
  if (!isCase) return null
  if (!cursor) return <span className="statusbar-item muted">{t('status.cursorIdle')}</span>
  return (
    <span className="statusbar-item num">
      {t('status.cursor', { ijk: cursor.ijk.join(','), ras: cursor.ras.join(', '), hu: cursor.value, label: cursor.label || '—' })}
    </span>
  )
}

export function WindowStatus() {
  const { t } = useTranslation()
  const { ww, wl } = useViewerSync()
  const isCase = useWorkbench((s) => s.active?.type === 'case')
  if (!isCase) return null
  return <span className="statusbar-item num">{t('status.wl', { ww, wl })}</span>
}
