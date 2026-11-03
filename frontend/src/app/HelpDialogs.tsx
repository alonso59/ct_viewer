// Help › Keyboard shortcuts and Help › About, on every route
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useHealth } from '../api'
import { Dialog } from '../lib'
import { bindingOf, commandMatches, commandTitle, formatChord, registry } from '../shell'
import { codicon } from '../theme'
import { useHelp } from './help'


/** Main open-source components of the web app and their licences */
const COMPONENTS: [string, string][] = [
  ['React', 'MIT'],
  ['NiiVue', 'BSD-2-Clause'],
  ['Apache ECharts', 'Apache-2.0'],
  ['dockview', 'MIT'],
  ['Radix UI', 'MIT'],
  ['TanStack Query, Table, Virtual', 'MIT'],
  ['cmdk', 'MIT'],
  ['i18next', 'MIT'],
  ['Zustand', 'MIT'],
  ['React Router', 'MIT'],
  ['VS Code Codicons', 'CC-BY-4.0'],
]

function About({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const version = useHealth().data?.version
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('about.title')} icon={codicon('info')}>
      <div className="about">
        {/* no logo in dialogs */}
        <div>
          <strong>{t('app.title')}</strong>
          <div className="muted">{t('about.version', { version: version ?? '—' })}</div>
        </div>
        <p className="about-notice" role="note">
          <strong>{t('about.researchOnly')}</strong>
        </p>
        <p className="muted">{t('about.local')}</p>
        <h3>{t('about.components')}</h3>
        <table className="table">
          <tbody>
            {COMPONENTS.map(([name, licence]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="mono muted">{licence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Dialog>
  )
}

/** The viewer's pointer gestures and the commands that do the same from the keyboard; a row
 *  without commands names its keyboard way in `keys.mouse.<row>.keys` */
const MOUSE: [string, string[]][] = [
  ['click', ['viewer.nextSlice', 'viewer.previousSlice', 'viewer.centerCrosshair']],
  ['wheel', ['viewer.nextSlice', 'viewer.previousSlice']],
  ['zoom', ['viewer.zoomIn', 'viewer.zoomOut', 'viewer.fit']],
  ['pan', ['viewer.panLeft', 'viewer.panRight', 'viewer.panUp', 'viewer.panDown']],
  ['window', []],
  ['orbit', ['viewer.orbitLeft', 'viewer.orbitRight', 'viewer.orbitUp', 'viewer.orbitDown']],
  ['measure', ['viewer.measurePoint']],
  ['maximize', ['viewer.restore']],
]

function Keys({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState('')
  const rows = [...registry.commands.values()].filter((c) => bindingOf(c) && registry.allowed(c) && commandMatches(c, filter, t))
  const chord = (id: string) => {
    const c = registry.commands.get(id)
    return c ? formatChord(bindingOf(c)) : ''
  }
  const needle = filter.trim().toLowerCase()
  const gestures = MOUSE.map(([id, cmds]) => ({
    id,
    gesture: t(`keys.mouse.${id}.gesture`, { mod: formatChord('mod') }),
    action: t(`keys.mouse.${id}.action`),
    keys: cmds.map(chord).filter(Boolean),
  })).filter((g) => !needle || [g.gesture, g.action, ...g.keys].join(' ').toLowerCase().includes(needle))
  const mouse = gestures.length ? (
    <section>
      <h3>{t('keys.mouseTitle')}</h3>
      <table className="table">
        <tbody>
          {gestures.map((g) => (
            <tr key={g.id}>
              <td>{g.gesture}</td>
              <td>{g.action}</td>
              <td className="num">{g.keys.length ? g.keys.map((k) => <span key={k} className="kbd">{k}</span>) : <span className="muted">{t(`keys.mouse.${g.id}.keys`)}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  ) : null
  // in the viewer, how to use it comes first
  const inViewer = registry.inContext('viewer')
  // one group per menu name: view toggles and "Views ›" are both "View"
  const groups = new Map<string, typeof rows>()
  for (const c of rows) {
    const name = c.category ? t(c.category) : ''
    groups.set(name, [...(groups.get(name) ?? []), c])
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('cmd.keyboardShortcuts')} description={t('keys.help')} icon={codicon('keyboard')} size="lg">
      <input className="input input-sm keys-filter" type="search" value={filter} aria-label={t('keys.filter')} placeholder={t('keys.filter')} onChange={(e) => setFilter(e.target.value)} />
      {/* scrolls on its own, so the keyboard can scroll it */}
      <div className="keys-list" tabIndex={0} role="region" aria-label={t('keys.list')}>
        {inViewer ? mouse : null}
        {[...groups].map(([name, cmds]) => (
          <section key={name}>
            <h3>{name}</h3>
            <table className="table">
              <tbody>
                {cmds.map((c) => (
                  <tr key={c.id}>
                    <td>{commandTitle(c, t)}</td>
                    <td className="num"><span className="kbd">{formatChord(bindingOf(c))}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
        {inViewer ? null : mouse}
        {rows.length || gestures.length ? null : <p className="muted">{t('keys.none')}</p>}
      </div>
    </Dialog>
  )
}

export default function HelpDialogs() {
  const open = useHelp((s) => s.open)
  const close = () => useHelp.getState().show(null)
  if (open === 'about') return <About onClose={close} />
  if (open === 'keys') return <Keys onClose={close} />
  return null
}
