// F6 / Shift+F6 move focus between the workbench regions, in reading order; a hidden region is
// skipped. The region itself takes focus (Tab then enters it), so it is announced as a landmark.
export const EDITOR_REGION_ID = 'workbench-editor'

const REGIONS = ['.wb > .titlebar', '.wb-main > .sidebar', `#${EDITOR_REGION_ID}`, '.wb-center > .panel', '.wb-main > .inspector']

/** Focus the region after (1) or before (-1) the one that holds focus */
export function focusRegion(step: 1 | -1) {
  const shown = REGIONS.map((s) => document.querySelector<HTMLElement>(s)).filter((el): el is HTMLElement => el !== null)
  if (!shown.length) return
  const at = shown.findIndex((el) => el.contains(document.activeElement))
  const next = shown[at === -1 ? (step > 0 ? 0 : shown.length - 1) : (at + step + shown.length) % shown.length]
  if (!next) return
  if (!next.hasAttribute('tabindex')) next.setAttribute('tabindex', '-1')
  next.focus()
}
