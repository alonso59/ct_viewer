// Title-bar brand: project switcher ▾ (UI_SHELL §Layout)
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useProjects } from '../../api'
import { Icon, codicon, ct } from '../../theme'
import { NewProjectDialog } from './WorkspaceHome'

export function ProjectSwitcher({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const projects = useProjects().data ?? []
  const current = projects.find((p) => p.project_id === pid)
  const [creating, setCreating] = useState(false)
  return (
    <>
      <Menu.Root>
        <Menu.Trigger className="titlebar-brand" aria-label={t('projects.switch')}>
          <span style={{ color: 'var(--accent)', display: 'inline-flex' }}>
            <Icon spec={ct('layout-four-up')} />
          </span>
          {current?.name ?? t('common.loading')}
          <Icon spec={codicon('chevron-down')} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="overlay menu" align="start" sideOffset={2}>
            {projects.map((p) => (
              <Menu.Item key={p.project_id} className="menu-item" onSelect={() => navigate(`/p/${p.project_id}`)}>
                <Icon spec={codicon(p.project_id === pid ? 'check' : 'folder')} />
                {p.name}
                <span className="kbd">{t('projects.casesShort', { n: p.n_cases })}</span>
              </Menu.Item>
            ))}
            <Menu.Separator className="menu-sep" />
            <Menu.Item className="menu-item" onSelect={() => setCreating(true)}>
              <Icon spec={codicon('new-folder')} />
              {t('home.newProject')}
            </Menu.Item>
            <Menu.Item className="menu-item" onSelect={() => navigate('/')}>
              <Icon spec={codicon('home')} />
              {t('projects.home')}
            </Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}
