// Settings view (activity bar, bottom): theme, reviewer, list density, keybindings (UI-11, UI-12)
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { API_MODE, api } from '../api'
import { bindingOf, chordOf, formatChord, openEditor, registry, toast } from '../shell'
import { useReviewer, useSettings } from '../state'
import type { ThemeChoice } from '../theme'

export function SettingsView() {
  const { t } = useTranslation()
  const s = useSettings()
  const reviewer = useReviewer()
  const [name, setName] = useState(reviewer.name)
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const cmds = [...registry.commands.values()].filter((c) => c.keybinding && (!filter || t(c.title).toLowerCase().includes(filter.toLowerCase())))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '0 12px 16px', fontSize: 'var(--fs-panel)' }}>
      <label className="field">
        <span className="field-label">{t('settings.theme')}</span>
        <div className="seg" role="group">
          {(['dark', 'light', 'system'] as ThemeChoice[]).map((th) => (
            <button key={th} type="button" aria-pressed={s.theme === th} onClick={() => s.set({ theme: th })}>{t(`settings.themes.${th}`)}</button>
          ))}
        </div>
      </label>
      <form className="field" onSubmit={(e) => { e.preventDefault(); reviewer.setName(name); toast({ message: t('settings.reviewerSaved'), tone: 'ok' }) }}>
        <span className="field-label">{t('settings.reviewer')}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <input className="input input-sm" style={{ flex: 1 }} value={name} placeholder={t('reviewer.placeholder')} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn btn-sm" disabled={!name.trim() || name.trim() === reviewer.name}>{t('common.save')}</button>
        </div>
        <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('reviewer.help')}</span>
      </form>
      <label className="field">
        <span className="field-label">{t('settings.rows')}</span>
        <div className="seg" role="group">
          <button type="button" aria-pressed={s.rowDensity === 'thumbnails'} onClick={() => s.set({ rowDensity: 'thumbnails' })}>{t('explorer.thumbnailRows')}</button>
          <button type="button" aria-pressed={s.rowDensity === 'compact'} onClick={() => s.set({ rowDensity: 'compact' })}>{t('explorer.compactRows')}</button>
        </div>
      </label>
      <div className="field">
        <span className="field-label">{t('settings.prototype')}</span>
        {API_MODE === 'mock' ? (
          <label className="check">
            <input type="checkbox" checked={s.simulateReviewer} onChange={(e) => s.set({ simulateReviewer: e.target.checked })} />
            {t('settings.simulate')}
          </label>
        ) : null}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-sm" onClick={() => openEditor('design', {})}>{t('design.open')}</button>
          {API_MODE === 'mock' ? (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => {
                api.reset()
                try {
                  for (const k of Object.keys(localStorage)) if (k.startsWith('rw.tabs.') || k.startsWith('rw.layout.')) localStorage.removeItem(k)
                } catch {
                  // ignore
                }
                location.assign('/')
              }}
            >
              {t('settings.resetMock')}
            </button>
          ) : null}
        </div>
      </div>
      <div className="field">
        <span className="field-label">{t('settings.keybindings')}</span>
        <input className="input input-sm" value={filter} placeholder={t('settings.keyFilter')} onChange={(e) => setFilter(e.target.value)} />
        <table className="table">
          <tbody>
            {cmds.map((c) => (
              <tr key={c.id}>
                <td style={{ whiteSpace: 'normal' }}>{t(c.title)}</td>
                <td className="num">
                  {editing === c.id ? (
                    <input
                      className="input input-sm mono"
                      data-keyrecorder="true"
                      autoFocus
                      style={{ width: 90 }}
                      placeholder={t('settings.pressKeys')}
                      onBlur={() => setEditing(null)}
                      onKeyDown={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) return
                        if (e.key === 'Escape') return setEditing(null)
                        s.setKeybinding(c.id, chordOf(e.nativeEvent))
                        setEditing(null)
                      }}
                    />
                  ) : (
                    <button type="button" className="link mono" title={t('settings.editKey')} onClick={() => setEditing(c.id)}>
                      {formatChord(bindingOf(c))}
                    </button>
                  )}
                  {s.keybindings[c.id] ? (
                    <button type="button" className="link" style={{ marginLeft: 6 }} title={t('settings.resetKey')} onClick={() => s.setKeybinding(c.id, null)}>
                      {t('settings.reset')}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
