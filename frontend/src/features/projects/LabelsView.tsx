// Labels view (QuPath Classes list): project label map, editable (PRJ-07); hotkeys 1–9 toggle visibility
import { useTranslation } from 'react-i18next'

import { useProject, useUpdateLabels, type LabelDef } from '../../api'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

export function LabelsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const project = useProject(pid).data
  const update = useUpdateLabels(pid)
  const vis = useViewerSync((s) => s.labelVisibility)
  const toggle = useViewerSync((s) => s.toggleLabel)
  const labels = project?.label_map ?? []
  const edit = (value: number, patch: Partial<LabelDef>) => update.mutate(labels.map((l) => (l.value === value ? { ...l, ...patch } : l)))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '0 8px 12px' }}>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)', padding: '0 4px 6px' }}>{t('labels.help')}</div>
      {labels.map((l, i) => (
        <div key={l.value} className="label-row">
          <input type="checkbox" aria-label={t('labels.visible', { name: l.name })} checked={vis[l.value] ?? l.visible} onChange={() => toggle(l.value, l.visible)} />
          <input type="color" className="label-swatch" aria-label={t('labels.color', { name: l.name })} value={l.color} onChange={(e) => edit(l.value, { color: e.target.value.toUpperCase() })} />
          <input className="input input-sm" aria-label={t('labels.name')} value={l.name} onChange={(e) => edit(l.value, { name: e.target.value })} />
          <span className="muted num" title={t('labels.value')}>{l.value}</span>
          <kbd className="key" title={t('labels.hotkey')}>{i + 1}</kbd>
        </div>
      ))}
      <div className="muted" style={{ fontSize: 'var(--fs-badge)', padding: '8px 4px 0' }}>{t('labels.defaultsNote')}</div>
    </div>
  )
}
