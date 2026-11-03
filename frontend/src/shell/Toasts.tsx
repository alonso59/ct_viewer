import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Icon, codicon } from '../theme'
import { useWorkbench, type Toast } from './workbenchStore'

const ICON = { info: 'info', ok: 'pass', warn: 'warning', error: 'error' } as const
/** How long an info or success toast stays (paused while hovered or focused) */
export const TOAST_MS = 6000

/** Errors and warnings are announced at once and stay; info and success are polite and transient */
export function Toasts() {
  const toasts = useWorkbench((s) => s.toasts)
  const urgent = toasts.filter((x) => x.tone === 'error' || x.tone === 'warn')
  const calm = toasts.filter((x) => !(x.tone === 'error' || x.tone === 'warn'))
  return (
    <div className="toasts">
      {/* an alert is announced when it appears; an empty one would read as a second error on the page */}
      {urgent.length ? <div role="alert">{urgent.map((x) => <ToastItem key={x.id} toast={x} />)}</div> : null}
      <div role="status" aria-live="polite">{calm.map((x) => <ToastItem key={x.id} toast={x} />)}</div>
    </div>
  )
}

function ToastItem({ toast: x }: { toast: Toast }) {
  const { t } = useTranslation()
  const dismiss = useWorkbench((s) => s.dismissToast)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const left = useRef(TOAST_MS)
  // a repeat restarts the clock
  useEffect(() => {
    left.current = TOAST_MS
  }, [x.count])
  useEffect(() => {
    if (x.sticky || hovered || focused) return
    const started = Date.now()
    const timer = setTimeout(() => dismiss(x.id), left.current)
    return () => {
      clearTimeout(timer)
      left.current = Math.max(0, left.current - (Date.now() - started))
    }
  }, [x.id, x.sticky, x.count, hovered, focused, dismiss])
  return (
    <div
      className="overlay toast"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') dismiss(x.id)
      }}
    >
      <span style={{ color: `var(--${x.tone === 'info' || !x.tone ? 'accent' : x.tone})`, display: 'inline-flex' }}>
        <Icon spec={codicon(ICON[x.tone ?? 'info'])} />
      </span>
      <span style={{ flex: 1 }}>{x.message}</span>
      {(x.count ?? 1) > 1 ? <span className="badge">{t('shell.toastCount', { n: x.count })}</span> : null}
      {x.action ? (
        <button type="button" className="link" onClick={() => { x.action?.run(); dismiss(x.id) }}>
          {x.action.label}
        </button>
      ) : null}
      <button type="button" className="icon-btn" aria-label={t('shell.dismiss')} onClick={() => dismiss(x.id)}>
        <Icon spec={codicon('close')} />
      </button>
    </div>
  )
}
