// Settings › Storage: the folders the app works in, inside the folders the operator allows.
// Registering, testing or removing a location never changes data on disk; workspace allocation
// and renewal stay commands the user runs.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useStorage, useStorageEdit, type LocationTest, type StorageLocation, type StorageState } from '../../api'
import { Button, ConfirmInline, Dialog, ProblemCard, RadioSeg, fmtAgo } from '../../lib'
import { toast } from '../../shell'
import { codicon } from '../../theme'
import { FolderBrowser } from '../import'
import './setup.css'

const DAY = 86_400
/** Warn this long before a workspace expires */
const WARN_DAYS = 14
const EXTEND_DAYS = 30

function copy(text: string, done: string) {
  if (navigator.clipboard) void navigator.clipboard.writeText(text).then(() => toast({ message: done, tone: 'ok' }), () => toast({ message: text }))
  else toast({ message: text, sticky: true })
}

function Command({ text }: { text: string }) {
  const { t } = useTranslation()
  return (
    <div className="setup-command">
      <code className="mono">{text}</code>
      <button type="button" className="btn btn-sm" onClick={() => copy(text, t('setup.copied'))}>{t('setup.copy')}</button>
    </div>
  )
}

function Expiry({ location }: { location: StorageLocation }) {
  const { t } = useTranslation()
  const ws = location.workspace
  if (!ws) return null
  const left = location.remaining_seconds
  const days = left == null ? null : Math.floor(left / DAY)
  const tone = left == null ? undefined : left <= 0 ? 'error' : days !== null && days < WARN_DAYS ? 'warn' : undefined
  return (
    <div className="setup-expiry">
      <span className="badge" data-tone={tone}>
        {left == null ? t('setup.expiryUnknown') : left <= 0 ? t('setup.expired') : t('setup.expiresIn', { count: days ?? 0 })}
      </span>
      <span className="muted small">
        {t('setup.workspaceMeta', { name: ws.name, fs: ws.filesystem ?? '?', extensions: ws.extensions ?? '?' })}
        {ws.observed_at ? ` · ${t('setup.observed', { ago: fmtAgo(ws.observed_at) })}` : ''}
      </span>
      {ws.filesystem ? <Command text={`ws_extend -F ${ws.filesystem} ${ws.name} ${EXTEND_DAYS}`} /> : null}
    </div>
  )
}

function TestResult({ result }: { result: LocationTest }) {
  const { t } = useTranslation()
  if (result.error) return <p className="field-error" role="alert">{t('setup.testFailed', { error: result.error })}</p>
  const l = result.location
  const key = !l.available ? 'setup.testUnavailable' : result.method === 'probe' ? 'setup.testProbe' : result.method === 'permissions' ? (l.writable ? 'setup.testPermissions' : 'setup.testReadOnly') : 'setup.testReadOnly'
  return <p className="muted small" role="status">{t(key)}</p>
}

function Row({ location, state }: { location: StorageLocation; state: StorageState }) {
  const { t } = useTranslation()
  const edit = useStorageEdit()
  const [tested, setTested] = useState<LocationTest | null>(null)
  const isDefault = state.default_location === location.id
  return (
    <li className="setup-row">
      <div className="setup-row-head">
        <strong>{location.label || location.path}</strong>
        <span className="badge">{t(location.kind === 'managed_hpc_workspace' ? 'setup.kindWorkspace' : 'setup.kindLocal')}</span>
        <span className="badge">{t(location.access === 'read_only' ? 'setup.readOnly' : 'setup.readWrite')}</span>
        {location.available ? (
          <span className="badge" data-tone="ok">{t(location.writable ? 'setup.writable' : location.readable ? 'setup.readable' : 'setup.noAccess')}</span>
        ) : (
          <span className="badge" data-tone="error">{t('setup.unavailable')}</span>
        )}
        {isDefault ? <span className="badge" data-tone="info">{t('setup.default')}</span> : null}
      </div>
      {location.label ? <span className="mono small">{location.path}</span> : null}
      <Expiry location={location} />
      {location.projects.length ? <span className="muted small">{t('setup.projects', { names: location.projects.join(', ') })}</span> : null}
      <div className="row wrap">
        <Button className="btn btn-sm" disabled={edit.test.isPending} onClick={() => edit.test.mutate(location.id, { onSuccess: setTested })}>{t('setup.test')}</Button>
        {!isDefault && location.access === 'read_write' ? (
          <Button className="btn btn-sm" disabled={edit.setDefault.isPending} onClick={() => edit.setDefault.mutate(location.id)}>{t('setup.makeDefault')}</Button>
        ) : null}
        <ConfirmInline
          question={t('setup.removeQuestion')}
          confirm={t('setup.remove')}
          onConfirm={() => edit.remove.mutate(location.id)}
          trigger={(ask) => <button type="button" className="btn btn-sm" onClick={ask}>{t('setup.remove')}</button>}
        />
      </div>
      {tested ? <TestResult result={tested} /> : null}
      {edit.test.isError ? <ProblemCard error={edit.test.error} /> : null}
    </li>
  )
}

function AddLocation({ state, initial }: { state: StorageState; initial: string | null }) {
  const { t } = useTranslation()
  const edit = useStorageEdit()
  const [path, setPath] = useState<string | null>(initial)
  const [access, setAccess] = useState<'read_write' | 'read_only'>('read_write')
  const [label, setLabel] = useState('')
  if (!state.registrable) return <p className="muted">{t('setup.notRegistrable')}</p>
  const add = () => {
    if (!path) return
    edit.register.mutate({ path, access, label }, { onSuccess: () => { setPath(null); setLabel('') } })
  }
  return (
    <div className="setup-add">
      <FolderBrowser path={path} onPath={setPath} scope="allowed" fileFilter={() => false} />
      <div className="row wrap">
        <RadioSeg
          label={t('setup.access')}
          value={access}
          options={[{ value: 'read_write', label: t('setup.readWrite') }, { value: 'read_only', label: t('setup.readOnly') }]}
          onChange={setAccess}
        />
        <input className="input input-sm grow" value={label} maxLength={80} placeholder={t('setup.labelPlaceholder')} aria-label={t('setup.label')} onChange={(e) => setLabel(e.target.value)} />
        <Button className="btn btn-sm btn-primary" disabled={!path || edit.register.isPending} reason={t(!path ? 'setup.pickFolder' : 'reason.working')} onClick={add}>
          {t('setup.add')}
        </Button>
      </div>
      <span className="muted small">{t(access === 'read_only' ? 'setup.readOnlyHelp' : 'setup.readWriteHelp')}</span>
      {edit.register.isError ? <ProblemCard error={edit.register.error} /> : null}
    </div>
  )
}

function Discovered({ state, onPick }: { state: StorageState; onPick: (path: string) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('rw-data')
  if (state.discovered == null) return null
  const fs = state.discovered.find((w) => w.filesystem)?.filesystem ?? state.locations.find((l) => l.workspace?.filesystem)?.workspace?.filesystem
  return (
    <section>
      <h3>{t('setup.discovered')}</h3>
      {state.discovery_error ? <p className="field-error">{state.discovery_error}</p> : null}
      {state.discovered.length ? (
        <ul className="setup-list">
          {state.discovered.map((w) => (
            <li key={w.path} className="setup-row">
              <div className="setup-row-head">
                <strong>{w.name}</strong>
                <span className="mono small">{w.path}</span>
              </div>
              <span className="muted small">{t('setup.workspaceMeta', { name: w.name, fs: w.filesystem ?? '?', extensions: w.extensions ?? '?' })}</span>
              {w.blocked ? <span className="muted small">{t('setup.blocked')}</span> : <button type="button" className="btn btn-sm" onClick={() => onPick(w.path)}>{t('setup.useWorkspace')}</button>}
            </li>
          ))}
        </ul>
      ) : <p className="muted">{t('setup.noneDiscovered')}</p>}
      <p className="muted small">{t('setup.allocateHelp')}</p>
      <div className="row wrap">
        <input className="input input-sm" value={name} aria-label={t('setup.workspaceName')} onChange={(e) => setName(e.target.value.replace(/[^A-Za-z0-9_.-]/g, ''))} />
      </div>
      <Command text={`ws_allocate -F ${fs ?? '<filesystem>'} ${name || 'rw-data'} ${EXTEND_DAYS}`} />
    </section>
  )
}

export function StorageDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const storage = useStorage()
  const [pick, setPick] = useState<{ path: string; n: number } | null>(null)
  const state = storage.data
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('setup.storageTitle')} description={t('setup.storageHelp')} icon={codicon('database')} size="lg">
      <div className="setup">
        {storage.isError ? <ProblemCard error={storage.error} onRetry={() => void storage.refetch()} /> : null}
        {!state ? (storage.isLoading ? <p className="muted">{t('common.loading')}</p> : null) : (
          <>
            <section>
              <h3>{t('setup.locations')}</h3>
              {state.locations.length ? (
                <ul className="setup-list">{state.locations.map((l) => <Row key={l.id} location={l} state={state} />)}</ul>
              ) : <p className="muted">{t('setup.noLocations')}</p>}
            </section>
            <section>
              <h3>{t('setup.addTitle')}</h3>
              <AddLocation key={pick?.n ?? 0} state={state} initial={pick?.path ?? null} />
            </section>
            <Discovered state={state} onPick={(path) => setPick({ path, n: (pick?.n ?? 0) + 1 })} />
          </>
        )}
      </div>
    </Dialog>
  )
}
