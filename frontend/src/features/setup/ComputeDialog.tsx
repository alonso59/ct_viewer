// Settings › Compute: what the scheduler reports and the user's compute profiles. The runner reads
// the scheduler and decides whether a profile is valid; this dialog only shows and stores.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useCompute, useComputeCheck, useComputeEdit, type ComputeProfile, type ComputeProfileBody, type ComputeState } from '../../api'
import { Button, ConfirmInline, Dialog, NumberInput, ProblemCard, fmtAgo, fmtDate, fmtDuration } from '../../lib'
import { codicon } from '../../theme'
import './setup.css'

const MAX_GPUS = 2
const GIB = 1024

const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'profile'

function Verdict({ profile }: { profile: ComputeProfile }) {
  const { t } = useTranslation()
  if (profile.status === 'valid')
    return (
      <span className="setup-verdict">
        <span className="badge" data-tone="ok">{t('compute.valid')}</span>
        {profile.estimated_start ? <span className="muted small">{t('compute.estimate', { at: fmtDate(profile.estimated_start) })}</span> : null}
      </span>
    )
  if (profile.status === 'rejected')
    return (
      <span className="setup-verdict">
        <span className="badge" data-tone="error">{t('compute.rejected')}</span>
        <span className="small">{profile.reason}</span>
      </span>
    )
  return <span className="badge">{t('compute.unchecked')}</span>
}

function ProfileForm({ state, profile, onDone }: { state: ComputeState; profile: ComputeProfile | null; onDone: () => void }) {
  const { t } = useTranslation()
  const edit = useComputeEdit()
  const limits = state.limits
  const maxGpus = Math.min(MAX_GPUS, limits?.gpus ?? MAX_GPUS)
  const [body, setBody] = useState<ComputeProfileBody>(() => ({
    name: profile && !profile.implicit ? profile.name : '',
    account: profile?.account ?? state.accounts?.[0] ?? null,
    partition: profile?.partition ?? state.partitions?.find((p) => p.up && p.gpus)?.name ?? null,
    gpus: Math.min(profile?.gpus ?? 1, maxGpus),
    cpus: profile?.cpus ?? Math.min(8, limits?.cpus ?? 8),
    memory_mb: profile?.memory_mb ?? Math.min(32 * GIB, limits?.memory_mb ?? 32 * GIB),
    seconds: profile?.seconds ?? Math.min(8 * 3600, limits?.seconds ?? 8 * 3600),
  }))
  const set = (patch: Partial<ComputeProfileBody>) => setBody((b) => ({ ...b, ...patch }))
  const partition = state.partitions?.find((p) => p.name === body.partition)
  const taken = new Set(state.profiles.filter((p) => !p.implicit).map((p) => p.id))
  const newId = () => {
    const base = slug(body.name)
    let id = base
    for (let n = 2; taken.has(id); n++) id = `${base.slice(0, 36)}-${n}`
    return id
  }
  const save = () => edit.save.mutate({ id: profile && !profile.implicit ? profile.id : newId(), body }, { onSuccess: onDone })
  const nameField = (key: 'account' | 'partition', options: string[] | null) => (
    <div className="field">
      <label className="field-label" htmlFor={`profile-${key}`}>{t(`compute.${key}`)}</label>
      {options ? (
        <select id={`profile-${key}`} className="input input-sm" value={body[key] ?? ''} onChange={(e) => set({ [key]: e.target.value || null })}>
          <option value="">{t('compute.siteDefault')}</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input id={`profile-${key}`} className="input input-sm mono" value={body[key] ?? ''} placeholder={t('compute.unknownList')} onChange={(e) => set({ [key]: e.target.value.trim() || null })} />
      )}
    </div>
  )
  return (
    <form className="setup-form" onSubmit={(e) => { e.preventDefault(); if (body.name.trim()) save() }}>
      <div className="field">
        <label className="field-label" htmlFor="profile-name">{t('compute.name')}</label>
        <input id="profile-name" className="input input-sm" value={body.name} maxLength={60} autoFocus onChange={(e) => set({ name: e.target.value })} />
      </div>
      {nameField('account', state.accounts ?? null)}
      {nameField('partition', state.partitions ? state.partitions.map((p) => p.name) : null)}
      {partition ? (
        <span className="muted small">
          {[
            t(partition.up ? 'compute.partitionUp' : 'compute.partitionDown'),
            partition.max_seconds != null ? t('compute.partitionMax', { time: fmtDuration(partition.max_seconds) }) : t('compute.partitionNoMax'),
            ...(partition.gpu_types.length ? [t('compute.gpuTypes', { types: partition.gpu_types.join(', ') })] : []),
          ].join(' · ')}
        </span>
      ) : null}
      <div className="setup-grid">
        <label className="field">
          <span className="field-label">{t('compute.gpus', { max: maxGpus })}</span>
          <NumberInput className="input input-sm" value={body.gpus} min={1} max={maxGpus} onChange={(v) => set({ gpus: v ?? 1 })} />
        </label>
        <label className="field">
          <span className="field-label">{t('compute.cpus', { max: limits?.cpus ?? '?' })}</span>
          <NumberInput className="input input-sm" value={body.cpus} min={1} max={limits?.cpus} onChange={(v) => set({ cpus: v ?? 1 })} />
        </label>
        <label className="field">
          <span className="field-label">{t('compute.memory', { max: limits ? Math.floor(limits.memory_mb / GIB) : '?' })}</span>
          <NumberInput className="input input-sm" value={Math.round(body.memory_mb / GIB)} min={1} max={limits ? Math.floor(limits.memory_mb / GIB) : undefined} onChange={(v) => set({ memory_mb: (v ?? 1) * GIB })} />
        </label>
        <label className="field">
          <span className="field-label">{t('compute.hours', { max: limits ? limits.seconds / 3600 : '?' })}</span>
          <NumberInput className="input input-sm" value={body.seconds / 3600} min={1} step={1} max={limits ? limits.seconds / 3600 : undefined} onChange={(v) => set({ seconds: Math.round((v ?? 1) * 3600) })} />
        </label>
      </div>
      {partition?.max_seconds != null && body.seconds > partition.max_seconds ? <p className="field-error">{t('compute.overPartition')}</p> : null}
      <p className="muted small">{t('compute.formHelp')}</p>
      <div className="row">
        <button type="button" className="btn btn-sm" onClick={onDone}>{t('common.cancel')}</button>
        <Button type="submit" className="btn btn-sm btn-primary" disabled={!body.name.trim() || edit.save.isPending} reason={t(!body.name.trim() ? 'compute.nameRequired' : 'reason.working')}>
          {t('common.save')}
        </Button>
      </div>
      {edit.save.isError ? <ProblemCard error={edit.save.error} /> : null}
    </form>
  )
}

function Scheduler({ state }: { state: ComputeState }) {
  const { t } = useTranslation()
  return (
    <section>
      <h3>{t('compute.scheduler')}</h3>
      <p className="muted small">{state.read_at ? t('compute.readAt', { ago: fmtAgo(state.read_at) }) : t('compute.notRead')}</p>
      {state.error ? <p className="field-error">{state.error}</p> : null}
      <p className="small">{state.accounts ? t('compute.accounts', { list: state.accounts.join(', ') || '—' }) : t('compute.accountsUnknown')}</p>
      {state.partitions ? (
        <table className="table setup-table">
          <thead><tr><th>{t('compute.partition')}</th><th>{t('compute.state')}</th><th>{t('compute.maxTime')}</th><th>{t('compute.gpuCol')}</th></tr></thead>
          <tbody>
            {state.partitions.map((p) => (
              <tr key={p.name}>
                <td className="mono">{p.name}</td>
                <td>{t(p.up ? 'compute.up' : 'compute.down')}</td>
                <td className="num">{p.max_seconds != null ? fmtDuration(p.max_seconds) : t('compute.noLimitReported')}</td>
                <td>{p.gpus ? p.gpu_types.join(', ') || t('compute.gpuUntyped') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="small">{t('compute.partitionsUnknown')}</p>}
      {state.limits ? <p className="muted small">{t('compute.limits', { cpus: state.limits.cpus, gib: Math.floor(state.limits.memory_mb / GIB), hours: state.limits.seconds / 3600, gpus: Math.min(MAX_GPUS, state.limits.gpus) })}</p> : null}
    </section>
  )
}

export function ComputeDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const compute = useCompute()
  const edit = useComputeEdit()
  const check = useComputeCheck()
  const [editing, setEditing] = useState<ComputeProfile | 'new' | null>(null)
  const state = compute.data
  const scheduler = state?.backend === 'slurm'
  const userProfiles = state?.profiles.filter((p) => !p.implicit) ?? []
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('compute.title')} description={t('compute.help')} icon={codicon('server-process')} size="lg">
      <div className="setup">
        {compute.isError ? <ProblemCard error={compute.error} onRetry={() => void compute.refetch()} /> : null}
        {!state ? (compute.isLoading ? <p className="muted">{t('common.loading')}</p> : null) : !scheduler ? (
          <p className="muted">{state.backend ? t('compute.notScheduler', { backend: state.backend }) : t('compute.noRunner')}</p>
        ) : (
          <>
            <Scheduler state={state} />
            <section>
              <div className="setup-row-head">
                <h3>{t('compute.profiles')}</h3>
                <Button className="btn btn-sm ml-auto" disabled={check.checking} onClick={() => void check.check()}>{t(check.checking ? 'compute.checking' : 'compute.check')}</Button>
              </div>
              {check.failed === 'timeout' ? <p className="field-error" role="alert">{t('compute.timeout')}</p> : check.failed ? <ProblemCard error={check.failed} /> : null}
              {!userProfiles.length ? <p className="muted small">{t('compute.implicitHelp')}</p> : null}
              <ul className="setup-list">
                {state.profiles.map((p) => (
                  <li key={p.id} className="setup-row">
                    <div className="setup-row-head">
                      <strong>{p.implicit ? t('compute.implicit') : p.name}</strong>
                      <Verdict profile={p} />
                    </div>
                    <span className="muted small">
                      {t('compute.summary', { account: p.account ?? t('compute.siteDefault'), partition: p.partition ?? t('compute.siteDefault'), gpus: p.gpus, cpus: p.cpus, gib: Math.round(p.memory_mb / GIB), time: fmtDuration(p.seconds) })}
                    </span>
                    {p.implicit ? null : (
                      <div className="row">
                        <button type="button" className="btn btn-sm" onClick={() => setEditing(p)}>{t('compute.edit')}</button>
                        <ConfirmInline
                          question={t('compute.deleteQuestion')}
                          confirm={t('compute.delete')}
                          onConfirm={() => edit.remove.mutate(p.id)}
                          trigger={(ask) => <button type="button" className="btn btn-sm" onClick={ask}>{t('compute.delete')}</button>}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {editing ? (
                <ProfileForm key={editing === 'new' ? 'new' : editing.id} state={state} profile={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />
              ) : (
                <button type="button" className="btn btn-sm" onClick={() => setEditing('new')}>{t('compute.add')}</button>
              )}
              <p className="muted small">{t('compute.predictionNote')}</p>
            </section>
          </>
        )}
      </div>
    </Dialog>
  )
}
