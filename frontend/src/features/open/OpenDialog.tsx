// "Open file or folder…" (UI-17, SRC-09): pick any accepted file or a folder, then the Open route.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { Dialog } from '../../lib'
import { FolderBrowser } from '../import'
import { codicon } from '../../theme'
import { useOpenDialog } from './store'

export default function OpenDialog() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const hide = useOpenDialog((s) => s.hide)
  const [dir, setDir] = useState<string | null>(null)
  const [file, setFile] = useState<string | null>(null)
  const target = file ?? dir
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && hide()}
      title={t('open.dialogTitle')}
      icon={codicon('folder-opened')}
      footer={
        <>
          <button type="button" className="btn" onClick={hide}>{t('common.cancel')}</button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!target}
            onClick={() => {
              hide()
              navigate(`/open?path=${encodeURIComponent(target ?? '')}`)
            }}
          >
            {t(file ? 'open.openFile' : 'open.openFolder')}
          </button>
        </>
      }
    >
      <p className="muted">{t('open.dialogHelp')}</p>
      <FolderBrowser path={dir} onPath={(d) => { setDir(d); setFile(null) }} selected={file} onSelectFile={(f) => setFile(file === f ? null : f)} />
    </Dialog>
  )
}
