// QuPath "Image" section under the left pane: properties of the active item (UI_SHELL §Left pane views)
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useItem } from '../../api'
import { ItemName, PhaseChip, ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

/** `00100020` → `0010,0020` */
const tagName = (k: string) => [k.slice(0, 4), k.slice(4)].join(',')

/** DICOM JSON Model element → a short text value */
const tagText = (v: unknown): string => {
  const vals = (v as { Value?: unknown[] } | null)?.Value ?? []
  return vals
    .map((x) => (typeof x === 'object' && x !== null ? ((x as { Alphabetic?: string }).Alphabetic ?? JSON.stringify(x)) : String(x)))
    .join('\\')
    .slice(0, 120)
}

/** DCM-05: DICOM tags only on demand (they can hold PHI) */
function DicomTags({ pid, iid }: { pid: string; iid: string }) {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: keys.dicomTags(pid, iid), queryFn: () => api.dicomTags(pid, iid), retry: false })
  if (q.error) return <ProblemCard error={q.error} />
  if (!q.data) return <span className="muted">{t('common.loading')}</span>
  const rows = Object.entries(q.data).filter(([k]) => /^[0-9A-F]{8}$/.test(k))
  // IMP-15 / ADR-0025: a reconstructed sidecar is never shown as a real DICOM header
  const partial = (q.data._provenance as { fidelity?: string } | undefined)?.fidelity === 'partial'
  return (
    <>
      {partial ? (
        <div className="badge" data-tone="warn" role="note" style={{ marginBottom: 4 }} title={t('image.tagsPartialHelp')}>
          {t('image.tagsPartial')}
        </div>
      ) : null}
      <table className="table mono small">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{tagName(k)}</td>
              <td>{(v as { vr?: string }).vr ?? ''}</td>
              <td>{tagText(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function ImageSection() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const { data: it } = useItem(pid, iid)
  const [advanced, setAdvanced] = useState(false)
  const [tags, setTags] = useState(false)
  if (!iid || !it) return <div className="muted" style={{ padding: '4px 16px 8px', fontSize: 'var(--fs-panel)' }}>{t('image.none')}</div>
  const g = it.geometry
  // API names (API-22 ItemAdvanced); the P0.5 mock called them image_abs/mask_abs
  const adv = it.advanced as { image_path?: string | null; mask_path?: string | null }
  return (
    <dl className="props">
      <dt>{t('image.item')}</dt>
      <dd><ItemName id={it.item_id} phase={it.phase.canonical} /></dd>
      <dt>{t('image.phase')}</dt>
      <dd style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <PhaseChip phase={it.phase.canonical} />
        <span className="muted">{t('image.phaseRaw', { raw: it.phase.raw || '—', source: it.phase.source })}</span>
      </dd>
      <dt>{t('image.size')}</dt>
      <dd className="num">{g ? g.shape.join(' × ') : '—'}</dd>
      <dt>{t('image.spacing')}</dt>
      <dd className="num">{g ? t('image.mm', { v: g.spacing.join(' × ') }) : '—'}</dd>
      <dt>{t('image.type')}</dt>
      <dd>{g ? `${g.dtype} · ${g.orientation}` : '—'}</dd>
      <dt>{t('image.mask')}</dt>
      <dd>{it.mask ? t('image.labels', { labels: it.labels_present.join(', ') || '—' }) : t('image.noMask')}</dd>
      {advanced ? (
        <>
          <dt>{t('image.imageRef')}</dt>
          <dd className="mono" title={adv.image_path ?? ''}>{it.image?.ref ?? '—'}</dd>
          <dt>{t('image.maskRef')}</dt>
          <dd className="mono" title={adv.mask_path ?? ''}>{it.mask?.ref ?? '—'}</dd>
          <dt>{t('image.absolute')}</dt>
          <dd className="mono" title={adv.image_path ?? ''}>{adv.image_path ?? '—'}</dd>
        </>
      ) : null}
      <dt />
      <dd>
        <button type="button" className="link small" onClick={() => setAdvanced(!advanced)}>
          {t(advanced ? 'image.hidePaths' : 'image.showPaths')}
        </button>
      </dd>
      {it.extra?.dicom_sidecar ? (
        <>
          <dt />
          <dd>
            <button type="button" className="link small" onClick={() => setTags(!tags)}>
              {t(tags ? 'image.hideTags' : 'image.showTags')}
            </button>
          </dd>
          {tags ? (
            <dd style={{ gridColumn: '1 / -1' }}>
              <DicomTags pid={pid} iid={it.item_id} />
            </dd>
          ) : null}
        </>
      ) : null}
    </dl>
  )
}
