// Embedding scatter: PCA (default) or UMAP on z-scored features, coloured by the colour variable
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDashboardView } from '../../../api'
import { fmt1 } from '../../../lib'
import type { ChartInstance } from '../Chart'
import { useRunDashboard } from '../store'
import { asStatus, useLevelName, usePid, ViewFrame, type ViewProps } from './common'
import { Scatter, type ScatterPoint } from './Scatter'

export function EmbeddingView({ runId }: ViewProps) {
  const { t } = useTranslation()
  const pid = usePid()
  const { filters, colorBy } = useRunDashboard(runId)
  const [method, setMethod] = useState<'pca' | 'umap'>('pca')
  const [chart, setChart] = useState<ChartInstance | null>(null)
  const q = useDashboardView(pid, runId, 'embedding', { filters, method, color_by: colorBy })
  const levelName = useLevelName(colorBy)
  const d = q.data
  const points = useMemo<ScatterPoint[]>(
    () =>
      (d?.points ?? []).map((p) => ({
        item_id: p.item_id, case_id: p.case_id, x: p.coords[0] ?? 0, y: p.coords[1] ?? 0, level: p.color ?? null,
        note: t(`status.${asStatus(p.status)}`),
      })),
    [d, t],
  )
  const ev = d?.explained_variance_ratio ?? []
  const axis = (i: number) => (d?.method === 'umap' ? `UMAP${i + 1}` : t('dashboard.pc', { n: i + 1, pct: fmt1((ev[i] ?? 0) * 100) }))
  return (
    <ViewFrame
      name={t('dashboard.view.embedding')}
      query={q}
      chart={chart}
      csv={() => [['item_id', 'case_id', 'label', 'color', 'dim1', 'dim2'], ...(d?.points ?? []).map((p) => [p.item_id, p.case_id, p.label, p.color, p.coords[0], p.coords[1]])]}
      controls={
        <>
          <div className="seg" role="group" aria-label={t('dashboard.method')}>
            {(['pca', 'umap'] as const).map((m) => (
              <button key={m} type="button" aria-pressed={method === m} onClick={() => setMethod(m)}>{t(`dashboard.embed.${m}`)}</button>
            ))}
          </div>
          {d ? <span className="muted">{t('dashboard.featuresUsed', { count: d.features_used.length })}</span> : null}
        </>
      }
    >
      <Scatter runId={runId} points={points} xName={axis(0)} yName={axis(1)} levelName={levelName} onReady={setChart} />
    </ViewFrame>
  )
}
