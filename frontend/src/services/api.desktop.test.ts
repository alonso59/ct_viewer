import { afterEach, describe, expect, it } from 'vitest'

import {
  AUTH_TOKEN_STORAGE_KEY,
  apiClient,
  configureApiBaseUrl,
  configureRuntimeAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from './api'

describe('desktop API transport', () => {
  afterEach(() => {
    configureApiBaseUrl('')
    configureRuntimeAuthToken('')
    window.localStorage.clear()
  })

  it('keeps generated resource URLs relative in the browser', () => {
    configureApiBaseUrl('')

    expect(apiClient.sliceUrl('axial', 12)).toBe('/api/slice/axial/12')
    expect(apiClient.meshUrl(2, 'load-handle')).toContain('/api/mesh/2?')
  })

  it('uses the loopback runtime base URL in desktop mode', () => {
    configureApiBaseUrl('http://127.0.0.1:49152/')

    expect(apiClient.sliceUrl('coronal', 8)).toBe(
      'http://127.0.0.1:49152/api/slice/coronal/8',
    )
    expect(apiClient.meshUrl(1, 'load-handle')).toContain(
      'http://127.0.0.1:49152/api/mesh/1?',
    )
  })

  it('never replaces or persists the ephemeral runtime token', () => {
    window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, 'stored-web-token')
    configureRuntimeAuthToken('runtime-token')

    setStoredAuthToken('replacement-token')

    expect(getStoredAuthToken()).toBe('runtime-token')
    expect(window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBe('stored-web-token')
  })
})
