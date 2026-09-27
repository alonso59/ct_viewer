// Server folder browser (IMP-01, API-10), shared by the import wizard, Open mode and tasks
import { useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { useFsList, type RootRole } from '../../api'
import { ProblemCard } from '../../lib'
import { Icon, codicon } from '../../theme'
import { ACCEPTED } from './store'
import './import.css'

/** SRC-02: files the browser lets you pick (folders are always navigable) */
export { ACCEPTED }

/** The filter box shows for folders longer than this (AUD-A1-16) */
const FILTER_FROM = 12

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
  const roots = useFsList(null, role).data
  // AUD-A1-16: a filter for long folders (resets per folder) and type-to-select in the list
  const [filter, setFilter] = useState({ path, text: '' })
  const text = filter.path === path ? filter.text : ''
  const list = useRef<HTMLDivElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const q = text.trim().toLowerCase()
  const entries = (data?.entries ?? []).filter((e) => !q || e.name.toLowerCase().includes(q))
  // at an allowed root there is no parent folder: only the list of shared folders, when there are several
  const atRoot = path !== null && data?.path === path && data.parent === null
  const upRow = path === null ? null : !atRoot ? 'up' : (roots?.entries.length ?? 0) > 1 ? 'roots' : null
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
      <div ref={list} className="fs-list" role="listbox" aria-label={t('import.folders')} onKeyDown={onKeyDown}>
        {upRow ? (
          <button type="button" className="list-row" onClick={() => onPath(upRow === 'up' ? (data?.parent ?? null) : null)}>
            <Icon spec={codicon(upRow === 'up' ? 'arrow-up' : 'list-flat')} />
            {t(upRow === 'up' ? 'import.up' : 'import.allRoots')}
          </button>
        ) : null}
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {isError ? <ProblemCard error={error} /> : null}
        {data && data.entries.length === 0 ? <div className="empty">{t(path === null ? 'import.noRoots' : 'import.emptyFolder')}</div> : null}
        {data && data.entries.length > 0 && entries.length === 0 ? <div className="empty">{t('import.noMatch', { text })}</div> : null}
        {entries.map((e) => {
          const pickable = e.kind === 'file' && !!onSelectFile && ACCEPTED.test(e.name)
          return (
            <button
              key={e.path}
              type="button"
              className="list-row"
              data-name={e.name}
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
