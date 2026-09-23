// Workspace home (`/`, UI-04): New Project, Open Recent with thumbnail + progress, share-link copy.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { DEMO_PID, useCreateProject, useProjects, type Project } from '../../api'
import { Dialog, IconButton, Progress, SliceThumb, fmtAgo } from '../../lib'
import { toast } from '../../shell'
import { Icon, codicon, ct } from '../../theme'
import { useImportWizard } from '../import'
import './projects.css'

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const create = useCreateProject()
  const navigate = useNavigate()
  const submit = async () => {
    const p = await create.mutateAsync(name.trim())
    onOpenChange(false)
    setName('')
    navigate(`/p/${p.project_id}`)
    useImportWizard.getState().open(p.project_id)
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
      <form className="field" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void submit() }}>
        <label className="field-label" htmlFor="project-name">{t('projects.name')}</label>
        <input id="project-name" className="input" autoFocus value={name} placeholder={t('projects.namePlaceholder')} onChange={(e) => setName(e.target.value)} />
        <span className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('projects.newHelp')}</span>
      </form>
    </Dialog>
  )
}

export function RelinkDialog({ project, onOpenChange }: { project: Project | null; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [state, setState] = useState<'idle' | 'checking' | 'failed'>('idle')
  const root = project?.roots[0]
  return (
    <Dialog
      open={project !== null}
      onOpenChange={(o) => { onOpenChange(o); setState('idle') }}
      title={t('projects.relinkTitle', { name: project?.name ?? '' })}
      icon={codicon('link')}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>{t('common.cancel')}</button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!path.trim() || state === 'checking'}
            onClick={() => {
              setState('checking')
              setTimeout(() => setState('failed'), 900)
            }}
          >
            {state === 'checking' ? t('projects.verifying') : t('projects.verify')}
          </button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="muted" style={{ fontSize: 'var(--fs-panel)' }}>{t('projects.relinkHelp')}</div>
        <div className="props" style={{ padding: 0 }}>
          <span className="muted">{t('projects.alias')}</span>
          <span className="mono">{root?.alias}</span>
          <span className="muted">{t('projects.oldPath')}</span>
          <span className="mono">{root?.path}</span>
        </div>
        <label className="field">
          <span className="field-label">{t('projects.newPath')}</span>
          <input className="input mono" value={path} placeholder={t('projects.newPathPlaceholder')} onChange={(e) => setPath(e.target.value)} />
        </label>
        {state === 'failed' ? (
          <div className="error-card" style={{ margin: 0 }}>
            {t('projects.verifyFailed')}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}

function ProjectCard({ p, onRelink }: { p: Project; onRelink: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const offline = p.roots.some((r) => !r.reachable)
  const empty = p.n_cases === 0
  return (
    <div className="home-project" role="listitem">
      <button type="button" className="home-project-main" onClick={() => (offline ? onRelink() : navigate(`/p/${p.project_id}`))}>
        <SliceThumb itemId={p.project_id === DEMO_PID ? 'case_00014.01.complete.-' : null} labels={p.label_map} size={56} />
        <span className="home-project-text">
          <span className="home-project-name">
            {p.name}
            {offline ? <span className="badge" data-tone="error">{t('projects.offline')}</span> : null}
            {empty ? <span className="badge">{t('projects.empty')}</span> : null}
          </span>
          <span className="muted">
            {t('projects.meta', { cases: p.n_cases, items: p.n_items, ago: fmtAgo(p.last_opened_at) })}
          </span>
          <span className="home-progress">
            <Progress value={p.progress.reviewed} total={p.progress.total} />
            <span className="muted num">{t('projects.reviewed', { done: p.progress.reviewed, total: p.progress.total })}</span>
          </span>
        </span>
      </button>
      <IconButton
        icon={codicon('link')}
        label={t('shell.copyShareLink')}
        onClick={() => {
          void navigator.clipboard?.writeText(p.share_url)
          toast({ message: t('shell.shareLinkCopied'), tone: 'ok' })
        }}
      />
    </div>
  )
}

export function WorkspaceHome() {
  const { t } = useTranslation()
  const projects = useProjects()
  const [creating, setCreating] = useState(false)
  const [relink, setRelink] = useState<Project | null>(null)
  const sorted = [...(projects.data ?? [])].sort((a, b) => b.last_opened_at.localeCompare(a.last_opened_at))
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
              <button type="button" className="home-action" onClick={() => toast({ message: t('home.bundleSoon'), tone: 'info' })}>
                <Icon spec={codicon('package')} size={20} />
                <span>
                  <strong>{t('home.importBundle')}</strong>
                  <span className="muted">{t('home.importBundleHelp')}</span>
                </span>
              </button>
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
      <RelinkDialog project={relink} onOpenChange={(o) => !o && setRelink(null)} />
    </div>
  )
}
