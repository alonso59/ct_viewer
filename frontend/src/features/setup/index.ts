// Workspace setup: where data lives (storage locations) and what the scheduler is asked for
// (compute profiles). One flow for a workstation and a cluster; reachable from the home screen,
// Settings and the palette.
import { registry } from '../../shell'
import { SetupDialogs } from './SetupDialogs'
import { useSetup } from './store'

export function registerSetup() {
  registry.overlay({ id: 'setup.dialogs', writes: true, component: SetupDialogs })
  registry.command({
    id: 'setup.storage',
    writes: true,
    title: 'cmd.storage',
    category: 'cat.file',
    keywords: ['kw.storage'],
    scope: ['home', 'project', 'open'],
    menuGroup: 7,
    run: () => useSetup.getState().show('storage'),
  })
  registry.command({
    id: 'setup.compute',
    writes: true,
    title: 'cmd.compute',
    category: 'cat.tasks',
    keywords: ['kw.compute'],
    scope: ['home', 'project', 'open'],
    menuGroup: 7,
    run: () => useSetup.getState().show('compute'),
  })
}
