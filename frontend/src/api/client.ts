// API client. P0.5 binds the mock server; P2 swaps in the openapi-fetch client with the
// same surface (FE-03), so hooks and features do not change.
import { mockServer } from './mock/server'

export const api = mockServer
export type Api = typeof api
export { ProblemError, DEMO_PID, setReviewerSimulation, type CaseFilter } from './mock/server'
