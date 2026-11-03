import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, CURATION_STATUSES, QUEUE_STATUSES, ReviewerCancelled, useCurationExports, useImportV2, useProject, useQueue, useSegmentations, type CurationStatus, type QueueRow, type V2ImportReport } from '../../api'
import { Dialog, ItemName, PhaseChip, StatusBadge, fmtAgo, midEllipsis, problemMessage, useRowKeys } from '../../lib'
import { toast, useWorkbench, toastProblem } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openInContext } from '../../features/explorer'
import { targetName } from './model'
import '../../i18n/lazy'

function download(name: string, blob: Blob) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

/** Copy to the clipboard; plain-http hosts have no clipboard API, so show the text instead */
async function copy(text: string, t: (k: string, o?: Record<string, unknown>) => string) {
  try {
    await navigator.clipboard.writeText(text)
    toast({ message: t('queue.copied'), tone: 'ok' })
  } catch {
    toast({ message: t('queue.copyManual', { text }) })
  }
}

function PathCell({ path }: { path: string | null }) {
  const { t } = useTranslation()
  if (!path) return <span className="muted">{t('queue.noPath')}</span>
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, maxWidth: 320 }}>
      {/* middle ellipsis, so the root and the file name stay readable */}
      <span className="mono muted truncate" title={path}>
        {midEllipsis(path, 44)}
      </span>
      <button
        type="button"
        className="icon-btn"
        aria-label={t('queue.copyPath')}
        title={t('queue.copyPath')}
        onClick={(e) => {
          e.stopPropagation()
          void copy(path, t)
        }}
      >
        <Icon spec={codicon('copy')} />
      </button>
    </span>
  )
}

const PRIORITY_RANK: Record<string, number> = { low: 0, medium: 1, high: 2 }
/** Sortable columns and the value each sorts by; the reviewer column sorts by time */
const SORT_BY = {
  case: (r: QueueRow) => r.case_id,
  item: (r: QueueRow) => r.item_id,
  phase: (r: QueueRow) => r.phase ?? '',
  target: (r: QueueRow) => r.target,
  set: (r: QueueRow) => r.seg_id ?? '',
  status: (r: QueueRow) => CURATION_STATUSES.indexOf(r.status),
  priority: (r: QueueRow) => PRIORITY_RANK[r.priority] ?? 0,
  comment: (r: QueueRow) => r.comment ?? '',
  reviewer: (r: QueueRow) => r.at,
  image: (r: QueueRow) => r.image_path_abs ?? '',
  mask: (r: QueueRow) => r.mask_path_abs ?? '',
} satisfies Record<string, (r: QueueRow) => string | number>
type SortCol = keyof typeof SORT_BY
type Sort = { col: SortCol; dir: 'ascending' | 'descending' } | null

function sorted(rows: QueueRow[], sort: Sort): QueueRow[] {
  if (!sort) return rows
  const by = SORT_BY[sort.col]
  const sign = sort.dir === 'ascending' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = by(a)
    const y = by(b)
    return sign * (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y)))
  })
}

function ImportReport({ report, onClose }: { report: V2ImportReport; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('queue.importV2Title')}
      icon={codicon('cloud-upload')}
      footer={<button type="button" className="btn btn-primary" onClick={onClose}>{t('common.close')}</button>}
    >
      <p>{t('queue.importV2Summary', { imported: report.imported, rows: report.n_rows, skipped: report.skipped.length })}</p>
      {report.skipped.length ? (
        <div style={{ maxHeight: 280, overflow: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                <th className="num">{t('queue.col.line')}</th>
                <th>{t('queue.col.reviewId')}</th>
                <th>{t('queue.col.reason')}</th>
              </tr>
            </thead>
            <tbody>
              {report.skipped.map((s) => (
                <tr key={s.line}>
                  <td className="num">{s.line}</td>
                  <td className="mono muted">{s.review_id ?? ''}</td>
                  <td className="ws-normal">{s.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Dialog>
  )
}

export function QueueEditor() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading, isError, error } = useQueue(pid)
  const exportsM = useCurationExports(pid)
  const importM = useImportV2(pid)
  const fileRef = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<V2ImportReport | null>(null)
  const [status, setStatus] = useState<CurationStatus | ''>('')
  const [busyCsv, setBusyCsv] = useState(false)
  const [sort, setSort] = useState<Sort>(null)
  const rows = sorted((data ?? []).filter((r) => !status || r.status === status), sort)
  const sortBy = (col: SortCol) => setSort((s) => ({ col, dir: s?.col === col && s.dir === 'ascending' ? 'descending' : 'ascending' }))
  const labels = useProject(pid).data?.label_map ?? []
  const sets = useSegmentations(pid).data ?? []
  const rowId = (r: (typeof rows)[number]) => `${r.item_id}|${r.target}|${r.seg_id ?? ''}`
  const rowKeys = useRowKeys(rows.map(rowId))

  /** The whole queue, or with `only` the rows the status filter shows */
  const exportCsv = async (only?: CurationStatus) => {
    setBusyCsv(true)
    try {
      download(only ? `correction_queue_${only}.csv` : 'correction_queue.csv', await api.queueCsv(pid, only))
      toast({ message: t('queue.exported', { count: only ? rows.length : (data?.length ?? 0) }), tone: 'ok' })
    } catch (e) {
      toastProblem(e, t('common.error'))
    } finally {
      setBusyCsv(false)
    }
  }
  const writeExports = () =>
    exportsM.mutate(undefined, {
      onSuccess: (r) => toast({ message: t('queue.exportsWritten', { dir: r.dir ?? 'exports', files: r.files.join(', ') }), tone: 'ok' }),
      onError: (e) => toastProblem(e, t('common.error')),
    })
  const importV2 = (file: File) =>
    importM.mutate(file, {
      onSuccess: setReport,
      onError: (e) => {
        if (!(e instanceof ReviewerCancelled)) toastProblem(e, t('common.error'))
      },
    })

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <Icon spec={codicon('checklist')} />
        <strong>{t('queue.title')}</strong>
        <span className="count">{rows.length}</span>
        <span className="muted panel-size">{t('queue.subtitle')}</span>
        <span className="grow" />
        <select className="select input-sm" value={status} onChange={(e) => setStatus(e.target.value as CurationStatus | '')} aria-label={t('search.status')}>
          <option value="">{t('queue.allStatuses')}</option>
          {QUEUE_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`status.${s}`)}</option>
          ))}
        </select>
        {status ? (
          <button type="button" className="btn btn-sm" disabled={!rows.length || busyCsv} onClick={() => void exportCsv(status)} title={t('queue.exportShownHelp')}>
            <Icon spec={codicon('export')} />
            {t('queue.exportShown', { count: rows.length })}
          </button>
        ) : null}
        <button type="button" className="btn btn-sm" disabled={!data?.length || busyCsv} onClick={() => void exportCsv()} title={t('queue.exportCsvHelp')}>
          <Icon spec={codicon('export')} />
          {t('queue.exportCsv')}
        </button>
        <button type="button" className="btn btn-sm" disabled={exportsM.isPending} onClick={writeExports} title={t('queue.writeExportsHelp')}>
          <Icon spec={codicon('save-all')} />
          {t('queue.writeExports')}
        </button>
        <button type="button" className="btn btn-sm" disabled={importM.isPending} onClick={() => fileRef.current?.click()} title={t('queue.importV2Help')}>
          <Icon spec={codicon('cloud-upload')} />
          {importM.isPending ? t('queue.importing') : t('queue.importV2')}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          hidden
          aria-label={t('queue.importV2')}
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (f) importV2(f)
          }}
        />
      </div>
      {isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {isError ? <div className="error-card">{problemMessage(error, t('common.error'))}</div> : null}
      {!isLoading && !isError && rows.length === 0 ? (
        // a filter that hides every row is not an empty queue
        data?.length ? (
          <div className="empty">
            {t('queue.noMatch')}
            <button type="button" className="link" onClick={() => setStatus('')}>{t('queue.showAllStatuses')}</button>
          </div>
        ) : (
          <div className="empty">{t('queue.empty')}</div>
        )
      ) : null}
      {rows.length ? (
        <table className="table">
          <thead>
            <tr>
              {(Object.keys(SORT_BY) as SortCol[]).map((col) => (
                <th key={col} aria-sort={sort?.col === col ? sort.dir : undefined}>
                  <button type="button" className="th-sort" onClick={() => sortBy(col)}>
                    {t(`queue.col.${col}`)}
                    {sort?.col === col ? <Icon spec={codicon(sort.dir === 'ascending' ? 'arrow-up' : 'arrow-down')} /> : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              // Alt+↓ then follows the queue
              <tr key={rowId(r)} data-clickable="true" onClick={() => openInContext(t('queue.title'), rows.map((x) => ({ caseId: x.case_id, itemId: x.item_id })), i, false)} {...rowKeys(rowId(r))}>
                <td className="mono">{r.case_id}</td>
                <td className="muted"><ItemName id={r.item_id} phase={r.phase} /></td>
                <td>{r.phase ? <PhaseChip phase={r.phase} /> : null}</td>
                <td title={r.target}>{targetName(r.target, labels, t)}</td>
                <td className="muted" title={r.seg_id ?? undefined}>{r.seg_id ? sets.find((s) => s.seg_id === r.seg_id)?.name || r.seg_id : ''}</td>
                <td><StatusBadge status={r.status} /></td>
                <td>
                  <span className="badge" data-tone={r.priority === 'high' ? 'error' : r.priority === 'medium' ? 'warn' : undefined}>{t(`priority.${r.priority}`)}</span>
                </td>
                <td style={{ whiteSpace: 'normal', maxWidth: 360 }}>{r.comment}</td>
                <td className="muted">{t('curation.byAt', { reviewer: r.reviewer, ago: fmtAgo(r.at) })}</td>
                <td><PathCell path={r.image_path_abs} /></td>
                <td><PathCell path={r.mask_path_abs} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {report ? <ImportReport report={report} onClose={() => setReport(null)} /> : null}
    </div>
  )
}
