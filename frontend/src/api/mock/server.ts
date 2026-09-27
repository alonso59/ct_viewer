// Mock binding of the API surface (VITE_API_MODE=mock: the standalone prototype and the unit
// tests, TST-04). It is the HTTP binding itself over a replay of responses recorded from the real
// backend on the synthetic fixtures (`make record-mock`, replay.ts), so the wire adaptation in
// http.ts runs in every unit test and the mock holds no domain logic of its own (AUD-A6-03):
// what a response says (rollups, variables, phase precedence, dashboards) is what the backend
// said on the fixtures. Writes answer with their recorded response and change no later answer.
// Not recorded: server events, binary routes (volumes, masks, thumbnails, downloads).
import { createHttpApi } from '../http'
import type { Api } from '../surface'
import { RECORDED_PID, replayFetch } from './replay'

/** The recorded demo project (Dataset900 of the fixtures) */
export const DEMO_PID = RECORDED_PID

const replay = createHttpApi(replayFetch, 'http://mock.invalid')

export const mockServer: Api = {
  ...replay,
  mode: 'mock',
  // a replay has no event stream; the connection reads "live" so nothing waits for it
  subscribe(_pid, _listener, onState) {
    onState?.('live')
    return () => undefined
  },
  thumbnailUrl: () => null,
  maskUrl: () => null,
  openImageUrl: () => null,
  openPreviewUrl: () => null,
  runExportUrl: () => '#',
  datasetTableUrl: () => '#',
  labelExportUrl: () => '#',
}
