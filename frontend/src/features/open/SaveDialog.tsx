// SRC-14 "Save as NIfTI…": a new .nii.gz (+ DICOM sidecar) under ALLOWED_DERIVED_ROOTS, written once.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, useFsList, type AxisOrder, type OpenItem, type OpenSession } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { toast } from '../../shell'
import { codicon } from '../../theme'
import { FolderBrowser } from '../import'

const KEY = 'rw.open.saveDir'
const remembered = () => {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function SaveDialog({ session, item, axisOrder, onClose }: { session: OpenSession; item: OpenItem; axisOrder: AxisOrder | null; onClose: () => void }) {
  const { t } = useTranslation()
  const roots = useFsList(null, 'derived')
  const [dest, setDest] = useState<string | null>(remembered())
  const [browse, setBrowse] = useState<string | null>(null)
  const [changing, setChanging] = useState(false)
  const [anonymize, setAnonymize] = useState(false)
  const [sidecar, setSidecar] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const today = new Date().toISOString().slice(0, 10)
  const first = roots.data?.entries[0]?.path
  const shown = dest ?? (first ? [first, '_open', today].join('/') : null)
  const dicom = item.format === 'dicom'
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.saveOpen(session.sid, item.n, { dest_dir: dest, sidecar: dicom && sidecar, anonymize: anonymize ? 'basic' : 'none', axis_order: axisOrder })
      if (dest) {
        try {
          localStorage.setItem(KEY, dest)
        } catch {
          // storage unavailable: the choice is not remembered
        }
      }
      toast({ message: t('open.saved', { path: r.path }), tone: 'ok' })
      onClose()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('open.saveTitle', { name: item.name })}
      icon={codicon('save')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>{t('open.save')}</button>
        </>
      }
    >
      <p className="muted">{t('open.saveHelp')}</p>
      {roots.error ? <ProblemCard error={roots.error} /> : null}
      <p className="mono">{shown ?? t('common.loading')}</p>
      <button type="button" className="btn btn-sm" onClick={() => setChanging((c) => !c)}>{t('open.changeFolder')}</button>
      {changing ? (
        <FolderBrowser
          path={browse}
          role="derived"
          onPath={(d) => {
            setBrowse(d)
            setDest(d)
          }}
        />
      ) : null}
      {dicom ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          <label className="check">
            <input type="checkbox" checked={sidecar} onChange={(e) => setSidecar(e.target.checked)} />
            {t('open.sidecar')}
          </label>
          <label className="check">
            <input type="checkbox" checked={anonymize} onChange={(e) => setAnonymize(e.target.checked)} />
            {t('open.anonymize')}
          </label>
          <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('open.phiNotice')}</p>
        </div>
      ) : null}
      {error ? <ProblemCard error={error} /> : null}
    </Dialog>
  )
}
