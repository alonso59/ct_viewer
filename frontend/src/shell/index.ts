// Shell regions and registry (UI-01/02). No domain logic here.
import './shell.css'

export { registry, routeScope } from './registry'
export type {
  Command,
  EditorContribution,
  EditorProps,
  ViewContribution,
  PanelTabContribution,
  QuickOpenProvider,
  MenuId,
  RouteScope,
} from './registry'
export { MENUS, menuOf, menuSections } from './menus'
export { paletteScore } from './paletteMatch'
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
  type EditorParams,
} from './workbenchStore'
export { useGlobalKeybindings, runCommand, formatChord, bindingOf, chordOf, isMac, commandTitle, dispatchKey, modalOpen } from './keybindings'
