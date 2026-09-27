// Open mode records (SRC-09): an OpenItem shown through the project viewer's item shape.
import type { ItemRecord, LabelDef, OpenItem, OpenSession } from '../../api'
import { autoLabelColor } from '../../theme'

/** Auto label colours for a label map without a project label map (VW-21: `label_{value}`) */
export const autoLabels = (n = 16): LabelDef[] =>
  Array.from({ length: n }, (_, k) => ({ value: k + 1, name: `label_${k + 1}`, color: autoLabelColor(k + 1), opacity: 0.35, visible: true }))

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

const join = (root: string, rel: string) => (rel.startsWith('/') ? rel : `${root.replace(/\/+$/, '')}/${rel}`)
const dirOf = (p: string) => p.slice(0, p.lastIndexOf('/')) || '/'

/** Absolute path of an item: attachments outside the session root keep an absolute `rel` (ADR-0027) */
export const itemPath = (s: Pick<OpenSession, 'root'>, it: Pick<OpenItem, 'rel'>) => join(s.root, it.rel)

function commonDir(a: string, b: string): string {
  const x = dirOf(a).split('/')
  const y = dirOf(b).split('/')
  let n = 0
  while (n < x.length && n < y.length && x[n] === y[n]) n++
  return x.slice(0, n).join('/') || '/'
}

/**
 * "Create project from this" / "Add to project…" (SRC-05/15): the open path, or, with an attached
 * segmentation, the folder holding both files with an include list and the image → mask pair, so
 * the mask becomes the item's segmentation (`nifti-files` `masks`, ADR-0027, AUD-A2-12).
 */
export function importSource(s: Pick<OpenSession, 'root'>, item: Pick<OpenItem, 'rel' | 'format'>, mask: Pick<OpenItem, 'rel'> | null, path: string) {
  if (!mask || item.format !== 'nifti') return { path }
  const img = itemPath(s, item)
  const seg = itemPath(s, mask)
  const root = commonDir(img, seg)
  const rel = (p: string) => p.slice(root === '/' ? 1 : root.length + 1)
  return { path: root, adapter: 'nifti-files', options: { include: [rel(img), rel(seg)], masks: { [rel(img)]: rel(seg) } } }
}

/** Folder names that usually hold the segmentations next to the images (SRC-10 attach browser) */
export const MASK_DIR = /^(seg|segs|segmentations?|labels\w*|masks?)$/i

/** Where the attach browser starts: a mask folder inside the opened folder or next to it, else the root */
export function attachStart(root: string, inRoot: string[], besideRoot: string[]): string {
  const here = inRoot.find((n) => MASK_DIR.test(n))
  if (here) return join(root, here)
  const sib = besideRoot.find((n) => MASK_DIR.test(n))
  return sib ? join(dirOf(root), sib) : root
}
