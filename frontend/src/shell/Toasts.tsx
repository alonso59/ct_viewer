import { useTranslation } from 'react-i18next'

import { Icon, codicon } from '../theme'
import { useWorkbench } from './workbenchStore'

const ICON = { info: 'info', ok: 'pass', warn: 'warning', error: 'error' } as const

/** Notifications at bottom-right (UI-10) */
export function Toasts() {
  const { t } = useTranslation()
  const toasts = useWorkbench((s) => s.toasts)
  const dismiss = useWorkbench((s) => s.dismissToast)
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((x) => (
        <div key={x.id} className="overlay toast">
          <span style={{ color: `var(--${x.tone === 'info' || !x.tone ? 'accent' : x.tone})`, display: 'inline-flex' }}>
            <Icon spec={codicon(ICON[x.tone ?? 'info'])} />
          </span>
          <span style={{ flex: 1 }}>{x.message}</span>
          {x.action ? (
            <button type="button" className="link" onClick={() => { x.action?.run(); dismiss(x.id) }}>
              {x.action.label}
            </button>
          ) : null}
          <button type="button" className="icon-btn" aria-label={t('shell.dismiss')} onClick={() => dismiss(x.id)}>
            <Icon spec={codicon('close')} />
          </button>
        </div>
      ))}
    </div>
  )
}
