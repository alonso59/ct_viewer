// Variables view (UI_SHELL §Left pane, VAR-*): the study-agnostic variable catalog. Each field is
// profiled on import (type, level, missing %, levels); the user confirms "Review" inferences,
// overrides type/visibility/tags, and adds derived or external variables. Nothing here names a field.
import { lazy, Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  OVERRIDE_TYPES,
  ProblemError,
  VARIABLE_TAGS,
  useBrokenDerived,
  useDeleteDerived,
  usePatchVariable,
  useVariables,
  type BrokenDerived,
  type OverrideType,
  type Variable,
  type VariablePatch,
  type VariableTag,
} from '../../api'
import { fmt1 } from '../../lib'
import { toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { useVariablesUi } from './store'
import './variables.css'

// Derived/external dialogs load on first open, outside the initial bundle (NFR-07)
const VariablesDialogs = lazy(() => import('./Dialogs').then((m) => ({ default: m.VariablesDialogs })))

type Section = 'study' | 'acquisition' | 'derived' | 'external'
const SECTIONS: Section[] = ['study', 'derived', 'external', 'acquisition']
const isOverrideType = (ty: string): ty is OverrideType => (OVERRIDE_TYPES as readonly string[]).includes(ty)
const sectionOf = (v: Variable): Section => (v.source === 'derived' ? 'derived' : v.source === 'external' ? 'external' : v.group)

/** Problem detail when the server gives one (e.g. 422 "used by …" on deleting a derived variable) */
const problemText = (e: Error) => (e instanceof ProblemError && e.detail ? e.detail : e.message)

/** Short summary of a derived definition, e.g. "bin(score) at 50" */
function definitionText(v: Variable, t: (k: string, o?: Record<string, unknown>) => string): string {
  const d = v.definition
  if (!d) return ''
  if (d.op === 'bin')
    return d.thresholds?.length
      ? t('variables.def.binThresholds', { source: d.source, thresholds: d.thresholds.join(', ') })
      : t('variables.def.binQuantiles', { source: d.source, n: d.quantiles ?? 2 })
  if (d.op === 'recode') return t('variables.def.recode', { source: d.source, n: Object.keys(d.map).length })
  return t('variables.def.dominant', { sources: d.sources.join(', ') })
}

function Detail({ pid, v }: { pid: string; v: Variable }) {
  const { t } = useTranslation()
  const patch = usePatchVariable(pid)
  const del = useDeleteDerived(pid)
  const fail = (e: Error) => toast({ message: problemText(e), tone: 'error' })
  const apply = (p: VariablePatch) => patch.mutate({ name: v.name, patch: p }, { onError: fail })
  const toggleTag = (tag: VariableTag) => apply({ tags: v.tags.includes(tag) ? v.tags.filter((x) => x !== tag) : [...v.tags, tag] })
  const levels = v.profile.levels ?? []
  return (
    <div className="var-detail">
      {v.review ? (
        <div className="var-review" role="note">
          <Icon spec={codicon('question')} />
          <span>{t(v.inferred_type === 'numeric-discrete' ? 'variables.reviewDiscrete' : 'variables.reviewLow', { type: t(`varType.${v.inferred_type}`) })}</span>
          <span className="var-review-actions">
            {(v.inferred_type === 'numeric-discrete' ? (['categorical', 'continuous'] as const) : [v.type].filter(isOverrideType)).map((ty) => (
              <button key={ty} type="button" className="btn btn-sm" disabled={patch.isPending} onClick={() => apply({ type: ty })}>
                {t('variables.useType', { type: t(`varType.${ty}`) })}
              </button>
            ))}
          </span>
        </div>
      ) : null}
      <dl className="props" style={{ padding: 0 }}>
        <dt>{t('variables.type')}</dt>
        <dd>
          <select
            className="select input-sm"
            aria-label={t('variables.typeOf', { name: v.name })}
            value={v.type}
            disabled={v.source === 'derived'}
            onChange={(e) => isOverrideType(e.target.value) && apply({ type: e.target.value })}
          >
            {[...new Set<Variable['type']>([v.type, ...OVERRIDE_TYPES])].map((ty) => (
              <option key={ty} value={ty}>{t(`varType.${ty}`)}</option>
            ))}
          </select>
          {v.overridden && v.type !== v.inferred_type ? <span className="muted"> {t('variables.inferred', { type: t(`varType.${v.inferred_type}`) })}</span> : null}
        </dd>
        <dt>{t('variables.level')}</dt>
        <dd title={t(`variables.levelName.${v.level}`)}>{t(`variables.levelShort.${v.level}`)}</dd>
        <dt>{t('variables.source')}</dt>
        <dd>{t(`variables.sourceName.${v.source}`)}</dd>
        <dt>{t('variables.missing')}</dt>
        <dd className="num">{t('variables.pct', { v: fmt1(v.profile.missing_pct) })}</dd>
        <dt>{t('variables.distinct')}</dt>
        <dd className="num">{v.profile.n_distinct}</dd>
        {v.profile.min != null && v.profile.max != null ? (
          <>
            <dt>{t('variables.range')}</dt>
            <dd className="num">{t('variables.rangeValue', { min: v.profile.min, max: v.profile.max })}</dd>
          </>
        ) : null}
        {v.definition ? (
          <>
            <dt>{t('variables.definition')}</dt>
            <dd className="mono">{definitionText(v, t)}</dd>
          </>
        ) : null}
      </dl>
      {levels.length ? (
        <div className="var-levels" aria-label={t('variables.levels')}>
          {levels.slice(0, 12).map((l) => (
            <span key={l.value} className="badge">{t('variables.levelCount', { value: l.value, count: l.count })}</span>
          ))}
          {levels.length > 12 ? <span className="muted">{t('variables.moreLevels', { n: levels.length - 12 })}</span> : null}
        </div>
      ) : v.profile.examples.length ? (
        <div className="muted var-examples">{t('variables.examples', { values: v.profile.examples.join(', ') })}</div>
      ) : null}
      <div className="var-tags" role="group" aria-label={t('variables.tags')}>
        {VARIABLE_TAGS.map((tag) => (
          <button key={tag} type="button" className="badge var-tag" aria-pressed={v.tags.includes(tag)} data-tone={v.tags.includes(tag) ? 'accent' : undefined} onClick={() => toggleTag(tag)} title={t(`variables.tagHelp.${tag}`)}>
            {t(`variables.tag.${tag}`)}
          </button>
        ))}
      </div>
      {v.source === 'derived' ? (
        <button
          type="button"
          className="btn btn-sm btn-danger"
          disabled={del.isPending}
          onClick={() => del.mutate(v.name, { onError: fail })}
        >
          <Icon spec={codicon('trash')} />
          {t('variables.deleteDerived')}
        </button>
      ) : null}
    </div>
  )
}

function Row({ pid, v, open, onToggle }: { pid: string; v: Variable; open: boolean; onToggle: () => void }) {
  const { t } = useTranslation()
  const patch = usePatchVariable(pid)
  return (
    <div className="var-item" data-open={open}>
      <div className="list-row var-row">
        <button
          type="button"
          className="icon-btn var-eye"
          aria-pressed={v.visible}
          aria-label={t(v.visible ? 'variables.hide' : 'variables.show', { name: v.name })}
          title={t(v.visible ? 'variables.hide' : 'variables.show', { name: v.name })}
          onClick={() => patch.mutate({ name: v.name, patch: { visible: !v.visible } }, { onError: (e) => toast({ message: problemText(e), tone: 'error' }) })}
        >
          <Icon spec={codicon(v.visible ? 'eye' : 'eye-closed')} />
        </button>
        <button type="button" className="var-name" aria-expanded={open} onClick={onToggle}>
          <span className="mono" title={v.name}>{v.name}</span>
          {v.review ? <span className="badge" data-tone="warn">{t('variables.review')}</span> : null}
          <span className="var-meta">
            <span className="badge" title={t(`variables.levelName.${v.level}`)}>{t(`varTypeShort.${v.type}`)}</span>
            <span className="muted num" title={t('variables.missing')}>{t('variables.pct', { v: fmt1(v.profile.missing_pct) })}</span>
          </span>
        </button>
      </div>
      {open ? <Detail pid={pid} v={v} /> : null}
    </div>
  )
}

/** VAR-06: a derived variable whose source is gone (e.g. its label table was deleted): shown with
 *  the reason so it can be deleted (AUD-A5-08) */
function BrokenRow({ pid, b }: { pid: string; b: BrokenDerived }) {
  const { t } = useTranslation()
  const del = useDeleteDerived(pid)
  return (
    <div className="var-item">
      <div className="list-row var-row" title={b.reason}>
        <span className="var-name">
          <span className="mono" title={b.name}>{b.name}</span>
          <span className="badge" data-tone="error">{t('variables.broken')}</span>
          <span className="muted var-meta">{b.reason}</span>
        </span>
        <button type="button" className="icon-btn" aria-label={t('variables.deleteNamed', { name: b.name })} title={t('variables.deleteDerived')} disabled={del.isPending} onClick={() => del.mutate(b.name, { onError: (e) => toast({ message: problemText(e), tone: 'error' }) })}>
          <Icon spec={codicon('trash')} />
        </button>
      </div>
    </div>
  )
}

export function VariablesView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vars = useVariables(pid)
  const broken = useBrokenDerived(pid).data ?? []
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const collapsed = useVariablesUi((s) => s.collapsed)
  const toggleSection = useVariablesUi((s) => s.toggleSection)
  const list = (vars.data ?? []).filter((v) => !q || v.name.toLowerCase().includes(q.trim().toLowerCase()))
  const review = (vars.data ?? []).filter((v) => v.review).length
  if (vars.isError)
    return (
      <div className="error-card" role="alert">
        <strong>{t('common.error')}</strong>
        <div className="muted">{vars.error.message}</div>
      </div>
    )
  return (
    <div className="var-view">
      <div style={{ padding: '0 8px 6px' }}>
        <input className="input input-sm" style={{ width: '100%' }} value={q} placeholder={t('variables.filter')} aria-label={t('variables.filter')} onChange={(e) => setQ(e.target.value)} />
      </div>
      {vars.data ? (
        <div className="muted var-summary">
          {t('variables.summary', { count: vars.data.length })}
          {review ? <span className="badge" data-tone="warn">{t('variables.toReview', { count: review })}</span> : null}
        </div>
      ) : null}
      {vars.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      {vars.data?.length === 0 ? <div className="empty">{t('variables.none')}</div> : null}
      <div className="var-list" role="list">
        {SECTIONS.map((s) => {
          const rows = list.filter((v) => sectionOf(v) === s)
          const bad = s === 'derived' ? broken.filter((b) => !q || b.name.toLowerCase().includes(q.trim().toLowerCase())) : []
          if (!rows.length && !bad.length) return null
          const shut = collapsed[s] ?? s === 'acquisition'
          return (
            <section key={s} role="listitem" aria-label={t(`variables.section.${s}`)}>
              <button type="button" className="var-section" aria-expanded={!shut} onClick={() => toggleSection(s, !shut)}>
                <Icon spec={codicon(shut ? 'chevron-right' : 'chevron-down')} />
                {t(`variables.section.${s}`)}
                <span className="count">{rows.length + bad.length}</span>
              </button>
              {!shut ? rows.map((v) => <Row key={v.name} pid={pid} v={v} open={open === v.name} onToggle={() => setOpen(open === v.name ? null : v.name)} />) : null}
              {!shut ? bad.map((b) => <BrokenRow key={b.name} pid={pid} b={b} />) : null}
            </section>
          )
        })}
      </div>
      <LazyDialogs />
    </div>
  )
}

function LazyDialogs() {
  const dialog = useVariablesUi((s) => s.dialog)
  return dialog ? (
    <Suspense fallback={null}>
      <VariablesDialogs />
    </Suspense>
  ) : null
}

export function VariablesActions() {
  const { t } = useTranslation()
  const open = useVariablesUi((s) => s.openDialog)
  return (
    <>
      <button type="button" className="icon-btn" aria-label={t('variables.newDerived')} title={t('variables.newDerived')} onClick={() => open('derived')}>
        <Icon spec={codicon('symbol-operator')} />
      </button>
      <button type="button" className="icon-btn" aria-label={t('variables.importTable')} title={t('variables.importTable')} onClick={() => open('external')}>
        <Icon spec={codicon('table')} />
      </button>
    </>
  )
}
