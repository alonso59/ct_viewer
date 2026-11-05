import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Variable } from '../../api'
import { toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { allRows } from './allRows'
import { gridCsv } from './csv'
import { useCohort } from './store'

/** Download the grid as CSV: every filtered case (not just the open page), one row per scan */
export function ExportButton({ columns }: { columns: Variable[] }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const filters = useCohort((s) => s.filters)
  const sort = useCohort((s) => s.sort)
  const [withSensitive, setWithSensitive] = useState(false)
  const [busy, setBusy] = useState(false)
  const hasSensitive = columns.some((v) => v.tags.includes('sensitive'))
  const run = async () => {
    setBusy(true)
    try {
      const rows = await allRows(pid, columns.map((v) => v.name), filters, sort)
      const url = URL.createObjectURL(new Blob([gridCsv(columns, rows, withSensitive)], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'cohort.csv'
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      toast({ message: t('cohort.export.failed'), tone: 'error' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <span className="cohort-export">
      {hasSensitive ? (
        <label className="cohort-toggle">
          <input type="checkbox" checked={withSensitive} onChange={(e) => setWithSensitive(e.target.checked)} />
          {t('cohort.export.sensitive')}
        </label>
      ) : null}
      <button type="button" className="btn btn-sm" disabled={busy || columns.length === 0} onClick={() => void run()}>
        <Icon spec={codicon('export')} />
        {t('cohort.export.csv')}
      </button>
    </span>
  )
}
