// Measurements panel (UI-14): features of the active item from the selected run, robust z, outliers
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useFeatures, useProject, useRuns } from '../../api'
import { fmt1, fmtNum, robustZ } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'

export function MeasurementsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const runs = (useRuns(pid).data ?? []).filter((r) => r.status === 'completed' || r.status === 'completed_with_errors')
  const [runId, setRunId] = useState<string | null>(null)
  const rid = runId ?? runs[0]?.run_id ?? null
  const all = useFeatures(pid, rid).data
  const labels = useProject(pid).data?.label_map ?? []
  const [label, setLabel] = useState(2)
  const rows = useMemo(() => {
    const forLabel = (all ?? []).filter((f) => f.label === label)
    const byFeature = new Map<string, number[]>()
    for (const f of forLabel) byFeature.set(f.feature, [...(byFeature.get(f.feature) ?? []), f.value])
    return forLabel
      .filter((f) => f.item_id === iid)
      .map((f) => ({ ...f, z: robustZ(byFeature.get(f.feature) ?? [])(f.value) }))
      .sort((a, b) => a.feature.localeCompare(b.feature))
  }, [all, iid, label])

  if (!runs.length) return <div className="empty">{t('measurements.noRuns')}</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 8px', fontSize: 'var(--fs-panel)' }}>
        <span className="muted">{t('measurements.run')}</span>
        <select className="select input-sm" value={rid ?? ''} onChange={(e) => setRunId(e.target.value)}>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>{r.name}</option>
          ))}
        </select>
        <span className="muted">{t('dashboard.label')}</span>
        <select className="select input-sm" value={label} onChange={(e) => setLabel(+e.target.value)}>
          {labels.map((l) => (
            <option key={l.value} value={l.value}>{l.name}</option>
          ))}
        </select>
        <span className="mono muted" style={{ marginLeft: 'auto' }}>{iid ?? ''}</span>
      </div>
      {!iid ? <div className="empty">{t('measurements.noItem')}</div> : null}
      {iid && rows.length === 0 ? <div className="empty">{t('measurements.none')}</div> : null}
      {rows.length ? (
        <div style={{ overflow: 'auto', flex: 1 }}>
          <table className="table">
            <thead>
              <tr>
                <th>{t('dashboard.feature')}</th>
                <th className="num">{t('measurements.value')}</th>
                <th className="num">{t('dashboard.z')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const out = Math.abs(r.z) >= 3.5
                return (
                  <tr key={r.feature}>
                    <td className="mono">{r.feature}</td>
                    <td className="num">{fmtNum(r.value)}</td>
                    <td className="num" style={{ color: out ? 'var(--warn)' : undefined }}>{fmt1(r.z)}</td>
                    <td style={{ color: 'var(--warn)' }}>{out ? <Icon spec={codicon('warning')} /> : null}</td>
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
