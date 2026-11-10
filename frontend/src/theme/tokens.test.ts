// UI-11 (AUD-A3-17): colours come only from theme tokens. A stand-in for a stylelint
// `color-no-hex` rule (no new dependency): no hex / rgb() / hsl() colour in any stylesheet outside
// theme/, and no hex colour literal in a component (label colours are data in theme/labelPalette).
// UI-27 (AUD-A3-16): every interface size defines the same size tokens.
// `?cssraw`: the stylesheet text (vitest.config.ts; plain `?raw` CSS is empty under Vitest)
const css = import.meta.glob(['../**/*.css', '!./**'], { query: '?cssraw', import: 'default', eager: true }) as Record<string, string>
const tokens = (import.meta.glob('./tokens.css', { query: '?cssraw', import: 'default', eager: true }) as Record<string, string>)['./tokens.css'] ?? ''
const tsx = import.meta.glob(['../**/*.tsx', '!./**', '!../**/*.test.tsx', '!../api/mock/**'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

const HEX = /#[0-9A-Fa-f]{3,8}\b/
const FUNC = /\b(?:rgba?|hsla?)\(/

test('no raw colours outside theme/', () => {
  expect(Object.keys(css).length).toBeGreaterThan(10)
  expect(Object.values(css).every((src) => src.length > 0)).toBe(true)
  const hits: string[] = []
  for (const [file, src] of Object.entries(css))
    src.split('\n').forEach((line, i) => {
      const code = line.replace(/\/\*.*?\*\//g, '')
      if (HEX.test(code) || FUNC.test(code)) hits.push(`${file}:${i + 1}: ${line.trim()}`)
    })
  for (const [file, src] of Object.entries(tsx))
    src.split('\n').forEach((line, i) => {
      if (/['"`]#[0-9A-Fa-f]{3,8}['"`]/.test(line)) hits.push(`${file}:${i + 1}: ${line.trim()}`)
    })
  expect(hits).toEqual([])
})

test('every interface size sets the same font and height tokens', () => {
  const block = (sel: string) => {
    const at = tokens.indexOf(sel)
    return at < 0 ? '' : tokens.slice(at, tokens.indexOf('}', at))
  }
  const names = (b: string) => [...b.matchAll(/(--(?:fs|h)-[a-z-]+):/g)].map((m) => m[1]).sort()
  const compact = names(block(':root[data-size="compact"]'))
  const large = names(block(':root[data-size="large"]'))
  expect(compact.length).toBeGreaterThan(10)
  expect(large).toEqual(expect.arrayContaining(compact))
  expect(block(':root[data-size="compact"]')).toContain('--fs-ui: 13px')
  expect(block(':root {')).toContain('--fs-ui: 14px')
})

// UI-16 (AUD-A3-18): reduced motion zeroes the durations and stops the codicon spinners
test('reduced motion stops the spinners', () => {
  const at = tokens.indexOf('@media (prefers-reduced-motion: reduce)')
  const block = tokens.slice(at)
  expect(at).toBeGreaterThan(0)
  expect(block).toContain('--dur-base: 0ms')
  expect(block).toMatch(/\.codicon-modifier-spin[^{]*\{\s*animation: none/)
})

// UI-06 (AUD-A3-02): the pressed toggle has its own token in both themes, never the blue focus colour
test('a pressed toggle uses --bg-pressed in both themes', () => {
  expect(tokens.match(/--bg-pressed: #[0-9A-F]{6}/g)).toHaveLength(2)
  const base = (import.meta.glob('./base.css', { query: '?cssraw', import: 'default', eager: true }) as Record<string, string>)['./base.css'] ?? ''
  const pressed = base.slice(base.indexOf(".icon-btn[aria-pressed='true']"), base.indexOf('}', base.indexOf(".icon-btn[aria-pressed='true']")))
  expect(pressed).toContain('background: var(--bg-pressed)')
  expect(pressed).not.toMatch(/--focus|--accent|box-shadow/)
})

// WCAG relative luminance and contrast of #RRGGBB colours; an #RRGGBBAA token is first laid
// over the surface it sits on
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}
const ratio = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi! + 0.05) / (lo! + 0.05)
}
const over = (colour: string, surface: string) => {
  if (colour.length === 7) return colour
  const a = parseInt(colour.slice(7, 9), 16) / 255
  return `#${[1, 3, 5].map((i) => Math.round(a * parseInt(colour.slice(i, i + 2), 16) + (1 - a) * parseInt(surface.slice(i, i + 2), 16)).toString(16).padStart(2, '0')).join('')}`
}
const themeColours = (selector: string) => {
  const at = tokens.indexOf(selector)
  const block = tokens.slice(at, tokens.indexOf('}', at))
  return Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+): (#[0-9A-Fa-f]{6,8})\b/g)].map((m) => [m[1]!, m[2]!])) as Record<string, string>
}

// UI-11: the destructive confirm is a filled red that keeps white text at >= 4.5:1 in both themes
test('the danger button keeps its text readable in both themes', () => {
  const fills = [...tokens.matchAll(/--btn-danger(?:-hover)?: (#[0-9A-F]{6})/g)].map((m) => m[1]!)
  expect(fills).toHaveLength(4)
  for (const fill of fills) expect(ratio(fill, '#FFFFFF')).toBeGreaterThanOrEqual(4.5)
})

// UI-11 (contrast by construction): every text colour is >= 4.5:1 on every surface, on hover, on a
// secondary button (kbd hints) and on a selected row; control boundaries (--border-control) and the
// pressed toggle are >= 3:1 against what surrounds them, and the pressed toggle's icon >= 3:1
test('text, control boundaries and pressed toggles keep their contrast in both themes', () => {
  const dark = themeColours(':root[data-theme="dark"]')
  const light = { ...dark, ...themeColours(':root[data-theme="light"]') }
  const surfaces = ['--bg-editor', '--bg-sidebar', '--bg-panel', '--bg-overlay', '--bg-input', '--bg-hover', '--btn-secondary', '--btn-secondary-hover']
  const lists = ['--bg-editor', '--bg-sidebar', '--bg-panel', '--bg-overlay', '--bg-hover']
  const low: string[] = []
  for (const [theme, c] of [['dark', dark], ['light', light]] as const) {
    const grounds = [...surfaces.map((s) => [s, c[s]!]), ...lists.flatMap((s) => [[`selected row on ${s}`, over(c['--bg-selected']!, c[s]!)], [`--danger-bg on ${s}`, over(c['--danger-bg']!, c[s]!)]])]
    for (const text of ['--fg', '--fg-muted', '--accent', '--ok', '--warn', '--error', '--done'])
      for (const [where, ground] of grounds) if (ratio(c[text]!, ground!) < 4.5) low.push(`${theme}: ${text} on ${where}`)
    for (const s of surfaces) if (ratio(c['--border-control']!, c[s]!) < 3) low.push(`${theme}: --border-control on ${s}`)
    for (const s of ['--bg-editor', '--bg-sidebar', '--bg-statusbar', '--bg-hover']) if (ratio(c['--bg-pressed']!, c[s]!) < 3) low.push(`${theme}: --bg-pressed on ${s}`)
    if (ratio(c['--fg']!, c['--bg-pressed']!) < 3) low.push(`${theme}: --fg icon on --bg-pressed`)
    // filled controls: their --fg-on-emphasis text, and the focus ring drawn in that colour
    for (const fill of ['--btn-primary', '--btn-primary-hover', '--btn-danger', '--btn-danger-hover', '--focus', '--warn-emphasis'])
      if (ratio(c['--fg-on-emphasis']!, c[fill]!) < 4.5) low.push(`${theme}: --fg-on-emphasis on ${fill}`)
    if (ratio(c['--fg-on-emphasis']!, c['--bg-pressed']!) < 3) low.push(`${theme}: focus ring on --bg-pressed`)
  }
  expect(low).toEqual([])
  for (const [file, src] of Object.entries(css))
    for (const rule of src.match(/[^{}]*\{[^{}]*color: var\(--fg-on-emphasis\)[^{}]*\}/g) ?? [])
      expect(rule, file).not.toMatch(/background: var\(--(accent|ok|warn|error|done)\)/)
  // controls are bounded by the control border, dividers keep the quiet one
  const base = (import.meta.glob('./base.css', { query: '?cssraw', import: 'default', eager: true }) as Record<string, string>)['./base.css'] ?? ''
  for (const rule of ['.btn {', '.input,\n.select {', '.seg {']) {
    const at = base.indexOf(rule)
    expect(base.slice(at, base.indexOf('}', at))).toContain('var(--border-control)')
  }
})
