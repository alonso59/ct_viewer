// Association: feature × continuous variable scatter with ρ, and the ranked table (ANA §Tests)
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmtInt } from '../../../lib'
import type { ChartInstance } from '../Chart'
import { useRunDashboard } from '../store'
import { asStatus, FeatureSelect, str, unitFor, useFocusParams, usePid, VariableSelect, ViewFrame, type ViewProps } from './common'
import { Scatter, type ScatterPoint } from './Scatter'
import { ResultsTable, TestResult, TestSwitch, type TestMode } from './stats'

export function AssociationView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters } = useRunDashboard(runId)
  const [variable, setVariable] = useState<string | null>(null)
  const [feature, setFeature] = useState<string | null>(null)
  const [test, setTest] = useState<TestMode>('auto')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  useFocusParams(runId, 'association', (p) => {
    setVariable(str(p.variable) ?? variable)
    setFeature(str(p.feature) ?? feature)
  })
  const q = useDashboardView(pid, runId, 'association', variable ? { filters, variable, feature, test, unit: unitFor(filters.label) } : null)
  const d = q.data
  const points = useMemo<ScatterPoint[]>(
    () =>
      (d?.points ?? []).flatMap((p) =>
        p.x == null || p.value == null ? [] : [{ item_id: p.item_id, case_id: p.case_id, x: p.x, y: p.value, level: null, note: t(`status.${asStatus(p.status)}`) }],
      ),
    [d, t],
  )
  const levelName = useMemo(() => () => '', [])
  return (
    <ViewFrame
      name={t('dashboard.view.association')}
      query={q}
      chart={chart}
      empty={variable ? null : t('dashboard.pickContinuous')}
      csv={() => [['feature', 'test', 'n', 'effect', 'p', 'q'], ...(d?.results ?? []).map((r) => [r.feature, r.test, r.n, r.effect, r.p, r.q])]}
      controls={
        <>
          <VariableSelect kind="continuous" value={variable} onChange={setVariable} label={t('dashboard.variable')} />
          <FeatureSelect runId={runId} value={d?.feature ?? feature} onChange={setFeature} />
          <TestSwitch value={test} onChange={setTest} />
          {d ? <span className="muted">{t('dashboard.unitSummary', { rows: fmtInt(d.unit.n_rows), cases: fmtInt(d.unit.n_cases) })}</span> : null}
        </>
      }
    >
      {d ? (
        <div className="db-split">
          <div className="db-split-main db-stack">
            <TestResult choice={d.choice} row={d.selected} />
            <div className="db-chart-fill">
              <Scatter runId={runId} points={points} xName={d.variable} yName={d.feature ?? ''} levelName={levelName} onReady={setChart} />
            </div>
          </div>
          <div className="db-split-side">
            <ResultsTable rows={d.results} selected={d.feature} onPick={(r) => r.feature && setFeature(r.feature)} />
          </div>
        </div>
      ) : null}
    </ViewFrame>
  )
}
