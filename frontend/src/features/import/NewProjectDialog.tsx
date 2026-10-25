// New project (PRJ-14): name + default modality, then the import wizard (IMP-*). In the import
// feature so the workspace home and Open mode both reach it without importing each other (AUD-A6-10).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { MODALITIES, useCreateProject, type ProjectModality } from '../../api'
import { Dialog } from '../../lib'
import { FolderBrowser } from './FolderBrowser'
import { codicon } from '../../theme'
import { useImportWizard, type WizardPrefill } from './store'

/** `prefill`: "Create project from this" (Open mode) starts the import wizard on that path */
type Props = { open: boolean; onOpenChange: (o: boolean) => void; prefill?: WizardPrefill }

export function NewProjectDialog(props: Props) {
  return props.open ? <ProjectDialog {...props} /> : null
}

function ProjectDialog({ open, onOpenChange, prefill }: Props) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [dataset, setDataset] = useState(prefill?.kind === 'folder' ? prefill.path : prefill?.kind === 'file' ? prefill.path.slice(0, prefill.path.lastIndexOf('/')) || '/' : (prefill?.path ?? '').replace(/\/[^/]+\.(nii(?:\.gz)?|npy|dcm)$/i, ''))
  const [browse, setBrowse] = useState(false)
  const [modality, setModality] = useState<ProjectModality>('CT')
  const create = useCreateProject()
  const navigate = useNavigate()
  const submit = async () => {
    const p = await create.mutateAsync({ name: name.trim(), default_modality: modality, ...(dataset.trim() ? { dataset_root: dataset.trim() } : {}) })
    onOpenChange(false)
    setName('')
    navigate(`/p/${p.project_id}`)
    const root = dataset.trim()
    const keepPrefill = prefill?.path === root || prefill?.path?.startsWith(`${root}/`)
    useImportWizard.getState().open(p.project_id, keepPrefill ? prefill : { path: root })
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('projects.newTitle')}
      icon={codicon('new-folder')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!name.trim() || !dataset.trim() || create.isPending} onClick={() => void submit()}>
            {t('projects.createAndImport')}
          </button>
        </>
      }
    >
      <form style={{ display: 'flex', flexDirection: 'column', gap: 14 }} onSubmit={(e) => { e.preventDefault(); if (name.trim() && dataset.trim()) void submit() }}>
        <div className="field">
          <label className="field-label" htmlFor="project-name">{t('projects.name')}</label>
          <input id="project-name" className="input" autoFocus value={name} placeholder={t('projects.namePlaceholder')} onChange={(e) => setName(e.target.value)} />
          <span className="muted panel-size">{t('projects.newHelp')}</span>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="dataset-folder">{t('dataset.folder')}</label>
          <input id="dataset-folder" className="input mono" value={dataset} onChange={(e) => setDataset(e.target.value)} placeholder={t('dataset.pathPlaceholder')} />
          <span className="muted small">{t('dataset.storageHelp')}</span>
          <button type="button" className="btn" onClick={() => setBrowse(!browse)}>{t('dataset.browse')}</button>
          {browse ? <FolderBrowser path={dataset || null} onPath={(p) => setDataset(p ?? '')} /> : null}
        </div>
        <div className="field">
          <span className="field-label">{t('projects.modality')}</span>
          <div className="seg" role="group" aria-label={t('projects.modality')}>
            {MODALITIES.map((m) => (
              <button key={m} type="button" aria-pressed={modality === m} onClick={() => setModality(m)}>{t(`projects.modalities.${m}`)}</button>
            ))}
          </div>
          <span className="muted small">{t('projects.modalityHelp')}</span>
        </div>
        {create.isError ? <div className="error-card" style={{ margin: 0 }}>{create.error.message}</div> : null}
      </form>
    </Dialog>
  )
}
