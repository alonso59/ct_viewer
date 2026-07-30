export interface LayerStyle {
  color: string
  defaultOpacity: number
  label: string
}

export interface LayerVisibilityState {
  opacity: number
  visible: boolean
}

export type LayerState = Record<number, LayerVisibilityState>

export const BASE_SEGMENTATION_META: Record<number, LayerStyle> = {
  1: { label: 'Kidney', color: '#22d3ee', defaultOpacity: 0.15 },
  2: { label: 'Tumor', color: '#facc15', defaultOpacity: 0.2 },
  3: { label: 'Cyst', color: '#e879f9', defaultOpacity: 0.15 },
}

const EXTRA_SEGMENTATION_COLORS = [
  '#60a5fa',
  '#fb7185',
  '#34d399',
  '#f97316',
  '#a78bfa',
  '#2dd4bf',
  '#f472b6',
  '#84cc16',
  '#f59e0b',
  '#c084fc',
  '#f43f5e',
  '#38bdf8',
]

function validLabel(label: number): boolean {
  return Number.isInteger(label) && label > 0
}

function normalizeOpacity(value: number | undefined, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return fallback
  }
  return Math.min(1, Math.max(0, value))
}

export function getSegmentationColor(label: number): string {
  return (
    BASE_SEGMENTATION_META[label]?.color ??
    EXTRA_SEGMENTATION_COLORS[Math.abs(label - 4) % EXTRA_SEGMENTATION_COLORS.length]
  )
}

export function isBaseSegmentationLabel(label: number): boolean {
  return Boolean(BASE_SEGMENTATION_META[label])
}

export function getSegmentationLabel(label: number): string {
  return BASE_SEGMENTATION_META[label]?.label ?? `Label ${label}`
}

export function getSegmentationDefaultOpacity(label: number): number {
  return BASE_SEGMENTATION_META[label]?.defaultOpacity ?? 0.14
}

export function createDefaultLayerState(): LayerState {
  return {
    1: { visible: true, opacity: BASE_SEGMENTATION_META[1].defaultOpacity },
    2: { visible: true, opacity: BASE_SEGMENTATION_META[2].defaultOpacity },
    3: { visible: false, opacity: BASE_SEGMENTATION_META[3].defaultOpacity },
  }
}

export function layerStateFromSettings(
  visibleLayers: number[],
  opacityByLabel: Record<string, number>,
): LayerState {
  const state = createDefaultLayerState()
  const persistedLabels = new Set<number>()

  visibleLayers.forEach((label) => {
    if (validLabel(label)) {
      persistedLabels.add(label)
    }
  })
  Object.keys(opacityByLabel).forEach((labelKey) => {
    const label = Number(labelKey)
    if (validLabel(label)) {
      persistedLabels.add(label)
    }
  })

  persistedLabels.forEach((label) => {
    state[label] = {
      visible: visibleLayers.includes(label),
      opacity: normalizeOpacity(opacityByLabel[String(label)], getSegmentationDefaultOpacity(label)),
    }
  })

  return state
}

export function ensureLayerStateForLabels(current: LayerState, labels: number[]): LayerState {
  let changed = false
  const next: LayerState = { ...current }

  labels.forEach((label) => {
    if (!validLabel(label) || next[label]) {
      return
    }
    next[label] = {
      visible: true,
      opacity: getSegmentationDefaultOpacity(label),
    }
    changed = true
  })

  return changed ? next : current
}

export function getLayerStateEntry(layerState: LayerState, label: number): LayerVisibilityState {
  return (
    layerState[label] ?? {
      visible: false,
      opacity: getSegmentationDefaultOpacity(label),
    }
  )
}

export function layerColorsForLabels(labels: number[]): Record<number, string> {
  return Object.fromEntries(labels.map((label) => [label, getSegmentationColor(label)]))
}

export function layerOpacitiesForLabels(
  labels: number[],
  layerState: LayerState,
): Record<number, number> {
  return Object.fromEntries(
    labels.map((label) => [
      label,
      getLayerStateEntry(layerState, label).opacity,
    ]),
  )
}

export function sortedLayerLabels(labels: number[]): number[] {
  return [...labels].sort((left, right) => left - right)
}
