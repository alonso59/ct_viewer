// The review step of `voi.extract`, under the task tab's preflight. It stays usable from one scan
// to thousands: pages of 50 scans, VOIs found only for the page on screen (or for everything on
// request, in the background), counts and the "needs review" filter over what has been found so
// far, and the reviewer's decisions kept in the settings (`overrides`).
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, useProject, useSegmentations, useVoiRegions, voiCandidatesQuery, type VoiCandidates } from '../../api'
import { Button, Progress, RadioSeg } from '../../lib'
import type { TaskReviewProps } from '../../shell'
import { activeLabels, chosenLabels, detectionKey, dropOverrides, flagsOf, flaggedScan, orphanOverrides, requestOf, reviewCounts, type CandFlags } from './model'
import { ScanCard } from './ScanCard'
import './voi.css'

const PAGE = 50
const WORKERS = 4
type View = 'all' | 'needs'

export default function VoiReview({ pid, values, onChange, segId, itemIds }: TaskReviewProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const project = useProject(pid).data
  const sets = useSegmentations(pid).data ?? []
  const regions = useVoiRegions().data ?? []
  const region = regions.find((r) => r.id === values.region) ?? regions.find((r) => r.id === 'kidney')
  const set = sets.find((s) => s.seg_id === segId)
  const labels = chosenLabels(values, region, activeLabels(project?.label_map ?? [], set).map((l) => l.name))
  const ids = itemIds ?? []
  const key = detectionKey(values, segId, labels)
  const req = requestOf(values, segId, labels)
  // what was found per scan, under the detection settings it was found with: margin and size
  // changes keep the counts
  const [found] = useState(() => new Map<string, CandFlags[]>())
  const [failed] = useState(() => new Set<string>())
  const record = (id: string, data: VoiCandidates) => void found.set(`${key}\n${id}`, flagsOf(data))
  const flagsFor = (id: string) => found.get(`${key}\n${id}`)
  // the detection key the reviewer asked for; one scan needs no request
  const [prepared, setPrepared] = useState<string | null>(null)
  const [prep, setPrep] = useState({ running: false, done: 0 })
  const [view, setView] = useState<View>('all')
  const [offset, setOffset] = useState(0)
  const [expandAll, setExpandAll] = useState(false)
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const cards = useRef(new Map<string, HTMLElement>())
  const cursor = useRef(-1)
  const token = useRef(0)
  const currentKey = useRef(key)
  useEffect(() => {
    currentKey.current = key
  }, [key])
  const active = labels.length > 0 && (ids.length <= 1 || prepared === key)

  const flaggedIds = ids.filter((id) => flaggedScan(flagsFor(id)))
  const list = view === 'needs' ? flaggedIds : ids
  const start = Math.min(offset, Math.max(0, Math.floor((list.length - 1) / PAGE) * PAGE))
  const pageIds = list.slice(start, start + PAGE)
  const queries = useQueries({
    queries: pageIds.map((id) => {
      const o = voiCandidatesQuery(pid, id, req)
      return {
        ...o,
        enabled: o.enabled && active,
        queryFn: async () => {
          const data = await api.voiCandidates(pid, id, req)
          record(id, data)
          return data
        },
      }
    }),
  })
  const items = pageIds.map((itemId, i) => ({ itemId, data: queries[i]?.data, error: queries[i]?.error ?? null, fetching: !!queries[i]?.isFetching }))
  const counts = reviewCounts(
    values,
    ids.map((itemId) => ({ itemId, cands: flagsFor(itemId), failed: failed.has(itemId) || queries.some((q, i) => pageIds[i] === itemId && !!q.error) })),
  )
  const loading = active && queries.some((q) => q.isPending)
  const candIds = new Map(ids.flatMap((id) => (flagsFor(id) ? [[id, flagsFor(id)!.map((c) => c.id)] as const] : [])))
  const orphans = itemIds && prepared !== null ? orphanOverrides(values, new Set(ids), candIds) : []

  const prepareAll = async () => {
    const mine = ++token.current
    const todo = ids.filter((id) => !flagsFor(id))
    let next = 0
    let done = 0
    setPrep({ running: true, done })
    const worker = async () => {
      while (next < todo.length && token.current === mine && currentKey.current === key) {
        const id = todo[next++]!
        try {
          const o = voiCandidatesQuery(pid, id, req)
          record(id, await qc.fetchQuery({ queryKey: o.queryKey, queryFn: o.queryFn, staleTime: o.staleTime }))
        } catch {
          failed.add(id)
        }
        done++
        if (done % 10 === 0) setPrep({ running: true, done })
      }
    }
    await Promise.all(Array.from({ length: WORKERS }, worker))
    if (token.current === mine) setPrep({ running: false, done })
  }
  const cancelPrep = () => {
    token.current++
    setPrep((p) => ({ ...p, running: false }))
  }
  const nextFlagged = () => {
    const here = items.filter((it) => flaggedScan(flagsFor(it.itemId)))
    if (!here.length) return
    cursor.current = (cursor.current + 1) % here.length
    const el = cards.current.get(here[cursor.current]!.itemId)
    el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    el?.focus({ preventScroll: true })
  }

  if (!itemIds) return null
  if (!labels.length) return <p className="muted">{t('voi.noLabels')}</p>
  if (!ids.length) return null
  const paged = ids.length > PAGE
  const to = Math.min(start + PAGE, list.length)
  return (
    <div className="voi-review">
      {!active ? (
        <div className="task-run-actions voi-prepare">
          <Button className="btn btn-primary" onClick={() => setPrepared(key)}>
            {t(paged ? 'voi.prepareFirst' : 'voi.prepare', { count: paged ? PAGE : ids.length, total: ids.length })}
          </Button>
          <span className="muted">{t(prepared ? 'voi.prepareAgain' : paged ? 'voi.prepareHelpPaged' : 'voi.prepareHelp')}</span>
        </div>
      ) : (
        <>
          {paged ? (
            <div className="voi-progress">
              {prep.running ? (
                <>
                  <Progress value={counts.prepared} total={ids.length} label={t('voi.preparing')} />
                  <Button className="btn btn-sm" onClick={cancelPrep}>
                    {t('common.cancel')}
                  </Button>
                </>
              ) : (
                <>
                  <span className="muted">{t('voi.checked', { done: counts.prepared, total: ids.length })}</span>
                  {counts.prepared < ids.length ? (
                    <Button className="btn btn-sm" onClick={() => void prepareAll()}>
                      {t('voi.prepareAll', { count: ids.length - counts.prepared })}
                    </Button>
                  ) : null}
                </>
              )}
            </div>
          ) : loading ? (
            <Progress value={counts.prepared} total={ids.length} label={t('voi.preparing')} />
          ) : null}
          <p className="voi-summary">
            <span>
              {t('voi.sum.vois', { count: counts.vois })} {t('voi.sum.scans', { count: counts.prepared })}
            </span>
            <span>{t('voi.sum.included', { count: counts.included })}</span>
            {counts.excluded ? <span>{t('voi.sum.excluded', { count: counts.excluded })}</span> : null}
            {counts.uncertain ? <span className="voi-warn">{t('voi.sum.uncertain', { count: counts.uncertain })}</span> : null}
            {counts.warnings ? <span className="voi-warn">{t('voi.sum.warnings', { count: counts.warnings })}</span> : null}
            {counts.failed ? <span className="field-error">{t('voi.sum.failed', { count: counts.failed })}</span> : null}
          </p>
          {paged && counts.prepared < ids.length ? <p className="muted">{t('voi.unchecked', { count: ids.length - counts.prepared })}</p> : null}
          {orphans.length ? (
            <div className="voi-notice" role="status">
              <span>{t('voi.orphans', { count: orphans.length })}</span>
              <Button className="btn btn-sm" onClick={() => onChange(dropOverrides(values, orphans))}>
                {t('voi.dropOrphans')}
              </Button>
            </div>
          ) : null}
          <div className="voi-toolbar">
            <RadioSeg
              label={t('voi.view')}
              value={view}
              onChange={(v: View) => {
                setView(v)
                setOffset(0)
              }}
              options={[
                { value: 'all', label: t('voi.views.all', { count: ids.length }) },
                { value: 'needs', label: t('voi.views.needs', { count: flaggedIds.length }) },
              ]}
            />
            <Button className="btn btn-sm" disabled={!items.some((it) => flaggedScan(flagsFor(it.itemId)))} onClick={nextFlagged}>
              {t('voi.nextReview')}
            </Button>
            <Button className="btn btn-sm" aria-pressed={expandAll} onClick={() => setExpandAll((e) => !e)}>
              {t(expandAll ? 'voi.collapseAll' : 'voi.expandAll')}
            </Button>
            <span className="muted voi-hint">{t('voi.hint')}</span>
          </div>
          {view === 'needs' && !flaggedIds.length ? <p className="muted">{t('voi.noneToReview')}</p> : null}
          {view === 'needs' && ids.length > flaggedIds.length ? <p className="muted">{t('voi.hiddenOk', { count: counts.prepared - flaggedIds.length })}</p> : null}
          <div className="voi-grid">
            {items.map((it) => (
              <ScanCard
                key={it.itemId}
                pid={pid}
                itemId={it.itemId}
                data={it.data}
                error={it.error}
                fetching={it.fetching}
                values={values}
                onChange={onChange}
                labels={labels}
                expanded={toggled[it.itemId] ?? expandAll}
                onToggle={() => setToggled((s) => ({ ...s, [it.itemId]: !(s[it.itemId] ?? expandAll) }))}
                cardRef={(el) => {
                  if (el) cards.current.set(it.itemId, el)
                  else cards.current.delete(it.itemId)
                }}
              />
            ))}
          </div>
          {list.length > PAGE ? (
            <div className="voi-pager">
              <span className="muted">{t('voi.res.range', { from: (start + 1).toLocaleString(), to: to.toLocaleString(), total: list.length.toLocaleString() })}</span>
              <Button className="btn btn-sm" disabled={start === 0} onClick={() => setOffset(Math.max(0, start - PAGE))}>
                {t('voi.prev')}
              </Button>
              <Button className="btn btn-sm" disabled={to >= list.length} onClick={() => setOffset(start + PAGE)}>
                {t('voi.next')}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
