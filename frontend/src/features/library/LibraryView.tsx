// Plugin Library (UI-22, PLG-05/06/09): one card per installed first-party plugin with what it
// adds, its status and reason, and Open. Pending plugins are listed but cannot be opened.
import { useTranslation } from 'react-i18next'

import { usePlugins, type PluginInfo } from '../../api'
import { ProblemCard } from '../../lib'
import { openerOf } from '../../plugins/host'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import './library.css'

const TONE: Record<PluginInfo['status'], string> = {
  ready: 'ok',
  needs_runner: 'warn',
  needs_derived_root: 'warn',
  needs_segmentation: 'warn',
  pending: 'muted',
}
const POINTS = ['tasks', 'views', 'editors', 'overlays', 'panels', 'commands', 'columns', 'packs'] as const

export function PluginCard({ info }: { info: PluginInfo }) {
  const { t } = useTranslation()
  const m = info.manifest
  const open = info.status === 'pending' ? null : openerOf(m.id)
  const adds = POINTS.filter((k) => (m.contributes?.[k] ?? []).length > 0).map((k) => t(`library.point.${k}`, { count: (m.contributes?.[k] ?? []).length }))
  return (
    <li className="plugin-card" data-plugin={m.id} data-status={info.status}>
      <div className="plugin-card-head">
        <Icon spec={codicon(m.icon)} size={20} />
        <strong>{m.title}</strong>
        <span className="muted num">{m.version}</span>
        <span className="badge" data-tone={TONE[info.status]}>{t(`library.status.${info.status}`)}</span>
      </div>
      <p className="plugin-card-desc">{m.description}</p>
      {adds.length ? <p className="muted plugin-card-adds">{t('library.adds', { list: adds.join(' · ') })}</p> : null}
      {info.reason ? <p className="muted plugin-card-reason">{info.reason}</p> : null}
      <div>
        <button type="button" className="btn btn-sm" disabled={!open} onClick={() => open?.()} aria-label={t('library.openNamed', { name: m.title })}>
          {t('common.open')}
        </button>
      </div>
    </li>
  )
}

export default function LibraryView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid)
  const { data, error, isLoading } = usePlugins(pid)
  return (
    <div className="library-view">
      {error ? <ProblemCard error={error} /> : null}
      {isLoading ? <p className="muted">{t('common.loading')}</p> : null}
      <ul className="plugin-list">{(data?.plugins ?? []).map((p) => <PluginCard key={p.manifest.id} info={p} />)}</ul>
      {data?.invalid.length ? <p className="muted">{t('library.invalid', { count: data.invalid.length })}</p> : null}
    </div>
  )
}
