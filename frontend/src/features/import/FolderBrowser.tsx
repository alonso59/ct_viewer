// Server folder browser (IMP-01, API-10), shared by the import wizard, Open mode and tasks
import { useTranslation } from 'react-i18next'

import { useFsList, type RootRole } from '../../api'
import { ProblemCard } from '../../lib'
import { Icon, codicon } from '../../theme'
import './import.css'

/** SRC-02: files the browser lets you pick (folders are always navigable) */
export const ACCEPTED = /\.(nii|nii\.gz|npy|dcm)$/i

/** IMP-01: browse folders under ALLOWED_DATA_ROOTS (or ALLOWED_DERIVED_ROOTS); `null` = the roots */
export function FolderBrowser({
  path,
  onPath,
  selected,
  onSelectFile,
  role = 'source',
}: {
  path: string | null
  onPath: (p: string | null) => void
  /** Highlighted file (single-file selection, SRC-05) */
  selected?: string | null
  /** Makes accepted files clickable */
  onSelectFile?: (p: string) => void
  role?: RootRole
}) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error } = useFsList(path, role)
  return (
    <div className="fs">
      <div className="fs-path mono" title={path ?? ''}>
        <Icon spec={codicon('folder-opened')} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'rtl', textAlign: 'left' }}>
          {path ?? t('import.allowedRootsTitle')}
        </span>
      </div>
      <div className="fs-list" role="listbox" aria-label={t('import.folders')}>
        {path !== null ? (
          <button type="button" className="list-row" onClick={() => onPath(data?.parent ?? null)}>
            <Icon spec={codicon('arrow-up')} />
            {t('import.up')}
          </button>
        ) : null}
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {isError ? <ProblemCard error={error} /> : null}
        {data && data.entries.length === 0 ? <div className="empty">{t(path === null ? 'import.noRoots' : 'import.emptyFolder')}</div> : null}
        {data?.entries.map((e) => {
          const pickable = e.kind === 'file' && !!onSelectFile && ACCEPTED.test(e.name)
          return (
            <button
              key={e.path}
              type="button"
              className="list-row"
              aria-selected={selected === e.path}
              disabled={e.kind === 'file' && !pickable}
              onClick={() => (e.kind === 'dir' ? onPath(e.path) : onSelectFile?.(e.path))}
              title={e.path}
            >
              <Icon spec={codicon(e.kind === 'dir' ? 'folder' : 'file')} />
              <span>{e.name}</span>
              {e.has_metadata ? <span className="badge" data-tone="ok" style={{ marginLeft: 'auto' }}>{t('import.hasMetadata')}</span> : null}
              {selected === e.path ? <Icon spec={codicon('check')} style={{ marginLeft: 'auto' }} /> : null}
            </button>
          )
        })}
        {data?.truncated ? <div className="muted" style={{ padding: '4px 12px' }}>{t('import.truncated')}</div> : null}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t(role === 'derived' ? 'import.allowedDerived' : 'import.allowedRoots')}</div>
    </div>
  )
}
