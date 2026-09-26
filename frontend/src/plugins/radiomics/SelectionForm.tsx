// Run selection (RAD-05): items (all active / filter on any variable (VAR-10) / explicit list,
// or the current Explorer filter), scope and labels (one extraction per label).
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { PHASES, useProject, useSegmentations, useVariables, type Variable } from '../../api'
import { IconButton } from '../../lib'
import { codicon } from '../../theme'
import { explorerSelection, useExplorerFilter, type ExplorerSelection } from '../../features/explorer'
import { SIDES, parseItemIds, type ItemsMode, type SelectionForm as Sel } from './model/selection'
import { fieldOf } from './model/validate'
import type { Issue } from './model/types'
import { IssueText } from './IssueText'

/** Variables a level filter can use: those with a finite set of levels */
export const filterable = (v: Variable) => (v.type === 'categorical' || v.type === 'numeric-discrete' || v.type === 'constant') && (v.profile.levels?.length ?? 0) > 0

function toggle<T>(list: T[], v: T, on: boolean): T[] {
  return on ? (list.includes(v) ? list : [...list, v]) : list.filter((x) => x !== v)
}

/** "Use the current Explorer filter": what was applied, and what could not be sent */
function ExplorerNote({ applied }: { applied: ExplorerSelection }) {
  const { t } = useTranslation()
  const notes = [
    ...applied.dropped.map((d) => t(`rad.fromExplorer.dropped.${d}`)),
    ...(applied.ranges.length ? [t('rad.fromExplorer.ranges', { names: applied.ranges.join(', ') })] : []),
  ]
  return (
    <div className="muted rad-help" role="status">
      {t(applied.itemIds ? 'rad.fromExplorer.appliedList' : 'rad.fromExplorer.appliedFilter', { count: applied.itemIds?.length ?? 0 })}
      {notes.length ? (
        <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function SelectionForm({ pid, sel, onChange, issues }: { pid: string; sel: Sel; onChange: (patch: Partial<Sel>) => void; issues: Issue[] }) {
  const { t } = useTranslation()
  const project = useProject(pid).data
  const variables = useVariables(pid).data ?? []
  const sets = useSegmentations(pid).data ?? []
  const [adding, setAdding] = useState('')
  const explorerFilter = useExplorerFilter()
  const fromExplorer = explorerSelection(explorerFilter, variables)
  const explorerEmpty = !fromExplorer.itemIds && !fromExplorer.phase.length && !Object.keys(fromExplorer.vars).length && !fromExplorer.ranges.length && !fromExplorer.dropped.length
  const [applied, setApplied] = useState<ExplorerSelection | null>(null)
  const applyExplorer = () => {
    const x = fromExplorer
    if (x.itemIds) onChange({ mode: 'list', list: x.itemIds.join('\n'), ...(x.scope ? { scope: x.scope } : {}) })
    else onChange({ mode: 'filter', phase: x.phase, side: [], vars: x.vars })
    setApplied(x)
  }
  const phases = project?.phase_vocabulary.length ? project.phase_vocabulary : PHASES
  const levelVars = variables.filter(filterable)
  const continuous = variables.filter((v) => v.type === 'continuous')
  const chosen = Object.keys(sel.vars)
  const ids = parseItemIds(sel.list)
  const labelIssues = issues.filter((i) => fieldOf(i.loc) === 'labels' || fieldOf(i.loc) === 'n_items')

  return (
    <section>
      <h2>{t('rad.selection')}</h2>
      <div className="rad-field">
        <span className="rad-label">{t('rad.items')}</span>
        <div className="field">
          <div className="seg" role="radiogroup" aria-label={t('rad.items')}>
            {(['all', 'filter', 'list'] as ItemsMode[]).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={sel.mode === m} aria-pressed={sel.mode === m} onClick={() => onChange({ mode: m })}>
                {t(`rad.itemsMode.${m}`)}
              </button>
            ))}
          </div>
          <span className="muted rad-help">{t(`rad.itemsHelp.${sel.mode}`)}</span>
          <div>
            <button type="button" className="btn btn-sm" disabled={explorerEmpty} title={t(explorerEmpty ? 'rad.fromExplorer.empty' : 'rad.fromExplorer.hint')} onClick={applyExplorer}>
              {t('rad.fromExplorer.use')}
            </button>
          </div>
          {applied ? <ExplorerNote applied={applied} /> : null}
        </div>
      </div>

      {sel.mode === 'filter' ? (
        <div className="rad-filter">
          <div className="rad-field">
            <span className="rad-label">{t('rad.phase')}</span>
            <div className="rad-chips">
              {phases.map((p) => (
                <label key={p} className="check">
                  <input type="checkbox" checked={sel.phase.includes(p)} onChange={(e) => onChange({ phase: toggle(sel.phase, p, e.target.checked) })} />
                  <span>{p}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="rad-field">
            <span className="rad-label">{t('rad.side')}</span>
            <div className="rad-chips">
              {SIDES.map((s) => (
                <label key={s} className="check">
                  <input type="checkbox" checked={sel.side.includes(s)} onChange={(e) => onChange({ side: toggle(sel.side, s, e.target.checked) })} />
                  <span>{t(`rad.sideName.${s === '-' ? 'none' : s}`)}</span>
                </label>
              ))}
            </div>
          </div>
          {chosen.map((name) => {
            const v = variables.find((x) => x.name === name)
            const levels = v?.profile.levels ?? []
            const picked = sel.vars[name] ?? []
            return (
              <div key={name} className="rad-field">
                <span className="rad-label mono">{name}</span>
                <div className="rad-chips">
                  {levels.map((l) => (
                    <label key={l.value} className="check">
                      <input
                        type="checkbox"
                        checked={picked.includes(l.value)}
                        onChange={(e) => onChange({ vars: { ...sel.vars, [name]: toggle(picked, l.value, e.target.checked) } })}
                      />
                      <span>{l.value}</span>
                      <span className="muted num">{l.count}</span>
                    </label>
                  ))}
                  <IconButton
                    label={t('rad.removeVar', { name })}
                    icon={codicon('close')}
                    onClick={() => onChange({ vars: Object.fromEntries(Object.entries(sel.vars).filter(([k]) => k !== name)) })}
                  />
                </div>
              </div>
            )
          })}
          <div className="rad-field">
            <label className="rad-label" htmlFor="rad-add-var">{t('rad.addVar')}</label>
            <div className="field">
              <select
                id="rad-add-var"
                className="select input-sm"
                value={adding}
                onChange={(e) => {
                  const name = e.target.value
                  setAdding('')
                  if (name) onChange({ vars: { ...sel.vars, [name]: [] } })
                }}
              >
                <option value="">{t('rad.addVarPlaceholder')}</option>
                {levelVars
                  .filter((v) => !chosen.includes(v.name))
                  .map((v) => (
                    <option key={v.name} value={v.name}>{v.name}</option>
                  ))}
              </select>
              {continuous.length ? <span className="muted rad-help">{t('rad.continuousHint', { names: continuous.map((v) => v.name).join(', ') })}</span> : null}
            </div>
          </div>
        </div>
      ) : null}

      {sel.mode === 'list' ? (
        <div className="rad-field">
          <label className="rad-label" htmlFor="rad-item-list">{t('rad.itemIds')}</label>
          <div className="field">
            <textarea id="rad-item-list" className="input rad-textarea mono" rows={6} value={sel.list} placeholder={t('rad.itemIdsPlaceholder')} onChange={(e) => onChange({ list: e.target.value })} />
            <span className="muted rad-help">{t('rad.itemIdsCount', { count: ids.length })}</span>
          </div>
        </div>
      ) : null}

      <div className="rad-field">
        <span className="rad-label">{t('rad.scope')}</span>
        <div className="seg" role="radiogroup" aria-label={t('rad.scope')}>
          {(['complete', 'voi'] as const).map((s) => (
            <button key={s} type="button" role="radio" aria-checked={sel.scope === s} aria-pressed={sel.scope === s} onClick={() => onChange({ scope: s })}>
              {t(`rad.scopeName.${s}`)}
            </button>
          ))}
        </div>
      </div>

      {/* RAD-05: the set is always visible (default `default_seg`), so the run names its masks */}
      {sets.length ? (
        <div className="rad-field">
          <label className="rad-label" htmlFor="rad-seg">{t('rad.segSet')}</label>
          <select id="rad-seg" className="select" value={sel.seg ?? project?.default_seg ?? 'imported'} onChange={(e) => onChange({ seg: e.target.value })}>
            {sets.map((s) => (
              <option key={s.seg_id} value={s.seg_id}>{s.name || s.seg_id}</option>
            ))}
          </select>
        </div>
      ) : null}

      <div className="rad-field">
        <span className="rad-label">{t('rad.labels')}</span>
        <div className="field">
          <div className="rad-chips">
            {(project?.label_map ?? []).map((l) => (
              <label key={l.value} className="check">
                <input type="checkbox" checked={sel.labels.includes(l.value)} onChange={(e) => onChange({ labels: toggle(sel.labels, l.value, e.target.checked) })} />
                <span className="dot" style={{ background: l.color }} />
                <span>{l.name}</span>
                <span className="muted num">{l.value}</span>
              </label>
            ))}
          </div>
          <span className="muted rad-help">{t('rad.labelsHelp')}</span>
          {labelIssues.map((i) => (
            <IssueText key={fieldOf(i.loc)} issue={i} className="field-error" />
          ))}
        </div>
      </div>
    </section>
  )
}
