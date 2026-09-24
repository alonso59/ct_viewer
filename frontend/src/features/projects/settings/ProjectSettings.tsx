// Project settings tab (UI-23, PRJ-18): General · Display · Labels · Data · Plugins. Every save
// sends `If-Match` with the ETag of the version the form was loaded from (PRJ-15); a 412 offers
// "Reload and reapply" (the same changes on the fresh version) or discarding them.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  api,
  MODALITIES,
  ProblemError,
  useApplyPack,
  usePacks,
  usePlugins,
  useProject,
  useLayers,
  useRoots,
  useSegmentations,
  useUpdateProject,
  useViewToken,
  type DisplaySettings,
  type LabelDef,
  type Project,
  type ProjectPatch,
} from '../../../api'
import { ProblemCard } from '../../../lib'
import { runCommand, toast, useWorkbench, type EditorProps } from '../../../shell'
import { useLayout } from '../../../state'
import { Icon, codicon } from '../../../theme'
import { useImportWizard } from '../../import'
import { RelinkDialog } from '../WorkspaceHome'
import { mergeLabels, parseLabelFile } from './labelFiles'
import './settings.css'

const TABS = ['general', 'display', 'labels', 'data', 'plugins'] as const
type Tab = (typeof TABS)[number]
const LAYOUTS = ['four-up', 'conventional', 'three-mpr', 'one-up-axial', 'one-up-sagittal', 'one-up-coronal', 'one-up-3d'] as const

export interface SettingsParams {
  tab?: Tab
}

/** Draft of some project fields, based on one project version (its ETag). `changes` holds only the
 *  fields that differ from that version, so "reapply" never reverts someone else's other edits. */
function useDraft<T extends object>(project: Project | undefined, pick: (p: Project) => T) {
  const [base, setBase] = useState<{ etag: string; value: T } | null>(null)
  const [draft, setDraft] = useState<T | null>(null)
  const pickRef = useRef(pick)
  useEffect(() => {
    if (project && (!base || (draft === null && base.etag !== project.etag))) {
      setBase({ etag: project.etag, value: pickRef.current(project) })
    }
  }, [project, base, draft])
  const value = draft ?? base?.value ?? null
  const changes = Object.fromEntries(
    Object.entries(draft ?? {}).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify((base?.value as Record<string, unknown> | undefined)?.[k])),
  ) as Partial<T>
  return {
    value,
    changes,
    etag: base?.etag ?? '',
    dirty: draft !== null && JSON.stringify(draft) !== JSON.stringify(base?.value),
    set: (v: T) => setDraft(v),
    reset: (p?: Project) => {
      setDraft(null)
      setBase(p ? { etag: p.etag, value: pickRef.current(p) } : null)
    },
  }
}

function SaveBar({ pid, dirty, patch, etag, onSaved, onDiscard }: { pid: string; dirty: boolean; patch: ProjectPatch; etag: string; onSaved: (p: Project) => void; onDiscard: () => void }) {
  const { t } = useTranslation()
  const update = useUpdateProject(pid)
  const project = useProject(pid)
  const conflict = update.error instanceof ProblemError && update.error.status === 412
  const save = async (withEtag: string) => {
    const p = await update.mutateAsync({ patch, etag: withEtag })
    toast({ message: t('psettings.saved'), tone: 'ok' })
    onSaved(p)
  }
  const reapply = async () => {
    const fresh = await project.refetch()
    if (fresh.data) await save(fresh.data.etag)
  }
  return (
    <div className="psettings-save">
      {conflict ? (
        <div className="error-card" role="alert">
          <strong>{t('psettings.conflict')}</strong>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void reapply().catch(() => undefined)}>{t('psettings.reapply')}</button>
            <button type="button" className="btn btn-sm" onClick={() => { update.reset(); void project.refetch().then(() => onDiscard()) }}>{t('psettings.discard')}</button>
          </div>
        </div>
      ) : update.error ? (
        <ProblemCard error={update.error} />
      ) : null}
      <button type="button" className="btn btn-primary" disabled={!dirty || update.isPending} onClick={() => void save(etag).catch(() => undefined)}>
        {t('common.save')}
      </button>
    </div>
  )
}

function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {help ? <span className="muted psettings-help">{help}</span> : null}
    </label>
  )
}

function copy(text: string, done: string) {
  const ok = () => toast({ message: done, tone: 'ok' })
  if (navigator.clipboard) void navigator.clipboard.writeText(text).then(ok, () => toast({ message: text }))
  else toast({ message: text })
}

function General({ pid, project }: { pid: string; project: Project }) {
  const { t } = useTranslation()
  const d = useDraft(project, (p) => ({ name: p.name, description: p.description ?? '', default_modality: p.default_modality }))
  const view = useViewToken(pid)
  if (!d.value) return null
  const v = d.value
  return (
    <div className="psettings-form">
      <Field label={t('projects.name')}>
        <input className="input" value={v.name} onChange={(e) => d.set({ ...v, name: e.target.value })} />
      </Field>
      <Field label={t('psettings.description')}>
        <textarea className="input" rows={3} value={v.description} onChange={(e) => d.set({ ...v, description: e.target.value })} />
      </Field>
      <div className="field">
        <span className="field-label">{t('projects.modality')}</span>
        <div className="seg" role="group" aria-label={t('projects.modality')}>
          {MODALITIES.map((m) => (
            <button key={m} type="button" aria-pressed={v.default_modality === m} onClick={() => d.set({ ...v, default_modality: m })}>{t(`projects.modalities.${m}`)}</button>
          ))}
        </div>
        <span className="muted psettings-help">{t('projects.modalityHelp')}</span>
      </div>
      <SaveBar pid={pid} dirty={d.dirty && !!v.name.trim()} patch={{ ...d.changes, ...(d.changes.name != null ? { name: v.name.trim() } : {}) }} etag={d.etag} onSaved={(p) => d.reset(p)} onDiscard={() => d.reset()} />
      <h3>{t('psettings.links')}</h3>
      <div className="field">
        <span className="field-label">{t('psettings.fullLink')}</span>
        <div className="psettings-row">
          <code className="mono psettings-url">{project.share_url}</code>
          <button type="button" className="btn btn-sm" onClick={() => copy(project.share_url, t('shell.shareLinkCopied'))}>{t('psettings.copy')}</button>
        </div>
        <span className="muted psettings-help">{t('psettings.fullLinkHelp')}</span>
      </div>
      <div className="field" data-testid="view-link">
        <span className="field-label">{t('psettings.viewLink')}</span>
        {project.view_url ? (
          <div className="psettings-row">
            <code className="mono psettings-url">{project.view_url}</code>
            <button type="button" className="btn btn-sm" onClick={() => copy(project.view_url ?? '', t('shell.shareLinkCopied'))}>{t('psettings.copy')}</button>
            <button type="button" className="btn btn-sm" onClick={() => view.create.mutate()}>{t('psettings.rotate')}</button>
            <button type="button" className="btn btn-sm" onClick={() => view.revoke.mutate()}>{t('psettings.revoke')}</button>
          </div>
        ) : (
          <div>
            <button type="button" className="btn btn-sm" onClick={() => view.create.mutate()}>{t('psettings.createViewLink')}</button>
          </div>
        )}
        <span className="muted psettings-help">{t('psettings.viewLinkHelp')}</span>
      </div>
    </div>
  )
}

function Display({ pid, project }: { pid: string; project: Project }) {
  const { t } = useTranslation()
  const d = useDraft<DisplaySettings>(project, (p) => p.display)
  if (!d.value) return null
  const v = d.value
  const ct = typeof v.wl?.CT === 'object' ? v.wl.CT : { ww: 400, wl: 50 }
  const presets = v.wl_presets ?? []
  const setCt = (k: 'ww' | 'wl', n: number) => d.set({ ...v, wl: { ...v.wl, CT: { ...ct, [k]: n } } })
  const setPresets = (list: typeof presets) => d.set({ ...v, wl_presets: list.length ? list : null })
  return (
    <div className="psettings-form">
      <Field label={t('psettings.layout')}>
        <select className="input" value={v.layout} onChange={(e) => d.set({ ...v, layout: e.target.value as DisplaySettings['layout'] })}>
          {LAYOUTS.map((l) => <option key={l} value={l}>{t(`viewer.layouts.${l}`)}</option>)}
        </select>
      </Field>
      <div className="field">
        <span className="field-label">{t('psettings.ctWindow')}</span>
        <div className="psettings-row">
          <label className="psettings-inline">{t('psettings.ww')}<input className="input input-sm num" type="number" min={1} value={ct.ww} onChange={(e) => setCt('ww', Number(e.target.value))} /></label>
          <label className="psettings-inline">{t('psettings.wl')}<input className="input input-sm num" type="number" value={ct.wl} onChange={(e) => setCt('wl', Number(e.target.value))} /></label>
        </div>
        <span className="muted psettings-help">{t('psettings.ctWindowHelp')}</span>
      </div>
      <label className="psettings-check">
        <input type="checkbox" checked={v.use_dicom_window ?? true} onChange={(e) => d.set({ ...v, use_dicom_window: e.target.checked })} />
        {t('psettings.dicomWindow')}
      </label>
      <div className="field">
        <span className="field-label">{t('psettings.interpolation')}</span>
        <div className="seg" role="group">
          {(['linear', 'nearest'] as const).map((k) => <button key={k} type="button" aria-pressed={v.interpolation === k} onClick={() => d.set({ ...v, interpolation: k })}>{t(`psettings.interp.${k}`)}</button>)}
        </div>
      </div>
      <div className="field">
        <span className="field-label">{t('psettings.convention')}</span>
        <div className="seg" role="group">
          {(['radiological', 'neurological'] as const).map((k) => <button key={k} type="button" aria-pressed={v.convention === k} onClick={() => d.set({ ...v, convention: k })}>{t(`psettings.conv.${k}`)}</button>)}
        </div>
        <span className="muted psettings-help">{t('psettings.conventionHelp')}</span>
      </div>
      <div className="field">
        <span className="field-label">{t('psettings.presets')}</span>
        {presets.map((p, i) => (
          <div key={i} className="psettings-row">
            <input className="input input-sm" aria-label={t('psettings.presetName')} value={p.name} onChange={(e) => setPresets(presets.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            <input className="input input-sm num" type="number" aria-label={t('psettings.ww')} value={p.ww} onChange={(e) => setPresets(presets.map((x, j) => (j === i ? { ...x, ww: Number(e.target.value) } : x)))} />
            <input className="input input-sm num" type="number" aria-label={t('psettings.wl')} value={p.wl} onChange={(e) => setPresets(presets.map((x, j) => (j === i ? { ...x, wl: Number(e.target.value) } : x)))} />
            <button type="button" className="icon-btn" aria-label={t('psettings.removePreset')} onClick={() => setPresets(presets.filter((_, j) => j !== i))}><Icon spec={codicon('close')} /></button>
          </div>
        ))}
        <div><button type="button" className="btn btn-sm" onClick={() => setPresets([...presets, { name: t('psettings.newPreset'), ww: 400, wl: 40 }])}>{t('psettings.addPreset')}</button></div>
        <span className="muted psettings-help">{t('psettings.presetsHelp')}</span>
      </div>
      <SaveBar pid={pid} dirty={d.dirty} patch={{ display: v }} etag={d.etag} onSaved={(p) => d.reset(p)} onDiscard={() => d.reset()} />
    </div>
  )
}

function Labels({ pid, project }: { pid: string; project: Project }) {
  const { t } = useTranslation()
  const d = useDraft(project, (p) => ({ label_map: p.label_map, default_seg: p.default_seg }))
  const sets = useSegmentations(pid).data ?? []
  const [importError, setImportError] = useState<string | null>(null)
  if (!d.value) return null
  const v = d.value
  const edit = (value: number, patch: Partial<LabelDef>) => d.set({ ...v, label_map: v.label_map.map((l) => (l.value === value ? { ...l, ...patch } : l)) })
  const onFile = async (file: File | undefined) => {
    if (!file) return
    setImportError(null)
    try {
      const { kind, labels } = parseLabelFile(file.name, await file.text())
      d.set({ ...v, label_map: mergeLabels(v.label_map, labels) })
      toast({ message: t('psettings.imported', { n: labels.length, kind: t(`psettings.kind.${kind}`) }), tone: 'ok' })
    } catch {
      setImportError(t('psettings.importFailed', { name: file.name }))
    }
  }
  const nextValue = Math.max(0, ...v.label_map.map((l) => l.value)) + 1
  return (
    <div className="psettings-form">
      <table className="psettings-table">
        <thead>
          <tr><th>{t('labels.value')}</th><th>{t('labels.name')}</th><th>{t('psettings.color')}</th><th>{t('psettings.opacity')}</th><th>{t('psettings.visible')}</th></tr>
        </thead>
        <tbody>
          {v.label_map.map((l) => (
            <tr key={l.value}>
              <td className="num">{l.value}</td>
              <td><input className="input input-sm" aria-label={t('labels.name')} value={l.name} onChange={(e) => edit(l.value, { name: e.target.value })} /></td>
              <td><input type="color" className="label-swatch" aria-label={t('labels.color', { name: l.name })} value={l.color} onChange={(e) => edit(l.value, { color: e.target.value.toUpperCase() })} /></td>
              <td><input className="input input-sm num" type="number" min={0} max={1} step={0.05} aria-label={t('psettings.opacity')} value={l.opacity} onChange={(e) => edit(l.value, { opacity: Number(e.target.value) })} /></td>
              <td><input type="checkbox" aria-label={t('labels.visible', { name: l.name })} checked={l.visible} onChange={(e) => edit(l.value, { visible: e.target.checked })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!v.label_map.length ? <p className="muted">{t('psettings.noLabels')}</p> : null}
      <div className="psettings-row">
        <button type="button" className="btn btn-sm" onClick={() => d.set({ ...v, label_map: [...v.label_map, { value: nextValue, name: `label_${nextValue}`, color: '#00FF00', opacity: 0.2, visible: true }] })}>{t('psettings.addLabel')}</button>
        <label className="btn btn-sm">
          {t('psettings.importLabels')}
          <input type="file" accept=".ctbl,.txt,.json,.label" hidden onChange={(e) => void onFile(e.target.files?.[0])} />
        </label>
      </div>
      <span className="muted psettings-help">{t('psettings.importHelp')}</span>
      {importError ? <div className="error-card">{importError}</div> : null}
      <Field label={t('psettings.defaultSeg')}>
        <select className="input" value={v.default_seg} onChange={(e) => d.set({ ...v, default_seg: e.target.value })}>
          {sets.map((s) => <option key={s.seg_id} value={s.seg_id}>{s.name || s.seg_id}</option>)}
        </select>
      </Field>
      <SaveBar pid={pid} dirty={d.dirty} patch={d.changes} etag={d.etag} onSaved={(p) => d.reset(p)} onDiscard={() => d.reset()} />
    </div>
  )
}

function Data({ pid, project }: { pid: string; project: Project }) {
  const { t } = useTranslation()
  const roots = useRoots(pid).data ?? []
  const layers = useLayers(pid).data ?? []
  const [relink, setRelink] = useState(false)
  return (
    <div className="psettings-form">
      <table className="psettings-table">
        <thead><tr><th>{t('psettings.alias')}</th><th>{t('psettings.role')}</th><th>{t('psettings.path')}</th><th /></tr></thead>
        <tbody>
          {roots.map((r) => (
            <tr key={r.alias}>
              <td className="mono">{r.alias}</td>
              <td>{t(`psettings.roles.${r.role ?? 'source'}`)}</td>
              <td className="mono psettings-url">{r.path}</td>
              <td>{r.exists ? <Icon spec={codicon('pass')} /> : <span className="badge" data-tone="warn">{t('psettings.missing')}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!roots.length ? <p className="muted">{t('psettings.noRoots')}</p> : null}
      <div className="psettings-row">
        <button type="button" className="btn btn-sm" onClick={() => useImportWizard.getState().open(pid)}>{t('import.title')}</button>
        <button type="button" className="btn btn-sm" onClick={() => runCommand('tasks.convertDicom')}>{t('cmd.convertDicom')}</button>
        {roots.length ? <button type="button" className="btn btn-sm" onClick={() => setRelink(true)}>{t('projects.relink')}</button> : null}
      </div>
      {relink ? <RelinkDialog pid={pid} name={project.name} onOpenChange={(o) => setRelink(o)} /> : null}
      <h3>{t('psettings.layers')}</h3>
      <p className="muted psettings-help">{t('psettings.layersHelp')}</p>
      {layers.length ? (
        <table className="psettings-table">
          <thead><tr><th>{t('psettings.layerField')}</th><th>{t('psettings.layerPlugin')}</th><th>{t('psettings.layerSource')}</th></tr></thead>
          <tbody>
            {layers.map((l) => (
              <tr key={l.column}><td className="mono">{l.field}</td><td>{l.plugin}</td><td className="muted">{l.source}</td></tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">{t('psettings.noLayers')}</p>}
      <div className="psettings-row">
        <a className="btn btn-sm" href={api.datasetTableUrl(pid, 'csv')} download>{t('psettings.exportCsv')}</a>
        <a className="btn btn-sm" href={api.datasetTableUrl(pid, 'parquet')} download>{t('psettings.exportParquet')}</a>
      </div>
    </div>
  )
}

function Plugins({ pid, project }: { pid: string; project: Project }) {
  const { t } = useTranslation()
  const packs = usePacks().data ?? []
  const apply = useApplyPack(pid)
  const plugins = usePlugins(pid).data?.plugins ?? []
  return (
    <div className="psettings-form">
      <h3>{t('psettings.packs')}</h3>
      <p className="muted psettings-help">{t('psettings.packsHelp')}</p>
      <ul className="psettings-list">
        {packs.map((p) => {
          const applied = project.packs.includes(p.pack_id)
          return (
            <li key={p.pack_id} data-pack={p.pack_id}>
              <div>
                <strong>{p.title}</strong>
                <div className="muted psettings-help">{t('psettings.packSummary', { labels: p.labels.join(', ') || '—', phases: p.phase_vocabulary.join(', ') || '—' })}</div>
              </div>
              <button
                type="button"
                className="btn btn-sm"
                disabled={apply.isPending}
                onClick={() => apply.mutate(p.pack_id, { onSuccess: () => toast({ message: t('psettings.packApplied', { name: p.title }), tone: 'ok' }) })}
              >
                {t(applied ? 'psettings.reapplyPack' : 'psettings.applyPack')}
              </button>
              {applied ? <span className="badge" data-tone="ok">{t('psettings.applied')}</span> : null}
            </li>
          )
        })}
      </ul>
      {apply.error ? <ProblemCard error={apply.error} /> : null}
      <h3>{t('psettings.installed')}</h3>
      <ul className="psettings-list">
        {plugins.map((p) => (
          <li key={p.manifest.id}>
            <Icon spec={codicon(p.manifest.icon)} />
            <span>{p.manifest.title}</span>
            <span className="muted num">{p.manifest.version}</span>
            <span className="badge">{t(`library.status.${p.status}`)}</span>
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-sm" onClick={() => useLayout.getState().set({ activeView: 'library', sidebarVisible: true })}>{t('psettings.openLibrary')}</button>
    </div>
  )
}

export default function ProjectSettings({ params }: EditorProps<SettingsParams>) {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const project = useProject(pid)
  const [tab, setTab] = useState<Tab>(params.tab ?? 'general')
  const p = project.data
  return (
    <div className="page psettings">
      <div className="page-inner">
        <h1>{t('psettings.title')}</h1>
        <div className="psettings-tabs" role="tablist">
          {TABS.map((k) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className="psettings-tab" onClick={() => setTab(k)}>{t(`psettings.tab.${k}`)}</button>
          ))}
        </div>
        {project.error ? <ProblemCard error={project.error} /> : null}
        {p ? (
          <div role="tabpanel">
            {tab === 'general' ? <General pid={pid} project={p} /> : null}
            {tab === 'display' ? <Display pid={pid} project={p} /> : null}
            {tab === 'labels' ? <Labels pid={pid} project={p} /> : null}
            {tab === 'data' ? <Data pid={pid} project={p} /> : null}
            {tab === 'plugins' ? <Plugins pid={pid} project={p} /> : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
