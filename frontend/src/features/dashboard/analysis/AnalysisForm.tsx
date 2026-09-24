// DB-08 form: question type → variable → (confounder), unit of analysis (ANA-03), test override (ANA-04)
import { useTranslation } from 'react-i18next'

import { PHASES, type AnalysisSpec, type LabelDef, type UnitSpec, type Variable } from '../../../api'
import { Icon, codicon } from '../../../theme'
import { QUESTIONS, analysisVariables, confounderVariables, needsConfirmation, needsVariable, questionsFor, type PanelQuestion } from './model'

export interface FormState {
  question: PanelQuestion
  variable: string | null
  confounder: string | null
  unit: UnitSpec
  test: NonNullable<AnalysisSpec['test']>
  name: string
}

export const INITIAL_FORM: FormState = { question: 'compare', variable: null, confounder: null, unit: { aggregate: 'first' }, test: 'auto', name: '' }

/** Can the form be submitted as is? */
export function formReady(f: FormState, vars: Variable[]): boolean {
  if (!needsVariable(f.question)) return true
  const v = vars.find((x) => x.name === f.variable)
  if (!v || !questionsFor(v).includes(f.question)) return false
  return f.question !== 'balance' || (!!f.confounder && f.confounder !== f.variable)
}

export function AnalysisForm({ form, onChange, vars, labels, phases, busy, onRun, nFilters }: {
  form: FormState
  onChange: (p: Partial<FormState>) => void
  vars: Variable[]
  labels: LabelDef[]
  phases: string[]
  busy: boolean
  onRun: () => void
  nFilters: number
}) {
  const { t } = useTranslation()
  const q = form.question
  const candidates = analysisVariables(vars)
  const valid = candidates.filter((v) => questionsFor(v).includes(q))
  const unconfirmed = candidates.filter(needsConfirmation)
  const selected = vars.find((v) => v.name === form.variable) ?? null
  const confounders = confounderVariables(vars, form.variable)
  const setUnit = (p: Partial<UnitSpec>) => onChange({ unit: { ...form.unit, ...p } })

  return (
    <form
      className="an-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (formReady(form, vars)) onRun()
      }}
    >
      <div className="field">
        <span className="field-label">{t('analysis.question.label')}</span>
        <div className="seg an-seg" role="radiogroup" aria-label={t('analysis.question.label')}>
          {QUESTIONS.map((x) => (
            <button key={x} type="button" role="radio" aria-checked={q === x} aria-pressed={q === x} onClick={() => onChange({ question: x, variable: selected && questionsFor(selected).includes(x) ? form.variable : null })}>
              {t(`analysis.question.${x}`)}
            </button>
          ))}
        </div>
        <span className="muted an-help">{t(`analysis.questionHelp.${q}`)}</span>
      </div>

      {needsVariable(q) ? (
        <label className="field">
          <span className="field-label">{t('analysis.variable')}</span>
          <select className="select input-sm" aria-label={t('analysis.variable')} value={form.variable ?? ''} onChange={(e) => onChange({ variable: e.target.value || null })}>
            <option value="">{t('analysis.choose')}</option>
            {valid.map((v) => (
              <option key={v.name} value={v.name}>{v.name}</option>
            ))}
            {unconfirmed.map((v) => (
              <option key={v.name} value={v.name} disabled>{t('analysis.confirmOption', { name: v.name })}</option>
            ))}
          </select>
          {valid.length === 0 ? <span className="muted an-help">{t('analysis.noVariables')}</span> : null}
          {unconfirmed.length ? (
            <span className="an-help an-warn">
              <Icon spec={codicon('warning')} />
              {t('analysis.needsConfirm', { name: unconfirmed.map((v) => v.name).join(', ') })}
            </span>
          ) : null}
        </label>
      ) : null}

      {q === 'compare' || q === 'association' || q === 'balance' ? (
        <label className="field">
          <span className="field-label">{t(q === 'balance' ? 'analysis.other' : 'analysis.confounder')}</span>
          <select className="select input-sm" aria-label={t(q === 'balance' ? 'analysis.other' : 'analysis.confounder')} value={form.confounder ?? ''} onChange={(e) => onChange({ confounder: e.target.value || null })}>
            <option value="">{q === 'balance' ? t('analysis.choose') : t('analysis.noConfounder')}</option>
            {confounders.map((v) => (
              <option key={v.name} value={v.name}>{v.name}</option>
            ))}
          </select>
        </label>
      ) : null}

      <fieldset className="an-unit">
        <legend className="field-label">{t('analysis.unit.title')}</legend>
        <label className="field">
          <span className="field-label">{t('analysis.unit.label')}</span>
          <select className="select input-sm" aria-label={t('analysis.unit.label')} value={form.unit.label ?? ''} onChange={(e) => setUnit({ label: e.target.value === '' ? null : Number(e.target.value) })}>
            {labels.map((l) => (
              <option key={l.value} value={l.value}>{l.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t('analysis.unit.phase')}</span>
          <select className="select input-sm" aria-label={t('analysis.unit.phase')} value={form.unit.phase ?? ''} onChange={(e) => setUnit({ phase: e.target.value || null })}>
            <option value="">{t('analysis.unit.phaseAuto')}</option>
            {(phases.length ? phases : PHASES).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t('analysis.unit.scope')}</span>
          <select className="select input-sm" aria-label={t('analysis.unit.scope')} value={form.unit.scope ?? ''} onChange={(e) => setUnit({ scope: (e.target.value || null) as UnitSpec['scope'] })}>
            <option value="">{t('analysis.unit.scopeAuto')}</option>
            <option value="complete">{t('analysis.scope.complete')}</option>
            <option value="voi">{t('analysis.scope.voi')}</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">{t('analysis.unit.aggregate')}</span>
          <select className="select input-sm" aria-label={t('analysis.unit.aggregate')} value={form.unit.aggregate ?? 'first'} onChange={(e) => setUnit({ aggregate: e.target.value as 'first' | 'mean' })}>
            <option value="first">{t('analysis.unit.first')}</option>
            <option value="mean">{t('analysis.unit.mean')}</option>
          </select>
        </label>
      </fieldset>

      {q !== 'explore' ? (
        <div className="field">
          <span className="field-label">{t('analysis.testOverride.label')}</span>
          <div className="seg an-seg" role="radiogroup" aria-label={t('analysis.testOverride.label')}>
            {(['auto', 'default', 'alternative'] as const).map((x) => (
              <button key={x} type="button" role="radio" aria-checked={form.test === x} aria-pressed={form.test === x} onClick={() => onChange({ test: x })}>
                {t(`analysis.testOverride.${x}`)}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <label className="field">
        <span className="field-label">{t('analysis.name')}</span>
        <input className="input input-sm" aria-label={t('analysis.name')} value={form.name} maxLength={200} onChange={(e) => onChange({ name: e.target.value })} />
      </label>

      <div className="an-run">
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !formReady(form, vars)}>
          <Icon spec={codicon(busy ? 'loading' : 'play')} className={busy ? 'codicon-modifier-spin' : undefined} />
          {busy ? t('analysis.running') : t('analysis.run')}
        </button>
        {nFilters ? <span className="muted an-help">{t('analysis.filtersApplied', { count: nFilters })}</span> : null}
      </div>
    </form>
  )
}
