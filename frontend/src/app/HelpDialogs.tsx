// Help › Keyboard shortcuts and Help › About (AUD-A1-09, AUD-A4-05; NFR-16), on every route
import { useTranslation } from 'react-i18next'

import { useHealth } from '../api'
import { Dialog } from '../lib'
import { bindingOf, commandTitle, formatChord, registry } from '../shell'
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
        {/* UI-21: no logo in dialogs */}
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
  const rows = [...registry.commands.values()].filter((c) => bindingOf(c) && registry.allowed(c))
  const cats = [...new Set(rows.map((c) => c.category ?? ''))]
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('cmd.keyboardShortcuts')} icon={codicon('keyboard')} size="lg">
      <p className="muted">{t('keys.help')}</p>
      {cats.map((cat) => (
        <section key={cat}>
          <h3>{cat ? t(cat) : ''}</h3>
          <table className="table">
            <tbody>
              {rows
                .filter((c) => (c.category ?? '') === cat)
                .map((c) => (
                  <tr key={c.id}>
                    <td>{commandTitle(c, t)}</td>
                    <td className="num"><span className="kbd">{formatChord(bindingOf(c))}</span></td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      ))}
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
