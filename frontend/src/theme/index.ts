// Design tokens, base styles, icon sets (UI-11, UI-15). Owned by lane P0.5.
import '@vscode/codicons/dist/codicon.css'
import 'dockview-react/dist/styles/dockview.css'
import './tokens.css'
import './base.css'

export { BrandMark } from './BrandMark'
export { Icon, codicon, ct, type IconSpec } from './Icon'
export { CtIcon, CT_ICONS, type CtIconName } from './icons/CtIcon'
export { INTERFACE_SIZES, applySize, applyTheme, token, tokenPx, type InterfaceSize, type ThemeChoice } from './theme'
export { autoLabelColor } from './labelPalette'
