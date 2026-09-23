// Project welcome (empty editor area / Welcome tab): next steps and progress at a glance
import { useTranslation } from 'react-i18next'

import { useCases, useProject, useQueue, useRuns, useWarnings } from '../../api'
import { Progress } from '../../lib'
import { formatChord, openEditor, registry, bindingOf, useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { Icon, codicon, type IconSpec } from '../../theme'
import { useImportWizard } from '../import'

function Action({ icon, title, detail, onClick, chord }: { icon: IconSpec; title: string; detail: string; onClick: () => void; chord?: string }) {
  return (
    <button type="button" className="home-action" onClick={onClick}>
      <Icon spec={icon} size={20} />
      <span>
        <strong>{title}</strong>
        <span className="muted">{detail}</span>
      </span>
      {chord ? <span className="kbd" style={{ marginLeft: 'auto' }}>{chord}</span> : null}
    </button>
  )
}

const chordOf = (id: string) => {
  const c = registry.commands.get(id)
  return c ? formatChord(bindingOf(c)) : undefined
}

export function WelcomeEditor() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const project = useProject(pid).data
  const cases = useCases(pid).data ?? []
  const warnings = useWarnings(pid).data ?? []
  const queue = useQueue(pid).data ?? []
  const runs = useRuns(pid).data ?? []
  const reviewed = cases.filter((c) => c.curation_status !== 'not_reviewed').length
  const nextCase = cases.find((c) => c.curation_status === 'not_reviewed')
  if (project && project.n_cases === 0)
    return (
      <div className="page">
        <div className="page-inner">
          <h1>{project.name}</h1>
          <p className="muted">{t('welcome.emptyProject')}</p>
          <div className="home-actions" style={{ maxWidth: 420 }}>
            <Action icon={codicon('cloud-download')} title={t('import.title')} detail={t('welcome.importHelp')} onClick={() => useImportWizard.getState().open(pid)} />
          </div>
        </div>
      </div>
    )
  return (
    <div className="page">
      <div className="page-inner">
        <h1>{project?.name}</h1>
        <p className="muted">{t('welcome.subtitle', { cases: project?.n_cases ?? 0, items: project?.n_items ?? 0 })}</p>
        <div className="stat-grid">
          <div className="card">
            <span className="kpi num">{t('welcome.pct', { v: cases.length ? Math.round((reviewed / cases.length) * 100) : 0 })}</span>
            <span className="muted">{t('welcome.reviewed', { done: reviewed, total: cases.length })}</span>
            <Progress value={reviewed} total={cases.length} />
          </div>
          <button type="button" className="card" onClick={() => useLayout.getState().showPanelTab('problems')}>
            <span className="kpi num" style={{ color: 'var(--warn)' }}>{warnings.length}</span>
            <span className="muted">{t('welcome.warnings')}</span>
          </button>
          <button type="button" className="card" onClick={() => openEditor('queue', {})}>
            <span className="kpi num">{queue.length}</span>
            <span className="muted">{t('welcome.inQueue')}</span>
          </button>
          <button type="button" className="card" onClick={() => useLayout.getState().showView('dashboards')}>
            <span className="kpi num">{runs.length}</span>
            <span className="muted">{t('welcome.runs')}</span>
          </button>
        </div>
        <h2>{t('welcome.next')}</h2>
        <div className="home-actions" style={{ maxWidth: 560 }}>
          {nextCase ? (
            <Action icon={codicon('play')} title={t('welcome.reviewNext', { id: nextCase.case_id })} detail={t('welcome.reviewNextHelp')} onClick={() => openEditor('case', { caseId: nextCase.case_id, itemId: null })} chord={chordOf('explorer.nextCase')} />
          ) : null}
          <Action icon={codicon('search')} title={t('welcome.goTo')} detail={t('welcome.goToHelp')} onClick={() => useWorkbench.getState().openPalette('quickopen')} chord={chordOf('workbench.quickOpen')} />
          <Action icon={codicon('beaker')} title={t('radiomics.newRun')} detail={t('welcome.radiomicsHelp')} onClick={() => openEditor('radiomics', {})} />
          <Action icon={codicon('checklist')} title={t('curation.openQueue')} detail={t('welcome.queueHelp')} onClick={() => openEditor('queue', {})} />
          <Action icon={codicon('terminal')} title={t('welcome.commands')} detail={t('welcome.commandsHelp')} onClick={() => useWorkbench.getState().openPalette('commands')} chord={chordOf('workbench.commandPalette')} />
        </div>
      </div>
    </div>
  )
}
