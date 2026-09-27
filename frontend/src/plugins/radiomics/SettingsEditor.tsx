// Radiomics settings tab: generated from the engine schema (RAD-01/02) and opened on the engine
// defaults, live + server validation (RAD-04), profiles (RAD-03), selection (RAD-05), estimate
// (RAD-11) and the Run button. Nothing runs automatically.
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ReviewerCancelled, useEstimate, useProfiles, useProject, useRadiomicsSchema, useStartRun, useVariables } from '../../api'
import { fmtDuration, problemMessage } from '../../lib'
import { toast, useWorkbench, toastProblem } from '../../shell'
import { Icon, codicon } from '../../theme'
import { FeatureClassesForm, FiltersForm } from './GroupForms'
import { useServerValidation } from './hooks'
import { useIssueMessage } from './IssueText'
import { OptionField } from './OptionField'
import { ProfileBar } from './ProfileBar'
import { SelectionForm } from './SelectionForm'
import { criteriaCount, knownEmpty, toSelection } from './model/selection'
import { defaultForm, featureCount, optionsByGroup, setOption, toWire } from './model/settings'
import { SELECTION, fieldOf, fromServer, groupOf, hasErrors, validateForm } from './model/validate'
import type { EstimateResult, FormState, Issue } from './model/types'
import { useDraft } from './store'
import '../../i18n/lazy'
import './radiomics.css'

/** One glyph per settings group (AUD-A3-11); an unknown engine group falls back to `settings` */
const GROUP_ICON: Record<string, string> = {
  [SELECTION]: 'list-selection',
  resampling: 'symbol-ruler',
  intensity: 'color-mode',
  discretization: 'symbol-numeric',
  mask: 'circle-large-outline',
  resegmentation: 'layers',
  filters: 'filter',
  feature_classes: 'symbol-class',
  texture: 'symbol-array',
  two_d: 'split-horizontal',
  output: 'output',
}

export function SettingsEditor() {
  const { t } = useTranslation()
  const msg = useIssueMessage()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const schema = useRadiomicsSchema()
  const project = useProject(pid)
  const variables = useVariables(pid)
  const profiles = useProfiles(pid)
  const draft = useDraft()
  const estimate = useEstimate(pid)
  const startRun = useStartRun(pid)
  const [group, setGroup] = useState<string>(SELECTION)
  const [est, setEst] = useState<{ key: string; result: EstimateResult } | null>(null)

  // Open on the engine defaults (RADIOMICS §Principles), once per project
  const s = schema.data
  const labelMap = project.data?.label_map
  useEffect(() => {
    if (!s || !labelMap) return
    const d = useDraft.getState()
    const first = labelMap.find((l) => l.visible) ?? labelMap[0]
    if (d.pid !== pid || !d.form) d.reset(pid, defaultForm(s), first ? [first.value] : [])
  }, [s, pid, labelMap])

  const form = draft.pid === pid ? draft.form : null
  const wire = useMemo(() => (s && form ? toWire(s, form) : null), [s, form])
  const selection = useMemo(() => toSelection(draft.selection), [draft.selection])
  const estKey = JSON.stringify({ wire, selection })
  const currentEst = est?.key === estKey ? est.result : null
  const nItems = knownEmpty(draft.selection) ? 0 : (currentEst?.n_items ?? null)
  const labels = draft.selection.labels

  const clientIssues = useMemo(() => (s && form ? validateForm(s, form, { labels, nItems }) : []), [s, form, labels, nItems])
  const server = useServerValidation(wire, labels, nItems)
  // The server is authoritative once its answer matches the form; until then the live rules show
  const serverNow = server.isCurrent && server.data ? server.data : null
  const issues: Issue[] = serverNow ? serverNow.issues.map(fromServer) : clientIssues
  const blocked = serverNow ? !serverNow.ok : hasErrors(clientIssues)
  const matching = serverNow ? profiles.data?.find((p) => p.profile_hash === serverNow.profile_hash) : undefined

  if (schema.isLoading || (s && !form && !project.error)) return <div className="empty">{t('common.loading')}</div>
  if (!s || !form)
    return (
      <div className="error-card" role="alert">
        <strong>{t('rad.schemaError')}</strong>
        <span>{problemMessage(schema.error ?? project.error, t('common.error'))}</span>
      </div>
    )

  const setForm = (f: FormState) => draft.setForm(f)
  const byField = new Map<string, Issue[]>()
  for (const i of issues) {
    const k = fieldOf(i.loc)
    byField.set(k, [...(byField.get(k) ?? []), i])
  }
  const issuesAt = (field: string) => byField.get(field) ?? []
  const errorsIn = (g: string) => issues.filter((i) => i.severity === 'error' && groupOf(s, i) === g).length
  const groups = optionsByGroup(s)
  const navGroups = s.groups.filter((g) => g.id === 'filters' || g.id === 'feature_classes' || (groups.get(g.id)?.length ?? 0) > 0)
  const errors = issues.filter((i) => i.severity === 'error')
  const runName = draft.runName.trim() || t('rad.defaultRunName', { profile: draft.loadedFrom ?? t('rad.engineDefaults') })
  // RADIOMICS §Decisions: defaults assume CT; warn when the selection may contain another modality
  const modalityLevels = variables.data?.find((v) => v.name === 'modality')?.profile.levels?.map((l) => l.value) ?? []
  const nonCt = modalityLevels.filter((m) => m !== 'CT')
  const pickedModality = draft.selection.mode === 'filter' ? (draft.selection.vars.modality ?? []) : []
  const mayHaveNonCt = nonCt.length > 0 && (pickedModality.length === 0 || pickedModality.some((m) => m !== 'CT'))

  const doEstimate = async () => {
    if (!wire) return
    try {
      const result = await estimate.mutateAsync({ settings: wire, selection })
      setEst({ key: estKey, result })
    } catch (e) {
      toastProblem(e, t('common.error'))
    }
  }
  const run = async () => {
    if (!wire) return
    try {
      const r = await startRun.mutateAsync({ name: runName, settings: wire, selection })
      toast({ message: t('rad.started', { name: r.name }), tone: 'info' })
      draft.setRunName('')
    } catch (e) {
      if (e instanceof ReviewerCancelled) return
      toastProblem(e, t('common.error'))
    }
  }

  return (
    <div className="rad">
      <div className="rad-top">
        <div className="rad-top-row">
          <Icon spec={codicon('beaker')} />
          <strong>{t('rad.title')}</strong>
          <span className="muted">{t('rad.engine', { name: s.engine.name, version: s.engine.version })}</span>
          {matching ? <span className="badge" data-tone="accent">{t('rad.matchesProfile', { name: matching.name })}</span> : null}
          <span style={{ flex: 1 }} />
          <ProfileBar pid={pid} schema={s} wire={wire} />
          <button type="button" className="btn btn-sm" onClick={() => draft.setForm(defaultForm(s), null)}>
            <Icon spec={codicon('discard')} />
            {t('rad.resetDefaults')}
          </button>
        </div>
      </div>
      <div className="rad-body">
        <nav className="rad-nav" aria-label={t('rad.groups')}>
          {[{ id: SELECTION, label: t('rad.selection') }, ...navGroups].map((g) => (
            <button key={g.id} type="button" className="list-row" aria-current={group === g.id || undefined} onClick={() => setGroup(g.id)}>
              <Icon spec={codicon(GROUP_ICON[g.id] ?? 'settings')} />
              {g.label}
              {errorsIn(g.id) ? <span className="count rad-err-count">{errorsIn(g.id)}</span> : null}
            </button>
          ))}
        </nav>
        <div className="rad-form">
          {group === SELECTION ? (
            <SelectionForm pid={pid} sel={draft.selection} onChange={draft.setSelection} issues={issues} />
          ) : (
            <section>
              <h2>{s.groups.find((g) => g.id === group)?.label}</h2>
              {group === 'filters' ? <FiltersForm schema={s} form={form} onChange={setForm} issuesAt={issuesAt} /> : null}
              {group === 'feature_classes' ? <FeatureClassesForm schema={s} form={form} onChange={setForm} issuesAt={issuesAt} /> : null}
              {(groups.get(group) ?? []).map((o) => (
                <OptionField key={o.name} o={o} value={form.options[o.name] ?? null} issues={issuesAt(`settings.${o.name}`)} onChange={(v) => setForm(setOption(form, o.name, v))} />
              ))}
            </section>
          )}
        </div>
        <aside className="rad-side" aria-label={t('rad.run')}>
          <div className="section-title rad-side-title">{t('rad.validation')}</div>
          {issues.length === 0 ? (
            <div className="rad-issue" data-severity="ok">
              <Icon spec={codicon('pass')} />
              {t('rad.valid')}
            </div>
          ) : (
            issues.map((i) => (
              <button key={`${i.rule}-${i.loc.join('.')}`} type="button" className="rad-issue" data-severity={i.severity} onClick={() => setGroup(groupOf(s, i))}>
                <Icon spec={codicon(i.severity === 'error' ? 'error' : 'warning')} />
                <span>
                  <span className="mono muted">{fieldOf(i.loc)}</span>
                  <span>{msg(i)}</span>
                </span>
              </button>
            ))
          )}
          {mayHaveNonCt ? (
            <div className="rad-issue" data-severity="warning">
              <Icon spec={codicon('warning')} />
              <span>{t('rad.nonCt', { modalities: nonCt.join(', ') })}</span>
            </div>
          ) : null}
          <span className="muted rad-help">{serverNow ? t('rad.checkedByServer') : server.isError ? t('rad.serverCheckFailed') : t('rad.checking')}</span>

          <div className="section-title rad-side-title">{t('rad.summary')}</div>
          <dl className="rad-summary">
            <dt>{t('rad.items')}</dt>
            <dd>{draft.selection.mode === 'filter' ? t('rad.criteria', { count: criteriaCount(draft.selection) }) : t(`rad.itemsMode.${draft.selection.mode}`)}</dd>
            <dt>{t('rad.filtersEnabled')}</dt>
            <dd>{Object.values(form.filters).filter((f) => f.enabled).length}</dd>
            <dt>{t('rad.featuresSelected')}</dt>
            <dd>{featureCount(form)}</dd>
            <dt>{t('rad.labels')}</dt>
            <dd>{labels.length}</dd>
          </dl>

          <button type="button" className="btn btn-sm" disabled={blocked || estimate.isPending} onClick={() => void doEstimate()}>
            <Icon spec={codicon(estimate.isPending ? 'loading' : 'dashboard')} />
            {t('rad.estimate')}
          </button>
          {currentEst ? (
            <div className="rad-estimate" data-testid="estimate">
              <span>{t('rad.estimateUnits', { items: currentEst.n_items, labels: currentEst.n_labels, units: currentEst.n_units })}</span>
              {currentEst.estimated_total_s !== null ? <span>{t('rad.estimateTime', { time: fmtDuration(currentEst.estimated_total_s), workers: currentEst.workers })}</span> : null}
              {currentEst.n_skipped ? (
                // TSK-04 (AUD-A2-05): skipped per reason, in plain words
                <span className="field-warning">
                  {t('rad.estimateSkipped', {
                    count: currentEst.n_skipped,
                    why: Object.entries(currentEst.skipped_by ?? {})
                      .map(([code, n]) => t('rad.skipCount', { why: t(`rad.skipCode.${code}`, { defaultValue: code }), n }))
                      .join(', ') || t('rad.skipCode.label_absent'),
                  })}
                </span>
              ) : null}
              {(currentEst.sample_errors ?? []).map((e) => (
                <span key={e} className="field-warning">{e}</span>
              ))}
            </div>
          ) : est ? (
            <span className="muted rad-help">{t('rad.estimateStale')}</span>
          ) : null}

          <div className="section-title rad-side-title">{t('rad.run')}</div>
          <label className="field">
            <span className="field-label">{t('rad.runName')}</span>
            <input className="input input-sm" value={draft.runName} placeholder={runName} onChange={(e) => draft.setRunName(e.target.value)} />
          </label>
          <button type="button" className="btn btn-primary" disabled={blocked || startRun.isPending} onClick={() => void run()}>
            <Icon spec={codicon('play')} />
            {t('rad.runButton')}
          </button>
          {errors.length ? <span className="field-error">{t('rad.fixErrors', { count: errors.length })}</span> : null}
        </aside>
      </div>
    </div>
  )
}
