// @vitest-environment jsdom
// UI-01, FE-08: F6 / Shift+F6 move focus between the workbench regions in reading order and
// skip a hidden region.
import { EDITOR_REGION_ID, focusRegion } from './regions'

function shell({ panel = true } = {}) {
  document.body.innerHTML = `
    <div class="wb">
      <header class="titlebar"><button>switcher</button></header>
      <div class="wb-main">
        <aside class="sidebar"><input aria-label="filter" /></aside>
        <div class="wb-center">
          <main id="${EDITOR_REGION_ID}" tabindex="-1"></main>
          ${panel ? '<section class="panel"></section>' : ''}
        </div>
        <aside class="inspector"></aside>
      </div>
    </div>`
}
const focused = () => document.activeElement?.className || document.activeElement?.id

test('F6 walks title bar, left pane, editor, panel, inspector and wraps (UI-01)', () => {
  shell()
  const order: (string | undefined)[] = []
  for (let i = 0; i < 6; i++) {
    focusRegion(1)
    order.push(focused())
  }
  expect(order).toEqual(['titlebar', 'sidebar', EDITOR_REGION_ID, 'panel', 'inspector', 'titlebar'])
})

test('Shift+F6 goes back; focus inside a region counts as that region; a hidden panel is skipped (UI-01)', () => {
  shell({ panel: false })
  focusRegion(-1)
  expect(focused()).toBe('inspector')
  document.querySelector<HTMLInputElement>('.sidebar input')?.focus()
  focusRegion(1)
  expect(focused()).toBe(EDITOR_REGION_ID)
  focusRegion(1)
  expect(focused()).toBe('inspector')
  focusRegion(-1)
  expect(focused()).toBe(EDITOR_REGION_ID)
})
