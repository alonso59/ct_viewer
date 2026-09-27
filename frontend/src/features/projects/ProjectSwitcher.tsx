// Title-bar brand: project switcher ▾ (UI_SHELL §Layout)
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useProjects } from '../../api'
import { BrandMark, Icon, codicon } from '../../theme'
import { useProjectDialogs } from './store'
import { NewProjectDialog } from '../import'

export function ProjectSwitcher({ pid }: { pid: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const projects = useProjects().data ?? []
  const current = projects.find((p) => p.project_id === pid)
  const creating = useProjectDialogs((s) => s.creating)
  const setCreating = (creating: boolean) => useProjectDialogs.getState().set({ creating })
  return (
    <>
      <Menu.Root>
        <Menu.Trigger className="titlebar-brand" aria-label={t('projects.switch')}>
          <BrandMark size={18} />
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
