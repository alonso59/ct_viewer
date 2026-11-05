import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useCreateDerived, useVariables, type DerivedOp } from '../../api'
import { Dialog, NumberInput, RadioSeg, problemMessage } from '../../lib'
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
      onError: (e) => setError(problemMessage(e)),
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
        <div className="field">
          <span className="field-label">{t('variables.operation')}</span>
          <RadioSeg label={t('variables.operation')} value={d.op} options={OPS.map((op) => ({ value: op, label: t(`variables.op.${op}`) }))} onChange={(op) => set({ op, source: '', map: {}, sources: [] })} />
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

export function VariablesDialogs() {
  const pid = useWorkbench((s) => s.pid)
  const dialog = useVariablesUi((s) => s.dialog)
  if (!pid || !dialog) return null
  return dialog === 'derived' ? <DerivedDialog pid={pid} /> : null
}
