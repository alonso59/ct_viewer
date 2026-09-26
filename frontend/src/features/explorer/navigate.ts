// Opening cases from the Explorer and from lists (UI-08, AUD-A1-04 navigation context)
import { openEditor } from '../../shell'
import { uniqueEntries, useNavContext, type NavEntry } from '../../state'

export function openItem(caseId: string, itemId: string | null, preview = true) {
  openEditor('case', { caseId, itemId }, { preview })
}

/** AUD-A1-04: open an entry of a list (Outliers, queue, Problems, a label table) and remember the
 *  list, so Alt+↓ / Alt+↑ follow it and the case header shows the position */
export function openInContext(label: string, entries: NavEntry[], index: number, preview = true) {
  const list = uniqueEntries(entries)
  const at = entries[index]
  const i = at ? list.findIndex((e) => e.caseId === at.caseId && e.itemId === at.itemId) : -1
  const e = list[i]
  if (!e) return
  useNavContext.getState().set(label, list, i)
  openItem(e.caseId, e.itemId, preview)
}

/** Opens from the Explorer itself (tree, quick open) drop any list context */
export function openFromExplorer(caseId: string, itemId: string | null, preview = true) {
  useNavContext.getState().clear()
  openItem(caseId, itemId, preview)
}
