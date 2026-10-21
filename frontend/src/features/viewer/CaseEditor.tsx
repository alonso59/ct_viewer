// Case editor tab: header (case, scan drop-down, scope, phase, review status) + the NiiVue viewer (VIEWER.md; VW-11, 12, 14).
import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ProblemError, useCase, useProject, useSegmentations, viewPath, type ItemRecord, type LabelDef } from '../../api'
import { CaseRollupBadge, ProblemCard } from '../../lib'
import { bindingOf, formatChord, pinEditor, registry, runCommand, updateActiveParams, useWorkbench, type EditorProps } from '../../shell'
import { PhaseButtons, PhaseHistoryButton } from '../phase'
import { navPosition, resolveSeg, useNavContext, useViewerSync } from '../../state'
import { Icon, codicon } from '../../theme'
import { useLoadBudget } from './budget'
import { ItemSwitcher } from './ItemSwitcher'
import { ViewerSurface, viewerFocusProps } from './ViewerSurface'
import './viewer.css'

export interface CaseParams {
  caseId: string
  itemId: string | null
  preview?: boolean
}

/** API-23/24/25 (volumes are streamed as the original bytes, BE-04) */
const API = '/api/v1'
export const itemUrl = (pid: string, iid: string, what: 'image' | 'mask') => viewPath(`${API}/projects/${encodeURIComponent(pid)}/items/${encodeURIComponent(iid)}/${what}`)
export const meshUrlOf = (pid: string, iid: string, seg?: string) => (label: number) =>
  viewPath(`${API}/projects/${encodeURIComponent(pid)}/items/${encodeURIComponent(iid)}/mesh/${label}?smooth=1${seg ? `&seg=${encodeURIComponent(seg)}` : ''}`)

/** VW-19: overlay labels for a set: its values coloured by the project labels they map to */
export function setLabels(labels: LabelDef[], mapping: Record<string, number> | undefined): LabelDef[] {
  const entries = Object.entries(mapping ?? {})
  if (!entries.length || entries.every(([k, v]) => Number(k) === v)) return labels
  return entries.flatMap(([k, v]) => {
    const l = labels.find((x) => x.value === v)
    return l ? [{ ...l, value: Number(k) }] : []
  })
}

/** Warning codes that mean the image cannot be opened at all (IMP-08) */
export const FATAL_CODES = ['missing_path', 'unreadable_file', 'outside_root']

export function defaultItem(items: ItemRecord[]): ItemRecord | undefined {
  const complete = items.filter((i) => i.scope === 'complete' && i.status !== 'excluded_upstream')
  return complete.find((i) => i.phase.canonical === 'NP' && i.status === 'active') ?? complete.find((i) => i.status === 'active') ?? items[0]
}

/** AUD-A1-04: "Outliers 3/22 ›" while the case came from a list; × falls back to Explorer order */
function NavContextChip({ caseId, itemId }: { caseId: string; itemId: string | null }) {
  const { t } = useTranslation()
  const nav = useNavContext()
  const pos = navPosition(nav, caseId, itemId)
  if (pos === null || !nav.label) return null
  const next = registry.commands.get('explorer.nextCase')
  return (
    <span className="badge nav-context" data-tone="accent" role="group" aria-label={t('nav.context', { list: nav.label })}>
      <span>{t('nav.position', { list: nav.label, n: pos + 1, total: nav.entries.length })}</span>
      <button type="button" className="icon-btn" disabled={pos + 1 >= nav.entries.length} aria-label={t('nav.next', { list: nav.label })} title={`${t('nav.next', { list: nav.label })} ${next ? formatChord(bindingOf(next)) : ''}`} onClick={() => runCommand('explorer.nextCase')}>
        <Icon spec={codicon('chevron-right')} />
      </button>
      <button type="button" className="icon-btn" aria-label={t('nav.clear')} title={t('nav.clear')} onClick={() => nav.clear()}>
        <Icon spec={codicon('close')} />
      </button>
    </span>
  )
}

export function CaseEditor({ params, panelId, active }: EditorProps<CaseParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading, isError, error } = useCase(pid, params.caseId)
  const project = useProject(pid)
  const set = useViewerSync((s) => s.set)
  const loaded = useLoadBudget(panelId, active)

  const items = useMemo(() => data?.items ?? [], [data])
  const current = items.find((i) => i.item_id === params.itemId) ?? defaultItem(items)
  const iid = current?.item_id ?? ''
  // VW-19: the set chosen for this project (Layers section), else its default; an item without
  // a mask in that set shows the default set's mask with a notice (AUD-A5-05)
  const chosen = useViewerSync((s) => s.segChoice[pid])
  const defaultSeg = project.data?.default_seg ?? 'imported'
  const masks = current?.masks
  const { seg: shownSeg, missing } = useMemo(() => resolveSeg(masks ?? {}, chosen, defaultSeg), [masks, chosen, defaultSeg])
  const segId = shownSeg ?? chosen ?? defaultSeg
  const sets = useSegmentations(pid).data
  const mapping = sets?.find((s) => s.seg_id === segId)?.label_mapping
  const meshUrl = useMemo(() => meshUrlOf(pid, iid, segId), [pid, iid, segId])
  const labels = useMemo(() => setLabels(project.data?.label_map ?? [], mapping), [project.data, mapping])
  const shown = useMemo(() => (current ? { ...current, mask: current.masks[segId] ?? null } : null), [current, segId])

  useEffect(() => {
    if (active && current) set({ activeCaseId: params.caseId, activeItemId: current.item_id, shownSeg })
    // While the new case loads, no item is active: a curation key then does nothing instead of
    // landing on the previous case (AUD-A2-02); the Explorer already reveals the case (AUD-A1-03)
    else if (active && useViewerSync.getState().activeCaseId !== params.caseId) set({ activeCaseId: params.caseId, activeItemId: null, shownSeg: null })
  }, [active, current, params.caseId, set, shownSeg])

  // AUD-A2-02: after Alt+↓ the focus may be left on nothing (the old tab's viewer is gone); keep
  // it in the case editor so Tab / screen readers continue here. A focused Explorer tree keeps it.
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = document.activeElement
    if (active && (!el || el === document.body)) root.current?.focus({ preventScroll: true })
  }, [active, params.caseId, params.itemId, isLoading])

  const pick = (itemId: string) => {
    updateActiveParams(panelId, { itemId })
    pinEditor(panelId)
  }

  if (isLoading) return <div className="empty">{t('common.loading')}</div>
  if (isError || !data || !current) {
    // UI-18 (AUD-A3-03): the cause and how to go on, not a bare "Not found"
    const p = error instanceof ProblemError ? error : null
    const notFound = !p || p.status === 404
    const title = notFound ? t('viewer.caseNotFound') : t(`problemTitle.${p.type}`, { defaultValue: p.title })
    const problem = new ProblemError(p?.status ?? 404, p?.type ?? 'not-found', title, notFound ? t('viewer.caseNotFoundHelp', { id: params.caseId }) : p.detail, ['quick_open', 'close_tab'])
    const quick = registry.commands.get('workbench.quickOpen')
    return (
      <div className="case-editor-error">
        <ProblemCard
          error={problem}
          labels={{ quick_open: `${t('problemAction.quick_open')}${quick ? ` (${formatChord(bindingOf(quick))})` : ''}` }}
          onAction={{ quick_open: () => runCommand('workbench.quickOpen'), close_tab: () => runCommand('workbench.closeTab') }}
        />
      </div>
    )
  }

  const fatal = current.warning_codes.find((c) => FATAL_CODES.includes(c))
  const setName = (id: string) => sets?.find((x) => x.seg_id === id)?.name || id

  return (
    <div className="case-editor" ref={root} {...viewerFocusProps}>
      <div className="case-header">
        <span className="mono case-id">{params.caseId}</span>
        <NavContextChip caseId={params.caseId} itemId={current.item_id} />
        <ItemSwitcher items={items.filter((i) => i.status !== 'excluded_upstream')} current={current} onPick={pick} />
        {/* PHS-01: set this scan's phase (the switcher's chips only move between scans) */}
        <span className="switcher">
          <span className="switcher-sep" />
          <span className="switcher-label">{t('viewer.phase')}</span>
          <PhaseButtons pid={pid} scan={current} variant="seg" />
          <PhaseHistoryButton pid={pid} caseId={current.case_id} scanIdx={current.scan_idx} />
        </span>
        <span className="case-header-end" />
        {current.warning_codes.length ? (
          <span className="badge" data-tone="warn" title={current.warning_codes.join(', ')}>
            <Icon spec={codicon('warning')} />
            {current.warning_codes.length}
          </span>
        ) : null}
        {missing ? (
          <span className="badge" data-tone="warn" role="note">
            {shownSeg ? t('viewer.segMissing', { set: setName(missing), shown: setName(shownSeg) }) : t('viewer.segMissingNone', { set: setName(missing) })}
          </span>
        ) : null}
        <CaseRollupBadge summary={data.summary} />
      </div>
      {fatal || current.status === 'missing' ? (
        // UI-18 (AUD-A2-07): what failed, where, and the next steps (relink the root, Problems)
        <div className="case-editor-error">
          <ProblemCard
            error={new ProblemError(409, fatal ?? 'missing_path', t(`warning.${fatal ?? 'missing_path'}`), t('viewer.fileError', { ref: current.image?.ref ?? '—' }), ['relink_root', 'show_problems'])}
            onAction={{ relink_root: () => runCommand('project.relink'), show_problems: () => runCommand('panel.show.problems') }}
          />
        </div>
      ) : (
        <ViewerSurface
          item={shown ?? current}
          imageUrl={itemUrl(pid, current.item_id, 'image')}
          maskUrl={shownSeg ? `${itemUrl(pid, current.item_id, 'mask')}?seg=${encodeURIComponent(shownSeg)}` : undefined}
          labels={labels}
          meshUrl={meshUrl}
          active={active}
          loaded={loaded}
          tags={current.extra.dicom_sidecar ? () => api.dicomTags(pid, current.item_id) : undefined}
        />
      )}
    </div>
  )
}
