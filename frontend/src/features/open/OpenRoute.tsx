// Open mode (SRC-09/10/12, VW-21, UI-17): one file or folder in the viewer without a project.
// Nothing is written to a project; "Create project from this" hands the path to the import wizard.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'

import { api, useAttachOpen, useOpenSession, type AxisOrder, type OpenItem, type OpenSession } from '../../api'
import { Dialog, ProblemCard } from '../../lib'
import { NewProjectDialog } from '../projects'
import { FolderBrowser } from '../import'
import { StandaloneViewer } from '../viewer'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { attachedTo, autoLabels, toItemRecord } from './model'
import { useOpenDialog } from './store'
import '../import/import.css'

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
  const [sp] = useSearchParams()
  const path = sp.get('path')
  const { data: session, error, isLoading } = useOpenSession(path)
  const attach = useAttachOpen(path ?? '')
  const [picked, setPicked] = useState<number | null>(null)
  const [orders, setOrders] = useState<Record<number, AxisOrder>>({})
  const [askOrder, setAskOrder] = useState(false)
  const [attaching, setAttaching] = useState(false)
  const [creating, setCreating] = useState(false)
  const openDialog = useOpenDialog((s) => s.show)

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
    open_folder: () => path && navigate(`/open?path=${encodeURIComponent(parentOf(path))}`),
  }

  return (
    <div className="page">
      <div className="page-inner" style={{ maxWidth: 'none', display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
        <header style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button type="button" className="btn" onClick={() => navigate('/')} title={t('open.home')}>
            <Icon spec={codicon('home')} />
          </button>
          <h1 style={{ margin: 0, fontSize: 'var(--fs-title)' }}>{t('open.title')}</h1>
          <span className="mono muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={path ?? ''}>{path}</span>
          <span style={{ flex: 1 }} />
          <span className="badge" data-tone="accent">{t('open.noProject')}</span>
          <button type="button" className="btn" disabled={!current || current.kind === 'label'} onClick={() => setAttaching(true)}>
            <Icon spec={codicon('layers')} />
            {t('open.attachAction')}
          </button>
          <button type="button" className="btn btn-primary" disabled={!path} onClick={() => setCreating(true)}>
            <Icon spec={codicon('new-folder')} />
            {t('open.createProject')}
          </button>
        </header>
        {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
        {error ? <ProblemCard error={error} onAction={onAction} /> : null}
        {session ? (
          <div style={{ display: 'grid', gridTemplateColumns: '260px minmax(0, 1fr)', gap: 12, flex: 1, minHeight: 480 }}>
            <div className="fs-list" role="listbox" aria-label={t('open.items')} style={{ height: 'auto' }}>
              {viewable.map((i) => (
                <button key={i.n} type="button" className="list-row" aria-selected={i.n === current?.n} onClick={() => setPicked(i.n)} title={i.rel}>
                  <Icon spec={codicon(i.kind === 'label' ? 'symbol-color' : i.format === 'npy' ? 'symbol-array' : 'file-media')} />
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
                  maskUrl={(mask ? api.openImageUrl(session.sid, mask.n, mask.axis_order) : current.kind === 'label' ? api.openImageUrl(session.sid, current.n, order) : null) ?? undefined}
                  labels={autoLabels()}
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
          onPick={(file) => attach.mutate({ sid: session.sid, n: current.n, file }, { onSuccess: () => setAttaching(false) })}
        />
      ) : null}
      {path ? <NewProjectDialog open={creating} onOpenChange={setCreating} prefill={{ path }} /> : null}
    </div>
  )
}
