// Import wizard open/close state (eager; the wizard itself is a lazy chunk, NFR-07)
import { create } from 'zustand'

import type { NiftiOptions } from '../../api'

export interface WizardPrefill {
  path: string
  adapter?: string
  /** SRC-15 "Add to project…": keep the project's other sources */
  add?: boolean
  /** VW-05: the modality chosen in Open mode for a file without one → `nifti-files` option */
  modality?: string
  /** `nifti-files` options from Open mode: an include list with the attached mask (ADR-0027) */
  options?: NiftiOptions
}

interface WizardState {
  pid: string | null
  prefill: WizardPrefill | null
  open: (pid: string, prefill?: WizardPrefill) => void
  close: () => void
}
export const useImportWizard = create<WizardState>()((set) => ({
  pid: null,
  prefill: null,
  open: (pid, prefill) => set({ pid, prefill: prefill ?? null }),
  close: () => set({ pid: null, prefill: null }),
}))

/** Files the browser lets the user pick (SRC-01): NIfTI, NumPy, DICOM */
export const ACCEPTED = /\.(nii|nii\.gz|npy|dcm)$/i
