// Converter overlay state (UI-25): opened from Welcome, Open mode on DICOM, the Library and a
// project's Data tab. `pid` set = the window may convert into that project (DCM-14).
import { create } from 'zustand'

interface ConverterState {
  open: boolean
  source: string | null
  pid: string | null
  show: (p?: { source?: string | null; pid?: string | null }) => void
  close: () => void
}

export const useConverter = create<ConverterState>()((set) => ({
  open: false,
  source: null,
  pid: null,
  show: (p) => set({ open: true, source: p?.source ?? null, pid: p?.pid ?? null }),
  close: () => set({ open: false }),
}))

const pad = (n: number) => String(n).padStart(2, '0')
/** AUD-A5-16 (NFR-17): the suggested dataset name; never the source folder's (often a patient) name */
export const defaultDatasetName = (d = new Date()) => `dataset-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
