// Study pack plugins (PRJ-16): a pack has no surface of its own; the Library's Open goes to
// Project settings › Plugins, where packs are applied.
import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

const pack = (id: string): FrontendPlugin => ({ id, activate: () => undefined, open: () => openEditor('settings', { tab: 'plugins' }) })

export const packs: FrontendPlugin[] = [pack('ccrcc'), pack('generic-ct')]
