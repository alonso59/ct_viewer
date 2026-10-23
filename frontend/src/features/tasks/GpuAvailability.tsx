import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, type TaskInfo } from '../../api'
import { fmtAgo, ProblemCard } from '../../lib'

type Inventory = { at?: string; error?: string | null; devices?: { busy?: boolean }[] }
const inventoryOf = (info: TaskInfo) => info.execution?.inventory as Inventory | undefined

export function GpuAvailability({ info }: { info: TaskInfo }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const inventory = inventoryOf(info)
  const available = inventory?.devices?.filter((device) => device.busy === false).length ?? 0
  const check = async () => {
    setChecking(true); setError(null)
    const observe = async () => {
      const catalog = await api.listTasks()
      qc.setQueryData(keys.tasks(), catalog)
      const current = catalog.tasks.find((task) => task.manifest.id === info.manifest.id)
      if (!current?.runner_online) throw new Error(t('tasks.gpu.offline'))
      const snapshot = inventoryOf(current)
      if (!snapshot?.at || snapshot.error) throw new Error(t('tasks.gpu.unknown'))
      return snapshot.at
    }
    try {
      const previous = await observe()
      const deadline = performance.now() + 20_000
      while (alive.current && performance.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        if (!alive.current) return
        if (await observe() !== previous) return
      }
      if (alive.current) throw new Error(t('tasks.gpu.timeout'))
    } catch (e) {
      if (alive.current) setError(e)
    } finally {
      if (alive.current) setChecking(false)
    }
  }
  return <div className="task-gpu-availability">
    <div className="task-run-actions">
      <button type="button" className="btn btn-sm" disabled={checking} onClick={() => void check()}>{t(checking ? 'tasks.gpu.checking' : 'tasks.gpu.check')}</button>
      <span className="muted task-help" role="status">{inventory?.at && !inventory.error ? t('tasks.gpu.snapshot', { available, total: inventory.devices?.length ?? 0, age: fmtAgo(inventory.at) }) : t('tasks.gpu.unknown')}</span>
    </div>
    <p className="muted task-help">{t('tasks.gpu.help')}</p>
    {error ? <ProblemCard error={error} /> : null}
  </div>
}
