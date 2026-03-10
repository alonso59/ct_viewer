import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  apiClient,
  getApiErrorMessage,
  type DatasetViewerSettings,
  type ViewerSettings,
} from '../services/api'

const DEFAULT_DATASET_SETTINGS: DatasetViewerSettings = {
  last_patient: null,
  last_series: null,
  ww: 400,
  wl: 50,
  layers_visible: [1, 2],
  layers_opacity: {
    1: 0.15,
    2: 0.2,
    3: 0.15,
  },
}

function cloneDefaultSettings(): DatasetViewerSettings {
  return {
    ...DEFAULT_DATASET_SETTINGS,
    layers_visible: [...DEFAULT_DATASET_SETTINGS.layers_visible],
    layers_opacity: { ...DEFAULT_DATASET_SETTINGS.layers_opacity },
  }
}

function normalizeDatasetSettings(
  value?: DatasetViewerSettings | Partial<DatasetViewerSettings> | null,
): DatasetViewerSettings {
  const base = cloneDefaultSettings()
  if (!value) {
    return base
  }

  return {
    last_patient: value.last_patient ?? null,
    last_series: value.last_series ?? null,
    ww: typeof value.ww === 'number' ? value.ww : base.ww,
    wl: typeof value.wl === 'number' ? value.wl : base.wl,
    layers_visible: Array.isArray(value.layers_visible)
      ? value.layers_visible.filter((label) => [1, 2, 3].includes(label))
      : base.layers_visible,
    layers_opacity: {
      1:
        typeof value.layers_opacity?.['1'] === 'number'
          ? value.layers_opacity['1']
          : base.layers_opacity['1'],
      2:
        typeof value.layers_opacity?.['2'] === 'number'
          ? value.layers_opacity['2']
          : base.layers_opacity['2'],
      3:
        typeof value.layers_opacity?.['3'] === 'number'
          ? value.layers_opacity['3']
          : base.layers_opacity['3'],
    },
  }
}

function normalizeViewerSettings(payload: ViewerSettings): ViewerSettings {
  return Object.fromEntries(
    Object.entries(payload).map(([datasetId, value]) => [
      datasetId,
      normalizeDatasetSettings(value),
    ]),
  )
}

function arraysEqual(left: number[], right: number[]): boolean {
  if (left.length !== right.length) {
    return false
  }
  return left.every((value, index) => value === right[index])
}

function opacityEqual(
  left: DatasetViewerSettings['layers_opacity'],
  right: DatasetViewerSettings['layers_opacity'],
): boolean {
  return ['1', '2', '3'].every((key) => left[key] === right[key])
}

function datasetSettingsEqual(
  left: DatasetViewerSettings,
  right: DatasetViewerSettings,
): boolean {
  return (
    left.last_patient === right.last_patient &&
    left.last_series === right.last_series &&
    left.ww === right.ww &&
    left.wl === right.wl &&
    arraysEqual(left.layers_visible, right.layers_visible) &&
    opacityEqual(left.layers_opacity, right.layers_opacity)
  )
}

type DatasetSettingsUpdater =
  | DatasetViewerSettings
  | ((current: DatasetViewerSettings) => DatasetViewerSettings)

interface UseSettingsOptions {
  datasetId?: string | null
  onLoadedDatasetSettings?: (settings: DatasetViewerSettings) => void
}

export function useSettings({
  datasetId = null,
  onLoadedDatasetSettings,
}: UseSettingsOptions = {}) {
  const [state, setState] = useState<{
    draftSettings: ViewerSettings
    loadError: string | null
    loadRevision: number
    loaded: boolean
    remoteSettings: ViewerSettings
    saveError: string | null
  }>({
    draftSettings: {},
    loadError: null,
    loadRevision: 0,
    loaded: false,
    remoteSettings: {},
    saveError: null,
  })

  const onLoadedRef = useRef(onLoadedDatasetSettings)
  const lastNotifiedRef = useRef<string | null>(null)

  useEffect(() => {
    onLoadedRef.current = onLoadedDatasetSettings
  }, [onLoadedDatasetSettings])

  useEffect(() => {
    let active = true

    apiClient
      .getSettings()
      .then((payload) => {
        if (!active) {
          return
        }
        const normalized = normalizeViewerSettings(payload)
        setState({
          draftSettings: normalized,
          loadError: null,
          loadRevision: Date.now(),
          loaded: true,
          remoteSettings: normalized,
          saveError: null,
        })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setState((current) => ({
          ...current,
          loaded: true,
          loadError: getApiErrorMessage(requestError),
          loadRevision: Date.now(),
        }))
      })

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!datasetId || !state.loaded || state.loadRevision === 0) {
      return
    }
    const notifyKey = `${datasetId}:${state.loadRevision}`
    if (lastNotifiedRef.current === notifyKey) {
      return
    }
    lastNotifiedRef.current = notifyKey
    onLoadedRef.current?.(normalizeDatasetSettings(state.draftSettings[datasetId]))
  }, [datasetId, state.draftSettings, state.loadRevision, state.loaded])

  const remoteSerialized = useMemo(
    () => JSON.stringify(state.remoteSettings),
    [state.remoteSettings],
  )
  const draftSerialized = useMemo(
    () => JSON.stringify(state.draftSettings),
    [state.draftSettings],
  )

  useEffect(() => {
    if (!state.loaded || draftSerialized === remoteSerialized) {
      return
    }

    let active = true
    const timer = window.setTimeout(() => {
      apiClient
        .putSettings(state.draftSettings)
        .then((payload) => {
          if (!active) {
            return
          }
          const normalized = normalizeViewerSettings(payload)
          setState((current) => ({
            ...current,
            remoteSettings: normalized,
            saveError: null,
          }))
        })
        .catch((requestError) => {
          if (!active) {
            return
          }
          setState((current) => ({
            ...current,
            saveError: getApiErrorMessage(requestError),
          }))
        })
    }, 500)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [draftSerialized, remoteSerialized, state.draftSettings, state.loaded])

  const updateDatasetSettings = useCallback(
    (updater: DatasetSettingsUpdater) => {
      if (!datasetId || !state.loaded) {
        return
      }

      setState((current) => {
        const existing = normalizeDatasetSettings(current.draftSettings[datasetId])
        const nextValue =
          typeof updater === 'function'
            ? (updater as (value: DatasetViewerSettings) => DatasetViewerSettings)(existing)
            : updater
        const normalized = normalizeDatasetSettings(nextValue)
        if (datasetSettingsEqual(existing, normalized)) {
          return current
        }
        return {
          ...current,
          draftSettings: {
            ...current.draftSettings,
            [datasetId]: normalized,
          },
          saveError: null,
        }
      })
    },
    [datasetId, state.loaded],
  )

  return {
    allSettings: state.draftSettings,
    datasetSettings: datasetId
      ? normalizeDatasetSettings(state.draftSettings[datasetId])
      : null,
    loadError: state.loadError,
    loading: !state.loaded,
    saveError: state.saveError,
    updateDatasetSettings,
  }
}
