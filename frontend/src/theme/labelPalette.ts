// Auto label colours (PRJ-07, VW-21; AUD-A3-17): one palette for label files without colours and
// for Open-mode label maps, the same order as the backend's preset (`projects/presets.py`).
// Label colours are data drawn on the black viewport, so they are not theme tokens.
export const LABEL_PALETTE = ['#00FFFF', '#FFFF00', '#FF00FF', '#00FF00', '#FF8000', '#0080FF', '#FF0000', '#8000FF'] as const

/** Colour of label `value` (1-based) */
export const autoLabelColor = (value: number): string => LABEL_PALETTE[(Math.max(1, value) - 1) % LABEL_PALETTE.length] ?? LABEL_PALETTE[0]
