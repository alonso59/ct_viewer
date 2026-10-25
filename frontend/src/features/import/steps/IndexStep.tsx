// Import wizard, step 4: the indexing (or conversion) job's progress or failure.
import { useTranslation } from 'react-i18next'

import type { Job } from '../../../api'
import { Progress, runStatusKey } from '../../../lib'

export function IndexStep({ job, failed }: { job: (Pick<Job, 'status' | 'done' | 'total'> & { error?: string | null }) | undefined; failed: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="wiz-progress">
      <h3>{t(failed ? 'import.indexFailed' : 'import.indexing')}</h3>
      {failed && job ? (
        <div className="error-card" role="alert">{job.error ?? t(runStatusKey(job.status))}</div>
      ) : (
        <>
          <Progress value={job?.done ?? 0} total={job?.total || 1} />
          <span className="muted num">{t('jobs.count', { done: job?.done ?? 0, total: job?.total ?? 0 })}</span>
        </>
      )}
      <span className="muted panel-size">{t('import.indexingHelp')}</span>
    </div>
  )
}
