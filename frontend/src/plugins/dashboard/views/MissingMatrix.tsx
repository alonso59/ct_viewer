// Missing / invalid matrix: feature × item NaN/inf/absent heat map; a cell opens its item
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtInt } from '../../../lib'
import { token } from '../../../theme'
import { Chart, type ChartInstance, type ChartOption } from '../Chart'
import { useRunDashboard } from '../store'
import { openRef, useItemMenu, usePid, ViewFrame, type ViewProps } from './common'

const KINDS = ['nan', 'inf', 'absent'] as const

export function MissingMatrixView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const q = useDashboardView(pid, runId, 'missing-matrix', { filters })
  const d = q.data
  // Only rows/columns with at least one invalid value are drawn
  const view = useMemo(() => {
    if (!d) return null
    const fIdx = [...new Set(d.cells.map((c) => c.feature))].sort((a, b) => a - b)
    const iIdx = [...new Set(d.cells.map((c) => c.item))].sort((a, b) => a - b)
    return { fIdx, iIdx }
  }, [d])
  const option = useMemo<ChartOption>(() => {
    if (!d || !view) return {}
    const fPos = new Map(view.fIdx.map((f, k) => [f, k]))
    const iPos = new Map(view.iIdx.map((i, k) => [i, k]))
    return {
      grid: { left: 180, right: 16, top: 8, bottom: 90 },
      tooltip: {
        formatter: (p: { data: [number, number, number] }) => {
          const item = d.items[view.iIdx[p.data[0]] ?? -1]
          const feat = d.features[view.fIdx[p.data[1]] ?? -1]
          return `${item?.item_id ?? ''}<br/>${feat?.feature ?? ''}: ${t(`dashboard.missing.${KINDS[p.data[2]] ?? 'nan'}`)}`
        },
      },
      xAxis: { type: 'category', data: view.iIdx.map((i) => d.items[i]?.item_id ?? ''), axisLabel: { rotate: 60, fontSize: 10 } },
      yAxis: { type: 'category', data: view.fIdx.map((f) => d.features[f]?.feature ?? ''), axisLabel: { fontSize: 10 } },
      visualMap: {
        type: 'piecewise', show: true, orient: 'horizontal', left: 'center', bottom: 0, textStyle: { color: token('--fg-muted') },
        pieces: KINDS.map((k, i) => ({ value: i, label: t(`dashboard.missing.${k}`), color: [token('--warn'), token('--error'), token('--fg-muted')][i] })),
      },
      series: [{ type: 'heatmap', data: d.cells.map((c) => [iPos.get(c.item) ?? 0, fPos.get(c.feature) ?? 0, KINDS.indexOf(c.kind)]) }],
    }
  }, [d, view, t])
  const refAt = (x: number) => {
    const it = d?.items[view?.iIdx[x] ?? -1]
    return it ? { item_id: it.item_id, case_id: it.case_id } : undefined
  }
  const nInvalid = d?.features.reduce((s, f) => s + f.n_nan + f.n_inf + f.n_absent, 0) ?? 0
  return (
    <ViewFrame
      name={t('dashboard.view.missing-matrix')}
      query={q}
      chart={nInvalid ? chart : null}
      csv={() => [['feature', 'feature_class', 'n_nan', 'n_inf', 'n_absent'], ...(d?.features ?? []).map((f) => [f.feature, f.feature_class, f.n_nan, f.n_inf, f.n_absent])]}
      controls={d ? <span className="muted">{t('dashboard.missing.summary', { values: fmtInt(nInvalid), items: fmtInt(d.n_items_total) })}</span> : null}
    >
      {d && nInvalid === 0 ? <div className="empty">{t('dashboard.missing.none')}</div> : null}
      {d && nInvalid > 0 ? (
        <Chart
          option={option}
          onReady={setChart}
          onClick={(p) => openRef(refAt((p.data as number[] | undefined)?.[0] ?? -1))}
          onContextMenu={(p, x, y) => {
            const r = refAt((p.data as number[] | undefined)?.[0] ?? -1)
            if (r) useItemMenu.getState().open(r, x, y)
          }}
        />
      ) : null}
    </ViewFrame>
  )
}
