// QuPath "Image" section under the left pane: properties of the active item (UI_SHELL §Left pane views)
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useItem } from '../../api'
import { PhaseChip } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

export function ImageSection() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const { data: it } = useItem(pid, iid)
  const [advanced, setAdvanced] = useState(false)
  if (!iid || !it) return <div className="muted" style={{ padding: '4px 16px 8px', fontSize: 'var(--fs-panel)' }}>{t('image.none')}</div>
  const g = it.geometry
  return (
    <dl className="props">
      <dt>{t('image.item')}</dt>
      <dd className="mono" title={it.item_id}>{it.item_id}</dd>
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
      <dt>{t('image.group')}</dt>
      <dd>{it.group || '—'}</dd>
      {advanced ? (
        <>
          <dt>{t('image.imageRef')}</dt>
          <dd className="mono" title={it.advanced.image_abs ?? ''}>{it.image?.ref ?? '—'}</dd>
          <dt>{t('image.maskRef')}</dt>
          <dd className="mono" title={it.advanced.mask_abs ?? ''}>{it.mask?.ref ?? '—'}</dd>
          <dt>{t('image.absolute')}</dt>
          <dd className="mono" title={it.advanced.image_abs ?? ''}>{it.advanced.image_abs ?? '—'}</dd>
        </>
      ) : null}
      <dt />
      <dd>
        <button type="button" className="link" style={{ fontSize: 'var(--fs-badge)' }} onClick={() => setAdvanced(!advanced)}>
          {t(advanced ? 'image.hidePaths' : 'image.showPaths')}
        </button>
      </dd>
    </dl>
  )
}
