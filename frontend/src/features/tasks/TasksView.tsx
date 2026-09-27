// Left pane Tasks view (UI-17/20): every available task, grouped by kind, and the latest runs.
import { useTranslation } from 'react-i18next'

import { useTaskRuns, useTasks, type TaskInfo } from '../../api'
import { ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openTask, RADIOMICS_TASK } from './commands'
import { RunRow } from './TaskEditor'
import './tasks.css'

const KINDS = ['conversion', 'analyzer', 'segmentation', 'features'] as const
const ICON: Record<(typeof KINDS)[number], string> = { conversion: 'file-binary', analyzer: 'symbol-property', segmentation: 'layers', features: 'beaker' }

export default function TasksView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, error } = useTasks()
  const runs = useTaskRuns(pid).data ?? []
  const visible = (data?.tasks ?? []).filter((x) => !x.manifest.test_only || x.runner_online)
  const byKind = (k: string) => visible.filter((x: TaskInfo) => x.manifest.kind === k)
  return (
    <div className="tasks-view">
      {error ? <ProblemCard error={error} /> : null}
      {KINDS.map((k) =>
        byKind(k).length ? (
          <section key={k}>
            <h3 className="tasks-kind">{t(`tasks.kind.${k}`)}</h3>
            <ul className="tasks-list">
              {byKind(k).map((x) => (
                <li key={x.manifest.id}>
                  {/* AUD-A1-10: radiomics has one canonical tab, the Radiomics settings tab */}
                  <button type="button" className="list-row" onClick={() => openTask(x.manifest.id)} title={x.manifest.id === RADIOMICS_TASK ? t('tasks.radiomicsHere') : (x.manifest.description ?? '')}>
                    <Icon spec={codicon(ICON[k])} />
                    <span>{x.manifest.title}</span>
                    {!x.available ? <span className="badge ml-auto" data-tone="warn" >{t('tasks.unavailable')}</span> : null}
                    {x.manifest.runtime.type === 'external' ? <span className="badge ml-auto" data-tone={x.runner_online ? 'ok' : 'warn'} >{t(x.runner_online ? 'tasks.runnerOn' : 'tasks.runnerOff')}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null,
      )}
      {data?.invalid.length ? <p className="muted">{t('tasks.invalid', { count: data.invalid.length })}</p> : null}
      <h3 className="tasks-kind">{t('tasks.recent')}</h3>
      {runs.length ? <ul className="task-runs">{runs.slice(0, 20).map((r) => <RunRow key={r.run_id} pid={pid} run={r} />)}</ul> : <p className="muted">{t('tasks.noRuns')}</p>}
    </div>
  )
}
