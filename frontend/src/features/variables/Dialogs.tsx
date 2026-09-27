// New derived variable (VAR-06: bin / recode / dominant) and external table import (VAR-07)
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ProblemError, useCreateDerived, useImportExternal, useVariables, type DerivedOp, type ExternalImportResult } from '../../api'
import { Dialog, NumberInput } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { categoricalSources, defaultLabels, numericSources, parseNumbers, toDefinition, type DerivedDraft } from './derived'
import { useVariablesUi } from './store'

const OPS: DerivedOp[] = ['bin', 'recode', 'dominant']
const EMPTY: DerivedDraft = { name: '', op: 'bin', source: '', mode: 'thresholds', thresholds: '', quantiles: '4', labels: '', map: {}, sources: [] }

function DerivedDialog({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const close = () => useVariablesUi.getState().openDialog(null)
  const vars = useVariables(pid).data ?? []
  const create = useCreateDerived(pid)
  const [d, setD] = useState<DerivedDraft>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const set = (p: Partial<DerivedDraft>) => {
    setD((x) => ({ ...x, ...p }))
    setError(null)
  }
  const numeric = numericSources(vars)
  const categorical = categoricalSources(vars)
  const sources = d.op === 'bin' ? numeric : categorical
  const levels = vars.find((v) => v.name === d.source)?.profile.levels ?? []
  const suggested =
    d.mode === 'quantiles' ? defaultLabels(null, Number(d.quantiles) || null) : defaultLabels(parseNumbers(d.thresholds), null)
  const submit = () => {
    const r = toDefinition(d)
    if ('error' in r) {
      setError(t(r.error))
      return
    }
    create.mutate(r.def, {
      onSuccess: (v) => {
        toast({ message: t('variables.created', { name: v.name }), tone: 'ok' })
        close()
      },
      onError: (e) => setError(e instanceof ProblemError ? (e.detail ?? e.title) : e.message),
    })
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && close()}
      title={t('variables.newDerivedTitle')}
      icon={codicon('symbol-operator')}
      footer={
        <>
          <button type="button" className="btn" onClick={close}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!d.name.trim() || create.isPending} onClick={submit}>{t('variables.create')}</button>
        </>
      }
    >
      <form className="var-form" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <label className="field">
          <span className="field-label">{t('variables.name')}</span>
          <input className="input mono" autoFocus value={d.name} placeholder={t('variables.namePlaceholder')} onChange={(e) => set({ name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} />
        </label>
        <div className="field" role="radiogroup" aria-label={t('variables.operation')}>
          <span className="field-label">{t('variables.operation')}</span>
          <div className="seg">
            {OPS.map((op) => (
              <button key={op} type="button" role="radio" aria-checked={d.op === op} aria-pressed={d.op === op} onClick={() => set({ op, source: '', map: {}, sources: [] })}>
                {t(`variables.op.${op}`)}
              </button>
            ))}
          </div>
          <span className="muted panel-size">{t(`variables.opHelp.${d.op}`)}</span>
        </div>
        {d.op !== 'dominant' ? (
          <label className="field">
            <span className="field-label">{t('variables.sourceVar')}</span>
            <select
              className="select"
              value={d.source}
              onChange={(e) => {
                const src = e.target.value
                const lv = vars.find((v) => v.name === src)?.profile.levels ?? []
                set({ source: src, map: Object.fromEntries(lv.map((l) => [l.value, l.value])) })
              }}
            >
              <option value="">{t('variables.pick')}</option>
              {sources.map((v) => (
                <option key={v.name} value={v.name}>{v.name}</option>
              ))}
            </select>
            {sources.length === 0 ? <span className="muted">{t(d.op === 'bin' ? 'variables.noNumeric' : 'variables.noCategorical')}</span> : null}
          </label>
        ) : null}
        {d.op === 'bin' ? (
          <>
            <div className="seg" role="group">
              {(['thresholds', 'quantiles'] as const).map((m) => (
                <button key={m} type="button" aria-pressed={d.mode === m} onClick={() => set({ mode: m })}>{t(`variables.binMode.${m}`)}</button>
              ))}
            </div>
            {d.mode === 'thresholds' ? (
              <label className="field">
                <span className="field-label">{t('variables.thresholds')}</span>
                <input className="input mono" value={d.thresholds} placeholder={t('variables.thresholdsPlaceholder')} onChange={(e) => set({ thresholds: e.target.value })} />
              </label>
            ) : (
              <label className="field">
                <span className="field-label">{t('variables.quantiles')}</span>
                <NumberInput className="input num" min={2} max={10} value={d.quantiles} onChange={(_, raw) => set({ quantiles: raw })} />
              </label>
            )}
            <label className="field">
              <span className="field-label">{t('variables.labels')}</span>
              <input className="input" value={d.labels} placeholder={suggested.join(', ')} onChange={(e) => set({ labels: e.target.value })} />
              <span className="muted small">{t('variables.labelsHelp')}</span>
            </label>
          </>
        ) : null}
        {d.op === 'recode' && d.source ? (
          <table className="table" aria-label={t('variables.mapping')}>
            <thead>
              <tr>
                <th>{t('variables.from')}</th>
                <th>{t('variables.to')}</th>
              </tr>
            </thead>
            <tbody>
              {levels.map((l) => (
                <tr key={l.value}>
                  <td className="mono">{l.value}</td>
                  <td>
                    <input className="input input-sm" aria-label={t('variables.recodeTo', { value: l.value })} value={d.map[l.value] ?? l.value} onChange={(e) => set({ map: { ...d.map, [l.value]: e.target.value } })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {d.op === 'dominant' ? (
          <fieldset className="field bare">
            <legend className="field-label">{t('variables.sources')}</legend>
            {numeric.map((v) => (
              <label key={v.name} className="check">
                <input
                  type="checkbox"
                  checked={d.sources.includes(v.name)}
                  onChange={(e) => set({ sources: e.target.checked ? [...d.sources, v.name] : d.sources.filter((s) => s !== v.name) })}
                />
                <span className="mono">{v.name}</span>
              </label>
            ))}
            {numeric.length === 0 ? <span className="muted">{t('variables.noNumeric')}</span> : null}
          </fieldset>
        ) : null}
        {error ? <div className="error-card" role="alert" style={{ margin: 0 }}>{error}</div> : null}
      </form>
    </Dialog>
  )
}

function ExternalDialog({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const close = () => useVariablesUi.getState().openDialog(null)
  const upload = useImportExternal(pid)
  const [file, setFile] = useState<File | null>(null)
  const [key, setKey] = useState<'case_id' | 'patient_id'>('case_id')
  const [result, setResult] = useState<ExternalImportResult | null>(null)
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && close()}
      title={t('variables.importTableTitle')}
      icon={codicon('table')}
      footer={
        <>
          <button type="button" className="btn" onClick={close}>{t(result ? 'common.close' : 'common.cancel')}</button>
          {!result ? (
            <button type="button" className="btn btn-primary" disabled={!file || upload.isPending} onClick={() => file && upload.mutate({ file, key }, { onSuccess: setResult })}>
              {t('variables.importAction')}
            </button>
          ) : null}
        </>
      }
    >
      <div className="var-form">
        <p className="muted">{t('variables.importHelp')}</p>
        <label className="field">
          <span className="field-label">{t('variables.tableFile')}</span>
          <input type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null) }} />
        </label>
        <div className="field" role="radiogroup" aria-label={t('variables.keyColumn')}>
          <span className="field-label">{t('variables.keyColumn')}</span>
          <div className="seg">
            {(['case_id', 'patient_id'] as const).map((k) => (
              <button key={k} type="button" role="radio" aria-checked={key === k} aria-pressed={key === k} onClick={() => setKey(k)}>
                <span className="mono">{k}</span>
              </button>
            ))}
          </div>
        </div>
        {upload.isError ? (
          <div className="error-card" role="alert" style={{ margin: 0 }}>
            {upload.error instanceof ProblemError ? (upload.error.detail ?? upload.error.title) : upload.error.message}
          </div>
        ) : null}
        {result ? (
          <div className="card" role="status" style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <strong>{t('variables.importResult', { matched: result.matched, rows: result.n_rows })}</strong>
            <span>{t('variables.importAdded', { names: result.added.join(', ') || '—' })}</span>
            {result.duplicate_keys.length ? (
              <span className="muted">{t('variables.importDuplicates', { count: result.duplicate_keys.length, keys: result.duplicate_keys.slice(0, 20).join(', ') })}</span>
            ) : null}
            {result.conflicts.length ? (
              <span className="text-warn">{t('variables.importConflicts', { names: result.conflicts.join(', ') })}</span>
            ) : null}
            {result.unmatched_keys.length ? (
              <span className="muted">
                {t('variables.importUnmatched', { count: result.unmatched_keys.length, keys: result.unmatched_keys.slice(0, 20).join(', ') })}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}

export function VariablesDialogs() {
  const pid = useWorkbench((s) => s.pid)
  const dialog = useVariablesUi((s) => s.dialog)
  if (!pid || !dialog) return null
  return dialog === 'derived' ? <DerivedDialog pid={pid} /> : <ExternalDialog pid={pid} />
}
