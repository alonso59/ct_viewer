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

function Keys({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState('')
  const rows = [...registry.commands.values()].filter((c) => bindingOf(c) && registry.allowed(c) && commandMatches(c, filter, t))
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
        {rows.length ? null : <p className="muted">{t('keys.none')}</p>}
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
