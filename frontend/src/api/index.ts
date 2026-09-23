// API layer: client (mock in P0.5), query keys, hooks, domain types (FE-02/03)
export * from './hooks'
export * from './types'
export { api, ProblemError, DEMO_PID, setReviewerSimulation, type CaseFilter } from './client'
export { keys } from './keys'
export { loadSlices, type SliceSet, type Slice, type Plane } from './mock/slices'
export { defaultSettings, validateSettings } from './mock/schema'
export { rollup } from './mock/server'
export { queryClient } from './queryClient'
