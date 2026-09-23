// Shell regions and registry (UI-01/02). No domain logic here.
import './shell.css'

export { registry } from './registry'
export type {
  Command,
  EditorContribution,
  EditorProps,
  ViewContribution,
  PanelTabContribution,
  QuickOpenProvider,
  MenuId,
} from './registry'
export { Workbench, ShellOverlays, ShellProviders } from './Workbench'
export {
  useWorkbench,
  openEditor,
  pinEditor,
  closeActiveEditor,
  closeOtherEditors,
  splitActiveEditor,
  toast,
  updateActiveParams,
  refreshUrl,
  type EditorParams,
} from './workbenchStore'
export { useGlobalKeybindings, runCommand, formatChord, bindingOf, chordOf, isMac } from './keybindings'
