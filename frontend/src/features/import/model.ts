// Import wizard model (IMP-01..05, SRC-01..06; AUD-A6-07): the pure rules of the four steps, so
// the wizard component only wires state to them and each step renders its own part.
import type { DetectCandidate, ImportPreview, JobStatus, NiftiOptions } from '../../api'
import { converterPattern, sampleStems } from './patternSuggest'
import { ACCEPTED, type WizardPrefill } from './store'

export const STEPS = ['root', 'detect', 'preview', 'index'] as const
export type Step = (typeof STEPS)[number]
/** Preview errors listed at most */
export const MAX_ERRORS = 50
/** Adapters the wizard previews and commits itself; `open` and `dicom.convert` hand off */
export const IMPORTABLE = new Set<string>(['metadata-v1', 'nifti-files'])
// PROJECT_FORMAT §Path aliases
const ALIAS_RE = /^[A-Z][A-Z0-9_]{0,15}$/

export const normPath = (p: string) => p.replace(/\/+$/, '') || '/'
export const parentOf = (p: string) => p.slice(0, p.lastIndexOf('/')) || '/'

/** Where the wizard starts: a prefill (Open mode's "Create project from this") skips the root step */
export function initialState(prefill: WizardPrefill | null): { step: Step; dir: string | null; file: string | null } {
  if (!prefill) return { step: 'root', dir: null, file: null }
  const isFile = ACCEPTED.test(prefill.path)
  return { step: 'detect', dir: isFile ? parentOf(prefill.path) : prefill.path, file: isFile ? prefill.path : null }
}

/** The alias as typed: upper case letters, digits and `_` only */
export const cleanAlias = (raw: string) => raw.toUpperCase().replace(/[^A-Z0-9_]/g, '')

/** IMP-14: an invalid alias, or one of this project that points elsewhere (commit would repoint
 *  it); SRC-15 "add" picks a free alias on the server, so it never collides */
export function aliasProblem(alias: string, taken: { path: string } | undefined, add: boolean, dir: string | null): 'invalid' | 'taken' | null {
  if (!ALIAS_RE.test(alias)) return 'invalid'
  if (taken && !add && dir !== null && normPath(taken.path) !== normPath(dir)) return 'taken'
  return null
}

/** The adapter chosen after detection: the prefill's, else the first importable, else any available */
export function firstAdapter(cands: DetectCandidate[], want?: string | null): string | null {
  const pick = cands.find((c) => c.available && (want ? c.adapter === want : IMPORTABLE.has(c.adapter))) ?? cands.find((c) => c.available)
  return pick?.adapter ?? null
}

/** The image names being imported (AUD-A2-12, ADR-0027): an Open-mode include list without its
 *  masks, one file, or the browsed folder's files */
export function imageStems(options: NiftiOptions, file: string | null, folderFiles: string[]): string[] {
  const masks = new Set(Object.values(options.masks ?? {}))
  const names = options.include ? options.include.filter((f) => !masks.has(f)) : file ? [file] : folderFiles
  return sampleStems(names.map((n) => n.slice(n.lastIndexOf('/') + 1)))
}

/** SRC-17: until the user edits the options, the converter naming fills the pattern when every name follows it */
export function autoPattern(adapter: string | null, touched: boolean, options: NiftiOptions, stems: string[]): string | null {
  return adapter === 'nifti-files' && !touched && options.pattern === undefined ? converterPattern(stems) : null
}

export interface NextInput {
  step: Step
  path: string | null
  aliasOk: boolean
  upload: boolean
  hasUploadedMetadata: boolean
  adapter: string | null
  previewPending: boolean
  preview: ImportPreview | undefined
  commitPending: boolean
}

/** Whether the footer's primary button is enabled */
export function canNext(s: NextInput): boolean {
  if (s.step === 'root') return s.path !== null && s.aliasOk && (!s.upload || s.hasUploadedMetadata)
  if (s.step === 'detect') return s.adapter !== null && !s.previewPending && (s.adapter === 'open' || s.adapter === 'dicom.convert' || IMPORTABLE.has(s.adapter))
  if (s.step === 'preview') return (s.preview?.files.some((f) => f.kind === 'metadata') ?? false) && !s.commitPending
  return false
}

export type NextAction = 'upload-preview' | 'detect' | 'open' | 'convert' | 'preview' | 'commit' | null

/** What the primary button does in this step */
export function nextAction(step: Step, adapter: string | null, upload: boolean): NextAction {
  if (step === 'root') return upload ? 'upload-preview' : 'detect'
  if (step === 'detect') return adapter === 'open' ? 'open' : adapter === 'dicom.convert' ? 'convert' : adapter ? 'preview' : null
  if (step === 'preview') return 'commit'
  return null
}

/** A job that ended without importing */
export const jobFailed = (status: JobStatus | undefined) => status === 'failed' || status === 'cancelled' || status === 'interrupted'

/** The four KPI cards of the preview; the case count leaves out cases excluded upstream (AUD-A1-08) */
export function previewCounts(p: ImportPreview): { key: string; n: number }[] {
  return [
    { key: 'import.kpiRows', n: p.counts.scan_rows },
    { key: 'import.kpiCases', n: p.counts.cases },
    { key: 'import.kpiVoi', n: p.counts.voi_rows },
    { key: 'import.kpiExcluded', n: p.counts.excluded_upstream },
  ]
}
