import { configureApiBaseUrl, configureRuntimeAuthToken } from './api'

interface BackendRuntime {
  baseUrl: string
  token: string
}

interface TauriCore {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>
}

declare global {
  interface Window {
    __TAURI__?: {
      core?: TauriCore
    }
  }
}

function getTauriCore(): TauriCore | null {
  if (typeof window === 'undefined') {
    return null
  }
  return window.__TAURI__?.core ?? null
}

export function isDesktopRuntime(): boolean {
  return getTauriCore() !== null
}

export async function initializeDesktopRuntime(): Promise<void> {
  const core = getTauriCore()
  if (!core) {
    configureApiBaseUrl('')
    return
  }

  const runtime = await core.invoke<BackendRuntime>('get_backend_runtime')
  configureApiBaseUrl(runtime.baseUrl)
  configureRuntimeAuthToken(runtime.token)
}

export async function notifyDesktopFrontendReady(): Promise<void> {
  const core = getTauriCore()
  if (core) {
    await core.invoke('frontend_ready')
  }
}

export async function browseForDatasetDirectory(): Promise<string | null> {
  const core = getTauriCore()
  if (!core) {
    return null
  }
  return core.invoke<string | null>('browse_for_dataset_directory')
}
