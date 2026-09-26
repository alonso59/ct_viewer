// Sharing (PRJ-03, PRJ-17, AUD-A1-11): the title-bar share menu (edit link · view-only link) and
// the same actions as commands. Archive (PRJ-06, AUD-A4-03) and quick open of projects (AUD-A1-01).
import * as Menu from '@radix-ui/react-dropdown-menu'
import { Command } from 'cmdk'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import i18n from '../../i18n'
import { api, keys, queryClient, useArchiveProject, useProject, useProjects, type Project } from '../../api'
import { Dialog, ProblemCard, fmtAgo } from '../../lib'
import { registry, toast, useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { useProjectDialogs } from './store'

/** The current tab's deep link (case, item, layout) on another base: `/p/{pid}` or `/v/{token}` */
export function deepLink(base: string, loc: Pick<Location, 'pathname' | 'search'> = location): string {
  return base.replace(/\/$/, '') + loc.pathname.replace(/^\/p\/[^/]+/, '') + loc.search
}

/** Clipboard API needs a secure context; plain-http remote hosts fall back to the toast text */
function copyAndTell(url: string, done: string) {
  const ok = () => toast({ message: i18n.t(done, { url }), tone: 'ok' })
  const manual = () => toast({ message: i18n.t('shell.shareLinkManual', { url }), tone: 'info' })
  if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, manual)
  else manual()
}

const cached = (pid: string) => queryClient.getQueryData<Project>(keys.project(pid))

/** PRJ-03: the full (edit) link of the project, at the current tab */
export function copyEditLink(pid = useWorkbench.getState().pid) {
  const p = pid ? cached(pid) : undefined
  if (p) copyAndTell(deepLink(p.share_url), 'shell.shareLinkCopied')
}

/** PRJ-17: the view-only link at the current tab; created on first use (API-61) */
export async function copyViewLink(pid = useWorkbench.getState().pid) {
  if (!pid) return
  const p = cached(pid)
  let url = registry.readOnly ? p?.share_url : p?.view_url
  if (!url && !registry.readOnly) {
    try {
      url = (await api.createViewToken(pid)).view_url ?? undefined
      void queryClient.invalidateQueries({ queryKey: keys.project(pid) })
    } catch (e) {
      toast({ message: e instanceof Error ? e.message : i18n.t('common.error'), tone: 'error' })
      return
    }
  }
  if (url) copyAndTell(deepLink(url), 'shell.viewLinkCopied')
}

/** Title-bar share control: a menu with both links; a view-only link can only share itself */
export function ShareMenu({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const project = useProject(pid).data
  if (!project) return null
  if (registry.readOnly)
    return (
      <button type="button" className="icon-btn" aria-label={t('shell.copyViewLink')} title={t('shell.copyViewLink')} onClick={() => void copyViewLink(pid)}>
        <Icon spec={codicon('link')} />
      </button>
    )
  return (
    <Menu.Root>
      <Menu.Trigger className="icon-btn" aria-label={t('shell.share')} title={t('shell.share')}>
        <Icon spec={codicon('link')} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" align="end" sideOffset={2}>
          <Menu.Item className="menu-item" onSelect={() => copyEditLink(pid)}>
            <Icon spec={codicon('edit')} />
            {t('shell.copyEditLink')}
          </Menu.Item>
          <Menu.Item className="menu-item" onSelect={() => void copyViewLink(pid)}>
            <Icon spec={codicon('eye')} />
            {project.view_url ? t('shell.copyViewLink') : t('shell.createViewLink')}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

/** PRJ-06: confirm, then archive (never deletes; restore from the home's Archived list) */
export function ArchiveDialog() {
  const { t } = useTranslation()
  const target = useProjectDialogs((s) => s.archive)
  const close = () => useProjectDialogs.getState().set({ archive: null })
  const m = useArchiveProject().archive
  if (!target) return null
  const run = () =>
    m.mutate(target.pid, {
      onSuccess: () => {
        close()
        toast({ message: t('projects.archived', { name: target.name }), tone: 'ok' })
        // Leaving the project releases its volumes (UI-24)
        if (!target.home) location.assign('/')
      },
    })
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && close()}
      title={t('projects.archiveTitle', { name: target.name })}
      icon={codicon('archive')}
      footer={
        <>
          <button type="button" className="btn" onClick={close}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" disabled={m.isPending} onClick={run}>{t('projects.archive')}</button>
        </>
      }
    >
      <p className="muted">{t('projects.archiveHelp')}</p>
      {m.error ? <ProblemCard error={m.error} /> : null}
    </Dialog>
  )
}

/** Quick open on the home and in Open mode: the projects, most recent first (AUD-A1-01) */
export function QuickOpenProjects({ query, close }: { query: string; close: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const q = query.trim().toLowerCase()
  const list = [...(useProjects().data ?? [])]
    .sort((a, b) => (b.last_opened_at ?? b.created_at).localeCompare(a.last_opened_at ?? a.created_at))
    .filter((p) => !q || p.name.toLowerCase().includes(q))
  return (
    <Command.Group heading={t('palette.projects')}>
      {list.map((p) => (
        <Command.Item
          key={p.project_id}
          value={p.project_id}
          onSelect={() => {
            close()
            navigate(`/p/${p.project_id}`)
          }}
        >
          <Icon spec={codicon('folder')} />
          <span>{p.name}</span>
          <span className="palette-detail">{t('projects.casesShort', { n: p.n_cases })}</span>
          <span className="palette-detail" style={{ marginLeft: 'auto' }}>{fmtAgo(p.last_opened_at ?? p.created_at)}</span>
        </Command.Item>
      ))}
    </Command.Group>
  )
}
