// Keybinding dispatch. `mod` = Cmd on macOS, Ctrl elsewhere.
import { useEffect } from 'react'

import { useSettings } from '../state'
import { registry, routeScope, type Command } from './registry'

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

const CODE_KEYS: Record<string, string> = {
  ArrowDown: 'down',
  ArrowUp: 'up',
  ArrowLeft: 'left',
  ArrowRight: 'right',
  Escape: 'esc',
  Space: 'space',
  Enter: 'enter',
  Backspace: 'backspace',
  Delete: 'delete',
}

/** Normalize a KeyboardEvent into a chord like `mod+shift+p`. Uses `code` so Shift+1 stays `shift+1`. */
export function chordOf(e: KeyboardEvent): string {
  let key = CODE_KEYS[e.code] ?? ''
  if (!key && e.code.startsWith('Key')) key = e.code.slice(3).toLowerCase()
  if (!key && e.code.startsWith('Digit')) key = e.code.slice(5)
  if (!key && /^F\d+$/.test(e.code)) key = e.code.toLowerCase()
  if (!key) key = e.key.toLowerCase()
  const mods = [
    (isMac ? e.metaKey : e.ctrlKey) && 'mod',
    isMac && e.ctrlKey && 'ctrl',
    e.altKey && 'alt',
    e.shiftKey && 'shift',
  ].filter(Boolean)
  return [...mods, key].join('+')
}

export function bindingOf(c: Command): string | undefined {
  return useSettings.getState().keybindings[c.id] ?? c.keybinding
}

/** Display form: ⌘⇧P on macOS, Ctrl+Shift+P elsewhere */
export function formatChord(chord: string | undefined): string {
  if (!chord) return ''
  const parts = chord.split('+')
  const map: Record<string, string> = isMac
    ? { mod: '⌘', shift: '⇧', alt: '⌥', ctrl: '⌃', down: '↓', up: '↑', left: '←', right: '→', esc: 'Esc', space: 'Space' }
    : { mod: 'Ctrl', shift: 'Shift', alt: 'Alt', down: '↓', up: '↑', left: '←', right: '→', esc: 'Esc', space: 'Space' }
  const out = parts.map((p) => map[p] ?? p.toUpperCase())
  return isMac ? out.join('') : out.join('+')
}

function inTextField(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el?.tagName) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/** A modal (dialog, palette, wizard) is open: global keys stay off, its own keys and Escape
 *  (topmost layer first, Radix) apply */
function modalOpen(): boolean {
  return typeof document !== 'undefined' && document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]') !== null
}

const inMenu = (target: EventTarget | null) => !!(target as HTMLElement | null)?.closest?.('[role="menu"], [role="listbox"]')

/** A focused tree, grid, tab list or radio group moves with the arrow keys (also with Shift) */
const ownsArrows = (target: EventTarget | null) => !!(target as HTMLElement | null)?.closest?.('[role="tree"], [role="grid"], [role="treegrid"], [role="tablist"], [role="radiogroup"]')

/** One keydown through the registry. Returns whether a command ran.
 *  - only commands offered on the current route and allowed
 *  - nothing while a modal is open or a menu has focus
 *  - `when: 'viewer'`: a viewer is shown and focus is not in a text field; DOM focus inside the
 *    viewer is not needed, so the keys work right after Alt+↓ or a click in the Explorer; arrow
 *    chords leave a focused tree, grid or tab list alone
 *  - plain keys never fire while typing; chords with a modifier or F-keys do */
export function dispatchKey(e: KeyboardEvent): boolean {
  if (e.repeat && !e.altKey) return false
  const target = e.target as HTMLElement | null
  if (target?.dataset?.keyrecorder) return false
  if (modalOpen() || inMenu(target)) return false
  const chord = chordOf(e)
  const typing = inTextField(target)
  const scope = routeScope()
  for (const c of registry.commands.values()) {
    if (bindingOf(c) !== chord || !registry.available(c, scope)) continue
    if (c.when === 'viewer' && (typing || !registry.inContext('viewer') || (/(up|down|left|right)$/.test(chord) && ownsArrows(target)))) continue
    if (typing && !/mod|alt|ctrl|^f\d/.test(chord)) continue
    if (c.enabled && !c.enabled()) continue
    e.preventDefault()
    e.stopPropagation()
    c.run()
    return true
  }
  return false
}

export function useGlobalKeybindings() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => void dispatchKey(e)
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])
}

/** Run a command by id; features reach plugins this way, never through their modules */
export function runCommand(id: string, arg?: string) {
  const c = registry.commands.get(id)
  if (c && registry.available(c) && (!c.enabled || c.enabled())) c.run(arg)
}

/** The translated title of a command (its `titleArgs` filled in) */
export const commandTitle = (c: Command, t: (key: string, args?: Record<string, string>) => string) => t(c.title, c.titleArgs)

/** Other commands bound to `chord` (Settings asks before taking it from them; tests keep the
 *  defaults free of clashes) */
export function keyConflicts(chord: string, except?: string): Command[] {
  return [...registry.commands.values()].filter((c) => c.id !== except && bindingOf(c) === chord)
}

/** Shortcut filters (Settings, Keyboard shortcuts): a command matches by its title or its keys */
export function commandMatches(c: Command, query: string, t: (key: string, args?: Record<string, string>) => string): boolean {
  const q = query.trim().toLowerCase()
  return !q || commandTitle(c, t).toLowerCase().includes(q) || formatChord(bindingOf(c)).toLowerCase().includes(q)
}
