// Modeless settings stay above the viewer and can be moved away from the anatomy.
import { useCallback, useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import { Icon, codicon } from '../../theme'

type Point = { x: number; y: number }

export function Render3dPanel({ open, onClose, anchor, children }: { open: boolean; onClose: () => void; anchor: RefObject<HTMLButtonElement | null>; children: ReactNode }) {
  const { t } = useTranslation()
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const header = useRef<HTMLDivElement>(null)
  const drag = useRef<Point | null>(null)
  const [position, setPosition] = useState<Point | null>(null)
  const clamp = useCallback((p: Point): Point => ({
    x: Math.max(8, Math.min(p.x, window.innerWidth - (panel.current?.offsetWidth ?? 340) - 8)),
    y: Math.max(8, Math.min(p.y, window.innerHeight - (panel.current?.offsetHeight ?? 400) - 8)),
  }), [])
  useEffect(() => {
    if (!open) return
    header.current?.focus()
    const fit = () => setPosition((p) => clamp(p ?? { x: (anchor.current?.getBoundingClientRect().right ?? window.innerWidth) - 340, y: 80 }))
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [open, anchor, clamp])
  if (!open) return null
  const close = () => { onClose(); anchor.current?.focus() }
  return createPortal(<div ref={panel} className="overlay vp-3d-panel" role="dialog" aria-modal="false" aria-labelledby={titleId}
    style={{ left: position?.x ?? 8, top: position?.y ?? 80 }}
    onDoubleClick={(e) => e.stopPropagation()}
    onPointerDown={(e) => e.stopPropagation()}
    onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') { e.preventDefault(); close() } }}>
    <div ref={header} className="vp-3d-panel-header" tabIndex={0} title={t('vw.render.movePanel')}
      onPointerDown={(e) => {
        if (e.button !== 0 || (e.target as HTMLElement).closest('button')) return
        const box = panel.current!.getBoundingClientRect()
        drag.current = { x: e.clientX - box.left, y: e.clientY - box.top }
        e.currentTarget.setPointerCapture(e.pointerId)
        e.currentTarget.focus()
        e.preventDefault()
      }}
      onPointerMove={(e) => { if (drag.current) setPosition(clamp({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y })) }}
      onPointerUp={(e) => { drag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId) }}
      onPointerCancel={() => { drag.current = null }}
      onLostPointerCapture={() => { drag.current = null }}
      onKeyDown={(e) => {
        const delta: Record<string, Point> = { ArrowLeft: { x: -20, y: 0 }, ArrowRight: { x: 20, y: 0 }, ArrowUp: { x: 0, y: -20 }, ArrowDown: { x: 0, y: 20 } }
        const d = delta[e.key]
        if (e.target === e.currentTarget && d) { e.preventDefault(); setPosition((p) => clamp({ x: (p?.x ?? 8) + d.x, y: (p?.y ?? 80) + d.y })) }
      }}>
      <Icon spec={codicon('move')} /><strong id={titleId}>{t('vw.render.settings')}</strong>
      <button type="button" className="icon-btn" aria-label={t('common.close')} onClick={close}><Icon spec={codicon('close')} /></button>
    </div>
    <div className="vp-3d-panel-body">{children}</div>
  </div>, document.body)
}
