// Open mode records (SRC-09): an OpenItem shown through the project viewer's item shape.
import type { ItemRecord, LabelDef, OpenItem } from '../../api'

/** Auto label colours for a label map without a project label map (VW-21: `label_{value}`) */
const AUTO = ['#00FFFF', '#FFFF00', '#FF00FF', '#00FF00', '#FF8000', '#0080FF', '#FF0040', '#80FF00']
export const autoLabels = (n = 16): LabelDef[] =>
  Array.from({ length: n }, (_, k) => ({ value: k + 1, name: `label_${k + 1}`, color: AUTO[k % AUTO.length] ?? '#FFFFFF', opacity: 0.35, visible: true }))

/**
 * `modality`: Open mode knows it only from DICOM; otherwise `null`, which the viewer assumes to be CT
 * and lets the user change (VW-05). An opened file is always an image; its overlay is only a
 * segmentation attached to it (SRC-10).
 */
export function toItemRecord(it: OpenItem, mask: OpenItem | null): ItemRecord {
  const g = it.geometry
  const ref = { ref: it.rel, format: 'nifti' as const, fp: null, sha256: null }
  const maskRef = mask ? { ref: mask.rel, format: 'nifti' as const, fp: null, sha256: null } : null
  return {
    item_id: it.item_id,
    case_id: 'open',
    scan_idx: String(it.n),
    scope: 'complete',
    side: '-',
    patient_id: null,
    modality: it.modality ?? null,
    phase: { canonical: 'UNK', raw: null, source: 'none' },
    image: ref,
    masks: maskRef ? { open: maskRef } : {},
    mask: maskRef,
    geometry: g ? { shape: g.shape, spacing: g.spacing, dtype: g.dtype, orientation: g.orientation ?? null } : null,
    labels_present: [],
    status: 'active',
    warning_codes: [],
    import_id: 'open',
    // VW-22: the DICOM header window, read by the viewer like converter row facts
    extra: it.window ? { window_width: it.window[0], window_center: it.window[1] } : {},
  }
}

/** The label attached to item n last (SRC-10), if any */
export const attachedTo = (items: OpenItem[], n: number) => [...items].reverse().find((i) => i.attached_to === n) ?? null
