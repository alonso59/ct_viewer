// New project (PRJ-14): name + default modality, then the import wizard (IMP-*). In the import
// feature so the workspace home and Open mode both reach it without importing each other (AUD-A6-10).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { MODALITIES, useCreateProject, type ProjectModality } from '../../api'
import { Dialog } from '../../lib'
import { codicon } from '../../theme'
import { useImportWizard, type WizardPrefill } from './store'

/** `prefill`: "Create project from this" (Open mode) starts the import wizard on that path */
export function NewProjectDialog({ open, onOpenChange, prefill }: { open: boolean; onOpenChange: (o: boolean) => void; prefill?: WizardPrefill }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [modality, setModality] = useState<ProjectModality>('CT')
  const create = useCreateProject()
  const navigate = useNavigate()
  const submit = async () => {
    const p = await create.mutateAsync({ name: name.trim(), default_modality: modality })
    onOpenChange(false)
    setName('')
    navigate(`/p/${p.project_id}`)
    useImportWizard.getState().open(p.project_id, prefill)
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
          <button type="button" className="btn btn-primary" disabled={!name.trim() || create.isPending} onClick={() => void submit()}>
            {t('projects.createAndImport')}
          </button>
        </>
      }
    >
      <form style={{ display: 'flex', flexDirection: 'column', gap: 14 }} onSubmit={(e) => { e.preventDefault(); if (name.trim()) void submit() }}>
        <div className="field">
          <label className="field-label" htmlFor="project-name">{t('projects.name')}</label>
          <input id="project-name" className="input" autoFocus value={name} placeholder={t('projects.namePlaceholder')} onChange={(e) => setName(e.target.value)} />
          <span className="muted panel-size">{t('projects.newHelp')}</span>
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
