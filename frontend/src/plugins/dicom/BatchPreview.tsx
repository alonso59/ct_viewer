// The planned batches before anything runs: name, patients and files (counted in the background).
import { useTranslation } from 'react-i18next'

import type { SourceBatchPlan } from '../../api'
import { IndeterminateProgress } from '../../lib'

/** A batch's file count; `null` until the background count is done */
export function filesCell(plan: SourceBatchPlan, files: number | null, countingText: string): string {
  if (files != null) return String(files)
  return plan.counting === 'counting' ? countingText : '—'
}

export function BatchPreview({ plan }: { plan: SourceBatchPlan }) {
  const { t } = useTranslation()
  return (
    <div className="conv-body" data-testid="batch-preview">
      {plan.counting === 'counting' ? <>
        <IndeterminateProgress label={t('conv.counting')} />
        <p className="muted conv-help">{t('conv.counting')}</p>
      </> : null}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>{t('conv.batches.batch')}</th>
              <th className="num">{t('conv.batches.patients')}</th>
              <th className="num">{t('conv.batches.files')}</th>
            </tr>
          </thead>
          <tbody>
            {plan.batches.map((b) => (
              <tr key={b.index}>
                <td>{b.name}</td>
                <td className="num">{b.folder_count}</td>
                <td className="num">{filesCell(plan, b.files_total, t('conv.counting'))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
