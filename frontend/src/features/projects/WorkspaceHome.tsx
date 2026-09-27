// Workspace home (`/`, UI-04): New Project (name + optional default modality, PRJ-14), Open Recent with
// thumbnail + progress (PRJ-02), share-link copy (PRJ-03), relink (PRJ-05), bundles (PRJ-08/09).
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import {
  MODALITIES,
  pickThumbItem,
  useCase,
  useCases,
  useArchiveProject,
  useCreateProject,
  useProjects,
  useRelink,
  useRoots,
  useWorkspaceRuns,
  type ProjectModality,
  type ProjectSummary,
  type RelinkResult,
} from '../../api'
import { Dialog, IconButton, Progress, SliceThumb, fmtAgo } from '../../lib'
import { runCommand, toast } from '../../shell'
import { BrandMark, Icon, codicon } from '../../theme'
import { useImportWizard, type WizardPrefill } from '../import'
import { openPath, useOpenDialog } from '../open'
import { useConverter } from '../../plugins/dicom/store'
import { exportBundle, problemText } from './actions'
import { useProjectDialogs } from './store'
import './projects.css'

// The import report dialog and its strings load once a bundle is picked (NFR-07)
const BundleImport = lazy(() => import('./BundleImport'))

/** `prefill`: "Create project from this" (Open mode) starts the import wizard on that path */
export function NewProjectDialog({ open, onOpenChange, prefill }: { open: boolean; onOpenChange: (o: boolean) => void; prefill?: WizardPrefill }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [modality, setModality] = useState<ProjectModality>('CT')
  const create = useCreateProject()
  const navigate = useNavigate()
  const submit = async () => {
    const p = await create.mutateAsync({ name: name.trim(), default_modality: modality })
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
          <span className="muted panel-size">{t('projects.newHelp')}</span>
        </div>
        <div className="field">
          <span className="field-label">{t('projects.modality')}</span>
          <div className="seg" role="group" aria-label={t('projects.modality')}>
            {MODALITIES.map((m) => (
              <button key={m} type="button" aria-pressed={modality === m} onClick={() => setModality(m)}>{t(`projects.modalities.${m}`)}</button>
            ))}
          </div>
          <span className="muted small">{t('projects.modalityHelp')}</span>
        </div>
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
        <div className="muted panel-size">{t('projects.relinkHelp')}</div>
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
          {/* AUD-A1-08 / A2-08: one definition of a case; excluded cases are not counted */}
          <span className="muted" title={p.n_cases_excluded ? t('projects.casesHelp', { excluded: p.n_cases_excluded }) : undefined}>
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
      {/* AUD-A4-03 (PRJ-06): archive, with a confirmation */}
      <IconButton icon={codicon('archive')} label={t('projects.archiveMenu')} onClick={() => useProjectDialogs.getState().set({ archive: { pid: p.project_id, name: p.name, home: true } })} />
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

const MAX_DATASETS = 5

/** UI-04 / DCM-14 (AUD-A2-14): converted workspace datasets, found again from the home */
function RecentDatasets({ onCreate }: { onCreate: (path: string) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const runs = useWorkspaceRuns().data ?? []
  const seen = new Set<string>()
  const done = runs.filter((r) => r.status === 'completed' && !seen.has(r.dataset_dir) && seen.add(r.dataset_dir)).slice(0, MAX_DATASETS)
  if (!done.length) return null
  return (
    <>
      <h3 className="home-sub">{t('home.datasets')}</h3>
      <div role="list" className="home-list" aria-label={t('home.datasets')}>
        {done.map((r) => (
          <div key={r.run_id} className="home-project" role="listitem">
            <span className="home-project-main">
              <Icon spec={codicon('database')} size={20} />
              <span className="home-project-text">
                <span className="home-project-name">{r.name}</span>
                <span className="muted">{t('home.datasetMeta', { count: (r.counts?.converted ?? 0) + (r.counts?.already_converted ?? 0), ago: fmtAgo(r.finished_at ?? r.created_at) })}</span>
              </span>
            </span>
            <button type="button" className="btn btn-sm" onClick={() => openPath(navigate, r.dataset_dir)}>{t('home.datasetOpen')}</button>
            <button type="button" className="btn btn-sm" onClick={() => onCreate(r.dataset_dir)}>{t('home.datasetCreate')}</button>
          </div>
        ))}
      </div>
    </>
  )
}

/** PRJ-06: archived projects, each with Restore (AUD-A4-03) */
function ArchivedList() {
  const { t } = useTranslation()
  const archived = useProjects(true)
  const { restore } = useArchiveProject()
  if (archived.isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!archived.data?.length) return <div className="empty">{t('home.noArchived')}</div>
  return (
    <div role="list" className="home-list" aria-label={t('home.archived')}>
      {archived.data.map((p) => (
        <div key={p.project_id} className="home-project" role="listitem">
          <span className="home-project-main">
            <Icon spec={codicon('archive')} size={20} />
            <span className="home-project-text">
              <span className="home-project-name">{p.name}</span>
              <span className="muted">{t('projects.metaNew', { cases: p.n_cases, ago: fmtAgo(p.created_at) })}</span>
            </span>
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={restore.isPending}
            onClick={() =>
              restore.mutate(p.project_id, {
                onSuccess: () => toast({ message: t('projects.restored', { name: p.name }), tone: 'ok' }),
                onError: (e) => toast({ message: problemText(e), tone: 'error' }),
              })
            }
          >
            {t('projects.restore')}
          </button>
        </div>
      ))}
    </div>
  )
}

export function WorkspaceHome() {
  const { t } = useTranslation()
  const projects = useProjects()
  const creating = useProjectDialogs((s) => s.creating)
  const setCreating = (creating: boolean) => useProjectDialogs.getState().set({ creating })
  const bundlePick = useProjectDialogs((s) => s.bundlePick)
  const [showArchived, setShowArchived] = useState(false)
  const [relink, setRelink] = useState<ProjectSummary | null>(null)
  const [fromDataset, setFromDataset] = useState<string | null>(null)
  const [bundle, setBundle] = useState<File | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  // "Import project bundle…" from the palette (AUD-A1-01)
  const picked = useRef(bundlePick)
  useEffect(() => {
    if (picked.current === bundlePick) return
    picked.current = bundlePick
    picker.current?.click()
  }, [bundlePick])
  const sorted = [...(projects.data ?? [])]
    .filter((p) => !p.archived)
    .sort((a, b) => (b.last_opened_at ?? b.created_at).localeCompare(a.last_opened_at ?? a.created_at))
  return (
    <div className="home">
      <div className="home-inner">
        <header className="home-hero">
          <span className="home-logo"><BrandMark size={48} /></span>
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
              <button type="button" className="home-action" onClick={() => useConverter.getState().show({ pid: null })}>
                <Icon spec={codicon('file-binary')} size={20} />
                <span>
                  <strong>{t('home.convertDicom')}</strong>
                  <span className="muted">{t('home.convertDicomHelp')}</span>
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
            <div className="home-recent-head">
              <h2>{t(showArchived ? 'home.archived' : 'home.recent')}</h2>
              <button type="button" className="btn btn-sm" aria-pressed={showArchived} onClick={() => setShowArchived(!showArchived)}>
                <Icon spec={codicon('archive')} />
                {t('home.showArchived')}
              </button>
            </div>
            {showArchived ? <ArchivedList /> : <>
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
            <RecentDatasets onCreate={setFromDataset} />
            </>}
          </section>
        </div>
        <footer className="home-footer muted">
          {t('app.tagline')}
          {/* AUD-A4-05 (NFR-16) */}
          <button type="button" className="link" onClick={() => runCommand('help.about')}>{t('cmd.about')}</button>
        </footer>
      </div>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
      {fromDataset ? <NewProjectDialog open onOpenChange={(o) => !o && setFromDataset(null)} prefill={{ path: fromDataset }} /> : null}
      {bundle ? (
        <Suspense fallback={null}>
          <BundleImport file={bundle} onClose={() => setBundle(null)} />
        </Suspense>
      ) : null}
      {relink ? <RelinkDialog pid={relink.project_id} name={relink.name} onOpenChange={(o) => !o && setRelink(null)} /> : null}
    </div>
  )
}
