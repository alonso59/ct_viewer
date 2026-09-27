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
  // Compact is the P7 scale (13 px UI); Default raises the base to 14 px
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
