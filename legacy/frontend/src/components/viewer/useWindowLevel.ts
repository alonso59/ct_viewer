import { useState } from 'react'

export const WINDOW_LEVEL_PRESETS = {
  softTissue: { label: 'Soft Tissue', min: -150, max: 250 },
  bone: { label: 'Bone', min: -600, max: 1400 },
  lung: { label: 'Lung', min: -1350, max: 150 },
  brain: { label: 'Brain', min: 0, max: 80 },
  kidney: { label: 'Kidney', min: -45, max: 105 },
  pancreas: { label: 'Pancreas', min: -110, max: 190 },
} as const

export type WindowLevelPreset = keyof typeof WINDOW_LEVEL_PRESETS
export type WindowLevelMode = WindowLevelPreset | 'custom'

function clampWidth(value: number): number {
  return Math.max(1, Math.round(value))
}

function clampLevel(value: number): number {
  return Math.round(value)
}

function getWindowLevelFromRange(minHu: number, maxHu: number) {
  const min = Math.round(minHu)
  const max = Math.max(min + 1, Math.round(maxHu))
  return {
    minHu: min,
    maxHu: max,
    ww: clampWidth(max - min),
    wl: clampLevel((min + max) / 2),
  }
}

function getRangeFromWindowLevel(ww: number, wl: number) {
  const width = clampWidth(ww)
  const level = clampLevel(wl)
  return {
    minHu: Math.round(level - width / 2),
    maxHu: Math.round(level + width / 2),
    ww: width,
    wl: level,
  }
}

function findPresetForRange(minHu: number, maxHu: number): WindowLevelMode {
  const match = (Object.keys(WINDOW_LEVEL_PRESETS) as WindowLevelPreset[]).find((preset) => {
    const range = WINDOW_LEVEL_PRESETS[preset]
    return range.min === minHu && range.max === maxHu
  })
  return match ?? 'custom'
}

export function useWindowLevel() {
  const [state, setState] = useState<{
    activePreset: WindowLevelMode
    minHu: number
    maxHu: number
    ww: number
    wl: number
  }>(() => {
    const preset = WINDOW_LEVEL_PRESETS.softTissue
    return {
      activePreset: 'softTissue',
      ...getWindowLevelFromRange(preset.min, preset.max),
    }
  })

  function applyPreset(preset: WindowLevelPreset) {
    const range = WINDOW_LEVEL_PRESETS[preset]
    setState({
      activePreset: preset,
      ...getWindowLevelFromRange(range.min, range.max),
    })
  }

  function setWindowRange(minHu: number, maxHu: number) {
    const range = getWindowLevelFromRange(minHu, maxHu)
    setState({
      activePreset: 'custom',
      ...range,
    })
  }

  function setWindowLevel(ww: number, wl: number) {
    const range = getRangeFromWindowLevel(ww, wl)
    setState({
      activePreset: findPresetForRange(range.minHu, range.maxHu),
      ...range,
    })
  }

  function applyDrag(startWw: number, startWl: number, deltaX: number, deltaY: number) {
    const range = getRangeFromWindowLevel(startWw + deltaX * 6, startWl - deltaY * 3)
    setState({
      activePreset: 'custom',
      ...range,
    })
  }

  return {
    activePreset: state.activePreset,
    applyDrag,
    applyPreset,
    maxHu: state.maxHu,
    minHu: state.minHu,
    presets: WINDOW_LEVEL_PRESETS,
    setWindowLevel,
    setWindowRange,
    wl: state.wl,
    ww: state.ww,
  }
}
