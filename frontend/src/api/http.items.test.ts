import { expect, test, vi } from 'vitest'

import { createHttpApi } from './http'

test('select-all follows server cursors with the same filter and deduplicates item IDs', async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async (request) => {
    const url = request instanceof Request ? request.url : String(request)
    const second = new URL(url).searchParams.has('cursor')
    return new Response(JSON.stringify({ items: (second ? ['b', 'c'] : ['a', 'b']).map((item_id) => ({ item_id })), total: 3, next_cursor: second ? null : '2' }), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  const api = createHttpApi(fetch, 'http://local')
  expect(await api.listItemIds('p', { q: 'subject', modality: 'CT', has_mask: false, cursor: 'old', limit: 50 })).toEqual(['a', 'b', 'c'])
  const urls = fetch.mock.calls.map(([request]) => new URL(request instanceof Request ? request.url : String(request)))
  expect(urls.map((url) => url.searchParams.get('cursor'))).toEqual([null, '2'])
  for (const url of urls) {
    expect(url.searchParams.get('limit')).toBe('500')
    expect(url.searchParams.get('q')).toBe('subject')
    expect(url.searchParams.get('modality')).toBe('CT')
    expect(url.searchParams.get('has_mask')).toBe('false')
  }
})
