// Status bar items: the cursor readout (value, label, ijk, RAS; `readout.ts`) and W/L (UI-07, VW-08)
import { useTranslation } from 'react-i18next'

import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { useCursorText } from './readout'

export function CursorStatus() {
  const { t } = useTranslation()
  const text = useCursorText(true)
  const isCase = useWorkbench((s) => s.active?.type === 'case')
  if (!isCase) return null
  if (!text) return <span className="statusbar-item muted">{t('status.cursorIdle')}</span>
  return <span className="statusbar-item num">{text}</span>
}

export function WindowStatus() {
  const { t } = useTranslation()
  const { ww, wl } = useViewerSync()
  const isCase = useWorkbench((s) => s.active?.type === 'case')
  if (!isCase) return null
  return <span className="statusbar-item num">{t('status.wl', { ww, wl })}</span>
}
