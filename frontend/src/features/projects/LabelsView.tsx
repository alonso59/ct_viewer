// Labels view (QuPath Classes list): project label map, editable (PRJ-07); hotkeys 1–9 toggle visibility.
// Edits are a local draft per row, saved on blur / Enter (a colour when the picker closes), one PATCH at
// a time with the ETag of the version on screen; a 412 offers reload + reapply (PRJ-15, AUD-A5-07).
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, keys, ProblemError, useProject, type LabelDef, type Project } from '../../api'
import { ProblemCard } from '../../lib'
import { useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'

type Patch = Partial<Pick<LabelDef, 'name' | 'color'>>

/** The project's labels with the pending row changes applied */
export function applyLabelDrafts(labels: LabelDef[], drafts: Record<number, Patch>): LabelDef[] {
  return labels.map((l) => (drafts[l.value] ? { ...l, ...drafts[l.value] } : l))
}

function LabelRow({ l, index, draft, onDraft, onCommit }: { l: LabelDef; index: number; draft: Patch | undefined; onDraft: (p: Patch) => void; onCommit: () => void }) {
  const { t } = useTranslation()
  const vis = useViewerSync((s) => s.labelVisibility[l.value])
  const toggle = useViewerSync((s) => s.toggleLabel)
  const color = useRef<HTMLInputElement>(null)
  const commit = useRef(onCommit)
  useEffect(() => {
    commit.current = onCommit
  })
  // React's onChange is the native `input` event (every drag step); save on the native `change` (picker closed)
  useEffect(() => {
    const el = color.current
    const done = () => commit.current()
    el?.addEventListener('change', done)
    return () => el?.removeEventListener('change', done)
  }, [])
  return (
    <div className="label-row">
      <input type="checkbox" aria-label={t('labels.visible', { name: l.name })} checked={vis ?? l.visible} onChange={() => toggle(l.value, l.visible)} />
      <input ref={color} type="color" className="label-swatch" aria-label={t('labels.color', { name: l.name })} value={draft?.color ?? l.color} onChange={(e) => onDraft({ color: e.target.value.toUpperCase() })} />
      <input
        className="input input-sm"
        aria-label={t('labels.name')}
        value={draft?.name ?? l.name}
        onChange={(e) => onDraft({ name: e.target.value })}
        onBlur={onCommit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onCommit()
          if (e.key === 'Escape') onDraft({ name: l.name })
        }}
      />
      <span className="muted num" title={t('labels.value')}>{l.value}</span>
      <kbd className="key" title={t('labels.hotkey')}>{index + 1}</kbd>
    </div>
  )
}

export function LabelsView() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const queryClient = useQueryClient()
  const project = useProject(pid)
  const labels = project.data?.label_map ?? []
  const [drafts, setDraftsState] = useState<Record<number, Patch>>({})
  const [error, setError] = useState<unknown>(null)
  const chain = useRef<Promise<unknown>>(Promise.resolve())
  // Read by queued saves and native listeners, so it is updated with the state, not after render
  const draftsRef = useRef(drafts)
  const setDrafts = (next: Record<number, Patch>) => {
    draftsRef.current = next
    setDraftsState(next)
  }

  /** PATCH the pending drafts onto the version on screen; queued, so no write races its own reply */
  const save = (base?: Project) => {
    chain.current = chain.current.then(async () => {
      const shown = base ?? queryClient.getQueryData<Project>(keys.project(pid))
      const pending = draftsRef.current
      if (!shown || !Object.keys(pending).length) return
      const next = applyLabelDrafts(shown.label_map, pending)
      if (JSON.stringify(next) === JSON.stringify(shown.label_map)) return setDrafts({})
      try {
        const saved = await api.updateLabelMap(pid, next, shown.etag)
        queryClient.setQueryData(keys.project(pid), saved)
        setError(null)
        // keep edits typed while this save was in flight
        setDrafts(Object.fromEntries(Object.entries(draftsRef.current).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(pending[Number(k)]))))
      } catch (e) {
        setError(e)
      }
    })
  }
  const conflict = error instanceof ProblemError && error.status === 412
  const reapply = async () => {
    const fresh = await project.refetch()
    if (fresh.data) save(fresh.data)
  }
  const discard = () => {
    setDrafts({})
    setError(null)
    void project.refetch()
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '0 8px 12px' }}>
      <div className="muted" style={{ fontSize: 'var(--fs-badge)', padding: '0 4px 6px' }}>{t('labels.help')}</div>
      {conflict ? (
        <div className="error-card" role="alert">
          <strong>{t('labels.conflict')}</strong>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void reapply()}>{t('labels.reapply')}</button>
            <button type="button" className="btn btn-sm" onClick={discard}>{t('labels.discard')}</button>
          </div>
        </div>
      ) : error ? (
        <ProblemCard error={error} />
      ) : null}
      {labels.map((l, i) => (
        <LabelRow key={l.value} l={l} index={i} draft={drafts[l.value]} onDraft={(p) => setDrafts({ ...draftsRef.current, [l.value]: { ...draftsRef.current[l.value], ...p } })} onCommit={() => save()} />
      ))}
      <div className="muted" style={{ fontSize: 'var(--fs-badge)', padding: '8px 4px 0' }}>{t('labels.defaultsNote')}</div>
    </div>
  )
}
