import { useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { create } from 'zustand'

import { useLogStream } from '../../api'
import { IconButton } from '../../lib'
import { registry, runCommand, useWorkbench, type OutputChannelContribution } from '../../shell'
import { useLayout } from '../../state'
import { codicon } from '../../theme'
import { ActivityLog } from './JobsPanel'
import { LogView } from './LogView'

export const ACTIVITY = 'activity'

/** The channel the Output tab shows; `docked`: the Output panel shown outside a project */
export const useOutputView = create<{ channel: string; docked: boolean }>()(() => ({ channel: ACTIVITY, docked: false }))

const useChannels = () => useSyncExternalStore(registry.subscribeOutputChannels, () => registry.outputChannels)

/** Show the Output tab on a channel: the project panel, or the docked panel outside projects */
export function showOutputChannel(channel = ACTIVITY) {
  const inProject = !!useWorkbench.getState().pid
  useOutputView.setState({ channel, docked: !inProject })
  if (inProject) useLayout.getState().showPanelTab('output')
}

/** Register (or update) a server log channel and show it */
export function showOutput(channel: OutputChannelContribution) {
  registry.outputChannel(channel)
  runCommand('output.show', channel.id)
}

function ChannelLog({ channel }: { channel: OutputChannelContribution }) {
  const log = useLogStream(channel.kind, channel.ref)
  return (
    <LogView
      lines={log.data?.lines ?? []}
      first={log.data?.first}
      name={channel.label}
      loading={log.isLoading}
      error={log.error}
      onRetry={() => void log.refetch()}
      ended={log.data?.done}
      redacted
    />
  )
}

export function OutputPanel() {
  const { t } = useTranslation()
  const channels = useChannels()
  const selected = useOutputView((s) => s.channel)
  const channel = channels.find((c) => c.id === selected)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {channels.length ? (
        <div style={{ padding: 'var(--sp-1) var(--sp-3) 0' }}>
          <select
            className="select"
            aria-label={t('output.channel')}
            value={channel?.id ?? ACTIVITY}
            onChange={(e) => useOutputView.setState({ channel: e.target.value })}
          >
            <option value={ACTIVITY}>{t('output.activity')}</option>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>
        </div>
      ) : null}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {channel ? <ChannelLog key={channel.id} channel={channel} /> : <ActivityLog />}
      </div>
    </div>
  )
}

/** Outside a project there is no workbench panel: the Output tab docks at the bottom instead */
export function OutputDock() {
  const { t } = useTranslation()
  const docked = useOutputView((s) => s.docked)
  const inProject = useWorkbench((s) => !!s.pid)
  if (!docked || inProject) return null
  return (
    <section className="panel" aria-label={t('panel.output')} style={{ position: 'fixed', left: 0, right: 0, bottom: 0, height: 'min(320px, 40vh)' }}>
      <div className="panel-tabs">
        <span className="panel-tab" aria-current="true">{t('panel.output')}</span>
        <div className="panel-actions">
          <IconButton icon={codicon('close')} label={t('shell.closePanel')} onClick={() => useOutputView.setState({ docked: false })} />
        </div>
      </div>
      <div className="panel-body">
        <OutputPanel />
      </div>
    </section>
  )
}
