// Theme resolution (UI-11): Dark by default; Light or follow-the-OS on request. Interface size (UI-27).
export type ThemeChoice = 'dark' | 'light' | 'system'
export type InterfaceSize = 'compact' | 'default' | 'large'
export const INTERFACE_SIZES: readonly InterfaceSize[] = ['compact', 'default', 'large']

export function resolveTheme(choice: ThemeChoice): 'dark' | 'light' {
  if (choice !== 'system') return choice
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolveTheme(choice)
}

/** UI-27: `<html data-size>` selects the size set in tokens.css; Default has no attribute */
export function applySize(size: InterfaceSize) {
  const root = document.documentElement
  if (size === 'default') delete root.dataset.size
  else root.dataset.size = size
}

/** Read a token value at runtime (charts and canvases cannot use var()). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** A length token in px (e.g. a row height for a virtual list); `fallback` outside a browser */
export function tokenPx(name: string, fallback: number): number {
  const px = Number.parseFloat(token(name))
  return Number.isFinite(px) && px > 0 ? px : fallback
}
