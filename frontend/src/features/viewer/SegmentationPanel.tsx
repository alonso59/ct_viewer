import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useProject, useSegmentations, useSetSegmentationLabelActive, type LabelDef } from '../../api'
import { Dialog, ProblemCard, problemMessage } from '../../lib'
import { openEditor, toast, useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { autoLabelColor, codicon } from '../../theme'
import { setLabels } from './model/labels'
import { SegmentationControls } from './SegmentationControls'

export default function SegmentationPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((state) => state.pid) ?? ''
  const project = useProject(pid)
  const query = useSegmentations(pid)
  const sets = query.data ?? []
  const viewer = useViewerSync()
  const preferred = viewer.segChoice[pid] ?? project.data?.default_seg
  const selected = sets.find((set) => set.seg_id === preferred) ?? sets[0]
  const change = useSetSegmentationLabelActive(pid)
  const [search, setSearch] = useState('')
  const [confirm, setConfirm] = useState<{ segId: string; setName: string; label: LabelDef } | null>(null)
  const values = Object.keys(selected?.label_mapping ?? {})
  const labels = setLabels(project.data?.label_map ?? [], selected?.label_mapping).filter((label) => label.value > 0 && (!values.length || values.includes(String(label.value))))
  for (const value of selected?.removed_labels ?? []) {
    if (!labels.some((label) => label.value === value)) labels.push({ value, name: `label_${value}`, color: autoLabelColor(value), opacity: 0.2, visible: true })
  }
  const shown = labels.filter((label) => `${label.name} ${label.value}`.toLowerCase().includes(search.toLowerCase()))
  const error = project.error ?? query.error
  if (error) return <ProblemCard error={error} />
  return (
    <div className="segmentation-panel">
      <h2>{t('segmentation.title')}</h2>
      <p className="muted">{t('segmentation.help')}</p>
      <label className="field">
        <span className="field-label">{t('layers.segSet')}</span>
        <select className="select" value={selected?.seg_id ?? ''} disabled={!sets.length} onChange={(event) => viewer.set({ segChoice: { ...viewer.segChoice, [pid]: event.target.value } })}>
          {sets.map((set) => <option key={set.seg_id} value={set.seg_id}>{t('layers.segOption', { name: set.name || set.seg_id, n: set.n_items })}</option>)}
        </select>
      </label>
      <SegmentationControls pid={pid} sets={sets} active={selected?.seg_id ?? ''} itemId={viewer.activeItemId} onRemoved={() => viewer.set({ shownSeg: null })} />
      <button type="button" className="btn" onClick={() => openEditor('settings', { tab: 'labels' })}>{t('segmentation.catalog')}</button>
      <label className="field">
        <span className="field-label">{t('segmentation.search')}</span>
        <input className="input" value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <div className="segmentation-labels">
        <table className="segmentation-table">
          <thead><tr><th>{t('labels.value')}</th><th>{t('labels.name')}</th><th>{t('segmentation.status')}</th><th>{t('psettings.actions')}</th></tr></thead>
          <tbody>{shown.map((label) => {
            const removed = selected?.removed_labels?.includes(label.value) ?? false
            return (
              <tr key={label.value}>
                <td className="num">{label.value}</td>
                <td><span className="dot" style={{ background: label.color }} /> {label.name}</td>
                <td>{t(removed ? 'segmentation.removed' : 'segmentation.active')}</td>
                <td><button type="button" className="btn btn-sm" disabled={change.isPending || !selected} aria-label={t(removed ? 'segmentation.restoreLabel' : 'segmentation.removeLabel', { name: label.name })} onClick={() => {
                  if (!selected) return
                  if (!removed) return setConfirm({ segId: selected.seg_id, setName: selected.name || selected.seg_id, label })
                  change.mutate({ segId: selected.seg_id, label: label.value, active: true }, { onError: (cause) => toast({ message: problemMessage(cause), tone: 'error' }) })
                }}>{t(removed ? 'layers.restore' : 'layers.remove')}</button></td>
              </tr>
            )
          })}</tbody>
        </table>
        {!shown.length ? <p className="muted">{t('segmentation.noLabels')}</p> : null}
      </div>
      {confirm ? (
        <Dialog open title={t('segmentation.removeTitle')} icon={codicon('trash')} onOpenChange={(open) => !open && !change.isPending && setConfirm(null)} footer={
          <>
            <button type="button" className="btn" disabled={change.isPending} onClick={() => setConfirm(null)}>{t('common.cancel')}</button>
            <button type="button" className="btn btn-danger" disabled={change.isPending} onClick={() => change.mutate({ segId: confirm.segId, label: confirm.label.value, active: false }, {
              onSuccess: () => setConfirm(null),
              onError: (cause) => toast({ message: problemMessage(cause), tone: 'error' }),
            })}>{t('layers.remove')}</button>
          </>
        }>
          <p>{t('segmentation.removeHelp', { name: confirm.label.name, set: confirm.setName })}</p>
        </Dialog>
      ) : null}
    </div>
  )
}
