// SRC-15 "Add to project…": the open file becomes a new import next to the project's sources.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useProjects, type OpenItem, type OpenSession } from '../../api'
import { Dialog } from '../../lib'
import { codicon } from '../../theme'
import { useImportWizard } from '../import'

/** The path to add: the file itself; a DICOM series of several files → its folder */
export function addPath(session: OpenSession, item: OpenItem): string {
  const file = [session.root, item.rel].join('/')
  return item.format === 'dicom' && (item.files?.length ?? 0) > 1 ? file.slice(0, file.lastIndexOf('/')) : file
}

export function AddDialog({ session, item, modality, onClose }: { session: OpenSession; item: OpenItem; modality?: string; onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const projects = useProjects().data ?? []
  const [pid, setPid] = useState<string | null>(null)
  const go = () => {
    if (!pid) return
    onClose()
    navigate(`/p/${pid}`)
    useImportWizard.getState().open(pid, { path: addPath(session, item), adapter: item.format === 'dicom' ? 'dicom.convert' : 'nifti-files', add: true, modality })
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('open.addTitle', { name: item.name })}
      icon={codicon('add')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!pid} onClick={go}>{t('open.addNext')}</button>
        </>
      }
    >
      <p className="muted">{t('open.addHelp')}</p>
      <div className="fs-list" role="listbox" aria-label={t('open.projects')} style={{ height: 220 }}>
        {projects.map((p) => (
          <button key={p.project_id} type="button" className="list-row" aria-selected={pid === p.project_id} onClick={() => setPid(p.project_id)}>
            <span>{p.name}</span>
            <span className="muted" style={{ marginLeft: 'auto' }}>{t('open.cases', { count: p.n_cases })}</span>
          </button>
        ))}
        {!projects.length ? <div className="empty">{t('open.noProjects')}</div> : null}
      </div>
    </Dialog>
  )
}
