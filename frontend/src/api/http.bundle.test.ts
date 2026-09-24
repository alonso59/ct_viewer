// HTTP binding of API-06 (bundles) and the client-side item filter (DB-04). API-15 goes through the
// typed client (absolute URLs only under Node's Request), so it is covered by the E2E instead.
import { afterEach, expect, test, vi } from 'vitest'

import { attachmentName, httpApi } from './http'

afterEach(() => vi.unstubAllGlobals())

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

test('Content-Disposition file names', () => {
  expect(attachmentName('attachment; filename="p1-bundle.zip"')).toBe('p1-bundle.zip')
  expect(attachmentName('attachment; filename=plain.zip')).toBe('plain.zip')
  expect(attachmentName(`attachment; filename="x.zip"; filename*=UTF-8''caf%C3%A9.zip`)).toBe('café.zip')
  expect(attachmentName(null)).toBeNull()
  expect(attachmentName('inline')).toBeNull()
})

test('exportBundle POSTs and returns the zip with the server file name', async () => {
  const fn = vi.fn(async () => new Response('PK', { status: 200, headers: { 'content-disposition': 'attachment; filename="Demo_2026.zip"' } }))
  vi.stubGlobal('fetch', fn)
  const b = await httpApi.exportBundle('P1')
  const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toMatch(/\/api\/v1\/projects\/P1\/bundle$/)
  expect(init.method).toBe('POST')
  expect(b.filename).toBe('Demo_2026.zip')
  expect(await b.blob.text()).toBe('PK')
})

test('importBundle sends the multipart field `bundle`; problems surface with their slug', async () => {
  const fn = vi.fn(async () => json({ type: '/problems/format-version-unsupported', title: 'Unsupported', status: 409 }, 409))
  vi.stubGlobal('fetch', fn)
  const file = new File(['PK'], 'b.zip', { type: 'application/zip' })
  await expect(httpApi.importBundle(file)).rejects.toMatchObject({ status: 409, type: 'format-version-unsupported' })
  const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toMatch(/\/projects\/import-bundle$/)
  expect((init.body as FormData).get('bundle')).toBeInstanceOf(File)
})

test('listCases applies the item-id filter on the client (API-20 has none)', async () => {
  const c = (case_id: string) => ({ case_id, n_scans: 1, n_items: 1, has_seg: true, has_voi_L: false, has_voi_R: false, n_warnings: 0 })
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: [c('case_1'), c('case_2'), c('case_3')], next_cursor: null })))
  const out = await httpApi.listCases('P1', { itemIds: ['case_3.01.voi.L', 'case_1.01.complete.-'] })
  expect(out.map((x) => x.case_id)).toEqual(['case_1', 'case_3'])
})
