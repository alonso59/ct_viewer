// Import wizard, step 1 (IMP-01/02, SRC-09, IMP-14): the data root or one file on the server, its
// alias, or uploaded metadata files (images stay on the server).
import type { ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'

import type { PreviewRequest } from '../../../api'
import { Icon, codicon } from '../../../theme'
import { FolderBrowser } from '../FolderBrowser'
import { cleanAlias } from '../model'

export type Uploads = NonNullable<PreviewRequest['files']>

/** IMP-02 alternative: upload the metadata files (images stay on the server) */
function UploadFields({ files, onFiles }: { files: Partial<Uploads>; onFiles: (f: Partial<Uploads>) => void }) {
  const { t } = useTranslation()
  const pick = (k: keyof Uploads) => (e: ChangeEvent<HTMLInputElement>) => onFiles({ ...files, [k]: e.target.files?.[0] ?? null })
  return (
    <div className="upload-grid">
      <label className="field">
        <span className="field-label">{t('import.upload.metadata')}</span>
        <input type="file" accept=".jsonl,.json" onChange={pick('metadata')} />
      </label>
      <label className="field">
        <span className="field-label">{t('import.upload.phase')}</span>
        <input type="file" accept=".json" onChange={pick('phase')} />
      </label>
      <label className="field">
        <span className="field-label">{t('import.upload.voi')}</span>
        <input type="file" accept=".jsonl" onChange={pick('voi_catalog')} />
      </label>
    </div>
  )
}

export function RootStep(p: {
  dir: string | null
  file: string | null
  onDir: (dir: string | null) => void
  onFile: (file: string | null) => void
  alias: string
  onAlias: (alias: string) => void
  aliasError: string | null
  upload: boolean
  onUpload: (on: boolean) => void
  files: Partial<Uploads>
  onFiles: (f: Partial<Uploads>) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="wiz-grid">
      <div>
        <h3>{t('import.rootTitle')}</h3>
        <p className="muted">{t('import.rootHelp')}</p>
        {p.file ? (
          <p className="mono panel-size">
            <Icon spec={codicon('file')} /> {t('import.singleFile', { name: p.file.slice(p.file.lastIndexOf('/') + 1) })}
          </p>
        ) : null}
        <label className="field mt-3">
          <span className="field-label">{t('import.alias')}</span>
          <input className="input mono" value={p.alias} aria-invalid={p.aliasError !== null} aria-describedby="import-alias-help" onChange={(e) => p.onAlias(cleanAlias(e.target.value))} />
          <span id="import-alias-help" className={`muted small ${p.aliasError ? 'text-error' : ''}`}>
            {p.aliasError ?? t('import.aliasHelp', { alias: p.alias })}
          </span>
        </label>
        <label className="check mt-3">
          <input type="checkbox" checked={p.upload} onChange={(e) => p.onUpload(e.target.checked)} />
          {t('import.uploadToggle')}
        </label>
        {p.upload ? <UploadFields files={p.files} onFiles={p.onFiles} /> : null}
        <div className="wiz-note">
          <Icon spec={codicon('lock')} />
          {t('import.readOnly')}
        </div>
      </div>
      <FolderBrowser
        path={p.dir}
        onPath={(d) => {
          p.onDir(d)
          p.onFile(null)
        }}
        selected={p.file}
        onSelectFile={(f) => p.onFile(p.file === f ? null : f)}
      />
    </div>
  )
}
