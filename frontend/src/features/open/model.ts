// Open mode records (SRC-09): an OpenItem shown through the project viewer's item shape.
import type { ItemRecord, LabelDef, OpenItem } from '../../api'

/** Auto label colours for a label map without a project label map (VW-21: `label_{value}`) */
const AUTO = ['#00FFFF', '#FFFF00', '#FF00FF', '#00FF00', '#FF8000', '#0080FF', '#FF0040', '#80FF00']
export const autoLabels = (n = 16): LabelDef[] =>
  Array.from({ length: n }, (_, k) => ({ value: k + 1, name: `label_${k + 1}`, color: AUTO[k % AUTO.length] ?? '#FFFFFF', opacity: 0.35, visible: true }))

/**
 * `modality`: Open mode knows it only from DICOM; otherwise `OT` so W/L uses percentiles, not HU
 * presets (VW-05). A label shown alone is its own image and overlay (VW-21).
 */
export function toItemRecord(it: OpenItem, mask: OpenItem | null): ItemRecord {
  const g = it.geometry
  const ref = { ref: it.rel, format: 'nifti' as const, fp: null, sha256: null }
  const maskRef = mask ? { ref: mask.rel, format: 'nifti' as const, fp: null, sha256: null } : it.kind === 'label' ? ref : null
  return {
    item_id: it.item_id,
    case_id: 'open',
    scan_idx: String(it.n),
    scope: 'complete',
    side: '-',
    patient_id: null,
    modality: it.modality ?? 'OT',
    phase: { canonical: 'UNK', raw: null, source: 'none' },
    image: ref,
    masks: maskRef ? { open: maskRef } : {},
    mask: maskRef,
    geometry: g ? { shape: g.shape, spacing: g.spacing, dtype: g.dtype, orientation: g.orientation ?? null } : null,
    labels_present: [],
    status: 'active',
    warning_codes: [],
    import_id: 'open',
    extra: {},
  }
}

/** The label attached to item n last (SRC-10), if any */
export const attachedTo = (items: OpenItem[], n: number) => [...items].reverse().find((i) => i.attached_to === n) ?? null
