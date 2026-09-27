// Settings view (activity bar, bottom): theme, interface size, reviewer, list density, keybindings
// (UI-11, UI-12, UI-27)
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { API_MODE } from '../api'
import { bindingOf, chordOf, commandTitle, formatChord, openEditor, registry, toast } from '../shell'
import { useReviewer, useSettings } from '../state'
import { INTERFACE_SIZES, type ThemeChoice } from '../theme'

export function SettingsView() {
  const { t } = useTranslation()
  const s = useSettings()
  const reviewer = useReviewer()
  const [name, setName] = useState(reviewer.name)
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const cmds = [...registry.commands.values()].filter((c) => c.keybinding && (!filter || commandTitle(c, t).toLowerCase().includes(filter.toLowerCase())))
  return (
    <div className="settings-view">
      <div className="field">
        <span className="field-label" id="settings-theme">{t('settings.theme')}</span>
        <div className="seg" role="group" aria-labelledby="settings-theme">
          {(['dark', 'light', 'system'] as ThemeChoice[]).map((th) => (
            <button key={th} type="button" aria-pressed={s.theme === th} onClick={() => s.set({ theme: th })}>{t(`settings.themes.${th}`)}</button>
          ))}
        </div>
      </div>
      <div className="field">
        <span className="field-label" id="settings-size">{t('settings.size')}</span>
        <div className="seg" role="group" aria-labelledby="settings-size">
          {INTERFACE_SIZES.map((z) => (
            <button key={z} type="button" aria-pressed={s.uiSize === z} onClick={() => s.set({ uiSize: z })}>{t(`settings.sizes.${z}`)}</button>
          ))}
        </div>
        <span className="muted small">{t('settings.sizeHelp')}</span>
      </div>
      <form className="field" onSubmit={(e) => { e.preventDefault(); reviewer.setName(name); toast({ message: t('settings.reviewerSaved'), tone: 'ok' }) }}>
        <span className="field-label">{t('settings.reviewer')}</span>
        <div className="row">
          <input className="input input-sm grow" value={name} placeholder={t('reviewer.placeholder')} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn btn-sm" disabled={!name.trim() || name.trim() === reviewer.name}>{t('common.save')}</button>
        </div>
        <span className="muted small">{t('reviewer.help')}</span>
      </form>
      <div className="field">
        <span className="field-label" id="settings-rows">{t('settings.rows')}</span>
        <div className="seg" role="group" aria-labelledby="settings-rows">
          <button type="button" aria-pressed={s.rowDensity === 'thumbnails'} onClick={() => s.set({ rowDensity: 'thumbnails' })}>{t('explorer.thumbnailRows')}</button>
          <button type="button" aria-pressed={s.rowDensity === 'compact'} onClick={() => s.set({ rowDensity: 'compact' })}>{t('explorer.compactRows')}</button>
        </div>
      </div>
      <div className="field">
        <span className="field-label">{t('settings.prototype')}</span>
        <div className="row wrap">
          <button type="button" className="btn btn-sm" onClick={() => openEditor('design', {})}>{t('design.open')}</button>
          {API_MODE === 'mock' ? (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => {
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
                <td className="wrap-cell">{commandTitle(c, t)}</td>
                <td className="num">
                  {editing === c.id ? (
                    <input
                      className="input input-sm mono key-input"
                      data-keyrecorder="true"
                      autoFocus
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
                    <button type="button" className="link reset-key" title={t('settings.resetKey')} onClick={() => s.setKeybinding(c.id, null)}>
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
