// nnU-Net segmentation plugin: its only surface is the generic external task editor.
import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

const openNnunet = () => openEditor('task', { taskId: 'segment.nnunet' })

export const plugin: FrontendPlugin = {
  id: 'nnunet',
  activate: () => undefined,
  open: openNnunet,
}
