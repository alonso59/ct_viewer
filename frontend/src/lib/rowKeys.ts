// Keyboard for table rows that open something. A row keeps its one click and context-menu
// handler: Enter acts as the click and Shift+F10 (or the menu key) as the right click.
import { useState, type KeyboardEvent } from 'react'

export type RowKeys = (id: string) => {
  tabIndex: number
  onFocus: () => void
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
}

/** One Tab stop per table: the row focused last (else the first of `ids`); ↑ ↓ Home End move
 *  between the rows that carry these props, skipping the others */
export function useRowKeys(ids: readonly string[]): RowKeys {
  const [active, setActive] = useState<string | null>(null)
  const stop = active !== null && ids.includes(active) ? active : ids[0]
  return (id) => ({
    tabIndex: id === stop ? 0 : -1,
    onFocus: () => setActive(id),
    onKeyDown: (e) => {
      const row = e.currentTarget
      // keys of a control inside the row stay with that control
      if (e.target !== row) return
      if (e.key === 'Enter') {
        e.preventDefault()
        row.click()
        return
      }
      if (e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)) {
        const at = row.getBoundingClientRect()
        const menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: at.left + 16, clientY: at.bottom })
        // the row opened its own menu: no browser menu on top of it
        if (!row.dispatchEvent(menu)) e.preventDefault()
        return
      }
      const rows = Array.from(row.parentElement?.children ?? []).filter((el): el is HTMLElement => el instanceof HTMLElement && el.hasAttribute('tabindex'))
      const i = rows.indexOf(row)
      const to: Record<string, HTMLElement | undefined> = { ArrowDown: rows[i + 1], ArrowUp: rows[i - 1], Home: rows[0], End: rows[rows.length - 1] }
      const next = to[e.key]
      if (!next) return
      e.preventDefault()
      next.focus()
    },
  })
}
