// Design reference tab (P0.5): tokens, type, badges, buttons and the CT icon set, for review.
import { useTranslation } from 'react-i18next'

import { CURATION_STATUSES, PHASES } from '../api'
import { PhaseChip, StatusBadge } from '../lib'
import { useSettings } from '../state'
import { CT_ICONS, CtIcon, Icon, codicon, type CtIconName } from '../theme'

const TOKENS = [
  ['--bg-editor', '--bg-sidebar', '--bg-overlay', '--bg-hover', '--bg-selected', '--bg-viewport'],
  ['--fg', '--fg-muted', '--border', '--border-muted', '--focus', '--accent', '--tab-active-indicator'],
  ['--ok', '--warn', '--error', '--done', '--btn-primary'],
  ['--plane-axial', '--plane-sagittal', '--plane-coronal', '--plane-3d'],
  ['--cat-1', '--cat-2', '--cat-3', '--cat-4', '--cat-5', '--cat-6', '--cat-7', '--cat-8'],
]
const SHELL_CODICONS = ['files', 'info', 'checklist', 'tag', 'history', 'beaker', 'graph', 'search', 'settings-gear', 'move', 'zoom-in', 'discard', 'device-camera', 'link', 'warning', 'error', 'pass']

export function DesignReference() {
  const { t } = useTranslation()
  const theme = useSettings((s) => s.theme)
  return (
    <div className="page">
      <div className="page-inner" style={{ maxWidth: 1100 }}>
        <h1>{t('design.title')}</h1>
        <p className="muted">{t('design.subtitle', { theme })}</p>
        <h2>{t('design.colors')}</h2>
        {TOKENS.map((row) => (
          <div key={row[0]} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
            {row.map((tk) => (
              <div key={tk} style={{ width: 120, fontSize: 'var(--fs-badge)' }}>
                <div style={{ height: 36, borderRadius: 6, border: '1px solid var(--border)', background: `var(${tk})` }} />
                <div className="mono muted" style={{ marginTop: 4 }}>{tk}</div>
              </div>
            ))}
          </div>
        ))}
        <h2>{t('design.type')}</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 'var(--fs-title)', fontWeight: 600 }}>{t('design.sampleTitle')}</span>
          <span style={{ fontSize: 'var(--fs-heading)' }}>{t('design.sampleHeading')}</span>
          <span>{t('design.sampleUi')}</span>
          <span style={{ fontSize: 'var(--fs-panel)' }} className="muted">{t('design.samplePanel')}</span>
          <span className="num">{t('design.sampleMono')}</span>
        </div>
        <h2>{t('design.controls')}</h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className="btn btn-primary">{t('design.primary')}</button>
          <button type="button" className="btn">{t('design.secondary')}</button>
          <button type="button" className="btn btn-sm">{t('design.small')}</button>
          <button type="button" className="btn" disabled>{t('design.disabled')}</button>
          <input className="input" placeholder={t('design.input')} />
          <div className="seg" role="group">
            <button type="button" aria-pressed="true">{t('item.full')}</button>
            <button type="button">{t('item.voi')}</button>
          </div>
          <button type="button" className="icon-btn" aria-pressed="true" aria-label={t('design.pressed')}><Icon spec={codicon('move')} /></button>
        </div>
        <h2>{t('design.badges')}</h2>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {CURATION_STATUSES.map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          {PHASES.map((p) => (
            <PhaseChip key={p} phase={p} />
          ))}
        </div>
        <h2>{t('design.ctIcons')}</h2>
        <p className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('design.ctIconsHelp')}</p>
        <div className="icon-grid">
          {(Object.keys(CT_ICONS) as CtIconName[]).map((n) => (
            <div key={n} className="icon-cell">
              <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
                <CtIcon name={n} />
                <CtIcon name={n} size={32} />
                <span className="icon-zoom"><CtIcon name={n} size={64} /></span>
              </div>
              <span className="mono muted">{n}</span>
            </div>
          ))}
        </div>
        <h2>{t('design.codicons')}</h2>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {SHELL_CODICONS.map((n) => (
            <span key={n} title={n} style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4, width: 72, fontSize: 'var(--fs-badge)' }} className="muted">
              <Icon spec={codicon(n)} size={20} />
              {n}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
