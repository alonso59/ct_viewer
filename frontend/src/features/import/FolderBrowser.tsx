// Server folder browser, shared by the import wizard, Open mode and tasks
import { useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { useFsList, type FsScope, type RootRole } from '../../api'
import { ProblemCard, midEllipsis, useRowKeys } from '../../lib'
import { Icon, codicon } from '../../theme'
import { ACCEPTED } from './store'
import './import.css'

const FILTER_FROM = 12
/** The Parent folder / All shared folders row's id among the options */
const UP = '..'

/** Browse folders under the storage locations, else ALLOWED_DATA_ROOTS (or ALLOWED_DERIVED_ROOTS); `null` = the roots */
export function FolderBrowser({
  path,
  onPath,
  selected,
  onSelectFile,
  role = 'source',
  scope = 'locations',
  fileFilter = (name: string) => ACCEPTED.test(name),
}: {
  path: string | null
  onPath: (p: string | null) => void
  /** Highlighted file (single-file selection) */
  selected?: string | null
  /** Makes accepted files clickable */
  onSelectFile?: (p: string) => void
  role?: RootRole
  /** `allowed`: every folder the operator allows, not only the storage locations */
  scope?: FsScope
  fileFilter?: (name: string) => boolean
}) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error, refetch } = useFsList(path, role, scope)
  const roots = useFsList(null, role, scope).data
  // the filter resets per folder
  const [filter, setFilter] = useState({ path, text: '' })
  const text = filter.path === path ? filter.text : ''
  const list = useRef<HTMLDivElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const q = text.trim().toLowerCase()
  const entries = (data?.entries ?? []).filter((e) => !q || e.name.toLowerCase().includes(q))
  // at an allowed root there is no parent folder: only the list of shared folders, when there are several
  const atRoot = path !== null && data?.path === path && data.parent === null
  const upRow = path === null ? null : !atRoot ? 'up' : (roots?.entries.length ?? 0) > 1 ? 'roots' : null
  const rowKeys = useRowKeys([...(upRow ? [UP] : []), ...entries.map((e) => e.path)])
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey || e.key === ' ') return
    const now = Date.now()
    typed.current = { text: (now - typed.current.at < 700 ? typed.current.text : '') + e.key.toLowerCase(), at: now }
    const rows = [...(list.current?.querySelectorAll<HTMLButtonElement>('button[data-name]') ?? [])]
    const hit = rows.find((b) => (b.dataset.name ?? '').toLowerCase().startsWith(typed.current.text))
    if (hit) {
      e.preventDefault()
      hit.focus()
    }
  }
  return (
    <div className="fs">
      <div className="fs-path mono" title={path ?? ''}>
        <Icon spec={codicon('folder-opened')} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'rtl', textAlign: 'left' }}>
          {path ?? t('import.allowedRootsTitle')}
        </span>
      </div>
      {(data?.entries.length ?? 0) > FILTER_FROM || text ? (
        <input className="input fs-filter" type="search" value={text} placeholder={t('import.filter')} aria-label={t('import.filter')} onChange={(e) => setFilter({ path, text: e.target.value })} />
      ) : null}
      {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {isError ? <ProblemCard error={error} onRetry={() => void refetch()} /> : null}
      {data && data.entries.length === 0 && path !== null ? <div className="empty">{t('import.emptyFolder')}</div> : null}
      {/* the server setting's name is for administrators */}
      {data && data.entries.length === 0 && path === null ? (
        <div className="empty">
          {t('import.noRoots')}
          <details>
            <summary className="small">{t('common.details')}</summary>
            <span className="muted small">{t('import.noRootsAdmin')}</span>
          </details>
        </div>
      ) : null}
      {data && data.entries.length > 0 && entries.length === 0 ? <div className="empty">{t('import.noMatch', { text })}</div> : null}
      {/* a listbox of options only: one Tab stop, arrows move, Enter opens a folder or picks a file */}
      {upRow || entries.length ? (
        <div ref={list} className="fs-list" role="listbox" aria-label={t('import.folders')} onKeyDown={onKeyDown}>
          {upRow ? (
            <button type="button" role="option" aria-selected={false} className="list-row" onClick={() => onPath(upRow === 'up' ? (data?.parent ?? null) : null)} {...rowKeys(UP)}>
              <Icon spec={codicon(upRow === 'up' ? 'arrow-up' : 'list-flat')} />
              {t(upRow === 'up' ? 'import.up' : 'import.allRoots')}
            </button>
          ) : null}
          {entries.map((e) => {
            // a file that cannot be picked stays reachable by the arrows, but does nothing
            const inert = e.kind === 'file' && !(onSelectFile && fileFilter(e.name))
            return (
              <button
                key={e.path}
                type="button"
                role="option"
                className="list-row"
                data-name={e.name}
                aria-selected={selected === e.path}
                aria-disabled={inert || undefined}
                onClick={() => {
                  if (inert) return
                  if (e.kind === 'dir') onPath(e.path)
                  else onSelectFile?.(e.path)
                }}
                title={e.path}
                {...rowKeys(e.path)}
              >
                <Icon spec={codicon(e.kind === 'dir' ? 'folder' : 'file')} />
                {/* a shared root is a long server path: shortened in the middle, whole in the tooltip */}
                <span>{path === null ? midEllipsis(e.name) : e.name}</span>
                {e.has_metadata ? <span className="badge" data-tone="ok" style={{ marginLeft: 'auto' }}>{t('import.hasMetadata')}</span> : null}
                {selected === e.path ? <Icon spec={codicon('check')} style={{ marginLeft: 'auto' }} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
      {data?.truncated ? <div className="muted" style={{ padding: '4px 12px' }}>{t('import.truncated')}</div> : null}
      <div className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t(role === 'derived' ? 'import.allowedDerived' : 'import.allowedRoots')}</div>
    </div>
  )
}
