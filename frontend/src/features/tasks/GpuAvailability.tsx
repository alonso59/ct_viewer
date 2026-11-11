import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, useCompute, useComputeCheck, type TaskInfo } from '../../api'
import { fmtAgo, fmtDate, ProblemCard } from '../../lib'
import { runCommand } from '../../shell'

type Inventory = { at?: string; error?: string | null; required_free_mb?: number; devices?: { index?: string; name?: string; total_mb?: number; used_mb?: number; busy?: boolean; status?: 'ready' | 'warning' | 'unavailable'; reason?: string | null }[] }
const schedulerCapOf = (info: TaskInfo) => {
  const execution = info.execution
  if (execution?.backend !== 'slurm') return undefined
  return { gpus: typeof execution.gpus_per_run === 'number' ? execution.gpus_per_run : null }
}
const inventoryOf = (info: TaskInfo) => info.execution?.inventory as Inventory | undefined

export function GpuAvailability({ info }: { info: TaskInfo }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const inventory = inventoryOf(info)
  const stateOf = (device: NonNullable<Inventory['devices']>[number]) => device.status ?? (device.busy ? 'unavailable' : 'ready')
  const available = inventory?.devices?.filter((device) => stateOf(device) !== 'unavailable').length ?? 0
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
  const scheduler = schedulerCapOf(info)
  if (scheduler) return <QueueCheck gpus={scheduler.gpus} />
  return <div className="task-gpu-availability">
    <div className="task-run-actions">
      <button type="button" className="btn btn-sm" disabled={checking} onClick={() => void check()}>{t(checking ? 'tasks.gpu.checking' : 'tasks.gpu.check')}</button>
      <span className="muted task-help" role="status">{inventory?.at && !inventory.error ? t('tasks.gpu.snapshot', { available, total: inventory.devices?.length ?? 0, age: fmtAgo(inventory.at) }) : t('tasks.gpu.unknown')}</span>
    </div>
    <p className="muted task-help">{t('tasks.gpu.help')}</p>
    {inventory?.required_free_mb != null ? <p className="muted task-help">{t('tasks.gpu.memoryRequired', { gib: (inventory.required_free_mb / 1024).toFixed(1) })}</p> : null}
    {error ? <ProblemCard error={error} onRetry={() => void check()} /> : null}
  </div>
}

/** Under a scheduler: the GPU cap, and the scheduler's own start estimate per valid profile.
 *  An estimate is a prediction for a request made now, never a promise. */
function QueueCheck({ gpus }: { gpus: number | null }) {
  const { t } = useTranslation()
  const compute = useCompute().data
  const check = useComputeCheck()
  const valid = compute?.profiles.filter((p) => p.status === 'valid') ?? []
  return (
    <div className="task-gpu-availability">
      <p className="muted task-help">{t(gpus == null ? 'tasks.gpu.scheduler' : 'tasks.gpu.schedulerCap', { gpus })}</p>
      <div className="task-run-actions">
        <button type="button" className="btn btn-sm" disabled={check.checking} onClick={() => void check.check()}>{t(check.checking ? 'tasks.queue.checking' : 'tasks.queue.check')}</button>
        <button type="button" className="btn btn-sm" onClick={() => runCommand('setup.compute')}>{t('cmd.compute')}</button>
      </div>
      {valid.map((p) => (
        <p key={p.id} className="muted task-help" role="status">
          {p.estimated_start ? t('tasks.queue.estimate', { name: p.name, at: fmtDate(p.estimated_start) }) : t('tasks.queue.noEstimate', { name: p.name })}
        </p>
      ))}
      {compute?.read_at ? <p className="muted task-help">{t('tasks.queue.readAt', { ago: fmtAgo(compute.read_at) })}</p> : null}
      <p className="muted task-help">{t('tasks.queue.help')}</p>
      {check.failed === 'timeout' ? <p className="field-error" role="alert">{t('tasks.queue.timeout')}</p> : check.failed ? <ProblemCard error={check.failed} /> : null}
    </div>
  )
}
