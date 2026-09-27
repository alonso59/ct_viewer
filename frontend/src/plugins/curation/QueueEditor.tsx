// Correction queue editor tab (CUR-09): items in the queue set or flagged; server CSV with absolute
// paths for 3D Slicer (API-52), project exports (CUR-10, API-53) and v2 import (CUR-13, API-54).
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ProblemError, QUEUE_STATUSES, ReviewerCancelled, useCurationExports, useImportV2, useQueue, type CurationStatus, type V2ImportReport } from '../../api'
import { Dialog, ItemName, PhaseChip, StatusBadge, fmtAgo, midEllipsis } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openInContext } from '../../features/explorer'
import '../../i18n/lazy'

const problemText = (e: unknown, fallback: string) => (e instanceof ProblemError ? (e.detail ?? e.title) : fallback)

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
      {/* AUD-A3-13: middle ellipsis, so the root and the file name stay readable */}
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
  const rows = (data ?? []).filter((r) => !status || r.status === status)

  const exportCsv = async () => {
    setBusyCsv(true)
    try {
      download('correction_queue.csv', await api.queueCsv(pid))
      toast({ message: t('queue.exported', { count: data?.length ?? 0 }), tone: 'ok' })
    } catch (e) {
      toast({ message: problemText(e, t('common.error')), tone: 'error' })
    } finally {
      setBusyCsv(false)
    }
  }
  const writeExports = () =>
    exportsM.mutate(undefined, {
      onSuccess: (r) => toast({ message: t('queue.exportsWritten', { dir: r.dir ?? 'exports', files: r.files.join(', ') }), tone: 'ok' }),
      onError: (e) => toast({ message: problemText(e, t('common.error')), tone: 'error' }),
    })
  const importV2 = (file: File) =>
    importM.mutate(file, {
      onSuccess: setReport,
      onError: (e) => {
        if (!(e instanceof ReviewerCancelled)) toast({ message: problemText(e, t('common.error')), tone: 'error' })
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
      {isError ? <div className="error-card">{problemText(error, t('common.error'))}</div> : null}
      {!isLoading && !isError && rows.length === 0 ? <div className="empty">{t('queue.empty')}</div> : null}
      {rows.length ? (
        <table className="table">
          <thead>
            <tr>
              <th>{t('queue.col.case')}</th>
              <th>{t('queue.col.item')}</th>
              <th>{t('queue.col.phase')}</th>
              <th>{t('queue.col.target')}</th>
              <th>{t('queue.col.set')}</th>
              <th>{t('queue.col.status')}</th>
              <th>{t('queue.col.priority')}</th>
              <th>{t('queue.col.comment')}</th>
              <th>{t('queue.col.reviewer')}</th>
              <th>{t('queue.col.image')}</th>
              <th>{t('queue.col.mask')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              // AUD-A1-04: Alt+↓ then follows the queue
              <tr key={`${r.item_id}|${r.target}|${r.seg_id ?? ''}`} data-clickable="true" onClick={() => openInContext(t('queue.title'), rows.map((x) => ({ caseId: x.case_id, itemId: x.item_id })), i, false)}>
                <td className="mono">{r.case_id}</td>
                <td className="muted"><ItemName id={r.item_id} phase={r.phase} /></td>
                <td>{r.phase ? <PhaseChip phase={r.phase} /> : null}</td>
                <td className="mono">{r.target}</td>
                {/* AUD-A2-16: which segmentation set to fix (ADR-0015) */}
                <td className="mono muted">{r.seg_id ?? ''}</td>
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
