// Open mode by session id (AUD-A1-19, API-07): the URL is `/open/{sid}`, never the path. Specs
// that start in Open mode create the session through the API and load its route, which is what
// a reload or a bookmarked tab does.
import type { Page } from '@playwright/test'

import { api } from './helpers'

export async function gotoOpen(page: Page, path: string): Promise<string> {
  const { sid } = await api<{ sid: string }>('POST', '/open', { path })
  await page.goto(`/open/${sid}`)
  return sid
}

/** The in-app hand-off (`lib/openNavigate.ts`): a path in the history state, not the URL */
export async function openViaHistoryState(page: Page, path: string) {
  // React Router keeps `location.state` under `usr` in `history.state` (a string: e2e has no DOM lib)
  const state = JSON.stringify({ usr: { openPath: path }, key: 'e2e', idx: 1 })
  await page.evaluate(`history.pushState(${state}, '', '/open'); dispatchEvent(new PopStateEvent('popstate', { state: history.state }))`)
}
