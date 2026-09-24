// Measurements panel (UI-14): features of the active item from the selected run (API-36 `item_id`),
// with a robust z against the run's items of the same label; |z| ≥ 3.5 is marked as an outlier.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useFeatures, useProject, useRuns } from '../../api'
import { fmt1, fmtNum, robustZ } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import '../../i18n/lazy'

const OUTLIER_Z = 3.5

export function MeasurementsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const runs = (useRuns(pid).data ?? []).filter((r) => r.status === 'completed' || r.status === 'completed_with_errors')
  const [runId, setRunId] = useState<string | null>(null)
  const run = runs.find((r) => r.run_id === runId) ?? runs[0]
  const rid = run?.run_id ?? null
  const mine = useFeatures(pid, rid, iid)
  // Without an item the hook's key equals the full-run query's, so its cached rows must be ignored
  const itemRows = iid ? mine.data : undefined
  const all = useFeatures(pid, rid).data
  const labels = useProject(pid).data?.label_map ?? []
  const runLabels = labels.filter((l) => !run || run.selection.labels.includes(l.value))
  const [wantedLabel, setLabel] = useState<number | null>(null)
  const labelOfItem = (itemRows ?? []).map((f) => f.label)
  const label = wantedLabel ?? runLabels.find((l) => labelOfItem.includes(l.value))?.value ?? runLabels[0]?.value ?? null
  // Per-feature values of the run for this label (population for the robust z)
  const population = new Map<string, number[]>()
  for (const f of all ?? []) {
    if (f.label !== label || f.value === null) continue
    const list = population.get(f.feature)
    if (list) list.push(f.value)
    else population.set(f.feature, [f.value])
  }
  const rows = (itemRows ?? [])
    .filter((f) => f.label === label)
    .map((f) => ({ ...f, z: f.value === null ? null : robustZ(population.get(f.feature) ?? [])(f.value) }))
    .sort((a, b) => a.feature.localeCompare(b.feature))

  if (!runs.length) return <div className="empty">{t('measurements.noRuns')}</div>
  const nOut = rows.filter((r) => r.z !== null && Math.abs(r.z) >= OUTLIER_Z).length
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 8px', fontSize: 'var(--fs-panel)' }}>
        <span className="muted">{t('measurements.run')}</span>
        <select className="select input-sm" value={rid ?? ''} onChange={(e) => setRunId(e.target.value)} aria-label={t('measurements.run')}>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>{r.name}</option>
          ))}
        </select>
        <span className="muted">{t('dashboard.label')}</span>
        <select className="select input-sm" value={label ?? ''} onChange={(e) => setLabel(+e.target.value)} aria-label={t('dashboard.label')}>
          {runLabels.map((l) => (
            <option key={l.value} value={l.value}>{l.name}</option>
          ))}
        </select>
        {nOut ? <span className="badge" data-tone="warn">{t('measurements.outliers', { count: nOut })}</span> : null}
        <span className="mono muted" style={{ marginLeft: 'auto' }}>{iid ?? ''}</span>
      </div>
      {!iid ? <div className="empty">{t('measurements.noItem')}</div> : null}
      {iid && mine.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {iid && mine.error ? <div className="error-card">{t('common.error')}</div> : null}
      {iid && itemRows && rows.length === 0 ? <div className="empty">{t('measurements.none')}</div> : null}
      {rows.length ? (
        <div style={{ overflow: 'auto', flex: 1 }}>
          <table className="table" aria-label={t('panel.measurements')}>
            <thead>
              <tr>
                <th>{t('dashboard.feature')}</th>
                <th>{t('measurements.class')}</th>
                <th className="num">{t('measurements.value')}</th>
                <th className="num">{t('dashboard.z')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const out = r.z !== null && Math.abs(r.z) >= OUTLIER_Z
                return (
                  <tr key={r.feature}>
                    <td className="mono">{r.feature.replace(/^original_/, '')}</td>
                    <td className="muted">{r.feature_class}</td>
                    <td className="num">{r.value === null ? t('measurements.invalid') : fmtNum(r.value)}</td>
                    <td className="num" style={{ color: out ? 'var(--warn)' : undefined }}>{r.z === null ? '—' : fmt1(r.z)}</td>
                    <td style={{ color: 'var(--warn)' }}>{out ? <Icon spec={codicon('warning')} title={t('measurements.outlier')} /> : null}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
