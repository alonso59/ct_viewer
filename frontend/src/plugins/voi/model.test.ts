import { describe, expect, it } from 'vitest'

import { activeLabels, boxMode, chosenLabels, dropOverrides, effectiveBox, flaggedScan, fmtSize, isExcluded, isSwapped, namesSide, needsReview, orphanOverrides, overridesOf, reviewCounts, shownSide, sideConfidence, sideSource, skipExistingOf, toggleExclude, toggleSwap, withBoxMode } from './model'

const kidney = { labels: ['kidney', 'kidney_left', 'kidney_right', 'tumor', 'cyst'], organ: ['kidney', 'kidney_left', 'kidney_right'], margin_mm: 5, min_size_mm: [96, 96, 120] }

describe('voi model', () => {
  it('swaps only lateral sides', () => {
    expect(shownSide({ side: 'L' }, true)).toBe('R')
    expect(shownSide({ side: 'R' }, false)).toBe('R')
    expect(shownSide({ side: '' }, true)).toBe('')
  })

  it('keeps decisions in the settings as overrides, dropping empty ones', () => {
    let v: Record<string, unknown> = { region: 'kidney' }
    v = toggleSwap(v, 'a')
    v = toggleExclude(v, 'c', 'L')
    expect(isSwapped(v, 'a')).toBe(true)
    expect(isExcluded(v, 'c', 'L')).toBe(true)
    expect(overridesOf(v)).toEqual([
      { item_id: 'a', swap: true },
      { item_id: 'c', exclude: ['L'] },
    ])
    v = toggleSwap(v, 'a')
    v = toggleExclude(v, 'c', 'L')
    expect(v).toEqual({ region: 'kidney' })
  })

  it('finds decisions that no longer apply and drops them', () => {
    const v = toggleExclude(toggleSwap({}, 'gone'), 'b', 'V1')
    const found = new Map([['b', ['L', 'R']]])
    const orphans = orphanOverrides(v, new Set(['b', 'c']), found)
    expect(orphans.map((o) => o.item_id)).toEqual(['gone', 'b'])
    expect(orphanOverrides(v, new Set(['gone', 'b']), new Map())).toEqual([]) // b still loading: not judged
    expect(overridesOf(dropOverrides(v, orphans))).toEqual([])
  })

  it('lists the labels still active in the segmentation set', () => {
    const map = [
      { value: 1, name: 'kidney', color: '#f00', opacity: 1, visible: true },
      { value: 2, name: 'tumor', color: '#0f0', opacity: 1, visible: true },
      { value: 3, name: 'lung', color: '#00f', opacity: 1, visible: true },
    ]
    const names = (set?: { label_mapping?: Record<string, number>; removed_labels?: number[] }) => activeLabels(map, set).map((l) => l.name)
    expect(names()).toEqual(['kidney', 'tumor', 'lung'])
    expect(names({ label_mapping: { '1': 1, '2': 2, '3': 3 }, removed_labels: [3] })).toEqual(['kidney', 'tumor'])
    expect(names({ label_mapping: { '5': 3 } })).toEqual(['lung'])
  })

  it('takes the region labels only when the set has the organ', () => {
    expect(chosenLabels({}, kidney, ['Kidney_Left', 'kidney_right', 'tumor', 'liver'])).toEqual(['Kidney_Left', 'kidney_right', 'tumor'])
    expect(chosenLabels({}, kidney, ['tumor', 'liver'])).toEqual([])
    expect(chosenLabels({ labels: ['liver', 'gone'] }, kidney, ['tumor', 'liver'])).toEqual(['liver'])
    expect(namesSide('kidney_left')).toBe(true)
    expect(namesSide('kidney')).toBe(false)
    expect(sideSource({ warnings: [] }, ['kidney_left'])).toBe('names')
    expect(sideSource({ warnings: [] }, ['kidney'])).toBe('position')
    expect(sideSource({ warnings: ['sides_from_anatomy'] }, ['kidney_left'])).toBe('anatomy')
  })

  it('skips scans that already have VOIs unless the reviewer turns it off', () => {
    expect(skipExistingOf({})).toBe(true)
    expect(skipExistingOf({ skip_existing: false })).toBe(false)
  })

  it('reads and sets the box preset', () => {
    expect(boxMode({})).toBe('recommended')
    expect(boxMode({ margin_mm: 0, min_size_mm: [0, 0, 0] })).toBe('tight')
    expect(boxMode({ margin_mm: 5 })).toBe('custom')
    expect(effectiveBox({}, kidney)).toEqual({ margin: 5, size: [96, 96, 120] })
    expect(withBoxMode({ region: 'kidney', margin_mm: 2 }, 'recommended', kidney)).toEqual({ region: 'kidney' })
    expect(withBoxMode({}, 'tight', kidney)).toEqual({ margin_mm: 0, min_size_mm: [0, 0, 0] })
    expect(withBoxMode({}, 'custom', kidney)).toEqual({ margin_mm: 5, min_size_mm: [96, 96, 120] })
  })

  it('counts what the reviewer sees', () => {
    const f = (id: string, uncertain: boolean, warned = false) => ({ id, uncertain, warned })
    const items = [
      { itemId: 'a', failed: false, cands: [f('L', false), f('R', true)] },
      { itemId: 'b', failed: false, cands: [f('L', false, true)] },
      { itemId: 'c', failed: true },
      { itemId: 'd', failed: false },
    ]
    const v = toggleExclude({}, 'b', 'L')
    expect(reviewCounts(v, items)).toEqual({ scans: 4, prepared: 2, failed: 1, vois: 3, included: 2, excluded: 1, uncertain: 1, warnings: 1, needsReview: 2 })
    expect(reviewCounts(toggleSwap(v, 'a'), items).uncertain).toBe(0) // a swapped side is the reviewer's
    expect(flaggedScan([f('L', false)])).toBe(false)
    expect(flaggedScan(undefined)).toBe(false)
    expect(needsReview({ side: 'L', confidence: 'verified', warnings: [] })).toBe(false)
  })

  it('formats sizes and shows a reviewer swap instead of the engine confidence', () => {
    expect(fmtSize([96.4, 96, 120.6])).toBe('96 × 96 × 121 mm')
    expect(sideConfidence('uncertain', true)).toBe('reviewer')
    expect(sideConfidence('verified', false)).toBe('verified')
    expect(sideConfidence('', true)).toBe('')
  })
})
