// Type-aware cell editor (LBL-02/03), shared by the table tab and the Inspector section (AUD-A1-05).
// Enter / Tab / blur commit, Escape cancels; keys never reach the viewer or grid shortcuts.
import { useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { LabelColumn } from '../../api'

export function CellEditor({ col, value, onCommit, onCancel }: { col: LabelColumn; value: unknown; onCommit: (v: unknown) => void; onCancel: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(value == null ? '' : String(value))
  const norm = (d: string) => (col.type === 'number' ? d.trim().replace(',', '.') : d)
  const keys = (e: KeyboardEvent) => {
    e.stopPropagation()
    if (e.key === 'Escape') onCancel()
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      onCommit(norm(draft))
    }
  }
  if (col.type === 'category')
    return (
      <select className="lbl-input" autoFocus aria-label={col.name} value={draft} onKeyDown={keys} onChange={(e) => onCommit(e.target.value)} onBlur={onCancel}>
        <option value="">{t('lbl.empty_value')}</option>
        {(col.levels ?? []).map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
    )
  return (
    <input
      className="lbl-input"
      autoFocus
      aria-label={col.name}
      // numbers: a text field that accepts `,` or `.` as the decimal point (AUD-A3-04)
      type={col.type === 'date' ? 'date' : 'text'}
      {...(col.type === 'number' ? { inputMode: 'decimal' as const, role: 'spinbutton' } : {})}
      value={draft}
      onKeyDown={keys}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => onCommit(norm(draft))}
    />
  )
}
