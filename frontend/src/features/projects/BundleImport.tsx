// Import a project bundle (PRJ-09, API-06) and show its report: new project, id change, and a
// per-alias resolve check. When an alias does not resolve, Relink (PRJ-05) opens from here.
// Lazy chunk: loaded once a file is picked on the workspace home (NFR-07).
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useImportBundle } from '../../api'
import { Dialog, problemMessage } from '../../lib'
import { codicon } from '../../theme'
import '../../i18n/lazy'
import { RelinkDialog } from './RelinkDialog'

export default function BundleImport({ file, onClose }: { file: File; onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const importBundle = useImportBundle()
  const [relinking, setRelinking] = useState(false)
  // One upload per picked file (StrictMode mounts effects twice)
  const started = useRef<File | null>(null)
  const { mutate } = importBundle
  useEffect(() => {
    if (started.current === file) return
    started.current = file
    mutate(file)
  }, [file, mutate])
  const r = importBundle.data
  const pid = r?.project.project_id ?? ''
  if (relinking && r) return <RelinkDialog pid={pid} name={r.project.name} onOpenChange={(o) => !o && setRelinking(false)} />
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('bundle.title')}
      icon={codicon('package')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.close')}</button>
          {r?.needs_relink ? (
            <button type="button" className="btn" onClick={() => setRelinking(true)}>{t('projects.relink')}</button>
          ) : null}
          {r ? (
            <button type="button" className="btn btn-primary" onClick={() => { onClose(); navigate(`/p/${pid}`) }}>{t('bundle.open')}</button>
          ) : null}
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="muted mono" style={{ fontSize: 'var(--fs-panel)' }}>{file.name}</div>
        {importBundle.isPending ? <div className="empty" role="status">{t('bundle.importing')}</div> : null}
        {importBundle.isError ? (
          <div className="error-card" style={{ margin: 0 }} role="alert">
            <strong>{t('bundle.failed')}</strong>
            <div className="muted">{problemMessage(importBundle.error)}</div>
          </div>
        ) : null}
        {r ? (
          <>
            <div className="card" style={{ margin: 0 }} role="status">
              {t('bundle.imported', { name: r.project.name })}
              {r.id_changed ? <div className="muted">{t('bundle.idChanged', { from: r.source_project_id, to: pid })}</div> : null}
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>{t('projects.alias')}</th>
                  <th>{t('bundle.path')}</th>
                  <th>{t('bundle.check')}</th>
                </tr>
              </thead>
              <tbody>
                {r.roots.map(({ root, verify }) => {
                  const ok = root.exists && verify.missing === 0 && verify.mismatched === 0
                  return (
                    <tr key={root.alias}>
                      <td className="mono">{root.alias}</td>
                      <td className="mono">{root.path}</td>
                      <td>
                        <span className="badge" data-tone={ok ? 'ok' : 'error'}>
                          {root.exists
                            ? t('bundle.verify', { matched: verify.matched, sampled: verify.sampled, mismatched: verify.mismatched, missing: verify.missing })
                            : t('projects.offline')}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {r.needs_relink ? <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('bundle.needsRelink')}</div> : null}
          </>
        ) : null}
      </div>
    </Dialog>
  )
}
