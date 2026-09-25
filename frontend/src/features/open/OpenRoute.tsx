// Open mode (SRC-09/10/12, VW-21, UI-17): one file or folder in the viewer without a project.
// Nothing is written to a project; "Create project from this" hands the path to the import wizard.
// The URL is `/open/{sid}` (AUD-A1-19): a path arrives in the history state (`navigate.ts`), is
// opened once and replaced by the session id; reload and back re-read the session, and a session
// that has ended (Close, server restart) shows the problem with its next actions (UI-18).
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate, useParams } from 'react-router'

import { api, keys, ProblemError, useAttachOpen, useOpenPath, useOpenSession, type AxisOrder, type OpenItem, type OpenSession } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { NewProjectDialog } from '../projects'
import { FolderBrowser } from '../import'
import { CtToolbar, ModalityChip, resetDisplay, StandaloneViewer } from '../viewer'
import { useViewerSync } from '../../state'
import { BrandMark, Icon, codicon } from '../../theme'
import { attachedTo, autoLabels, toItemRecord } from './model'
import { AddDialog } from './AddDialog'
import { SaveDialog } from './SaveDialog'
import { openPath, pendingPath } from './navigate'
import { useOpenDialog } from './store'
import '../import/import.css'
import './open.css'
import { useConverter } from '../../plugins/dicom/store'

const parentOf = (p: string) => p.slice(0, p.lastIndexOf('/')) || '/'

/** SRC-12: the middle slice in both orders; the user picks */
function AxisOrderDialog({ session, item, onPick, onClose }: { session: OpenSession; item: OpenItem; onPick: (o: AxisOrder) => void; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('open.axisTitle', { name: item.name })} icon={codicon('symbol-array')}>
      <p className="muted">{t('open.axisHelp')}</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {(['xyz', 'zyx'] as const).map((o) => (
          <button key={o} type="button" className="card" style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }} onClick={() => onPick(o)}>
            <img alt={t('open.axisOption', { order: o })} src={api.openPreviewUrl(session.sid, item.n, o) ?? ''} style={{ maxWidth: '100%', imageRendering: 'pixelated' }} />
            <strong className="mono">{o}</strong>
            <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t(`open.axis.${o}`)}</span>
          </button>
        ))}
      </div>
    </Dialog>
  )
}

function AttachDialog({ start, onPick, onClose, error }: { start: string; onPick: (p: string) => void; onClose: () => void; error: unknown }) {
  const { t } = useTranslation()
  const [dir, setDir] = useState<string | null>(start)
  const [file, setFile] = useState<string | null>(null)
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('open.attachTitle')}
      icon={codicon('layers')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!file} onClick={() => file && onPick(file)}>{t('open.attach')}</button>
        </>
      }
    >
      <p className="muted">{t('open.attachHelp')}</p>
      {error ? <ProblemCard error={error} /> : null}
      <FolderBrowser path={dir} onPath={setDir} selected={file} onSelectFile={setFile} />
    </Dialog>
  )
}

export default function OpenRoute() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { sid = null } = useParams()
  const location = useLocation()
  const pending = sid ? null : pendingPath(location.state)
  const opening = useOpenPath()
  const { mutate: open } = opening
  const started = useRef<string | null>(null)
  useEffect(() => {
    if (!pending || started.current === location.key) return
    started.current = location.key // once per history entry (StrictMode runs effects twice)
    open(pending, { onSuccess: (s) => navigate(`/open/${encodeURIComponent(s.sid)}`, { replace: true }) })
  }, [pending, location.key, open, navigate])
  const live = useOpenSession(sid)
  const session = live.data
  const path = session?.path ?? pending
  // `/open` with neither a session id nor a path to open: the next steps of an ended session
  const none = useMemo(() => new ProblemError(404, 'not-found', t('open.noSession'), t('open.noSessionHelp'), ['choose_another_path', 'home']), [t])
  const error = sid ? live.error : pending ? opening.error : none
  const isLoading = live.isLoading || opening.isPending
  const attach = useAttachOpen(sid ?? '')
  const [picked, setPicked] = useState<number | null>(null)
  const [orders, setOrders] = useState<Record<number, AxisOrder>>({})
  const [askOrder, setAskOrder] = useState(false)
  const [attaching, setAttaching] = useState(false)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const openDialog = useOpenDialog((s) => s.show)
  useEffect(() => resetDisplay(), [])
  const qc = useQueryClient()
  const close = async () => {
    if (session) {
      await api.closeOpen(session.sid).catch(() => undefined)
      qc.removeQueries({ queryKey: keys.open(session.sid) }) // back to this URL = an ended session
    }
    navigate('/')
  }
  // VW-05: an assumed modality the user changed travels into the import (SRC-14/15)
  const active = useViewerSync((s) => s.activeModality)
  const modality = active?.assumed ? active.value : undefined

  const items = session?.items ?? []
  const viewable = items.filter((i) => i.attached_to == null)
  const current = viewable.find((i) => i.n === picked) ?? viewable.find((i) => !i.error) ?? viewable[0]
  const order = current ? (orders[current.n] ?? current.axis_order) : null
  const needsOrder = !!current && current.format === 'npy' && !order
  const mask = current ? attachedTo(items, current.n) : null
  // VW-21: a 1-slice volume shows 2D tiles only
  const oneSlice = current?.n_slices === 1
  useEffect(() => {
    if (oneSlice) useViewerSync.setState({ layout: 'one-up-axial', maximized: null })
  }, [oneSlice])

  const onAction = {
    choose_another_path: () => openDialog(),
    open_folder: () => path && openPath(navigate, parentOf(path)),
    home: () => navigate('/'),
  }

  return (
    <div className="page">
      <div className="page-inner" style={{ maxWidth: 'none', display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
        <header className="open-title">
          <button type="button" className="btn btn-brand" onClick={() => navigate('/')} title={t('open.home')} aria-label={t('open.home')}>
            <BrandMark size={18} />
          </button>
          <h1>{t('open.title')}</h1>
          <span className="mono muted open-path" title={path ?? ''}>{path}</span>
          <span className="badge" data-tone="accent">{t('open.noProject')}</span>
        </header>
        {/* UI-17: one left-aligned action row, in workflow order, right above the viewer */}
        <div className="open-actions" role="toolbar" aria-label={t('open.actions')}>
          <button type="button" className="btn btn-primary" disabled={!path} onClick={() => setCreating(true)}>
            <Icon spec={codicon('new-folder')} />
            {t('open.createProject')}
          </button>
          <button type="button" className="btn" disabled={!current || !!current.error || current.format === 'npy'} onClick={() => setAdding(true)}>
            <Icon spec={codicon('add')} />
            {t('open.addAction')}
          </button>
          <button type="button" className="btn" disabled={!current || !!current.error || needsOrder} onClick={() => setSaving(true)}>
            <Icon spec={codicon('save')} />
            {t('open.saveAction')}
          </button>
          {items.some((i) => i.format === 'dicom') && path ? (
            <button type="button" className="btn" onClick={() => useConverter.getState().show({ source: path, pid: null })}>
              <Icon spec={codicon('file-binary')} />
              {t('open.convertAction')}
            </button>
          ) : null}
          <span className="toolbar-sep" />
          <button type="button" className="btn" disabled={!current} onClick={() => setAttaching(true)}>
            <Icon spec={codicon('layers')} />
            {t('open.attachAction')}
          </button>
          <ModalityChip />
          <span className="toolbar-sep" />
          {/* UI-24: Close drops the session and releases the volumes; nothing is deleted */}
          <button type="button" className="btn open-close-btn" onClick={() => void close()}>
            <Icon spec={codicon('close')} />
            {t('open.close')}
          </button>
        </div>
        <CtToolbar />
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {error ? <ProblemCard error={error} onAction={onAction} /> : null}
        {session ? (
          <div style={{ display: 'grid', gridTemplateColumns: '260px minmax(0, 1fr)', gap: 12, flex: 1, minHeight: 480 }}>
            <div className="fs-list" role="listbox" aria-label={t('open.items')} style={{ height: 'auto' }}>
              {viewable.map((i) => (
                <button key={i.n} type="button" className="list-row" aria-selected={i.n === current?.n} onClick={() => setPicked(i.n)} title={i.rel}>
                  <Icon spec={codicon(i.format === 'npy' ? 'symbol-array' : 'file-media')} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{i.name}</span>
                  {attachedTo(items, i.n) ? <Icon spec={codicon('layers')} style={{ marginLeft: 'auto' }} /> : null}
                  {i.error ? <Icon spec={codicon('warning')} style={{ marginLeft: 'auto' }} /> : null}
                </button>
              ))}
              {session.truncated ? <div className="muted" style={{ padding: '4px 12px' }}>{t('open.truncated')}</div> : null}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              {current?.error ? (
                <ProblemCard error={new Error(current.error)} />
              ) : current && needsOrder ? (
                <div className="error-card" role="alert">
                  <strong>{t('open.axisNeeded')}</strong>
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn" onClick={() => setAskOrder(true)}>{t('open.axisChoose')}</button>
                  </div>
                </div>
              ) : current ? (
                <StandaloneViewer
                  key={`${current.n}|${order ?? ''}|${mask?.n ?? ''}`}
                  item={toItemRecord(current, mask)}
                  imageUrl={api.openImageUrl(session.sid, current.n, order) ?? ''}
                  maskUrl={(mask ? api.openImageUrl(session.sid, mask.n, null) : null) ?? undefined}
                  labels={autoLabels()}
                  tags={current.format === 'dicom' ? () => api.openDicomTags(session.sid, current.n) : undefined}
                />
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
      {askOrder && session && current ? (
        <AxisOrderDialog
          session={session}
          item={current}
          onClose={() => setAskOrder(false)}
          onPick={(o) => {
            setOrders((s) => ({ ...s, [current.n]: o }))
            setAskOrder(false)
          }}
        />
      ) : null}
      {attaching && session && current && path ? (
        <AttachDialog
          start={session.root}
          error={attach.error}
          onClose={() => {
            setAttaching(false)
            attach.reset()
          }}
          onPick={(file) => attach.mutate({ n: current.n, file }, { onSuccess: () => setAttaching(false) })}
        />
      ) : null}
      {path ? <NewProjectDialog open={creating} onOpenChange={setCreating} prefill={{ path, modality }} /> : null}
      {saving && session && current ? <SaveDialog session={session} item={current} axisOrder={order ?? null} onClose={() => setSaving(false)} /> : null}
      {adding && session && current ? <AddDialog session={session} item={current} modality={modality} onClose={() => setAdding(false)} /> : null}
    </div>
  )
}
