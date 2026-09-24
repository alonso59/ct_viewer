// Left pane Tasks view (UI-17/20): every available task, grouped by kind, and the latest runs.
import { useTranslation } from 'react-i18next'

import { useTaskRuns, useTasks, type TaskInfo } from '../../api'
import { ProblemCard } from '../../lib'
import { openEditor, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { RunRow } from './TaskEditor'
import './tasks.css'

const KINDS = ['conversion', 'analyzer', 'segmentation', 'features'] as const
const ICON: Record<(typeof KINDS)[number], string> = { conversion: 'file-binary', analyzer: 'lightbulb', segmentation: 'layers', features: 'beaker' }

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
                  <button type="button" className="list-row" onClick={() => openEditor('task', { taskId: x.manifest.id })} title={x.manifest.description ?? ''}>
                    <Icon spec={codicon(ICON[k])} />
                    <span>{x.manifest.title}</span>
                    {!x.available ? <span className="badge" data-tone="warn" style={{ marginLeft: 'auto' }}>{t('tasks.unavailable')}</span> : null}
                    {x.manifest.runtime.type === 'external' ? <span className="badge" data-tone={x.runner_online ? 'ok' : 'warn'} style={{ marginLeft: 'auto' }}>{t(x.runner_online ? 'tasks.runnerOn' : 'tasks.runnerOff')}</span> : null}
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
