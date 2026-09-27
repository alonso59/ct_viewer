// Import wizard, step 3 (IMP-03/04, IMP-08): counts, the field mapping or the `nifti-files` sample,
// and the errors that block the commit.
import { useTranslation } from 'react-i18next'

import type { ImportPreview } from '../../../api'
import { Icon, codicon } from '../../../theme'
import { MAX_ERRORS, previewCounts } from '../model'

function Mapping({ preview }: { preview: ImportPreview }) {
  const { t } = useTranslation()
  const m = preview.field_mapping
  const rows: [string, string][] = [
    ['image', m.image ?? '—'],
    ['mask', m.seg ? t(`import.seg.${m.seg}`) : '—'],
    ['phase', m.phase?.length ? m.phase.join(' → ') : '—'],
    ['side', m.side ?? '—'],
  ]
  return (
    <table className="table">
      <tbody>
        {rows.map(([field, source]) => (
          <tr key={field}>
            <td>{t(`import.field.${field}`)}</td>
            <td className="muted"><Icon spec={codicon('arrow-left')} /></td>
            <td className="mono">{source}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function NiftiSample({ p }: { p: ImportPreview }) {
  const { t } = useTranslation()
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>{t('import.nifti.file')}</th>
            <th>{t('import.nifti.case')}</th>
            <th>{t('import.nifti.scan')}</th>
            <th>{t('import.nifti.modality')}</th>
            <th>{t('import.field.mask')}</th>
          </tr>
        </thead>
        <tbody>
          {(p.sample ?? []).map((r) => (
            <tr key={r.file}>
              <td className="mono" title={r.file}>{r.matched ? null : <Icon spec={codicon('warning')} />} {r.file}</td>
              <td className="mono">{r.case_id}</td>
              <td className="mono">{r.scan_idx}</td>
              <td className="mono">{r.modality ?? '—'}</td>
              <td className="mono" title={r.mask ?? ''}>{r.mask ? <Icon spec={codicon('check')} /> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** IMP-03: unmatched names, orphan masks and ignored extensions, shown next to the counts */
function NiftiNotices({ p }: { p: ImportPreview }) {
  const { t } = useTranslation()
  return (
    <>
      {p.unmatched?.length ? (
        <p className="muted panel-size">{t('import.nifti.unmatched', { count: p.unmatched.length, names: p.unmatched.slice(0, 5).join(', ') })}</p>
      ) : null}
      {p.orphan_masks?.length ? (
        <p className="muted panel-size">{t('import.nifti.orphans', { count: p.orphan_masks.length })}</p>
      ) : null}
      {Object.keys(p.ignored ?? {}).length ? (
        <p className="muted panel-size">
          {t('import.ignored', { list: Object.entries(p.ignored ?? {}).map(([ext, n]) => `${n} ${ext}`).join(', ') })}
        </p>
      ) : null}
    </>
  )
}

export function PreviewStep({ p }: { p: ImportPreview }) {
  const { t } = useTranslation()
  const nifti = p.adapter === 'nifti-files'
  return (
    // nifti-files has no mapping column: stack KPIs, sample and errors instead of a half-empty grid
    <div className={nifti ? 'wiz-stack' : 'wiz-grid'}>
      <div>
        <h3>{t('import.previewTitle')}</h3>
        <div className="stat-grid" style={{ gridTemplateColumns: `repeat(${nifti ? 4 : 2}, 1fr)`, marginTop: 0 }}>
          {previewCounts(p).map(({ key, n }) => (
            // AUD-A1-08: the case count leaves out cases excluded upstream (and says so)
            <div key={key} className="card" data-zero={n === 0 || undefined} title={key === 'import.kpiCases' ? t('import.kpiCasesHelp', { excluded: p.counts.excluded_cases ?? 0 }) : undefined}><span className="kpi num">{n}</span><span className="muted">{t(key)}</span></div>
          ))}
        </div>
        {nifti ? (
          <div className="mt-2">
            <NiftiNotices p={p} />
          </div>
        ) : (
          <>
            <h3 className="mt-4">{t('import.mapping')}</h3>
            <Mapping preview={p} />
            <div className="table-scroll mt-3">
              <table className="table">
                <tbody>
                  {p.files.map((f) => (
                    <tr key={f.kind}>
                      <td className="text-ok"><Icon spec={codicon('pass')} /></td>
                      <td className="mono">{f.name}</td>
                      <td className="muted">{t(`import.source.${f.source}`)}</td>
                      <td className="num muted">{t('import.rows', { count: f.rows })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      <div>
        {nifti ? (
          <>
            <h3>{t('import.nifti.sampleTitle')}</h3>
            <NiftiSample p={p} />
          </>
        ) : null}
        <h3>{t('import.errors', { count: p.n_errors })}</h3>
        <p className="muted panel-size">{t('import.errorsHelp')}</p>
        {p.n_errors > MAX_ERRORS ? <p className="muted panel-size">{t('import.errorsFirst', { n: MAX_ERRORS })}</p> : null}
        <table className="table">
          <tbody>
            {p.errors.slice(0, MAX_ERRORS).map((e, k) => (
              <tr key={k}>
                <td className="text-error"><Icon spec={codicon('error')} /></td>
                <td className="num muted mono">{e.line != null ? t('import.fileLine', { file: e.file, n: e.line }) : e.file}</td>
                <td className="mono">{e.field ?? ''}</td>
                <td className="ws-normal">{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
