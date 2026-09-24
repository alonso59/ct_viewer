// DB-02 global filters (visible variables, phase, scope, side, label, curation status) and DB-07 colour
import * as Menu from '@radix-ui/react-dropdown-menu'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { CURATION_STATUSES, PHASES, useProject, type ColorBy, type GlobalFilters, type Variable } from '../../api'
import { Icon, codicon } from '../../theme'
import { useDashboardStore, useRunDashboard } from './store'
import { useLabelName, usePid, useVisibleVariables } from './views/common'

type ListKey = 'phase' | 'scope' | 'side' | 'label' | 'status'

function MultiMenu({ label, options, value, onChange }: {
  label: string
  options: { value: string; label: string }[]
  value: string[]
  onChange: (v: string[]) => void
}) {
  const { t } = useTranslation()
  const summary = value.length === 0 ? t('search.any') : value.length === 1 ? (options.find((o) => o.value === value[0])?.label ?? value[0]) : t('dashboard.filter.nSelected', { count: value.length })
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger className="btn btn-sm db-filter" data-active={value.length > 0 || undefined} aria-label={label}>
        <span className="muted">{label}</span>
        <span>{summary}</span>
        <Icon spec={codicon('chevron-down')} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" sideOffset={4} align="start">
          {options.map((o) => (
            <Menu.CheckboxItem
              key={o.value}
              className="menu-item"
              checked={value.includes(o.value)}
              onSelect={(e) => e.preventDefault()}
              onCheckedChange={(c) => onChange(c ? [...value, o.value] : value.filter((v) => v !== o.value))}
            >
              <Icon spec={codicon(value.includes(o.value) ? 'check' : 'blank')} />
              {o.label}
            </Menu.CheckboxItem>
          ))}
          {value.length ? (
            <>
              <Menu.Separator className="menu-sep" />
              <Menu.Item className="menu-item" onSelect={() => onChange([])}>{t('dashboard.filter.clear')}</Menu.Item>
            </>
          ) : null}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

/** `var.{name}`: categorical levels (OR) or one `min..max` range (VAR-10 syntax) */
function VarFilter({ v, value, onChange }: { v: Variable; value: string[]; onChange: (v: string[] | null) => void }) {
  const { t } = useTranslation()
  if (v.type !== 'continuous') {
    const levels = (v.profile.levels ?? []).map((l) => ({ value: l.value, label: t('search.levelOption', { value: l.value, count: l.count }) }))
    return (
      <span className="db-chip">
        <MultiMenu label={v.name} options={levels} value={value} onChange={(x) => onChange(x)} />
        <button type="button" className="icon-btn" aria-label={t('dashboard.filter.remove', { name: v.name })} onClick={() => onChange(null)}>
          <Icon spec={codicon('close')} />
        </button>
      </span>
    )
  }
  const [lo = '', hi = ''] = (value[0] ?? '..').split('..')
  const set = (a: string, b: string) => onChange(a || b ? [`${a}..${b}`] : [])
  return (
    <span className="db-chip db-range" data-active={value.length > 0 || undefined}>
      <span className="muted">{v.name}</span>
      <input className="input input-sm num" type="number" aria-label={t('search.min', { name: v.name })} placeholder={v.profile.min != null ? String(v.profile.min) : t('search.minShort')} value={lo} onChange={(e) => set(e.target.value, hi)} />
      <span className="muted">{t('search.to')}</span>
      <input className="input input-sm num" type="number" aria-label={t('search.max', { name: v.name })} placeholder={v.profile.max != null ? String(v.profile.max) : t('search.maxShort')} value={hi} onChange={(e) => set(lo, e.target.value)} />
      <button type="button" className="icon-btn" aria-label={t('dashboard.filter.remove', { name: v.name })} onClick={() => onChange(null)}>
        <Icon spec={codicon('close')} />
      </button>
    </span>
  )
}

export function FilterBar({ runId, labels, trailing }: { runId: string; labels: number[]; trailing?: ReactNode }) {
  const { t } = useTranslation()
  const pid = usePid()
  const project = useProject(pid).data
  const { filters, colorBy, filterVars } = useRunDashboard(runId)
  const setFilters = useDashboardStore((s) => s.setFilters)
  const patch = useDashboardStore((s) => s.patch)
  const vars = useVisibleVariables()
  const categorical = vars.filter((v) => v.type === 'categorical')
  const labelName = useLabelName()
  const phases = project?.phase_vocabulary.length ? project.phase_vocabulary : PHASES

  const list = (k: ListKey): string[] => ((filters[k] ?? []) as (string | number)[]).map(String)
  const setList = (k: ListKey, v: string[]) => {
    const next: GlobalFilters = { ...filters }
    if (!v.length) delete next[k]
    else if (k === 'label') next.label = v.map(Number)
    else (next as Record<string, string[]>)[k] = v
    setFilters(runId, next)
  }
  const varFilters = filters.var ?? {}
  const setVar = (name: string, v: string[] | null) => {
    const nextVar = { ...varFilters }
    if (v?.length) nextVar[name] = v
    else delete nextVar[name]
    const next: GlobalFilters = { ...filters, var: nextVar }
    if (!Object.keys(nextVar).length) delete next.var
    setFilters(runId, next)
    patch(runId, { filterVars: v === null ? filterVars.filter((n) => n !== name) : filterVars.includes(name) ? filterVars : [...filterVars, name] })
  }
  const activeVars = [...new Set([...filterVars, ...Object.keys(varFilters)])]
  const colorValue = colorBy ? (colorBy.kind === 'variable' ? `variable:${colorBy.name ?? ''}` : colorBy.kind) : ''
  const setColor = (v: string) => {
    const c: ColorBy | null = !v ? null : v.startsWith('variable:') ? { kind: 'variable', name: v.slice(9) } : { kind: v as ColorBy['kind'] }
    patch(runId, { colorBy: c })
  }
  const nActive = (['phase', 'scope', 'side', 'label', 'status'] as const).filter((k) => list(k).length).length + activeVars.filter((n) => varFilters[n]?.length).length
  return (
    <div className="db-filters" role="toolbar" aria-label={t('dashboard.filters')}>
      <Icon spec={codicon('filter')} />
      <MultiMenu label={t('dashboard.filter.phase')} options={phases.map((p) => ({ value: p, label: p }))} value={list('phase')} onChange={(v) => setList('phase', v)} />
      <MultiMenu label={t('dashboard.filter.scope')} options={(['complete', 'voi'] as const).map((s) => ({ value: s, label: t(`dashboard.scope.${s}`) }))} value={list('scope')} onChange={(v) => setList('scope', v)} />
      <MultiMenu label={t('dashboard.filter.side')} options={(['L', 'R', '-'] as const).map((s) => ({ value: s, label: t(`dashboard.side.${s === '-' ? 'none' : s}`) }))} value={list('side')} onChange={(v) => setList('side', v)} />
      <MultiMenu label={t('dashboard.label')} options={labels.map((l) => ({ value: String(l), label: labelName(l) }))} value={list('label')} onChange={(v) => setList('label', v)} />
      <MultiMenu label={t('dashboard.filter.status')} options={CURATION_STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) }))} value={list('status')} onChange={(v) => setList('status', v)} />
      {activeVars.map((name) => {
        const v = vars.find((x) => x.name === name)
        return v ? <VarFilter key={name} v={v} value={varFilters[name] ?? []} onChange={(x) => setVar(name, x)} /> : null
      })}
      <Menu.Root modal={false}>
        <Menu.Trigger className="btn btn-sm" disabled={!vars.length}>
          <Icon spec={codicon('add')} />
          {t('dashboard.filter.addVariable')}
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" sideOffset={4} align="start">
            {vars.filter((v) => !activeVars.includes(v.name) && (v.type === 'categorical' || v.type === 'continuous')).map((v) => (
              <Menu.Item key={v.name} className="menu-item" onSelect={() => setVar(v.name, [])}>
                <Icon spec={codicon(v.type === 'continuous' ? 'symbol-number' : 'symbol-enum')} />
                {v.name}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {nActive ? (
        <button type="button" className="btn btn-sm" onClick={() => {
          setFilters(runId, {})
          patch(runId, { filterVars: [] })
        }}>
          {t('dashboard.filter.clearAll', { count: nActive })}
        </button>
      ) : null}
      <span className="toolbar-sep" />
      <label className="db-inline">
        {t('dashboard.colorBy')}
        <select className="select input-sm" value={colorValue} onChange={(e) => setColor(e.target.value)}>
          <option value="">{t('common.none')}</option>
          {(['phase', 'scope', 'side', 'label', 'curation_status'] as const).map((k) => (
            <option key={k} value={k}>{t(`dashboard.by.${k}`)}</option>
          ))}
          {categorical.length ? (
            <optgroup label={t('search.variables')}>
              {categorical.map((v) => (
                <option key={v.name} value={`variable:${v.name}`}>{v.name}</option>
              ))}
            </optgroup>
          ) : null}
        </select>
      </label>
      {trailing}
    </div>
  )
}
