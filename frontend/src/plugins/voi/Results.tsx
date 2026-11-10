// What a `voi.extract` run wrote, as a read-only snapshot that stays usable at any size: the run's
// settings and folder, a summary whose counts are also the filters, and pages of 50 scans or
// cases. A row opens to its crops' previews, so a page never loads fifty images at once.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, isTaskRunPending, keys, useVoiRunResults, type TaskRunStatus, type VoiResult, type VoiResultsQuery, type VoiScanRow, type VoiSummary } from '../../api'
import { Button, ItemName, ProblemCard, RadioSeg, fmt1, parseItemId } from '../../lib'
import { toast } from '../../shell'
import { boxMode, effectiveBox, fmtSize, regionOf, resampleOf, WARNING_CODES, type Values } from './model'
import { SideConfidence } from './ScanCard'
import './voi.css'

const PAGE = 50
/** A run with this many scans per case or more is browsed by case first */
const SCANS_PER_CASE = 5
const KNOWN = new Set<string>(WARNING_CODES)
type Confidence = NonNullable<VoiResultsQuery['confidence']>
const CONFIDENCES: Confidence[] = ['verified', 'probable', 'uncertain', 'reviewer']

interface Nav {
  /** null = by the run's shape */
  view: 'scans' | 'cases' | null
  q: string
  confidence: Confidence | null
  review: boolean
  warning: string
  case: string | null
  offset: number
}

const START: Nav = { view: null, q: '', confidence: null, review: false, warning: '', case: null, offset: 0 }

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

const autoView = (s: VoiSummary | undefined): 'scans' | 'cases' => (s && s.n_cases > 0 && s.n_scans / s.n_cases >= SCANS_PER_CASE ? 'cases' : 'scans')
const n0 = (n: number) => n.toLocaleString()

function Crop({ pid, runId, r }: { pid: string; runId: string; r: VoiResult }) {
  const { t } = useTranslation()
  const src = api.voiResultPreviewUrl(pid, runId, r.n)
  const side = r.side ? t(`voi.side.${r.side}`) : t('voi.single')
  return (
    <li className="voi-result">
      <div className="voi-result-thumb">{src ? <img src={src} alt={t('voi.resultAlt', { side })} loading="lazy" /> : <span className="muted">{t('voi.noPreview')}</span>}</div>
      <div className="voi-meta">
        <div className="voi-cand-head">
          {r.side ? <span className={`voi-side voi-side-${r.side}`}>{r.side}</span> : null}
          <strong>{side}</strong>
          {r.side ? <SideConfidence level={r.side_confidence} /> : null}
        </div>
        <dl className="voi-metrics">
          <dt>{t('voi.metric.crop')}</dt>
          <dd>{fmtSize(r.crop_size_mm)}</dd>
          <dt>{t('voi.metric.voxels')}</dt>
          <dd>{t('voi.voxelLine', { shape: r.shape.join(' × '), mm: r.spacing.map((s) => fmt1(s)).join(' × ') })}</dd>
          <dt>{t('voi.metric.volume')}</dt>
          <dd>{t('voi.ml', { v: fmt1(r.volume_ml) })}</dd>
          <dt>{t('voi.metric.files')}</dt>
          <dd className="voi-files mono">
            <span title={r.image}>{r.image.split('/').pop()}</span>
            <span title={r.mask}>{r.mask.split('/').pop()}</span>
          </dd>
        </dl>
        {r.warnings.length ? (
          <ul className="voi-warnings">
            {r.warnings.map((w) => (
              <li key={w} className="voi-warn">
                <span className="codicon codicon-warning" aria-hidden />
                {KNOWN.has(w) ? t(`voi.warn.${w}`) : w}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  )
}

function ScanRow({ pid, runId, scan, numbered }: { pid: string; runId: string; scan: VoiScanRow; numbered: boolean }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const warned = scan.vois.reduce((n, v) => n + v.warnings.length, 0)
  return (
    <li className="voi-row">
      <button type="button" className="voi-row-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className={`codicon codicon-chevron-${open ? 'down' : 'right'}`} aria-hidden />
        <ItemName id={scan.item_id} phase={scan.phase} pid={pid} />
        {numbered ? <span className="muted">{t('voi.res.scanNo', { n: parseItemId(scan.item_id)?.scan_idx ?? '' })}</span> : null}
        <span className="voi-row-vois">
          {scan.vois.map((v) => (
            <span key={v.n} className="voi-row-voi">
              {v.side ? <span className={`voi-side voi-side-${v.side}`}>{v.side}</span> : null}
              {v.side ? <SideConfidence level={v.side_confidence} /> : null}
            </span>
          ))}
        </span>
        {warned ? (
          <span className="voi-warn">
            <span className="codicon codicon-warning" aria-hidden />
            {t('voi.res.warnings', { count: warned })}
          </span>
        ) : null}
      </button>
      {open ? (
        <ul className="voi-result-list">
          {scan.vois.map((v) => (
            <Crop key={v.n} pid={pid} runId={runId} r={v} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function Inner({ pid, runId }: { pid: string; runId: string }) {
  const { t } = useTranslation()
  const [nav, setNav] = useState<Nav>(START)
  const q = useDebounced(nav.q)
  // the whole run's summary, unfiltered; also decides how the run is browsed first
  const head = useVoiRunResults(pid, runId, { view: 'cases', offset: 0, limit: 1 })
  const summary = head.data?.summary
  const view = nav.case ? 'scans' : (nav.view ?? autoView(summary))
  const query: VoiResultsQuery = {
    view,
    offset: nav.offset,
    limit: PAGE,
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(nav.confidence ? { confidence: nav.confidence } : {}),
    ...(nav.review ? { review: true } : {}),
    ...(nav.warning ? { warning: nav.warning } : {}),
    ...(nav.case ? { case: nav.case } : {}),
  }
  const page = useVoiRunResults(pid, runId, query)
  const data = page.data ?? head.data
  const pending = isTaskRunPending(data?.status as TaskRunStatus | undefined)
  const qc = useQueryClient()
  const status = data?.status
  useEffect(() => {
    // the run list's counts are read once; refresh them when the shown run ends
    if (status && !isTaskRunPending(status as TaskRunStatus)) void qc.invalidateQueries({ queryKey: keys.taskRuns(pid) })
  }, [status, pid, qc])
  const copy = (text: string) => {
    const ok = () => toast({ message: t('voi.copied'), tone: 'ok' })
    if (navigator.clipboard) void navigator.clipboard.writeText(text).then(ok, () => undefined)
  }
  const go = (patch: Partial<Nav>) => setNav((s) => ({ ...s, offset: 0, ...patch }))
  const filtered = !!(nav.confidence || nav.review || nav.warning || nav.q.trim())
  const chip = (id: string, label: string, count: number | undefined, on: boolean, patch: Partial<Nav>) => (
    <button key={id} type="button" className="voi-chip" aria-pressed={on} onClick={() => go(patch)}>
      {label}
      {count !== undefined ? <span className="muted">{n0(count)}</span> : null}
    </button>
  )
  const settings = (data?.settings ?? {}) as Values
  const labels = Array.isArray(settings.labels) ? (settings.labels as string[]).join(', ') : t('voi.labelsOfRegion')
  const box = effectiveBox(settings, undefined)
  const total = page.data?.total ?? 0
  const from = total ? nav.offset + 1 : 0
  const to = Math.min(nav.offset + PAGE, total)
  const none = !!summary && summary.n_vois === 0
  const pager =
    total > PAGE ? (
      <div className="voi-pager">
        <span className="muted">{t('voi.res.range', { from: n0(from), to: n0(to), total: n0(total) })}</span>
        <Button className="btn btn-sm" disabled={nav.offset === 0} onClick={() => setNav((s) => ({ ...s, offset: Math.max(0, s.offset - PAGE) }))}>
          {t('voi.prev')}
        </Button>
        <Button className="btn btn-sm" disabled={to >= total} onClick={() => setNav((s) => ({ ...s, offset: s.offset + PAGE }))}>
          {t('voi.next')}
        </Button>
      </div>
    ) : null
  return (
    <div className="voi-results">
      {data ? (
        <dl className="voi-metrics voi-run-settings">
          <dt>{t('voi.region')}</dt>
          <dd>{t(`voi.regions.${regionOf(settings)}`)}</dd>
          <dt>{t('voi.labels')}</dt>
          <dd>{labels}</dd>
          <dt>{t('voi.box')}</dt>
          <dd>{boxMode(settings) === 'recommended' ? t('voi.boxMode.recommended') : t('voi.boxLine', { size: fmtSize(box.size), margin: box.margin })}</dd>
          <dt>{t('voi.resample')}</dt>
          <dd>{resampleOf(settings) ? `${resampleOf(settings)} mm` : t('voi.native')}</dd>
        </dl>
      ) : null}
      {data?.output_dir ? (
        <div className="voi-folder">
          <span className="muted">{t('voi.folder')}</span>
          <code className="mono voi-path" title={data.output_dir}>
            {data.output_dir}
          </code>
          <Button className="btn btn-sm" onClick={() => copy(data.output_dir ?? '')}>
            {t('voi.copyPath')}
          </Button>
        </div>
      ) : null}
      {head.error || page.error ? <ProblemCard error={page.error ?? head.error} /> : null}
      {pending ? <p className="muted">{t('voi.running')}</p> : null}
      {none && !pending ? <p className="muted">{t('voi.noResults')}</p> : null}
      {summary && summary.n_vois > 0 ? (
        <>
          <p className="voi-summary">
            <span>
              {[
                t('voi.res.nCases', { count: summary.n_cases, num: n0(summary.n_cases) }),
                t('voi.res.nScans', { count: summary.n_scans, num: n0(summary.n_scans) }),
                t('voi.res.nVois', { count: summary.n_vois, num: n0(summary.n_vois) }),
              ].join(' · ')}
            </span>
          </p>
          <div className="voi-chips" role="group" aria-label={t('voi.res.filter')}>
            {chip('all', t('voi.res.all'), summary.n_vois, !nav.confidence && !nav.review, { confidence: null, review: false })}
            {CONFIDENCES.map((c) => (summary.by_confidence[c] ? chip(c, t(`voi.conf.${c}`), summary.by_confidence[c], nav.confidence === c, { confidence: c, review: false }) : null))}
            {chip('review', t('voi.res.review'), summary.n_review, nav.review, { review: true, confidence: null })}
          </div>
          <div className="voi-toolbar">
            {nav.case ? (
              <span className="voi-crumb">
                <Button className="btn btn-sm" onClick={() => go({ case: null, view: 'cases' })}>
                  {t('voi.res.allCases')}
                </Button>
                <span className="codicon codicon-chevron-right muted" aria-hidden />
                <strong>{nav.case}</strong>
              </span>
            ) : (
              <RadioSeg
                label={t('voi.res.view')}
                value={view}
                onChange={(v) => go({ view: v })}
                options={[
                  { value: 'scans', label: t('voi.res.scans') },
                  { value: 'cases', label: t('voi.res.cases') },
                ]}
              />
            )}
            <input className="input input-sm voi-search" type="search" placeholder={t('voi.res.search')} aria-label={t('voi.res.search')} value={nav.q} onChange={(e) => go({ q: e.target.value })} />
            <select className="select input-sm" aria-label={t('voi.res.warning')} value={nav.warning} onChange={(e) => go({ warning: e.target.value })}>
              <option value="">{t('voi.res.anyWarning')}</option>
              {WARNING_CODES.map((w) => (
                <option key={w} value={w}>
                  {t(`voi.warn.${w}`)}
                </option>
              ))}
            </select>
            {filtered ? (
              <Button className="btn btn-sm" onClick={() => setNav({ ...START, view: nav.view, case: nav.case })}>
                {t('voi.res.clear')}
              </Button>
            ) : null}
          </div>
          {page.data && !total ? <p className="muted">{t('voi.res.noMatch')}</p> : null}
          {pager}
          {page.data?.view === 'cases' && page.data.cases.length ? (
            <ul className="voi-rows">
              {page.data.cases.map((c) => (
                <li key={c.case_id} className="voi-row">
                  <button type="button" className="voi-row-head" onClick={() => go({ case: c.case_id, view: 'scans' })}>
                    <span className="codicon codicon-chevron-right" aria-hidden />
                    <strong className="truncate">{c.case_id}</strong>
                    <span className="muted">{[t('voi.res.nScans', { count: c.n_scans, num: n0(c.n_scans) }), t('voi.res.nVois', { count: c.n_vois, num: n0(c.n_vois) })].join(' · ')}</span>
                    {c.n_review ? <span className="voi-warn">{t('voi.res.needReview', { count: c.n_review })}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {page.data?.view === 'scans' && page.data.scans.length ? (
            <ul className="voi-rows">
              {page.data.scans.map((s) => (
                <ScanRow key={s.item_id} pid={pid} runId={runId} scan={s} numbered={!!nav.case} />
              ))}
            </ul>
          ) : null}
          {pager}
        </>
      ) : null}
    </div>
  )
}

export default function VoiResults({ pid, runId }: { pid: string; runId: string }) {
  // another run starts from its own summary and filters
  return <Inner key={runId} pid={pid} runId={runId} />
}
