// Shell regions and registry (UI-01/02). No domain logic here.
import './shell.css'

export { registry } from './registry'
export type { EditorProps } from './registry'
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
  updateActiveParams,
  refreshUrl,
} from './workbenchStore'
export { useGlobalKeybindings, runCommand, formatChord, bindingOf, chordOf, commandTitle } from './keybindings'
