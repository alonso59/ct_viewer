// Keyboard for a `role="toolbar"`: one Tab stop. ← → Home End move between its controls; Tab and
// Shift+Tab leave it. Fields keep their own arrow keys. Works on whatever controls the toolbar
// holds (tools are contributed), so it sets no tabindex on them.
import type { KeyboardEvent } from 'react'

const CONTROLS = 'button:not(:disabled), select:not(:disabled), input:not(:disabled):not([type="hidden"]), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'

const shown = (el: HTMLElement) => el.getClientRects().length > 0

/** Inputs and selects use the arrow keys themselves (caret, value, options) */
const ownsArrows = (el: HTMLElement) => el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && (el as HTMLInputElement).type !== 'checkbox' && (el as HTMLInputElement).type !== 'radio')

/** The first tabbable element after (or, backwards, before) `bar` in document order */
function outside(bar: HTMLElement, backwards: boolean): HTMLElement | undefined {
  const all = Array.from(document.querySelectorAll<HTMLElement>(CONTROLS)).filter((el) => el.tabIndex >= 0 && !bar.contains(el) && shown(el))
  const follows = (el: HTMLElement) => (bar.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
  return backwards ? all.filter((el) => !follows(el)).at(-1) : all.find(follows)
}

export function toolbarKeyDown(e: KeyboardEvent<HTMLElement>) {
  // an inner toolbar (or a control) handled it
  if (e.defaultPrevented) return
  const bar = e.currentTarget
  const target = e.target as HTMLElement
  if (e.key === 'Tab') {
    const to = outside(bar, e.shiftKey)
    if (!to) return
    e.preventDefault()
    to.focus()
    return
  }
  if (e.altKey || e.ctrlKey || e.metaKey || ownsArrows(target)) return
  const controls = Array.from(bar.querySelectorAll<HTMLElement>(CONTROLS)).filter(shown)
  const at = controls.indexOf(target)
  const n = controls.length
  const moves: Record<string, HTMLElement | undefined> = { ArrowRight: controls[(at + 1) % n], ArrowLeft: controls[(at - 1 + n) % n], Home: controls[0], End: controls[n - 1] }
  const to = moves[e.key]
  if (at < 0 || !to) return
  e.preventDefault()
  to.focus()
}
