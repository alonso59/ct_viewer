import { useEffect, useState } from 'react'

import { apiClient, getApiErrorMessage, type WorkspaceStatus } from '../services/api'

const EMPTY_WORKSPACE: WorkspaceStatus = {
  configured: false,
  dataset_id: null,
  dataset_path: null,
  database_csv_path: null,
  workspace_dir: null,
}

export function useWorkspace() {
  const [workspace, setWorkspace] = useState<WorkspaceStatus>(EMPTY_WORKSPACE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    apiClient
      .getWorkspace()
      .then((response) => {
        if (!active) {
          return
        }
        setWorkspace(response)
        setError(null)
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setWorkspace(EMPTY_WORKSPACE)
        setError(getApiErrorMessage(requestError))
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [])

  return {
    error,
    loading,
    setWorkspace: (nextWorkspace: WorkspaceStatus) => {
      setWorkspace(nextWorkspace)
      setError(null)
    },
    workspace,
  }
}
