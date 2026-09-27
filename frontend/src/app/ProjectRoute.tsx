// /p/:pid/* — the workbench for one project, with runtime hooks (cache sync, live state, output log).
// Share links land here (PRJ-03), so an unknown project gets its own page.
import { useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import { isViewPid, ProblemError, useProject, useProjectEvents, useProjectSync, type ServerEvent } from '../api'
import { usePhaseRuntime } from '../features/phase'
import { useCurationRuntime } from '../plugins'
import { ImportWizard } from '../features/import'
import { logEvent } from '../features/jobs'
import { ProjectSwitcher, RelinkDialog, ShareMenu, useProjectDialogs, useRootsCheck } from '../features/projects'
import { TaskCommands } from '../features/tasks'
import { applyProjectDisplay } from '../features/viewer'
import { registry, ShellOverlays, Workbench } from '../shell'
import { BrandMark } from '../theme'

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

/** UI-26: the title-bar identity of a view-only workbench */
function ViewOnlyBrand({ name }: { name: string }) {
  const { t } = useTranslation()
  return (
    <span className="project-switcher view-only-brand">
      <BrandMark size={18} />
      <strong>{name}</strong>
      <span className="badge" data-tone="accent" title={t('viewOnly.help')}>{t('viewOnly.badge')}</span>
    </span>
  )
}

export function ProjectRoute() {
  const { pid = '' } = useParams()
  const readOnly = isViewPid(pid)
  registry.setReadOnly(readOnly) // before the workbench renders its contributions (UI-26)
  const project = useProject(pid)
  const relink = useRootsCheck(readOnly ? '' : pid)
  const relinkAsked = useProjectDialogs((s) => s.relink === pid)
  useProjectSync(pid)
  // VW-25: the project's display settings; the initial layout once per project unless the URL has one
  const displayed = useRef<string | null>(null)
  useEffect(() => {
    if (!project.data) return
    const first = displayed.current !== pid
    displayed.current = pid
    applyProjectDisplay(project.data, first && !new URLSearchParams(location.search).has('layout'))
  }, [project.data, pid])
  useCurationRuntime(pid)
  usePhaseRuntime(pid)
  useProjectEvents(pid, useCallback((e: ServerEvent) => logEvent(e), []))
  if (project.error instanceof ProblemError && project.error.status === 404)
    return <ProjectNotFound pid={pid} detail={project.error.detail} />
  return (
    <>
      <Workbench pid={pid} brand={readOnly ? <ViewOnlyBrand name={project.data?.name ?? ''} /> : <ProjectSwitcher pid={pid} />} share={<ShareMenu pid={pid} />} />
      {readOnly ? null : <ImportWizard />}
      {readOnly ? null : <TaskCommands />}
      {!readOnly && (relink.open || relinkAsked) ? (
        <RelinkDialog
          pid={pid}
          name={project.data?.name ?? ''}
          onOpenChange={(o) => {
            if (o) return
            relink.dismiss()
            useProjectDialogs.getState().set({ relink: null })
          }}
        />
      ) : null}
    </>
  )
}
