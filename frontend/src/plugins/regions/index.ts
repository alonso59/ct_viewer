// Tumor regions plugin: its only surface is the generic task editor.
import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

export const plugin: FrontendPlugin = {
  id: 'regions',
  activate: () => undefined,
  open: () => openEditor('task', { taskId: 'regions.derive' }),
}
