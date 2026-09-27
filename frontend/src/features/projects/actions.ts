// Project actions shared by buttons and commands: bundle export (PRJ-08, API-06) and the
// full-hash job (IMP-09, API-15; progress in the Jobs panel via `job.*` events).
import i18n from '../../i18n'
import { ProblemError, api, keys, queryClient } from '../../api'
import { toast } from '../../shell'
import { useLayout } from '../../state'
import { problemMessage } from '../../lib'


export function saveBlob(name: string, blob: Blob) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  // Revoke after the click has started the download (Firefox needs the URL a moment longer)
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** Download the project bundle (`.zip`, no image data) */
export async function exportBundle(pid: string): Promise<void> {
  try {
    const { blob, filename } = await api.exportBundle(pid)
    saveBlob(filename, blob)
    toast({ message: i18n.t('projects.bundle.exported', { name: filename }), tone: 'ok' })
  } catch (e) {
    toast({ message: i18n.t('projects.bundle.exportFailed', { detail: problemMessage(e) }), tone: 'error' })
  }
}

/** Start API-15; `force` re-hashes files that already have a current hash */
export async function computeHashes(pid: string, force = false): Promise<void> {
  const showJobs = () => useLayout.getState().showPanelTab('jobs')
  try {
    const r = await api.startHashJob(pid, force)
    void queryClient.invalidateQueries({ queryKey: keys.jobs(pid) })
    if (r.n_files === 0) toast({ message: i18n.t('projects.hash.upToDate', { count: r.n_skipped }), tone: 'info' })
    else {
      toast({ message: i18n.t('projects.hash.started', { count: r.n_files, skipped: r.n_skipped }), tone: 'info' })
      showJobs()
    }
  } catch (e) {
    if (e instanceof ProblemError && e.status === 409) {
      toast({ message: i18n.t('projects.hash.running'), tone: 'info' })
      showJobs()
    } else toast({ message: i18n.t('projects.hash.failed', { detail: problemMessage(e) }), tone: 'error' })
  }
}
