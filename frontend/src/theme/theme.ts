// Theme resolution (UI-11): GitHub Dark by default; Light or follow-the-OS on request.
export type ThemeChoice = 'dark' | 'light' | 'system'

export function resolveTheme(choice: ThemeChoice): 'dark' | 'light' {
  if (choice !== 'system') return choice
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolveTheme(choice)
}

/** Read a token value at runtime (charts and canvases cannot use var()). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
