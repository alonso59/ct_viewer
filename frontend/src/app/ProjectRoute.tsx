// /p/:pid/* — the workbench for one project, with runtime hooks (live sync, output log, simulation)
import { useCallback, useEffect } from 'react'
import { useParams } from 'react-router'

import { setReviewerSimulation, useProject, type ServerEvent } from '../api'
import { useCurationRuntime } from '../features/curation'
import { ImportWizard } from '../features/import'
import { logEvent } from '../features/jobs'
import { ProjectSwitcher } from '../features/projects'
import { Workbench } from '../shell'
import { useProjectEvents } from '../api'
import { useSettings } from '../state'

export function ProjectRoute() {
  const { pid = '' } = useParams()
  const project = useProject(pid)
  const simulate = useSettings((s) => s.simulateReviewer)
  useCurationRuntime(pid)
  useProjectEvents(pid, useCallback((e: ServerEvent) => logEvent(e), []))
  useEffect(() => {
    setReviewerSimulation(pid, simulate)
    return () => setReviewerSimulation(null, false)
  }, [pid, simulate])
  return (
    <>
      <Workbench pid={pid} brand={<ProjectSwitcher pid={pid} />} shareUrl={project.data?.share_url} />
      <ImportWizard />
    </>
  )
}
