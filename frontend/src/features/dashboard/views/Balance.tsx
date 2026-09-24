// Balance check: contingency heat map (grouping × confounder) with χ² / Fisher; a cell selects its items
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtInt, fmtNum } from '../../../lib'
import { token } from '../../../theme'
import { Chart, type ChartInstance, type ChartOption } from '../Chart'
import { useRunDashboard } from '../store'
import { openRef, str, unitFor, useFocusParams, usePid, useSelection, VariableSelect, ViewFrame, type ViewProps } from './common'
import { TestResult, TestSwitch, type TestMode } from './stats'

export function BalanceView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const [variable, setVariable] = useState<string | null>(null)
  const [other, setOther] = useState<string | null>(null)
  const [test, setTest] = useState<TestMode>('auto')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  useFocusParams(runId, 'balance', (p) => {
    setVariable(str(p.variable) ?? variable)
    setOther(str(p.other) ?? str(p.confounder) ?? other)
  })
  const q = useDashboardView(pid, runId, 'balance', variable && other ? { filters, variable, other, test, unit: unitFor(filters.label) } : null)
  const sel = useSelection(runId)
  const d = q.data
  const option = useMemo<ChartOption>(() => {
    if (!d) return {}
    const tb = d.table
    const max = Math.max(1, ...tb.cells.map((c) => c.n))
    return {
      grid: { left: 110, right: 70, top: 8, bottom: 50 },
      tooltip: {
        formatter: (p: { data: [number, number, number, number | null] }) =>
          `${tb.variable} = ${tb.rows[p.data[1]] ?? ''}<br/>${tb.other} = ${tb.cols[p.data[0]] ?? ''}<br/>${t('dashboard.cellN', { n: p.data[2], expected: p.data[3] != null ? fmtNum(p.data[3]) : '—' })}`,
      },
      xAxis: { type: 'category', data: tb.cols, name: tb.other, nameLocation: 'middle', nameGap: 28 },
      yAxis: { type: 'category', data: tb.rows, name: tb.variable },
      visualMap: { min: 0, max, calculable: true, right: 0, top: 'center', itemHeight: 120, textStyle: { color: token('--fg-muted') }, inRange: { color: [token('--bg-editor'), token('--cat-1')] } },
      series: [
        {
          type: 'heatmap',
          label: { show: true, color: token('--fg') },
          data: tb.cells.map((c) => [tb.cols.indexOf(c.col), tb.rows.indexOf(c.row), c.n, c.expected ?? null]),
        },
      ],
    }
  }, [d, t])
  const onCell = (p: { data?: unknown }) => {
    const [x, y] = (p.data as number[] | undefined) ?? []
    const cell = d?.table.cells.find((c) => c.col === d.table.cols[x ?? -1] && c.row === d.table.rows[y ?? -1])
    if (!cell) return
    if (cell.item_ids.length === 1) openRef({ item_id: cell.item_ids[0] ?? '', case_id: cell.case_ids[0] ?? '' })
    else sel.select(cell.item_ids)
  }
  return (
    <ViewFrame
      name={t('dashboard.view.balance')}
      query={q}
      chart={chart}
      empty={variable && other ? null : t('dashboard.pickTwo')}
      csv={() => [[d?.table.variable ?? '', d?.table.other ?? '', 'n', 'expected'], ...(d?.table.cells ?? []).map((c) => [c.row, c.col, c.n, c.expected])]}
      controls={
        <>
          <VariableSelect kind="categorical" value={variable} onChange={setVariable} label={t('dashboard.grouping')} exclude={other} />
          <VariableSelect kind="categorical" value={other} onChange={setOther} label={t('dashboard.confounder')} exclude={variable} />
          <TestSwitch value={test} onChange={setTest} />
          {d ? <span className="muted">{t('dashboard.unitSummary', { rows: fmtInt(d.unit.n_rows), cases: fmtInt(d.unit.n_cases) })}</span> : null}
        </>
      }
    >
      {d ? (
        <div className="db-stack">
          <TestResult choice={d.choice} row={d.table.result} />
          <div className="db-chart-fill">
            <Chart option={option} onReady={setChart} onClick={onCell} />
          </div>
        </div>
      ) : null}
    </ViewFrame>
  )
}
