// DICOM converter plugin (plugins/dicom, DCM-*): the `dicom.convert` task and its command.
import { openEditor } from '../../shell'
import type { FrontendPlugin } from '../host'

const openConverter = () => openEditor('task', { taskId: 'dicom.convert' })

export const plugin: FrontendPlugin = {
  id: 'dicom',
  activate: ({ registry }) => {
    registry.command({ id: 'tasks.convertDicom', writes: true, title: 'cmd.convertDicom', category: 'cat.project', menu: 'project', menuGroup: 2, run: openConverter })
  },
  open: openConverter,
}
