// VW-14 budget, API-25 polling, FE-11 keys of the viewer-local bundle
import { act, renderHook } from '@testing-library/react'

import { configureViewer, isLoaded, useBudget, useLoadBudget } from './budget'
import { VW_EN } from './i18n'
import { fetchMesh, MeshUnavailable } from './meshes'

describe('memory budget (VW-14)', () => {
  beforeEach(() => useBudget.setState({ maxLoaded: 3, order: [] }))

  test('isLoaded keeps the most recently shown tabs', () => {
    expect(isLoaded(['a', 'b', 'c', 'd'], 3, 'c')).toBe(true)
    expect(isLoaded(['a', 'b', 'c', 'd'], 3, 'd')).toBe(false)
    expect(isLoaded([], 3, 'x')).toBe(false)
  })

  test('hidden tabs beyond the budget unload; showing one reloads it', () => {
    configureViewer({ maxLoaded: 2 })
    const a = renderHook(({ active }) => useLoadBudget('a', active), { initialProps: { active: true } })
    const b = renderHook(({ active }) => useLoadBudget('b', active), { initialProps: { active: false } })
    const c = renderHook(({ active }) => useLoadBudget('c', active), { initialProps: { active: false } })
    act(() => a.rerender({ active: false }))
    act(() => b.rerender({ active: true }))
    act(() => b.rerender({ active: false }))
    act(() => c.rerender({ active: true }))
    // order: c, b, a → a is beyond max 2
    expect(c.result.current).toBe(true)
    expect(b.result.current).toBe(true)
    expect(a.result.current).toBe(false)
    act(() => c.rerender({ active: false }))
    act(() => a.rerender({ active: true }))
    expect(a.result.current).toBe(true)
    expect(c.result.current).toBe(true)
    expect(b.result.current).toBe(false)
  })

  test('closing a tab frees its slot', () => {
    const a = renderHook(() => useLoadBudget('a', true))
    a.unmount()
    expect(useBudget.getState().order).toEqual([])
  })
})

describe('mesh client (API-25)', () => {
  afterEach(() => vi.unstubAllGlobals())

  test('polls 202 until the mesh is cached', async () => {
    const bytes = new Uint8Array([1, 2, 3]).buffer
    const responses = [new Response(JSON.stringify({ status: 'running' }), { status: 202 }), new Response(bytes, { status: 200 })]
    const fetchMock = vi.fn(async () => responses.shift()!)
    vi.stubGlobal('fetch', fetchMock)
    const out = await fetchMesh('/m', undefined, 5000)
    expect(new Uint8Array(out)).toEqual(new Uint8Array([1, 2, 3]))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  test('failed job or error status rejects', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'failed', error: 'label-absent' }), { status: 202 })))
    await expect(fetchMesh('/m')).rejects.toBeInstanceOf(MeshUnavailable)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))
    await expect(fetchMesh('/m')).rejects.toBeInstanceOf(MeshUnavailable)
  })
})

describe('viewer strings (FE-11)', () => {
  const files = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

  test('every vw.* key used in the viewer exists in the local bundle', () => {
    type Tree = { [k: string]: string | Tree }
    const has = (key: string) => {
      let node: string | Tree | undefined = VW_EN as Tree
      for (const p of key.split('.').slice(1)) node = typeof node === 'object' ? node[p] : undefined
      return typeof node === 'string'
    }
    const missing: string[] = []
    for (const [file, src] of Object.entries(files))
      for (const m of src.matchAll(/'(vw\.[a-zA-Z0-9_.]+)'/g)) if (!has(m[1]!)) missing.push(`${m[1]} (${file})`)
    expect(missing).toEqual([])
  })
})
