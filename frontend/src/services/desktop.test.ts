import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  browseForDatasetDirectory,
  initializeDesktopRuntime,
  isDesktopRuntime,
  notifyDesktopFrontendReady,
} from './desktop'

vi.mock('./api', () => ({
  configureApiBaseUrl: vi.fn(),
  configureRuntimeAuthToken: vi.fn(),
}))

describe('desktop bridge', () => {
  afterEach(() => {
    delete window.__TAURI__
    vi.clearAllMocks()
  })

  it('keeps the browser transport relative and hides desktop capabilities', async () => {
    const api = await import('./api')

    expect(isDesktopRuntime()).toBe(false)
    expect(await browseForDatasetDirectory()).toBeNull()
    await initializeDesktopRuntime()

    expect(api.configureApiBaseUrl).toHaveBeenCalledWith('')
  })

  it('configures the runtime before notifying Tauri that the frontend is ready', async () => {
    const api = await import('./api')
    const invoke = vi
      .fn()
      .mockResolvedValueOnce({ baseUrl: 'http://127.0.0.1:49152', token: 'runtime-token' })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce('C:\\Research\\Dataset420')
    window.__TAURI__ = { core: { invoke } }

    await initializeDesktopRuntime()
    await notifyDesktopFrontendReady()

    expect(api.configureApiBaseUrl).toHaveBeenCalledWith('http://127.0.0.1:49152')
    expect(api.configureRuntimeAuthToken).toHaveBeenCalledWith('runtime-token')
    expect(await browseForDatasetDirectory()).toBe('C:\\Research\\Dataset420')
    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      'get_backend_runtime',
      'frontend_ready',
      'browse_for_dataset_directory',
    ])
  })
})
