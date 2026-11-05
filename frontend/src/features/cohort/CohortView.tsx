import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { useVariables, type Variable } from '../../api'
import { ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { CATEGORIES, ORIGINS, useCohort, type GroupSelection } from './store'
import './cohort.css'

const selEquals = (a: GroupSelection | null, b: GroupSelection) => a?.origin === b.origin && a?.category === b.category

function VarRow({ v, pinned, onPick }: { v: Variable; pinned: string[]; onPick?: () => void }) {
  const { t } = useTranslation()
  const togglePin = useCohort((s) => s.togglePin)
  const isPinned = pinned.includes(v.name)
  const constant = v.type === 'constant'
  const value = v.profile.levels?.[0]?.value ?? v.profile.examples[0] ?? ''
  const name: ReactNode = (
    <>
      <span className="mono" title={v.name}>{v.name}</span>
      {constant ? <span className="muted cohort-same">{t('cohort.nav.same', { value })}</span> : null}
      {isPinned ? <span className="badge" data-tone="accent">{t('cohort.nav.pinned')}</span> : null}
    </>
  )
  return (
    <div className="list-row cohort-var">
      {constant ? null : (
        <button
          type="button"
          className="icon-btn"
          aria-pressed={isPinned}
          aria-label={t(isPinned ? 'cohort.nav.unpin' : 'cohort.nav.pin', { name: v.name })}
          title={t(isPinned ? 'cohort.nav.unpin' : 'cohort.nav.pin', { name: v.name })}
          onClick={() => togglePin(v.name)}
        >
          <Icon spec={codicon(isPinned ? 'pinned' : 'pin')} />
        </button>
      )}
      {onPick ? <button type="button" className="cohort-var-name" onClick={onPick}>{name}</button> : <span className="cohort-var-name">{name}</span>}
    </div>
  )
}

function GroupRow({ label, count, open, onToggle, children }: { label: string; count: number; open: boolean; onToggle: () => void; children?: ReactNode }) {
  return (
    <section role="listitem" aria-label={label}>
      <button type="button" className="cohort-group" aria-expanded={open} onClick={onToggle}>
        <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />
        {label}
        <span className="count">{count}</span>
      </button>
      {open ? children : null}
    </section>
  )
}

/** Left-pane navigator: origin groups (Metadata by category), field search and pins */
export function CohortView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const vars = useVariables(pid)
  const group = useCohort((s) => s.group)
  const setGroup = useCohort((s) => s.setGroup)
  const pinned = useCohort((s) => s.pinned)
  const [q, setQ] = useState('')
  const all = vars.data ?? []
  const matches = q.trim() ? all.filter((v) => v.name.toLowerCase().includes(q.trim().toLowerCase())) : null
  // A search hit selects its group or category, so the field shows as a column
  const pick = (v: Variable) => {
    setGroup({ origin: v.origin, category: v.origin === 'metadata' ? v.category : null })
    setQ('')
  }
  if (vars.isError) return <ProblemCard error={vars.error} onRetry={() => void vars.refetch()} />
  return (
    <div className="cohort-nav">
      <div style={{ padding: '0 8px 6px' }}>
        <input className="input input-sm" style={{ width: '100%' }} value={q} placeholder={t('cohort.nav.search')} aria-label={t('cohort.nav.search')} onChange={(e) => setQ(e.target.value)} />
      </div>
      {vars.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
      <div className="cohort-list" role="list">
        {matches
          ? (
            <>
              {matches.map((v) => <VarRow key={v.name} v={v} pinned={pinned} onPick={() => pick(v)} />)}
              {matches.length === 0 ? <div className="empty">{t('cohort.nav.noMatch')}</div> : null}
            </>
          )
          : ORIGINS.map((origin) => {
            const inOrigin = all.filter((v) => v.origin === origin)
            if (!inOrigin.length) return null
            if (origin !== 'metadata') {
              const sel: GroupSelection = { origin, category: null }
              const open = selEquals(group, sel)
              return (
                <GroupRow key={origin} label={t(`cohort.nav.group.${origin}`)} count={inOrigin.length} open={open} onToggle={() => setGroup(open ? null : sel)}>
                  {inOrigin.map((v) => <VarRow key={v.name} v={v} pinned={pinned} />)}
                </GroupRow>
              )
            }
            return CATEGORIES.map((category) => {
              const inCat = inOrigin.filter((v) => v.category === category)
              if (!inCat.length) return null
              const sel: GroupSelection = { origin: 'metadata', category }
              const open = selEquals(group, sel)
              return (
                <GroupRow key={category} label={t(`cohort.nav.category.${category}`)} count={inCat.length} open={open} onToggle={() => setGroup(open ? null : sel)}>
                  {inCat.map((v) => <VarRow key={v.name} v={v} pinned={pinned} />)}
                </GroupRow>
              )
            })
          })}
      </div>
    </div>
  )
}
