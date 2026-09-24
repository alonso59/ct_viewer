// Workspace home (`/`, UI-04): New Project (with a study preset, PRJ-12), Open Recent with
// thumbnail + progress (PRJ-02), share-link copy (PRJ-03), relink (PRJ-05), bundles (PRJ-08/09).
import { lazy, Suspense, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import {
  PRESETS,
  pickThumbItem,
  useCase,
  useCases,
  useCreateProject,
  useProjects,
  useRelink,
  useRoots,
  type Preset,
  type ProjectSummary,
  type RelinkResult,
} from '../../api'
import { Dialog, IconButton, Progress, SliceThumb, fmtAgo } from '../../lib'
import { toast } from '../../shell'
import { Icon, codicon, ct } from '../../theme'
import { useImportWizard, type WizardPrefill } from '../import'
import { useOpenDialog } from '../open'
import { exportBundle } from './actions'
import './projects.css'

// The import report dialog and its strings load once a bundle is picked (NFR-07)
const BundleImport = lazy(() => import('./BundleImport'))

/** `prefill`: "Create project from this" (Open mode) starts the import wizard on that path */
export function NewProjectDialog({ open, onOpenChange, prefill }: { open: boolean; onOpenChange: (o: boolean) => void; prefill?: WizardPrefill }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [preset, setPreset] = useState<Preset>('ccrcc')
  const create = useCreateProject()
  const navigate = useNavigate()
  const submit = async () => {
    const p = await create.mutateAsync({ name: name.trim(), preset })
    onOpenChange(false)
    setName('')
    navigate(`/p/${p.project_id}`)
    useImportWizard.getState().open(p.project_id, prefill)
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('projects.newTitle')}
      icon={codicon('new-folder')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={!name.trim() || create.isPending} onClick={() => void submit()}>
            {t('projects.createAndImport')}
          </button>
        </>
      }
    >
      <form style={{ display: 'flex', flexDirection: 'column', gap: 14 }} onSubmit={(e) => { e.preventDefault(); if (name.trim()) void submit() }}>
        <div className="field">
          <label className="field-label" htmlFor="project-name">{t('projects.name')}</label>
          <input id="project-name" className="input" autoFocus value={name} placeholder={t('projects.namePlaceholder')} onChange={(e) => setName(e.target.value)} />
          <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('projects.newHelp')}</span>
        </div>
        <fieldset className="field preset-list" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field-label">{t('projects.preset')}</legend>
          {PRESETS.map((p) => (
            <label key={p} className="preset" data-checked={preset === p}>
              <input type="radio" name="preset" value={p} checked={preset === p} onChange={() => setPreset(p)} />
              <span>
                <strong>{t(`preset.${p}.name`)}</strong>
                <span className="muted">{t(`preset.${p}.help`)}</span>
              </span>
            </label>
          ))}
          <span className="muted" style={{ fontSize: 'var(--fs-badge)' }}>{t('projects.presetEditable')}</span>
        </fieldset>
        {create.isError ? <div className="error-card" style={{ margin: 0 }}>{create.error.message}</div> : null}
      </form>
    </Dialog>
  )
}

/** Relink (PRJ-05, API-05): point an alias at a new root; the server verifies a sample of items */
export function RelinkDialog({ pid, name, onOpenChange }: { pid: string; name: string; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const roots = useRoots(pid)
  const relink = useRelink(pid)
  const [alias, setAlias] = useState<string | null>(null)
  const [path, setPath] = useState('')
  const [result, setResult] = useState<RelinkResult | null>(null)
  const root = roots.data?.find((r) => r.alias === alias) ?? roots.data?.find((r) => !r.exists) ?? roots.data?.[0]
  const ok = result !== null && result.root.exists && result.verify.mismatched === 0 && result.verify.missing === 0
  const verify = async () => {
    if (!root) return
    const r = await relink.mutateAsync({ alias: root.alias, path: path.trim() })
    setResult(r)
    if (r.root.exists && r.verify.mismatched === 0 && r.verify.missing === 0) {
      void roots.refetch()
      toast({ message: t('projects.relinked', { alias: root.alias }), tone: 'ok' })
    }
  }
  return (
    <Dialog
      open
      onOpenChange={onOpenChange}
      title={t('projects.relinkTitle', { name })}
      icon={codicon('link')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>{t(ok ? 'common.close' : 'common.cancel')}</button>
          {!ok ? (
            <button type="button" className="btn btn-primary" disabled={!path.trim() || !root || relink.isPending} onClick={() => void verify()}>
              {relink.isPending ? t('projects.verifying') : t('projects.verify')}
            </button>
          ) : null}
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('projects.relinkHelp')}</div>
        {roots.data && roots.data.length > 1 ? (
          <label className="field">
            <span className="field-label">{t('projects.alias')}</span>
            <select className="select" value={root?.alias ?? ''} onChange={(e) => { setAlias(e.target.value); setResult(null) }}>
              {roots.data.map((r) => (
                <option key={r.alias} value={r.alias}>{r.alias}</option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="props" style={{ padding: 0 }}>
          <span className="muted">{t('projects.alias')}</span>
          <span className="mono">{root?.alias ?? '—'}</span>
          <span className="muted">{t('projects.oldPath')}</span>
          <span className="mono">
            {root?.path ?? '—'}
            {root && !root.exists ? <span className="badge" data-tone="error" style={{ marginLeft: 6 }}>{t('projects.offline')}</span> : null}
          </span>
        </div>
        <label className="field">
          <span className="field-label">{t('projects.newPath')}</span>
          <input className="input mono" value={path} placeholder={root?.path ?? t('projects.newPathPlaceholder')} onChange={(e) => { setPath(e.target.value); setResult(null) }} />
        </label>
        {relink.isError ? <div className="error-card" style={{ margin: 0 }}>{relink.error.message}</div> : null}
        {result ? (
          <div className={ok ? 'card' : 'error-card'} style={{ margin: 0 }} role="status">
            {t(ok ? 'projects.verifyOk' : 'projects.verifyFailed', {
              sampled: result.verify.sampled,
              matched: result.verify.matched,
              mismatched: result.verify.mismatched,
              missing: result.verify.missing,
            })}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}

/** Axial thumbnail of the project's first case (Open Recent) */
function ProjectThumb({ p }: { p: ProjectSummary }) {
  const first = useCases(p.n_cases > 0 ? p.project_id : '', { limit: 1 }).data?.[0] ?? null
  const detail = useCase(p.project_id, first && !first.thumb_item_id ? first.case_id : null)
  const itemId = first?.thumb_item_id ?? (detail.data ? (pickThumbItem(detail.data.items)?.item_id ?? null) : null)
  return <SliceThumb pid={p.project_id} itemId={itemId} size={56} />
}

function ProjectCard({ p, onRelink }: { p: ProjectSummary; onRelink: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const empty = p.n_cases === 0
  const reviewed = Math.round(p.curation_progress * p.n_cases)
  return (
    <div className="home-project" role="listitem">
      <button type="button" className="home-project-main" onClick={() => navigate(`/p/${p.project_id}`)}>
        <ProjectThumb p={p} />
        <span className="home-project-text">
          <span className="home-project-name">
            {p.name}
            {empty ? <span className="badge">{t('projects.empty')}</span> : null}
          </span>
          <span className="muted">
            {p.last_opened_at
              ? t('projects.meta', { cases: p.n_cases, ago: fmtAgo(p.last_opened_at) })
              : t('projects.metaNew', { cases: p.n_cases, ago: fmtAgo(p.created_at) })}
          </span>
          <span className="home-progress">
            <Progress value={reviewed} total={p.n_cases} />
            <span className="muted num">{t('projects.reviewed', { done: reviewed, total: p.n_cases })}</span>
          </span>
        </span>
      </button>
      <IconButton icon={codicon('plug')} label={t('projects.relink')} onClick={onRelink} />
      <IconButton icon={codicon('package')} label={t('projects.bundle.export')} onClick={() => void exportBundle(p.project_id)} />
      <IconButton
        icon={codicon('link')}
        label={t('shell.copyShareLink')}
        onClick={() => {
          const url = p.share_url
          const done = () => toast({ message: t('shell.shareLinkCopied', { url }), tone: 'ok' })
          const manual = () => toast({ message: t('shell.shareLinkManual', { url }), tone: 'info' })
          if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, manual)
          else manual()
        }}
      />
    </div>
  )
}

export function WorkspaceHome() {
  const { t } = useTranslation()
  const projects = useProjects()
  const [creating, setCreating] = useState(false)
  const [relink, setRelink] = useState<ProjectSummary | null>(null)
  const [bundle, setBundle] = useState<File | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const sorted = [...(projects.data ?? [])]
    .filter((p) => !p.archived)
    .sort((a, b) => (b.last_opened_at ?? b.created_at).localeCompare(a.last_opened_at ?? a.created_at))
  return (
    <div className="home">
      <div className="home-inner">
        <header className="home-hero">
          <span className="home-logo"><Icon spec={ct('layout-four-up')} size={40} /></span>
          <div>
            <h1>{t('app.title')}</h1>
            <p className="muted">{t('home.subtitle')}</p>
          </div>
        </header>
        <div className="home-cols">
          <section>
            <h2>{t('home.start')}</h2>
            <div className="home-actions">
              <button type="button" className="home-action" onClick={() => setCreating(true)}>
                <Icon spec={codicon('new-folder')} size={20} />
                <span>
                  <strong>{t('home.newProject')}</strong>
                  <span className="muted">{t('home.newProjectHelp')}</span>
                </span>
              </button>
              <button type="button" className="home-action" onClick={() => useOpenDialog.getState().show()}>
                <Icon spec={codicon('folder-opened')} size={20} />
                <span>
                  <strong>{t('home.openPath')}</strong>
                  <span className="muted">{t('home.openPathHelp')}</span>
                </span>
              </button>
              <button type="button" className="home-action" onClick={() => picker.current?.click()}>
                <Icon spec={codicon('package')} size={20} />
                <span>
                  <strong>{t('home.importBundle')}</strong>
                  <span className="muted">{t('home.importBundleHelp')}</span>
                </span>
              </button>
              <input
                ref={picker}
                type="file"
                accept=".zip,application/zip"
                hidden
                aria-label={t('home.importBundle')}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) setBundle(f)
                }}
              />
            </div>
            <h2>{t('home.tips')}</h2>
            <ul className="home-tips muted">
              <li>{t('home.tip1')}</li>
              <li>{t('home.tip2')}</li>
              <li>{t('home.tip3')}</li>
            </ul>
          </section>
          <section>
            <h2>{t('home.recent')}</h2>
            {projects.isLoading ? <div className="empty">{t('common.loading')}</div> : null}
            {projects.isError ? (
              <div className="error-card" role="alert">
                <strong>{t('home.serverDown')}</strong>
                <div className="muted">{projects.error.message}</div>
              </div>
            ) : null}
            {projects.data && sorted.length === 0 ? <div className="empty">{t('home.noProjects')}</div> : null}
            <div role="list" className="home-list">
              {sorted.map((p) => (
                <ProjectCard key={p.project_id} p={p} onRelink={() => setRelink(p)} />
              ))}
            </div>
          </section>
        </div>
        <footer className="home-footer muted">{t('app.tagline')}</footer>
      </div>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
      {bundle ? (
        <Suspense fallback={null}>
          <BundleImport file={bundle} onClose={() => setBundle(null)} />
        </Suspense>
      ) : null}
      {relink ? <RelinkDialog pid={relink.project_id} name={relink.name} onOpenChange={(o) => !o && setRelink(null)} /> : null}
    </div>
  )
}
