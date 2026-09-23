// /p/:pid/* — the workbench for one project, with runtime hooks (cache sync, live state, output log,
// mock simulation). Share links land here (PRJ-03), so an unknown project gets its own page.
import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import { api, ProblemError, useProject, useProjectEvents, useProjectSync, type ServerEvent } from '../api'
import { useCurationRuntime } from '../features/curation'
import { ImportWizard } from '../features/import'
import { logEvent } from '../features/jobs'
import { ProjectSwitcher, RelinkDialog, useRootsCheck } from '../features/projects'
import { ShellOverlays, Workbench } from '../shell'
import { useSettings } from '../state'

function ProjectNotFound({ pid, detail }: { pid: string; detail?: string }) {
  const { t } = useTranslation()
  return (
    <div className="home">
      <div className="home-inner">
        <div className="error-card" role="alert">
          <strong>{t('projects.notFound')}</strong>
          <div className="muted mono">{detail ?? pid}</div>
          <div className="muted">{t('projects.notFoundHelp')}</div>
        </div>
        <Link className="btn" to="/">{t('projects.home')}</Link>
      </div>
      <ShellOverlays />
    </div>
  )
}

export function ProjectRoute() {
  const { pid = '' } = useParams()
  const project = useProject(pid)
  const simulate = useSettings((s) => s.simulateReviewer)
  const relink = useRootsCheck(pid)
  useProjectSync(pid)
  useCurationRuntime(pid)
  useProjectEvents(pid, useCallback((e: ServerEvent) => logEvent(e), []))
  useEffect(() => {
    api.setReviewerSimulation(pid, simulate)
    return () => api.setReviewerSimulation(null, false)
  }, [pid, simulate])
  if (project.error instanceof ProblemError && project.error.status === 404)
    return <ProjectNotFound pid={pid} detail={project.error.detail} />
  return (
    <>
      <Workbench pid={pid} brand={<ProjectSwitcher pid={pid} />} shareUrl={project.data?.share_url} />
      <ImportWizard />
      {relink.open ? <RelinkDialog pid={pid} name={project.data?.name ?? ''} onOpenChange={(o) => !o && relink.dismiss()} /> : null}
    </>
  )
}
