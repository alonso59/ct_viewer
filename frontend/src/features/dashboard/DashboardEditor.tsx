// Run dashboard tab (DASHBOARD.md): QC-oriented views over one run; clicks open the item (DB-03).
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { PHASES, useCases, useFeatures, useProject, useRun, useRunErrors, type CurationStatus } from '../../api'
import { StatusBadge, fmtDuration, fmtNum, fmt1 } from '../../lib'
import { useWorkbench, type EditorProps } from '../../shell'
import { Icon, codicon, token } from '../../theme'
import { openItem } from '../explorer'
import { RUN_TONE } from '../radiomics'
import { histogram, outliers, pca2, spearman, toWide, zScores, type WideRow } from './analytics'
import { Chart, palette, type ChartInstance, type ChartOption } from './Chart'
import './dashboard.css'

export interface RunParams {
  runId: string
}
type ColorBy = 'phase' | 'group' | 'status'

function download(name: string, href: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
}
function csv(rows: (string | number)[][]) {
  return URL.createObjectURL(new Blob([rows.map((r) => r.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(',')).join('\n')], { type: 'text/csv' }))
}

function Card({ title, controls, children, chart, rows, wide }: {
  title: string
  controls?: ReactNode
  children: ReactNode
  chart?: ChartInstance
  rows?: () => (string | number)[][]
  wide?: boolean
}) {
  const { t } = useTranslation()
  return (
    <section className={`db-card card${wide ? ' db-wide' : ''}`}>
      <header className="db-card-header">
        <strong>{title}</strong>
        <div className="db-card-controls">{controls}</div>
        {chart ? (
          <button type="button" className="icon-btn" title={t('dashboard.exportPng')} aria-label={t('dashboard.exportPng')} onClick={() => download(`${title}.png`, chart.getDataURL({ pixelRatio: 2, backgroundColor: token('--bg-editor') }))}>
            <Icon spec={codicon('device-camera')} />
          </button>
        ) : null}
        {rows ? (
          <button type="button" className="icon-btn" title={t('dashboard.exportCsv')} aria-label={t('dashboard.exportCsv')} onClick={() => download(`${title}.csv`, csv(rows()))}>
            <Icon spec={codicon('export')} />
          </button>
        ) : null}
      </header>
      <div className="db-card-body">{children}</div>
    </section>
  )
}

export function DashboardEditor({ params }: EditorProps<RunParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const run = useRun(pid, params.runId)
  const feats = useFeatures(pid, params.runId)
  const errors = useRunErrors(pid, params.runId)
  const cases = useCases(pid, { showExcluded: true })
  const project = useProject(pid)
  const [label, setLabel] = useState(2)
  const [phase, setPhase] = useState('')
  const [group, setGroup] = useState('')
  const [status, setStatus] = useState<CurationStatus | ''>('')
  const [colorBy, setColorBy] = useState<ColorBy>('phase')
  const [feature, setFeature] = useState('firstorder_Mean')
  const [vsFeature, setVsFeature] = useState('firstorder_Maximum')
  const [threshold, setThreshold] = useState(3.5)
  const [charts, setCharts] = useState<Record<string, ChartInstance>>({})
  const keep = (k: string) => (c: ChartInstance) => setCharts((m) => ({ ...m, [k]: c }))

  const statusOf = useMemo(() => new Map((cases.data ?? []).map((c) => [c.case_id, c.curation_status])), [cases.data])
  const wide = useMemo(() => toWide(feats.data ?? []), [feats.data])
  const rows = useMemo(
    () =>
      wide.rows.filter(
        (r) => r.label === label && (!phase || r.phase === phase) && (!group || r.group === group) && (!status || statusOf.get(r.case_id) === status),
      ),
    [wide.rows, label, phase, group, status, statusOf],
  )
  const features = wide.features
  const groups = [...new Set(wide.rows.map((r) => r.group))]
  const cat = (r: WideRow) => (colorBy === 'phase' ? r.phase : colorBy === 'group' ? r.group : (statusOf.get(r.case_id) ?? 'not_reviewed'))
  const cats = [...new Set(rows.map(cat))].sort()
  const catName = (c: string) => (colorBy === 'status' ? t(`status.${c}`) : c)
  const open = (r: WideRow | undefined) => r && openItem(r.case_id, r.item_id, true)

  const pca = useMemo(() => pca2(zScores(rows, features)), [rows, features])
  const outl = useMemo(() => outliers(rows, features, threshold), [rows, features, threshold])
  const corrFeatures = features.filter((f) => f.startsWith('firstorder_') || f.startsWith('shape_')).slice(0, 14)
  const corr = useMemo(
    () => corrFeatures.flatMap((a, i) => corrFeatures.map((b, j) => [i, j, +spearman(rows.map((r) => r.values[a] ?? 0), rows.map((r) => r.values[b] ?? 0)).toFixed(2)])),
    [rows, corrFeatures],
  )

  if (run.isLoading || feats.isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!run.data) return <div className="error-card">{t('common.error')}</div>
  const r = run.data
  const colors = palette()
  const dur = r.started_at && r.finished_at ? (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000 : 0

  const hist = (() => {
    const all = rows.map((x) => x.values[feature]).filter((v): v is number => v !== undefined)
    const { edges, counts } = histogram(all, 12)
    const series = cats.map((c, ci) => ({
      name: catName(c),
      type: 'bar',
      stack: 'h',
      itemStyle: { color: colors[ci % colors.length] },
      data: counts.map((_, bi) => rows.filter((x) => cat(x) === c && (x.values[feature] ?? NaN) >= (edges[bi] ?? 0) && ((x.values[feature] ?? NaN) < (edges[bi + 1] ?? 0) || bi === counts.length - 1)).length),
    }))
    return {
      legend: { data: cats.map(catName) },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: edges.slice(0, -1).map((e) => fmtNum(e)), name: feature, nameLocation: 'middle', nameGap: 24 },
      yAxis: { type: 'value', name: t('dashboard.count'), minInterval: 1 },
      series,
    } as ChartOption
  })()

  const scatter = (xy: (r: WideRow, i: number) => [number, number], xName: string, yName: string): ChartOption => ({
    legend: { data: cats.map(catName) },
    tooltip: { trigger: 'item', formatter: (p: { data: [number, number, string] }) => `${p.data[2]}<br/>${xName}: ${fmtNum(p.data[0])}<br/>${yName}: ${fmtNum(p.data[1])}` },
    xAxis: { type: 'value', name: xName, nameLocation: 'middle', nameGap: 24, scale: true },
    yAxis: { type: 'value', name: yName, scale: true },
    series: cats.map((c, ci) => ({
      name: catName(c),
      type: 'scatter',
      symbolSize: 9,
      itemStyle: { color: colors[ci % colors.length], borderColor: token('--bg-editor'), borderWidth: 1 },
      data: rows.map((row, i) => [row, i] as const).filter(([row]) => cat(row) === c).map(([row, i]) => [...xy(row, i), row.item_id]),
    })),
  })
  const onScatterClick = (p: { data?: unknown }) => {
    const id = Array.isArray(p.data) ? String(p.data[2]) : ''
    open(rows.find((x) => x.item_id === id))
  }

  return (
    <div className="page db">
      <div className="db-top">
        <Icon spec={codicon('graph')} />
        <strong>{r.name}</strong>
        <span className="badge" data-tone={RUN_TONE[r.status]}>{t(`runStatus.${r.status}`)}</span>
        <span className="muted">{t('dashboard.meta', { engine: `${r.engine.name} ${r.engine.version}`, hash: r.profile_hash })}</span>
      </div>
      <div className="db-filters" role="toolbar" aria-label={t('dashboard.filters')}>
        <label>
          {t('dashboard.label')}
          <select className="select input-sm" value={label} onChange={(e) => setLabel(+e.target.value)}>
            {project.data?.label_map.filter((l) => r.selection.labels.includes(l.value)).map((l) => (
              <option key={l.value} value={l.value}>{l.name}</option>
            ))}
          </select>
        </label>
        <label>
          {t('search.phase')}
          <select className="select input-sm" value={phase} onChange={(e) => setPhase(e.target.value)}>
            <option value="">{t('search.any')}</option>
            {PHASES.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          {t('search.group')}
          <select className="select input-sm" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">{t('search.any')}</option>
            {groups.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
        </label>
        <label>
          {t('search.status')}
          <select className="select input-sm" value={status} onChange={(e) => setStatus(e.target.value as CurationStatus | '')}>
            <option value="">{t('search.any')}</option>
            {[...new Set(statusOf.values())].map((s) => (
              <option key={s} value={s}>{t(`status.${s}`)}</option>
            ))}
          </select>
        </label>
        <span className="toolbar-sep" />
        <label>
          {t('dashboard.colorBy')}
          <div className="seg" role="group">
            {(['phase', 'group', 'status'] as ColorBy[]).map((c) => (
              <button key={c} type="button" aria-pressed={colorBy === c} onClick={() => setColorBy(c)}>{t(`dashboard.by.${c}`)}</button>
            ))}
          </div>
        </label>
        <span className="muted" style={{ marginLeft: 'auto' }}>{t('dashboard.nItems', { count: rows.length })}</span>
      </div>
      <div className="db-grid">
        <Card title={t('dashboard.view.overview')} rows={() => [['item_id', 'label', 'error'], ...(errors.data ?? []).map((e) => [e.item_id, e.label, e.error])]}>
          <div className="kpis">
            <div><span className="kpi num">{r.counts.items}</span><span className="muted">{t('dashboard.kpi.items')}</span></div>
            <div><span className="kpi num" style={{ color: 'var(--ok)' }}>{r.counts.ok}</span><span className="muted">{t('dashboard.kpi.ok')}</span></div>
            <div><span className="kpi num" style={{ color: r.counts.failed ? 'var(--error)' : undefined }}>{r.counts.failed}</span><span className="muted">{t('dashboard.kpi.failed')}</span></div>
            <div><span className="kpi num">{r.counts.features}</span><span className="muted">{t('dashboard.kpi.features')}</span></div>
            <div><span className="kpi num">{dur ? fmtDuration(dur) : '—'}</span><span className="muted">{t('dashboard.kpi.runtime')}</span></div>
          </div>
          {errors.data?.length ? (
            <table className="table" style={{ marginTop: 8 }}>
              <tbody>
                {errors.data.map((e) => (
                  <tr key={e.item_id} data-clickable="true" onClick={() => openItem(e.item_id.split('.')[0] ?? '', e.item_id, true)}>
                    <td style={{ color: 'var(--error)' }}><Icon spec={codicon('error')} /></td>
                    <td className="mono">{e.item_id}</td>
                    <td className="muted" style={{ whiteSpace: 'normal' }}>{e.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </Card>
        <Card
          title={t('dashboard.view.distribution')}
          chart={charts.dist}
          rows={() => [['item_id', feature], ...rows.map((x) => [x.item_id, x.values[feature] ?? ''])]}
          controls={
            <select className="select input-sm" value={feature} onChange={(e) => setFeature(e.target.value)} aria-label={t('dashboard.feature')}>
              {features.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          }
        >
          <Chart option={hist} onReady={keep('dist')} />
        </Card>
        <Card title={t('dashboard.view.embedding', { a: fmt1(pca.explained[0] * 100), b: fmt1(pca.explained[1] * 100) })} chart={charts.pca} rows={() => [['item_id', 'pc1', 'pc2'], ...rows.map((x, i) => [x.item_id, pca.points[i]?.[0] ?? 0, pca.points[i]?.[1] ?? 0])]}>
          <Chart option={scatter((_, i) => pca.points[i] ?? [0, 0], 'PC1', 'PC2')} onClick={onScatterClick} onReady={keep('pca')} />
        </Card>
        <Card
          title={t('dashboard.view.vsVolume')}
          chart={charts.vol}
          rows={() => [['item_id', 'shape_MeshVolume', vsFeature], ...rows.map((x) => [x.item_id, x.values.shape_MeshVolume ?? '', x.values[vsFeature] ?? ''])]}
          controls={
            <select className="select input-sm" value={vsFeature} onChange={(e) => setVsFeature(e.target.value)} aria-label={t('dashboard.feature')}>
              {features.filter((f) => f !== 'shape_MeshVolume').map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          }
        >
          <Chart option={scatter((x) => [x.values.shape_MeshVolume ?? 0, x.values[vsFeature] ?? 0], 'shape_MeshVolume', vsFeature)} onClick={onScatterClick} onReady={keep('vol')} />
        </Card>
        <Card
          title={t('dashboard.view.outliers')}
          rows={() => [['item_id', 'feature', 'robust_z'], ...outl.map((o) => [o.row.item_id, o.feature, o.z.toFixed(2)])]}
          controls={
            <label className="muted" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              {t('dashboard.threshold')}
              <input className="input input-sm num" style={{ width: 64 }} type="number" step={0.5} min={1} value={threshold} onChange={(e) => setThreshold(+e.target.value || 3.5)} />
            </label>
          }
        >
          {outl.length === 0 ? <div className="empty">{t('dashboard.noOutliers')}</div> : null}
          <table className="table">
            {outl.length ? (
              <thead>
                <tr>
                  <th>{t('queue.col.item')}</th>
                  <th>{t('dashboard.feature')}</th>
                  <th className="num">{t('dashboard.z')}</th>
                  <th>{t('search.status')}</th>
                </tr>
              </thead>
            ) : null}
            <tbody>
              {outl.slice(0, 20).map((o) => (
                <tr key={o.row.key} data-clickable="true" onClick={() => open(o.row)} title={t('dashboard.openInViewer')}>
                  <td className="mono">{o.row.item_id}</td>
                  <td className="mono">{o.feature}</td>
                  <td className="num" style={{ color: Math.abs(o.z) > threshold * 2 ? 'var(--error)' : 'var(--warn)' }}>{fmt1(o.z)}</td>
                  <td><StatusBadge status={statusOf.get(o.row.case_id) ?? 'not_reviewed'} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title={t('dashboard.view.correlation')} chart={charts.corr} rows={() => [['a', 'b', 'rho'], ...corr.map(([i, j, v]) => [corrFeatures[i as number] ?? '', corrFeatures[j as number] ?? '', v ?? 0])]}>
          <Chart
            onReady={keep('corr')}
            option={{
              grid: { left: 150, right: 60, top: 8, bottom: 110 },
              tooltip: { formatter: (p: { data: [number, number, number] }) => `${corrFeatures[p.data[0]]} × ${corrFeatures[p.data[1]]}: ${p.data[2]}` },
              xAxis: { type: 'category', data: corrFeatures, axisLabel: { rotate: 60, fontSize: 10, color: token('--fg-muted') } },
              yAxis: { type: 'category', data: corrFeatures, axisLabel: { fontSize: 10, color: token('--fg-muted') } },
              visualMap: { min: -1, max: 1, calculable: true, orient: 'vertical', right: 0, top: 'center', itemHeight: 120, textStyle: { color: token('--fg-muted') }, inRange: { color: [token('--cat-1'), token('--bg-editor'), token('--cat-2')] } },
              series: [{ type: 'heatmap', data: corr }],
            }}
          />
        </Card>
      </div>
    </div>
  )
}
