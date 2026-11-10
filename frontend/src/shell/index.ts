// Shell regions and registry. No domain logic here.
import './shell.css'

export { registry } from './registry'
export type { EditorProps, OutputChannelContribution, TaskReviewProps, TaskSettingsProps } from './registry'
export type { EditorParams } from './workbenchStore'
export { Workbench, ShellOverlays, ShellProviders } from './Workbench'
export {
  useWorkbench,
  openEditor,
  pinEditor,
  closeActiveEditor,
  closeOtherEditors,
  splitActiveEditor,
  toast,
  toastProblem,
  notify,
  updateActiveParams,
  refreshUrl,
} from './workbenchStore'
export { useGlobalKeybindings, runCommand, formatChord, bindingOf, chordOf, commandTitle, commandMatches, keyConflicts } from './keybindings'
export { focusRegion } from './regions'
