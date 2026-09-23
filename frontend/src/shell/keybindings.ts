// Keybinding dispatch (UI_SHELL §Default keybindings, UI-12). `mod` = Cmd on macOS, Ctrl elsewhere.
import { useEffect } from 'react'

import { useSettings, useViewerSync } from '../state'
import { registry, type Command } from './registry'

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

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
    ? { mod: '⌘', shift: '⇧', alt: '⌥', ctrl: '⌃', down: '↓', up: '↑', esc: 'Esc', space: 'Space' }
    : { mod: 'Ctrl', shift: 'Shift', alt: 'Alt', down: '↓', up: '↑', esc: 'Esc', space: 'Space' }
  const out = parts.map((p) => map[p] ?? p.toUpperCase())
  return isMac ? out.join('') : out.join('+')
}

function inTextField(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

export function useGlobalKeybindings() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat && !e.altKey) return
      if ((e.target as HTMLElement | null)?.dataset?.keyrecorder) return
      const chord = chordOf(e)
      const typing = inTextField(e.target)
      const viewerFocused = useViewerSync.getState().viewerFocused
      for (const c of registry.commands.values()) {
        if (bindingOf(c) !== chord) continue
        if (c.when === 'viewer' && (!viewerFocused || typing)) continue
        // Plain keys never fire while typing; chords with a modifier or F-keys do
        if (typing && !/mod|alt|ctrl|^f\d/.test(chord)) continue
        if (c.enabled && !c.enabled()) continue
        e.preventDefault()
        e.stopPropagation()
        c.run()
        return
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])
}

export function runCommand(id: string) {
  const c = registry.commands.get(id)
  if (c && (!c.enabled || c.enabled())) c.run()
}
