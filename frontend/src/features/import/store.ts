// Eager on purpose: the wizard itself is a lazy chunk
import { create } from 'zustand'

import type { NiftiOptions } from '../../api'

export interface WizardPrefill {
  path: string
  adapter?: string
  /** "Add to project…": keep the project's other sources */
  add?: boolean
  /** The modality chosen in Open mode for a file without one → `nifti-files` option */
  modality?: string
  /** `nifti-files` options from Open mode: an include list with the attached mask */
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

export const ACCEPTED = /\.(nii|nii\.gz|npy|dcm)$/i
