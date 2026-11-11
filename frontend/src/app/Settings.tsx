// Settings view (activity bar, bottom): theme, interface size, reviewer, storage and compute, list density, keybindings
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { API_MODE } from '../api'
import { ConfirmInline } from '../lib'
import { bindingOf, chordOf, commandMatches, commandTitle, formatChord, keyConflicts, openEditor, registry, runCommand, toast } from '../shell'
import { useReviewer, useSettings } from '../state'
import { INTERFACE_SIZES, type ThemeChoice } from '../theme'

/** A recorded chord that another command already uses: Replace takes it, Cancel keeps both as they were */
interface Pending {
  id: string
  chord: string
  others: string[]
}

export function SettingsView() {
  const { t } = useTranslation()
  const s = useSettings()
  const reviewer = useReviewer()
  const [name, setName] = useState(reviewer.name)
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  // any command can get keys, also one without a default
  const cmds = [...registry.commands.values()].filter((c) => registry.allowed(c) && commandMatches(c, filter, t))
  const record = (id: string, chord: string) => {
    setEditing(null)
    const others = keyConflicts(chord, id)
    if (others.length) setPending({ id, chord, others: others.map((c) => c.id) })
    else s.setKeybinding(id, chord)
  }
  const replace = (p: Pending) => {
    for (const other of p.others) s.setKeybinding(other, '')
    s.setKeybinding(p.id, p.chord)
    setPending(null)
  }
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
        <label className="field-label" htmlFor="settings-reviewer">{t('settings.reviewer')}</label>
        <div className="row">
          <input id="settings-reviewer" className="input input-sm grow" value={name} placeholder={t('reviewer.placeholder')} aria-describedby="settings-reviewer-help" onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn btn-sm" disabled={!name.trim() || name.trim() === reviewer.name}>{t('common.save')}</button>
        </div>
        <span id="settings-reviewer-help" className="muted small">{t('reviewer.help')}</span>
      </form>
      <div className="field">
        <span className="field-label">{t('settings.setup')}</span>
        <div className="row wrap">
          <button type="button" className="btn btn-sm" onClick={() => runCommand('setup.storage')}>{t('cmd.storage')}</button>
          <button type="button" className="btn btn-sm" onClick={() => runCommand('setup.compute')}>{t('cmd.compute')}</button>
        </div>
        <span className="muted small">{t('settings.setupHelp')}</span>
      </div>
      <div className="field">
        <span className="field-label" id="settings-rows">{t('settings.rows')}</span>
        <div className="seg" role="group" aria-labelledby="settings-rows">
          <button type="button" aria-pressed={s.rowDensity === 'thumbnails'} onClick={() => s.set({ rowDensity: 'thumbnails' })}>{t('explorer.thumbnailRows')}</button>
          <button type="button" aria-pressed={s.rowDensity === 'compact'} onClick={() => s.set({ rowDensity: 'compact' })}>{t('explorer.compactRows')}</button>
        </div>
      </div>
      {/* developers only; Help › Open design reference stays for everyone */}
      {import.meta.env.DEV ? (
        <div className="field">
          <span className="field-label">{t('settings.prototype')}</span>
          <div className="row wrap">
            <button type="button" className="btn btn-sm" onClick={() => openEditor('design', {})}>{t('design.open')}</button>
            {API_MODE === 'mock' ? (
              <ConfirmInline
                question={t('settings.resetMockConfirm')}
                confirm={t('settings.resetMock')}
                onConfirm={() => {
                  try {
                    for (const k of Object.keys(localStorage)) if (k.startsWith('rw.tabs.') || k.startsWith('rw.layout.')) localStorage.removeItem(k)
                  } catch {
                    // ignore
                  }
                  location.assign('/')
                }}
                trigger={(ask) => <button type="button" className="btn btn-sm" onClick={ask}>{t('settings.resetMock')}</button>}
              />
            ) : null}
          </div>
        </div>
      ) : null}
      <div className="field">
        <label className="field-label" htmlFor="settings-key-filter">{t('settings.keybindings')}</label>
        <input id="settings-key-filter" className="input input-sm" type="search" value={filter} placeholder={t('settings.keyFilter')} onChange={(e) => setFilter(e.target.value)} />
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
                      aria-label={t('settings.pressKeysFor', { command: commandTitle(c, t) })}
                      placeholder={t('settings.pressKeys')}
                      onBlur={() => setEditing(null)}
                      onKeyDown={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) return
                        if (e.key === 'Escape') return setEditing(null)
                        record(c.id, chordOf(e.nativeEvent))
                      }}
                    />
                  ) : (
                    <button type="button" className="link mono" title={t('settings.editKey')} aria-label={t('settings.keyOf', { command: commandTitle(c, t), keys: formatChord(bindingOf(c)) || t('settings.noKey') })} onClick={() => { setPending(null); setEditing(c.id) }}>
                      {formatChord(bindingOf(c)) || t('settings.noKey')}
                    </button>
                  )}
                  {c.id in s.keybindings ? (
                    <button type="button" className="link reset-key" title={t('settings.resetKey')} onClick={() => s.setKeybinding(c.id, null)}>
                      {t('settings.reset')}
                    </button>
                  ) : null}
                  {pending?.id === c.id ? (
                    <div className="error-card key-conflict" role="alert">
                      {t('settings.keyConflict', { keys: formatChord(pending.chord), command: pending.others.map((id) => { const o = registry.commands.get(id); return o ? commandTitle(o, t) : id }).join(', ') })}
                      <div className="row mt-2">
                        <button type="button" className="btn btn-sm" onClick={() => replace(pending)}>{t('settings.replaceKey')}</button>
                        <button type="button" className="btn btn-sm" onClick={() => setPending(null)}>{t('common.cancel')}</button>
                      </div>
                    </div>
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
