import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  useImportSegmentation,
  useReindexSegmentations,
  useRemovedSegmentations,
  useRemoveSegmentation,
  useRestoreSegmentation,
  type SegmentationInfo,
} from '../../api'
import { Dialog, problemMessage } from '../../lib'
import { toast } from '../../shell'
import { codicon } from '../../theme'
import { FolderBrowser } from '../import'

function ImportDialog({ pid, itemId, initial, close }: { pid: string; itemId: string | null; initial: { segId: string; name: string }; close: () => void }) {
  const { t } = useTranslation()
  const start = useImportSegmentation(pid)
  const [path, setPath] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [segId, setSegId] = useState(initial.segId)
  const [name, setName] = useState(initial.name)
  const [template, setTemplate] = useState('{case_id}.nii.gz')
  const [mode, setMode] = useState<'auto' | 'combined' | 'binary'>('auto')
  const [error, setError] = useState<string | null>(null)
  const root = selected ?? path
  const submit = () => {
    if (!root) return
    setError(null)
    start.mutate(
      { seg_id: segId, name, root, template, mode, item_id: selected ? itemId : null },
      {
        onSuccess: (result) => {
          toast({
            message: t('layers.importStarted', { matched: result.matched, missing: result.missing }),
            tone: 'info',
          })
          close()
        },
        onError: (cause) => setError(problemMessage(cause)),
      },
    )
  }
  return (
    <Dialog
      open
      size="lg"
      onOpenChange={(open) => !open && close()}
      title={t('layers.importTitle')}
      icon={codicon('cloud-download')}
      footer={
        <>
          <button type="button" className="btn" onClick={close}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!root || !segId || start.isPending || (!!selected && !itemId)} onClick={submit}>
            {t('layers.import')}
          </button>
        </>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) minmax(240px, 1fr)', gap: 14 }}>
        <FolderBrowser
          path={path}
          selected={selected}
          onPath={(next) => { setPath(next); setSelected(null) }}
          onSelectFile={setSelected}
          fileFilter={(file) => /\.nii(?:\.gz)?$/i.test(file)}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label className="field">
            <span className="field-label">{t('layers.segId')}</span>
            <input className="input mono" value={segId} onChange={(event) => setSegId(event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} />
          </label>
          <label className="field">
            <span className="field-label">{t('layers.name')}</span>
            <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{t('layers.format')}</span>
            <select className="select" value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}>
              <option value="auto">{t('layers.formatAuto')}</option>
              <option value="combined">{t('layers.formatCombined')}</option>
              <option value="binary">{t('layers.formatBinary')}</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">{t('layers.maskTemplate')}</span>
            <input className="input mono" disabled={!!selected} value={template} onChange={(event) => setTemplate(event.target.value)} />
          </label>
          <span className="muted panel-size">{t(selected ? 'layers.singleFileHelp' : 'layers.maskTemplateHelp')}</span>
          {selected && !itemId ? <div className="error-inline" role="alert">{t('layers.noActiveItem')}</div> : null}
          {error ? <div className="error-inline" role="alert">{error}</div> : null}
        </div>
      </div>
    </Dialog>
  )
}

export function SegmentationControls({
  pid,
  sets,
  active,
  itemId,
  onRemoved,
}: {
  pid: string
  sets: SegmentationInfo[]
  active: string
  itemId: string | null
  onRemoved: (segId: string) => void
}) {
  const { t } = useTranslation()
  const removed = useRemovedSegmentations(pid).data ?? []
  const remove = useRemoveSegmentation(pid)
  const restore = useRestoreSegmentation(pid)
  const reindex = useReindexSegmentations(pid)
  const [importing, setImporting] = useState<{ segId: string; name: string } | null>(null)
  const [confirm, setConfirm] = useState<SegmentationInfo | null>(null)
  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-sm" onClick={() => setImporting({ segId: 'reviewed', name: '' })}>{t('layers.import')}</button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={reindex.isPending}
          onClick={() => reindex.mutate(undefined, {
            onSuccess: () => toast({ message: t('layers.reindexStarted'), tone: 'info' }),
            onError: (cause) => toast({ message: problemMessage(cause), tone: 'error' }),
          })}
        >
          {t('layers.reindex')}
        </button>
        {sets.some((set) => set.seg_id === active) ? (
          <button type="button" className="btn btn-sm" onClick={() => setConfirm(sets.find((set) => set.seg_id === active) ?? null)}>
            {t('layers.remove')}
          </button>
        ) : null}
      </div>
      {removed.length ? (
        <div className="field">
          <span className="field-label">{t('layers.removed')}</span>
          {removed.map((set) => (
            <div key={set.seg_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <span>{set.name || set.seg_id}</span>
              <button type="button" className="btn btn-sm" onClick={() => setImporting({ segId: set.seg_id, name: set.name })}>{t('layers.reimport')}</button>
              <button type="button" className="btn btn-sm" disabled={restore.isPending} onClick={() => restore.mutate(set.seg_id, {
                onError: (cause) => toast({ message: problemMessage(cause), tone: 'error' }),
              })}>
                {t('layers.restore')}
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {importing ? <ImportDialog pid={pid} itemId={itemId} initial={importing} close={() => setImporting(null)} /> : null}
      {confirm ? (
        <Dialog
          open
          onOpenChange={(open) => !open && setConfirm(null)}
          title={t('layers.removeTitle')}
          icon={codicon('trash')}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setConfirm(null)}>{t('common.cancel')}</button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(confirm.seg_id, {
                  onSuccess: () => {
                    onRemoved(confirm.seg_id)
                    setConfirm(null)
                  },
                  onError: (cause) => toast({ message: problemMessage(cause), tone: 'error' }),
                })}
              >
                {t('layers.remove')}
              </button>
            </>
          }
        >
          <p>{t('layers.removeHelp', { name: confirm.name || confirm.seg_id })}</p>
        </Dialog>
      ) : null}
    </>
  )
}
