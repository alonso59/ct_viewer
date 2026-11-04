// The imaging modality of an item as the GUI shows it (VW-05): a DICOM code, known or assumed.
import type { TFunction } from 'i18next'

import type { ItemRecord } from '../api'

/** Modalities the user can pick when the item has none; `OT` = other (percentile window) */
export const MODALITY_CHOICES = ['CT', 'MR', 'OT'] as const

/** Identity of an item for the display-only modality choice (Open-mode ids repeat across sessions) */
export const modalityKey = (item: Pick<ItemRecord, 'item_id' | 'case_id' | 'image'>): string =>
  `${item.case_id}|${item.item_id}|${item.image?.ref ?? ''}`

/** A known modality wins; an unknown one is the user's choice, else the project default
 *  (`mixed` assumes CT), else assumed CT */
export function effectiveModality(
  item: Pick<ItemRecord, 'item_id' | 'case_id' | 'image' | 'modality'>,
  overrides: Record<string, string>,
  fallback = 'CT',
): { value: string; assumed: boolean } {
  const known = typeof item.modality === 'string' && item.modality.trim() !== '' ? item.modality.trim().toUpperCase() : null
  if (known) return { value: known, assumed: false }
  return { value: overrides[modalityKey(item)] ?? (fallback === 'MR' ? 'MR' : 'CT'), assumed: true }
}

/** `Item.image_component` worth naming next to the modality (magnitude is the usual MR image) */
export const namedComponent = (item: Pick<ItemRecord, 'image_component'>): string | null =>
  item.image_component && item.image_component !== 'MAGNITUDE' ? item.image_component : null

/** The badge text: "CT", "MR", "MR · Phase", "Other" */
export function modalityText(t: TFunction, value: string, component: string | null = null): string {
  const name = t(`viewer.modality.${value}`, { defaultValue: value })
  return component ? `${name} · ${t(`viewer.component.${component}`, { defaultValue: component })}` : name
}
