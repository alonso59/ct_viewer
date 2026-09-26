// VW-08 / VW-22 cursor readout, one format for the status bar and the in-view probe (AUD-A2-11,
// AUD-A3-05): value with its unit (HU for CT, "value" otherwise, VW-05) · label name (value) ·
// ijk · RAS mm.
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { useViewerSync, type CursorReadout } from '../../state'
import { isCt } from './model/wl'

export interface ReadoutOptions {
  /** The visible item's effective modality (VW-05); unknown reads as CT */
  modality: string | null | undefined
  /** Show "label —" when the voxel has no label (the status bar keeps a stable width) */
  emptyLabel?: boolean
}

export function cursorParts(c: CursorReadout, { modality, emptyLabel = false }: ReadoutOptions, t: TFunction): string[] {
  const value = isCt({ modality: modality ?? null }) ? t('readout.hu', { v: c.value }) : t('readout.value', { v: c.value })
  const label = c.label ? t('readout.label', { name: c.labelName ?? t('readout.labelAuto', { n: c.label }), n: c.label }) : emptyLabel ? t('readout.noLabel') : null
  return [value, ...(label ? [label] : []), t('readout.ijk', { ijk: c.ijk.join(', ') }), t('readout.ras', { ras: c.ras.join(', ') })]
}

/** The readout of the store's cursor, or null when the pointer is outside the views */
export function useCursorText(emptyLabel = false): string | null {
  const { t } = useTranslation()
  const cursor = useViewerSync((s) => s.cursor)
  const modality = useViewerSync((s) => s.activeModality?.value)
  return cursor ? cursorParts(cursor, { modality, emptyLabel }, t).join(' · ') : null
}
