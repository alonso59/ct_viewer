// Draft run shared by the Radiomics view (profiles) and the settings tab. In memory only: the
// form reopens on the engine defaults (RADIOMICS §Principles) unless a profile is loaded.
import { create } from 'zustand'

import { emptySelection, type SelectionForm } from './model/selection'
import type { FormState } from './model/types'

interface DraftState {
  pid: string | null
  /** null until the schema is loaded; then the engine defaults */
  form: FormState | null
  selection: SelectionForm
  runName: string
  /** Profile the form was last loaded from (name shown in the tab header) */
  loadedFrom: string | null
  reset: (pid: string, form: FormState | null, labels: number[]) => void
  setForm: (form: FormState, loadedFrom?: string | null) => void
  /** Load a profile into the draft of `pid` (keeps that project's selection) */
  load: (pid: string, form: FormState, name: string) => void
  setSelection: (patch: Partial<SelectionForm>) => void
  setRunName: (name: string) => void
}

export const useDraft = create<DraftState>()((set) => ({
  pid: null,
  form: null,
  selection: emptySelection(),
  runName: '',
  loadedFrom: null,
  reset: (pid, form, labels) => set({ pid, form, selection: emptySelection(labels), runName: '', loadedFrom: null }),
  setForm: (form, loadedFrom) => set((s) => ({ form, loadedFrom: loadedFrom === undefined ? s.loadedFrom : loadedFrom })),
  load: (pid, form, name) => set((s) => ({ pid, form, loadedFrom: name, selection: s.pid === pid ? s.selection : emptySelection() })),
  setSelection: (patch) => set((s) => ({ selection: { ...s.selection, ...patch } })),
  setRunName: (runName) => set({ runName }),
}))
