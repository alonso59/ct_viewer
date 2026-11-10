// One scan in the review: its VOIs with the axial preview of each box's middle slice, the side and
// how sure it is, and the reviewer's decisions (swap the sides, leave a VOI out).
import { useTranslation } from 'react-i18next'

import { api, type VoiCandidate, type VoiCandidates } from '../../api'
import { openItem } from '../../features/explorer'
import { Button, IconButton, ItemName, ProblemCard, fmt1, parseItemId } from '../../lib'
import { codicon } from '../../theme'
import { fmtSize, isExcluded, isSwapped, needsReview, shownSide, sideConfidence, sideSource, toggleExclude, toggleSwap, WARNING_CODES, type Values } from './model'

const KNOWN = new Set<string>(WARNING_CODES)

/** How sure the side is: verified, probable, uncertain or corrected by the reviewer */
export function SideConfidence({ level }: { level: string }) {
  const { t } = useTranslation()
  if (!level) return null
  return (
    <span className={`voi-conf voi-conf-${level}`} title={t(`voi.confHelp.${level}`)}>
      <span className={`codicon codicon-${level === 'verified' ? 'pass' : level === 'uncertain' ? 'warning' : level === 'reviewer' ? 'person' : 'circle-large'}`} aria-hidden />
      {t(`voi.conf.${level}`)}
    </span>
  )
}

function Candidate({ pid, itemId, c, values, onChange, labels, full }: { pid: string; itemId: string; c: VoiCandidate; values: Values; onChange: (v: Values) => void; labels: readonly string[]; full: boolean }) {
  const { t } = useTranslation()
  const swapped = isSwapped(values, itemId)
  const excluded = isExcluded(values, itemId, c.id)
  const side = shownSide(c, swapped)
  const src = api.voiPreviewUrl(pid, c.preview)
  const title = side ? t(`voi.side.${side}`) : t('voi.single')
  const include = (
    <label className="voi-include">
      <input type="checkbox" checked={!excluded} onChange={() => onChange(toggleExclude(values, itemId, c.id))} />
      {t('voi.include')}
    </label>
  )
  if (!full)
    return (
      <li className="voi-cand voi-cand-compact" data-excluded={excluded || undefined} aria-label={title}>
        <div className="voi-thumb voi-thumb-sm">{src ? <img src={src} alt="" loading="lazy" /> : null}</div>
        {side ? <span className={`voi-side voi-side-${side}`}>{side}</span> : null}
        <strong>{title}</strong>
        {side ? <SideConfidence level={sideConfidence(c.confidence, swapped)} /> : null}
        <span className="muted">{fmtSize(c.crop_size_mm)}</span>
        {include}
      </li>
    )
  return (
    <li className="voi-cand" data-excluded={excluded || undefined} aria-label={title}>
      <div className="voi-thumb">
        {src ? <img src={src} alt={t('voi.previewAlt', { side: title, z: c.z_mid })} loading="lazy" /> : <span className="muted">{t('voi.noPreview')}</span>}
      </div>
      <div className="voi-meta">
        <div className="voi-cand-head">
          {side ? <span className={`voi-side voi-side-${side}`}>{side}</span> : null}
          <strong>{title}</strong>
          {side ? <SideConfidence level={sideConfidence(c.confidence, swapped)} /> : null}
          {include}
        </div>
        <dl className="voi-metrics">
          <dt>{t('voi.metric.labels')}</dt>
          <dd>{fmtSize(c.tight_size_mm)}</dd>
          <dt>{t('voi.metric.crop')}</dt>
          <dd>{fmtSize(c.crop_size_mm)}</dd>
          <dt>{t('voi.metric.volume')}</dt>
          <dd>
            {t('voi.ml', { v: fmt1(c.volume_ml) })}
            {Object.keys(c.label_ml).length > 1 ? (
              <span className="muted voi-breakdown">
                {Object.entries(c.label_ml)
                  .map(([name, ml]) => t('voi.labelMl', { name, v: ml < 0.1 ? '<0.1' : fmt1(ml) }))
                  .join(' · ')}
              </span>
            ) : null}
          </dd>
          {side ? (
            <>
              <dt>{t('voi.metric.sideSource')}</dt>
              <dd>{t(`voi.sideSource.${sideSource(c, labels)}`)}</dd>
            </>
          ) : null}
          <dt>{t('voi.metric.slice')}</dt>
          <dd>{c.z_mid}</dd>
        </dl>
        {c.warnings.length ? (
          <ul className="voi-warnings">
            {c.warnings.map((w) => (
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

export interface ScanCardProps {
  pid: string
  itemId: string
  data: VoiCandidates | undefined
  error: unknown
  fetching: boolean
  values: Values
  onChange: (v: Values) => void
  labels: readonly string[]
  /** Full cards for every VOI; otherwise only the ones that need review are full */
  expanded: boolean
  onToggle: () => void
  cardRef?: (el: HTMLElement | null) => void
}

export function ScanCard({ pid, itemId, data, error, fetching, values, onChange, labels, expanded, onToggle, cardRef }: ScanCardProps) {
  const { t } = useTranslation()
  const swapped = isSwapped(values, itemId)
  const lateral = !!data?.lateral && data.candidates.some((c) => c.side)
  const doubt = !swapped && !!data?.candidates.some((c) => c.side && c.confidence === 'uncertain')
  const flagged = !!data?.candidates.some(needsReview)
  return (
    <section ref={cardRef} className="voi-card" aria-busy={fetching || undefined} data-review={flagged || undefined} tabIndex={-1}>
      <header className="voi-card-head">
        <IconButton icon={codicon(expanded ? 'chevron-down' : 'chevron-right')} label={t(expanded ? 'voi.collapse' : 'voi.expand')} onClick={onToggle} />
        <ItemName id={itemId} pid={pid} />
        {flagged ? <span className="voi-flag">{t('voi.needsReview')}</span> : null}
        <span className="ml-auto" />
        {lateral ? (
          <Button className={`btn btn-sm ${doubt ? 'voi-fix-doubt' : ''}`} aria-pressed={swapped} title={t('voi.swapHelp')} onClick={() => onChange(toggleSwap(values, itemId))}>
            <span className="codicon codicon-arrow-swap" aria-hidden /> {swapped ? t('voi.unswap') : t('voi.swap')}
          </Button>
        ) : null}
        <IconButton icon={codicon('go-to-file')} label={t('voi.openInViewer')} onClick={() => openItem(parseItemId(itemId)?.case_id ?? itemId, itemId, true)} />
      </header>
      {!data && fetching ? <p className="muted voi-pad">{t('voi.computing')}</p> : null}
      {error ? <ProblemCard error={error} /> : null}
      {data && data.missing_labels.length ? (
        // only a problem when nothing was found; otherwise the region simply has extra names
        <p className={`voi-pad ${data.candidates.length ? 'muted voi-note' : 'voi-warn'}`}>{t('voi.missingLabels', { labels: data.missing_labels.join(', ') })}</p>
      ) : null}
      {data && !data.candidates.length && !data.missing_labels.length ? <p className="muted voi-pad">{t('voi.none')}</p> : null}
      {data?.candidates.length ? (
        <ul className="voi-cands">
          {data.candidates.map((c) => (
            <Candidate key={c.id} pid={pid} itemId={itemId} c={c} values={values} onChange={onChange} labels={labels} full={expanded || needsReview(c)} />
          ))}
        </ul>
      ) : null}
    </section>
  )
}
