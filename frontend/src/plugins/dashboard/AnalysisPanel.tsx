// Analysis panel (DB-08/09, ANALYSIS.md): question → variable → (confounder), unit, test; runs API-39
// with the dashboard's global filters and shows test choice, results, descriptives, recommendations.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ProblemError, useAnalyses, useAnalysis, useCreateAnalysis, useProject, useRun, useVariables, type AnalysisSpec, type GlobalFilters } from '../../api'
import { fmtAgo } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { AnalysisForm, INITIAL_FORM, type FormState } from './analysis/AnalysisForm'
import { AnalysisResult } from './analysis/AnalysisResult'
import { needsVariable, suggestedConfounder } from './analysis/model'
import { useRunDashboard } from './store'
import './analysis/analysis.css'

/** Number of active global filters (DB-02) */
function countFilters(f: GlobalFilters): number {
  const lists = [f.phase, f.scope, f.side, f.label, f.status, f.item_ids].filter((x) => x && x.length).length
  return lists + Object.values(f.var ?? {}).filter((v) => v.length).length
}

function ProblemCard({ error }: { error: unknown }) {
  const { t } = useTranslation()
  const p = error instanceof ProblemError ? error : null
  return (
    <div className="error-card" role="alert">
      <strong>{p?.title ?? t('analysis.failed')}</strong>
      {p?.detail ? <div className="an-help">{p.detail}</div> : null}
    </div>
  )
}

export function AnalysisPanel({ runId }: { runId: string }) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const run = useRun(pid, runId)
  const project = useProject(pid)
  const vars = useVariables(pid).data ?? []
  const saved = useAnalyses(pid, runId)
  const { filters } = useRunDashboard(runId)
  const create = useCreateAnalysis(pid)
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [aid, setAid] = useState<string | null>(null)
  const current = useAnalysis(pid, aid)

  const runLabels = run.data?.selection.labels ?? []
  const labelMap = project.data?.label_map ?? []
  const labels = labelMap.filter((l) => runLabels.includes(l.value))
  // Default unit label: the first run label (ANA-03: one label per unit)
  const unit = { ...form.unit, label: form.unit.label ?? runLabels[0] ?? null }

  const onChange = (p: Partial<FormState>) =>
    setForm((f) => {
      const next = { ...f, ...p }
      // Balance check needs a second variable: pre-select a tagged confounder (VAR-05)
      if (next.question === 'balance' && !next.confounder) next.confounder = suggestedConfounder(vars, next.variable)
      if (next.confounder === next.variable) next.confounder = null
      return next
    })

  const onRun = () => {
    const spec: AnalysisSpec = {
      run_id: runId,
      name: form.name.trim(),
      question: form.question,
      variable: needsVariable(form.question) ? form.variable : null,
      confounder: form.question === 'explore' ? null : form.confounder,
      filters,
      unit,
      test: form.test,
    }
    create.mutate(spec, { onSuccess: (a) => setAid(a.analysis_id) })
  }

  if (run.isError) return <ProblemCard error={run.error} />
  const list = saved.data ?? []
  return (
    <div className="an-panel">
      <div className="an-head">
        <Icon spec={codicon('beaker')} />
        <strong>{t('analysis.title')}</strong>
        <span className="muted an-help">{t('analysis.subtitle')}</span>
      </div>
      <label className="field an-saved">
        <span className="field-label">{t('analysis.saved')}</span>
        <select className="select input-sm" aria-label={t('analysis.saved')} value={aid ?? ''} onChange={(e) => setAid(e.target.value || null)} disabled={!list.length && !aid}>
          <option value="">{list.length ? t('analysis.newAnalysis') : t('analysis.savedEmpty')}</option>
          {list.map((a) => (
            <option key={a.analysis_id} value={a.analysis_id}>
              {t('analysis.savedOption', { name: a.name || `${t(`analysis.question.${a.question}`)}${a.variable ? ` · ${a.variable}` : ''}`, ago: fmtAgo(a.created_at) })}
            </option>
          ))}
        </select>
      </label>
      <AnalysisForm
        form={{ ...form, unit }}
        onChange={onChange}
        vars={vars}
        labels={labels}
        phases={project.data?.phase_vocabulary ?? []}
        busy={create.isPending}
        onRun={onRun}
        nFilters={countFilters(filters)}
      />
      {create.isError ? <ProblemCard error={create.error} /> : null}
      {aid && current.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {aid && current.isError ? <ProblemCard error={current.error} /> : null}
      {current.data ? <AnalysisResult key={current.data.analysis_id} analysis={current.data} runId={runId} labels={labelMap} /> : null}
    </div>
  )
}
