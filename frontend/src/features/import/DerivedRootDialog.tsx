// PRJ-13 / UI-19: a task that writes volumes asks for the project's derived folder on first use.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { FolderBrowser } from './FolderBrowser'
import { codicon } from '../../theme'

export function DerivedRootDialog({ pid, onClose }: { pid: string; onClose: (ok: boolean) => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [dir, setDir] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    if (!dir) return
    setBusy(true)
    try {
      await api.setDerivedRoot(pid, dir)
      void qc.invalidateQueries({ queryKey: keys.project(pid) })
      void qc.invalidateQueries({ queryKey: keys.roots(pid) })
      onClose(true)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose(false)}
      title={t('tasks.derivedTitle')}
      icon={codicon('folder-library')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onClose(false)}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!dir || busy} onClick={() => void save()}>{t('tasks.derivedUse')}</button>
        </>
      }
    >
      <p className="muted">{t('tasks.derivedHelp')}</p>
      {error ? <ProblemCard error={error} /> : null}
      <FolderBrowser path={dir} onPath={setDir} role="derived" />
    </Dialog>
  )
}
