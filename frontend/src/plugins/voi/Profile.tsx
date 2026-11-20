// A run's lesions and training profile: the volume distribution with the size bin cuts, per bin the
// counts, probabilities, patch budget, role priors and patch sizes. Edits recompute the profile from
// the run's measured lesions (no volume is read) and can be saved as named variants.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, useSaveVoiProfile, useVoiProfile, useVoiProfiles, type VoiProfileSettings } from '../../api'
import { Button, NumberInput, ProblemCard } from '../../lib'
import { openEditor, toast } from '../../shell'
import { parsePercentiles, percentilesOf, type Values } from './model'

type Role = 'center' | 'border' | 'context'
const ROLES: Role[] = ['center', 'border', 'context']
const NAME = /^[a-z0-9][a-z0-9_-]{0,63}$/

/** The parts of `sampling_profile.json` (schema 2) shown here */
interface ProfileJson {
  num_lesions: number
  settings_hash: string
  balancing_alpha: number
  size_bins: { name: string; label: string; max_inclusive: number | null }[]
  size_bin_counts: Record<string, number>
  empirical_size_bin_probabilities: Record<string, number>
  target_size_bin_probabilities: Record<string, number>
  suggested_patch_budget_by_size_bin: Record<string, number>
  suggested_patch_role_priors_by_size_bin: Record<string, Record<Role, number>>
  heuristic_patch_recommendations: Record<string, { recommended_min_patch_extent: number[]; recommended_context_patch_extent: number[]; recommended_min_patch_vox?: number[] }>
  warnings?: string[]
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

const pct = (p: number | undefined) => (p === undefined ? '—' : `${Math.round(p * 1000) / 10} %`)
const box = (mm: readonly number[] | undefined) => (mm ? mm.map((v) => Math.round(v)).join(' × ') : '—')

/** Lesion volumes on a log scale, 24 bars, with the size bin cuts drawn over them */
export function VolumeHistogram({ volumesMm3, cutsMm3 }: { volumesMm3: number[]; cutsMm3: number[] }) {
  const { t } = useTranslation()
  const logs = volumesMm3.filter((v) => v > 0).map((v) => Math.log10(v / 1000))
  if (!logs.length) return null
  const lo = Math.min(...logs)
  const hi = Math.max(...logs, lo + 1e-6)
  const n = 24
  const counts = new Array<number>(n).fill(0)
  for (const x of logs) {
    const k = Math.min(n - 1, Math.floor(((x - lo) / (hi - lo)) * n))
    counts[k] = (counts[k] ?? 0) + 1
  }
  const top = Math.max(...counts)
  const W = 480
  const H = 120
  const xOf = (log: number) => ((log - lo) / (hi - lo)) * W
  return (
    <figure className="voi-hist">
      <svg viewBox={`0 0 ${W} ${H + 16}`} role="img" aria-label={t('voi.lesions.histogram', { count: logs.length })}>
        {counts.map((c, i) => (c ? <rect key={i} x={(i * W) / n + 1} width={W / n - 2} y={H - (c / top) * H} height={(c / top) * H} className="voi-hist-bar" /> : null))}
        {cutsMm3.filter((c) => c > 0).map((c) => {
          const x = xOf(Math.log10(c / 1000))
          return <line key={c} x1={x} x2={x} y1={0} y2={H} className="voi-hist-cut" />
        })}
        <text x={0} y={H + 13} className="voi-hist-axis">{t('voi.ml', { v: Number((10 ** lo).toPrecision(2)) })}</text>
        <text x={W} y={H + 13} textAnchor="end" className="voi-hist-axis">{t('voi.ml', { v: Number((10 ** hi).toPrecision(2)) })}</text>
      </svg>
    </figure>
  )
}

export default function ProfilePanel({ pid, runId, settings }: { pid: string; runId: string; settings: Values }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<VoiProfileSettings>({})
  const [pctText, setPctText] = useState(() => percentilesOf(settings).join(', '))
  const [name, setName] = useState('')
  const body = useDebounced(draft)
  const q = useVoiProfile(pid, runId, body)
  const saved = useVoiProfiles(pid, runId)
  const save = useSaveVoiProfile(pid, runId)
  const prof = q.data?.profile as unknown as ProfileJson | undefined
  const bins = prof?.size_bins ?? []
  const budgets = bins.map((b) => prof?.suggested_patch_budget_by_size_bin[b.name] ?? 1)
  const priors = bins.map((b) => prof?.suggested_patch_role_priors_by_size_bin[b.name] ?? { center: 0.5, border: 0.3, context: 0.2 })
  const edit = (patch: VoiProfileSettings) => setDraft((d) => ({ ...d, ...patch }))
  const setBudget = (i: number, v: number | null) => edit({ budget_by_bin: budgets.map((b, j) => (j === i ? Math.max(1, Math.round(v ?? 1)) : b)) })
  const setPrior = (i: number, role: Role, v: number | null) => edit({ role_priors_by_bin: priors.map((p, j) => (j === i ? { ...p, [role]: Math.max(0, v ?? 0) } : p)) })
  const onPct = (text: string) => {
    setPctText(text)
    const ps = parsePercentiles(text)
    // other bins: the per-bin budgets and priors no longer line up
    if (ps) setDraft((d) => ({ ...d, bin_percentiles: ps, budget_by_bin: null, role_priors_by_bin: null }))
  }
  const reset = () => {
    setDraft({})
    setPctText(percentilesOf(settings).join(', '))
  }
  const onSave = () =>
    save.mutate(
      { name, body: draft },
      { onSuccess: (p) => toast({ message: t('voi.profile.saved', { name: p.name }), tone: 'ok' }) },
    )
  const edited = Object.keys(draft).length > 0
  return (
    <div className="voi-profile">
      {q.error ? <ProblemCard error={q.error} /> : null}
      <div className="voi-profile-controls">
        <label className="voi-field">
          <span>{t('voi.profile.percentiles')}</span>
          <input className="input input-sm" value={pctText} aria-invalid={!parsePercentiles(pctText)} onChange={(e) => onPct(e.target.value)} />
        </label>
        <label className="voi-field">
          <span>{t('voi.profile.alpha')}</span>
          <NumberInput className="input input-sm num" value={draft.balancing_alpha ?? prof?.balancing_alpha ?? 0.5} min={0} max={1} step={0.1} onChange={(v) => edit({ balancing_alpha: v ?? 0.5 })} />
        </label>
        <Button className="btn btn-sm" disabled={!edited} onClick={reset}>
          {t('voi.profile.reset')}
        </Button>
        <span style={{ flex: 1 }} />
        <Button className="btn btn-sm" onClick={() => openEditor('table', { tableId: `${runId}-lesions` })}>
          {t('voi.profile.openTable')}
        </Button>
      </div>
      {prof ? (
        <>
          <p className="muted">{t('voi.profile.summary', { count: prof.num_lesions, bins: bins.length, hash: prof.settings_hash.replace(/^sha256:/, '').slice(0, 12) })}</p>
          <VolumeHistogram volumesMm3={q.data?.lesion_volumes_mm3 ?? []} cutsMm3={bins.flatMap((b) => (b.max_inclusive === null ? [] : [b.max_inclusive]))} />
          <div className="voi-profile-table-wrap">
            <table className="table voi-profile-table">
              <thead>
                <tr>
                  <th>{t('voi.profile.bin')}</th>
                  <th className="num">{t('voi.profile.lesions')}</th>
                  <th className="num">{t('voi.profile.empirical')}</th>
                  <th className="num">{t('voi.profile.target')}</th>
                  <th className="num">{t('voi.profile.budget')}</th>
                  {ROLES.map((r) => (
                    <th key={r} className="num">{t(`voi.profile.role.${r}`)}</th>
                  ))}
                  <th>{t('voi.profile.patch')}</th>
                </tr>
              </thead>
              <tbody>
                {bins.map((b, i) => {
                  const rec = prof.heuristic_patch_recommendations[b.name]
                  return (
                    <tr key={b.name}>
                      <td>
                        <span className="mono">{b.name}</span> <span className="muted">{b.label}</span>
                      </td>
                      <td className="num">{prof.size_bin_counts[b.name] ?? 0}</td>
                      <td className="num">{pct(prof.empirical_size_bin_probabilities[b.name])}</td>
                      <td className="num">{pct(prof.target_size_bin_probabilities[b.name])}</td>
                      <td className="num">
                        <NumberInput className="input input-sm num" aria-label={t('voi.profile.budgetOf', { bin: b.name })} value={budgets[i]} min={1} max={64} step={1} onChange={(v) => setBudget(i, v)} />
                      </td>
                      {ROLES.map((r) => (
                        <td key={r} className="num">
                          <NumberInput className="input input-sm num" aria-label={t('voi.profile.roleOf', { bin: b.name, role: t(`voi.profile.role.${r}`) })} value={priors[i]?.[r] ?? 0} min={0} max={1} step={0.05} onChange={(v) => setPrior(i, r, v)} />
                        </td>
                      ))}
                      <td className="mono">
                        {rec ? t('voi.profile.patchLine', { min: box(rec.recommended_min_patch_extent), context: box(rec.recommended_context_patch_extent) }) : '—'}
                        {rec?.recommended_min_patch_vox ? <span className="muted"> {t('voi.profile.patchVox', { vox: box(rec.recommended_min_patch_vox) })}</span> : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {prof.warnings?.length ? (
            <ul className="voi-warnings">
              {prof.warnings.map((w) => (
                <li key={w} className="voi-warn">
                  <span className="codicon codicon-warning" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
      <div className="voi-profile-save">
        <label className="voi-field">
          <span>{t('voi.profile.name')}</span>
          <input className="input input-sm" value={name} placeholder="balanced" aria-invalid={!!name && (!NAME.test(name) || name === 'run')} onChange={(e) => setName(e.target.value.trim())} />
        </label>
        <Button className="btn btn-sm btn-primary" disabled={!NAME.test(name) || name === 'run' || save.isPending} onClick={onSave}>
          {t('voi.profile.save')}
        </Button>
        {save.error ? <ProblemCard error={save.error} /> : null}
      </div>
      <ul className="voi-profile-files">
        <li>
          <a href={api.voiProfileExportUrl(pid, runId, 'run')} download>
            {t('voi.profile.downloadRun')}
          </a>
        </li>
        {(saved.data ?? []).map((s) => (
          <li key={s.name}>
            <a href={api.voiProfileExportUrl(pid, runId, s.name)} download>
              {s.name}
            </a>{' '}
            <span className="muted">{t('voi.profile.savedBy', { who: s.saved_by ?? '—', count: s.num_lesions })}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
