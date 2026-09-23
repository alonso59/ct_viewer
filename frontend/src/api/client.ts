// API client (FE-03): the HTTP binding by default; `VITE_API_MODE=mock` binds the in-memory mock
// (standalone prototype, unit tests). The mock is imported only in that mode, so its seed data
// stays out of the production bundle (FE-05).
import { httpApi } from './http'
import type { Api } from './surface'

export const API_MODE: Api['mode'] = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'http'

export const api: Api = API_MODE === 'mock' ? (await import('./mock/server')).mockServer : httpApi
