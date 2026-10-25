// Register projects saved alongside a dataset in this workspace.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { api, keys, type Project } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { FolderBrowser } from '../import'
import { codicon } from '../../theme'

export function OpenDatasetDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [path, setPath] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const pick = (p: Project) => { onClose(); navigate(`/p/${p.project_id}`) }
  const open = async () => {
    setBusy(true); setError(null)
    try {
      const found = await api.openDataset(path.trim())
      await qc.invalidateQueries({ queryKey: keys.projects() })
      if (found.length === 1) pick(found[0]!)
      else setProjects(found)
    } catch (e) { setError(e) }
    finally { setBusy(false) }
  }
  return <Dialog open title={t('dataset.open')} onOpenChange={(o) => { if (!o && !busy) onClose() }} icon={codicon('folder-opened')} footer={<>
    <button type="button" className="btn" disabled={busy} onClick={onClose}>{t('common.cancel')}</button>
    <button type="button" className="btn btn-primary" disabled={!path.trim() || busy} onClick={() => void open()}>{t('dataset.open')}</button>
  </>}>
    <p className="muted">{t('dataset.openHelp')}</p>
    <label className="field-label" htmlFor="open-dataset-folder">{t('dataset.folder')}</label>
    <input id="open-dataset-folder" className="input mono" value={path} onChange={(e) => { setPath(e.target.value); setProjects([]) }} placeholder={t('dataset.pathPlaceholder')} />
    <FolderBrowser path={path || null} onPath={(p) => { setPath(p ?? ''); setProjects([]) }} />
    {error ? <ProblemCard error={error} /> : null}
    {projects.map((p) => <button key={p.project_id} className="list-row" onClick={() => pick(p)}>{p.name}</button>)}
  </Dialog>
}
